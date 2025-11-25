from django.urls import reverse
from django.contrib.auth.models import User, Group
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework import status
from orders.models import Order, Customer
from tenants.models import Tenant

class CashierAPITests(APITestCase):

    def setUp(self):
        """
        Menyiapkan data awal untuk setiap tes.
        """
        # Membuat grup yang diperlukan
        self.cashier_group, _ = Group.objects.get_or_create(name='CASHIER')
        self.customer_group, _ = Group.objects.get_or_create(name='CUSTOMER')

        # Membuat user kasir dan user biasa
        self.cashier_user = User.objects.create_user(username='cashier', password='password123', is_staff=True)
        self.cashier_user.groups.add(self.cashier_group)

        self.normal_user = User.objects.create_user(username='customer', password='password123')
        self.normal_user.groups.add(self.customer_group)

        # Membuat customer
        self.customer = Customer.objects.create(phone='08123456789', name='Test Customer')


        # Membuat tenant
        self.tenant = Tenant.objects.create(name='Kantin Sehat')

        # Membuat order untuk dites
        self.cash_order = Order.objects.create(
            customer=self.customer,
            tenant=self.tenant,
            total=50000,
            payment_method='CASH',
            status='AWAITING_PAYMENT',
            cashier_pin='123456'
        )

        self.paid_order = Order.objects.create(
            customer=self.customer,
            tenant=self.tenant,
            total=25000,
            payment_method='CASH',
            status='PAID',
            cashier_pin='654321'
        )

        self.non_cash_order = Order.objects.create(
            customer=self.customer,
            tenant=self.tenant,
            total=30000, 
            payment_method='TRANSFER', # Menggunakan pilihan yang valid dari model Order
            status='AWAITING_PAYMENT',
        )

    def test_verify_order_by_pin_success(self):
        """
        Tes: Kasir berhasil memverifikasi order dengan PIN yang valid.
        """
        self.client.force_authenticate(user=self.cashier_user)
        url = reverse('cashier:verify-order-by-pin')
        data = {'pin': '123456'}
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['references_code'], self.cash_order.references_code)
        self.assertEqual(response.data['status'], 'AWAITING_PAYMENT')

    def test_verify_order_by_pin_not_found(self):
        """
        Tes: Verifikasi gagal karena PIN tidak valid.
        """
        self.client.force_authenticate(user=self.cashier_user)
        url = reverse('cashier:verify-order-by-pin')
        data = {'pin': '000000'} # PIN salah
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['detail'], 'PIN tidak valid atau pesanan tidak tersedia.')

    def test_verify_order_by_pin_for_paid_order(self):
        """
        Tes: Verifikasi gagal karena order sudah dibayar (tidak lagi AWAITING_PAYMENT).
        """
        self.client.force_authenticate(user=self.cashier_user)
        url = reverse('cashier:verify-order-by-pin')
        data = {'pin': '654321'} # PIN untuk order yang sudah lunas
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_verify_order_by_pin_no_permission(self):
        """
        Tes: User biasa (bukan kasir) tidak bisa mengakses endpoint verifikasi.
        """
        self.client.force_authenticate(user=self.normal_user)
        url = reverse('cashier:verify-order-by-pin')
        data = {'pin': '123456'}
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cash_confirm_success(self):
        """
        Tes: Kasir berhasil mengonfirmasi pembayaran tunai.
        """
        self.client.force_authenticate(user=self.cashier_user)
        url = reverse('cashier:confirm-cash', kwargs={'order_uuid': self.cash_order.uuid})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['detail'], 'Order dikonfirmasi lunas.')

        # Cek status order di database
        self.cash_order.refresh_from_db()
        self.assertEqual(self.cash_order.status, 'PAID')
        self.assertIsNotNone(self.cash_order.paid_at)
        self.assertIn('payments', self.cash_order.meta)
        self.assertEqual(self.cash_order.meta['payments'][0]['method'], 'CASH')

    def test_cash_confirm_already_paid(self):
        """
        Tes: Gagal konfirmasi karena order sudah dibayar sebelumnya.
        """
        self.client.force_authenticate(user=self.cashier_user)
        url = reverse('cashier:confirm-cash', kwargs={'order_uuid': self.paid_order.uuid})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], 'Order sudah dibayar')

    def test_cash_confirm_not_cash_method(self):
        """
        Tes: Gagal konfirmasi karena metode pembayaran bukan CASH.
        """
        self.client.force_authenticate(user=self.cashier_user)
        url = reverse('cashier:confirm-cash', kwargs={'order_uuid': self.non_cash_order.uuid})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], 'Metode pembayaran ini bukan CASH')

    def test_cash_confirm_expired_order(self):
        """
        Tes: Gagal konfirmasi karena order sudah kadaluwarsa.
        """
        # Set order menjadi kadaluwarsa
        expired_order = Order.objects.create(
            customer=self.customer,
            tenant=self.tenant,
            total=10000,
            payment_method='CASH',
            status='AWAITING_PAYMENT',
            expired_at=timezone.now() - timezone.timedelta(minutes=1)
        )

        self.client.force_authenticate(user=self.cashier_user)
        url = reverse('cashier:confirm-cash', kwargs={'order_uuid': expired_order.uuid})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], 'Order sudah kadaluarsa, silahkan buat order baru')

        # Cek status order di database telah diupdate menjadi EXPIRED
        expired_order.refresh_from_db()
        self.assertEqual(expired_order.status, 'EXPIRED')