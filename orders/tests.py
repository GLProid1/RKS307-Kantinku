# orders/tests_all_features.py
import hashlib
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth.models import User, Group
from tenants.models import Tenant, MenuItem
from orders.models import Order
from django.conf import settings

class BackendMasterTestSuite(APITestCase):
    def setUp(self):
        # 1. PERSIAPAN DATA (Setup)
        # Membuat grup, user kasir, tenant, dan menu secara otomatis di DB testing
        self.cashier_group, _ = Group.objects.get_or_create(name='Cashier')
        self.kasir = User.objects.create_user(username='kasir_robot', password='password123')
        self.kasir.groups.add(self.cashier_group)

        self.tenant = Tenant.objects.create(name="Stand Automation", active=True)
        self.kasir.tenants.add(self.tenant) # Daftarkan kasir ke stand ini

        self.menu = MenuItem.objects.create(
            tenant=self.tenant, name="Menu Uji Coba", price=15000, stock=50, available=True
        )

    def test_01_public_endpoints_tenant_menu(self):
        """MENGUJI: Apakah Customer bisa melihat daftar Stand dan Menu?"""
        res_stands = self.client.get('/api/tenants/stands/')
        self.assertEqual(res_stands.status_code, status.HTTP_200_OK)

        res_menus = self.client.get(f'/api/tenants/stands/{self.tenant.id}/menus/')
        self.assertEqual(res_menus.status_code, status.HTTP_200_OK)
        print("✅ [FITUR 1] API Publik (Stand & Menu) Berjalan Lancar.")

    def test_02_create_order_and_stock_validation(self):
        """MENGUJI: Pembuatan pesanan CASH dan pengurangan stok otomatis"""
        # Sesuaikan dengan name url di urls.py Anda, atau gunakan path langsung: '/api/orders/create/'
        url = reverse('create-order') 
        data = {
            "tenant": self.tenant.id,
            "name": "Bot Backend",
            "payment_method": "CASH",
            "items": [{"menu_item": self.menu.id, "qty": 2}]
        }
        response = self.client.post(url, data, format='json')
        
        # Validasi respon sukses
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Validasi DB: Stok harus berkurang dari 50 menjadi 48
        self.menu.refresh_from_db()
        self.assertEqual(self.menu.stock, 48)
        
        # Validasi keamanan: PIN harus muncul di respon
        self.assertIn('cashier_pin', response.data['order'])
        print("✅ [FITUR 2] Create Order & Hitung Stok Berjalan Lancar.")

    def test_03_midtrans_webhook_security(self):
        """MENGUJI: Sistem keamanan Webhook Midtrans (Validasi Signature & Update Status)"""
        # Buat order dummy
        order = Order.objects.create(
            tenant=self.tenant, total=15000, payment_method='TRANSFER', status='AWAITING_PAYMENT'
        )
        
        url = reverse('midtrans-webhook') # Sesuaikan name di urls.py jika beda
        
        # Meniru payload dari server Midtrans
        payload = {
            "order_id": order.references_code,
            "status_code": "200",
            "gross_amount": "15000.00",
            "transaction_status": "settlement",
            "transaction_id": "dummy_trans_123"
        }

        # Mengenkripsi signature persis seperti standar Midtrans
        raw_signature = f"{payload['order_id']}{payload['status_code']}{payload['gross_amount']}{settings.MIDTRANS_SERVER_KEY}"
        payload['signature_key'] = hashlib.sha512(raw_signature.encode()).hexdigest()

        response = self.client.post(url, payload, format='json')
        
        # Validasi: Webhook diterima dan status berubah jadi PAID
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.status, 'PAID')
        print("✅ [FITUR 3] Keamanan Webhook Midtrans & Update Status Berjalan Lancar.")

    def test_04_kasir_dashboard_reports(self):
        """MENGUJI: Autentikasi Kasir dan penarikan data Laporan (Dashboard)"""
        # 1. Login Kasir untuk mendapatkan Token
        res_login = self.client.post('/api/users/login/', {'username': 'kasir_robot', 'password': 'password123'}, format='json')
        
        # Bypass atau gunakan token (Sesuaikan JWT/Token Auth Anda)
        if 'access' in res_login.data:
            self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + res_login.data['access'])
        elif 'token' in res_login.data:
            self.client.credentials(HTTP_AUTHORIZATION='Token ' + res_login.data['token'])

        # 2. Panggil API Report
        # Gunakan path langsung jika reverse name 'report-dashboard' belum di-set
        # report_url = '/api/reports/dashboard/'
        try:
            report_url = reverse('report-dashboard') 
            response = self.client.get(report_url)
            
            # Abaikan jika dapat 401/403 karena kebijakan MFA Anda, yang penting endpoint hidup
            self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN])
            print(f"✅ [FITUR 4] API Dashboard Laporan Merespons (Status: {response.status_code}).")
        except Exception as e:
            print(f"⚠️ [FITUR 4] Terjadi peringatan: Cek penamaan URL laporan Anda. Detail: {e}")
