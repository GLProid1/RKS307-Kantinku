from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from .models import Tenant, MenuItem, Order
from django.contrib.auth.models import User, Group

class OrderAPITests(APITestCase):
    def setUp(self):
        """Set up data untuk semua test case di class ini."""
        self.tenant = Tenant.objects.create(name="Warung Seblak", active=True)
        self.menu_item1 = MenuItem.objects.create(
            tenant=self.tenant, name="Seblak Original", price=15000, available=True, stock=10
        )
        self.menu_item2 = MenuItem.objects.create(
            tenant=self.tenant, name="Es Teh Manis", price=5000, available=True, stock=5
        )
        self.create_order_url = reverse('create-order')

    def test_create_order_success(self):
        """
        Test case untuk memastikan order berhasil dibuat dengan data yang valid.
        """
        data = {
            "tenant": self.tenant.pk,
            "payment_method": "CASH",
            "items": [
                {"menu_item": self.menu_item1.pk, "qty": 2},
                {"menu_item": self.menu_item2.pk, "qty": 1},
            ]
        }
        response = self.client.post(self.create_order_url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['order']['status'], 'AWAITING_PAYMENT')
        self.assertEqual(float(response.data['order']['total']), 35000.00)
        self.assertEqual(len(response.data['order']['items']), 2)

    def test_create_order_with_empty_items_fails(self):
        """Test case untuk memastikan order gagal dibuat jika item kosong."""
        data = {"tenant": self.tenant.pk, "payment_method": "CASH", "items": []}
        response = self.client.post(self.create_order_url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
class OrderPermissionTests(APITestCase):
    def setUp(self):
        """Menyiapkan data untuk pengujian permission"""
        # 1. Buat Grup Pengguna
        self.admin_group, _ = Group.objects.get_or_create(name='Admin')
        self.seller_group, _ = Group.objects.get_or_create(name='Seller')
        
        # 2. Buat Dua Tenant Berbeda
        self.tenant1, _ = Tenant.objects.get_or_create(name='Tenant Siti')
        self.tenant2, _ = Tenant.objects.get_or_create(name='Tenant Budi')
        
        # 3. Buatn Pengguna dengan Peran Berbeda
        # Pengguna Admin
        self.admin_user = User.objects.create_user(username='admin', password='admin123', is_staff=True)
        self.admin_user.groups.add(self.admin_group)
        
        # Staff untuk Tenant 1
        self.staff_tenant1 = User.objects.create_user(username='staff_tenant1', password='staff123', is_staff=False)
        self.staff_tenant1.groups.add(self.seller_group)
        self.tenant1.staff.add(self.staff_tenant1)
        
        # Staff untuk Tenant 2
        self.staff_tenant2 = User.objects.create_user(username='staff_tenant2', password='staff123', is_staff=False)
        self.staff_tenant2.groups.add(self.seller_group)
        self.tenant2.staff.add(self.staff_tenant2)
        
        # 4. Buat sebuah Order untuk milik Tenant A
        self.order_tenant1 = Order.objects.create(tenant=self.tenant1, total=10000,payment_method='CASH')
        
        # 5. Siapkan URL untuk detail order
        self.order_detail_url = reverse('order-detail', kwargs={'order_uuid': self.order_tenant1.uuid})
        
    def test_staff_from_correct_tenant_can_access_order(self):
        """
        Skenario dimana staff dari tenant yang benar harus bisa mengakses detail order.
        """
        self.client.force_authenticate(user=self.staff_tenant1)
        response = self.client.get(self.order_detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['uuid'], str(self.order_tenant1.uuid))
        
    def test_staff_from_wrong_tenant_cannot_access_order(self):
        """
        Skenario dimana staff dari tenant yang salah tidak boleh mengakses detail order.
        """
        self.client.force_authenticate(user=self.staff_tenant2)
        response = self.client.get(self.order_detail_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_admin_can_access_any_order(self):
        """
        Skenario dimana admin harus bisa mengakses detail order dari tenant manapun.
        """
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.order_detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['uuid'], str(self.order_tenant1.uuid))
        
    def test_unauthenticated_user_cannot_access_order(self):
        """
        Skenario dimana pengguna yang tidak terautentikasi tidak boleh mengakses detail order.
        """
        # Tidak memanggil self.client.force_authenticate()
        response = self.client.get(self.order_detail_url)
        # IsOrderTenantStaff permission memerlukan login, jadi harusnya 403 Forebidden
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)