from django.urls import reverse
from django.contrib.auth.models import User, Group
from rest_framework.test import APITestCase
from rest_framework import status
from rest_framework.authtoken.models import Token

class AuthAPITests(APITestCase):
    """
    Tes untuk endpoint autentikasi: Login, Logout, dan CheckAuth.
    """
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpassword123')
        self.login_url = reverse('users:login')
        self.logout_url = reverse('users:logout')
        self.check_auth_url = reverse('users:check-auth')

    def test_login_success(self):
        """Tes: Login berhasil dengan kredensial yang benar."""
        data = {'username': 'testuser', 'password': 'testpassword123'}
        response = self.client.post(self.login_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('token', response.data)
        self.assertIn('user', response.data)
        self.assertEqual(response.data['user']['username'], 'testuser')

    def test_login_fail_wrong_password(self):
        """Tes: Login gagal karena password salah."""
        data = {'username': 'testuser', 'password': 'wrongpassword'}
        response = self.client.post(self.login_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data['detail'], 'Username atau Password yang anda masukkan salah. Silahkan coba lagi.')

    def test_logout_success(self):
        """Tes: Logout berhasil untuk pengguna yang terautentikasi."""
        # Login dulu untuk mendapatkan token
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token.key)
        
        response = self.client.post(self.logout_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Pastikan token sudah terhapus
        token_exists = Token.objects.filter(user=self.user).exists()
        self.assertFalse(token_exists)

    def test_logout_fail_unauthenticated(self):
        """Tes: Logout gagal jika tidak terautentikasi."""
        response = self.client.post(self.logout_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_check_auth_success(self):
        """Tes: Check auth berhasil untuk pengguna yang terautentikasi."""
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token.key)
        
        response = self.client.get(self.check_auth_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user']['username'], 'testuser')

    def test_check_auth_fail_unauthenticated(self):
        """Tes: Check auth gagal jika tidak terautentikasi."""
        response = self.client.get(self.check_auth_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class UserViewSetPermissionTests(APITestCase):
    """
    Tes untuk perizinan pada UserViewSet berdasarkan peran pengguna.
    """
    def setUp(self):
        # Membuat grup
        self.admin_group, _ = Group.objects.get_or_create(name='Admin')
        self.seller_group, _ = Group.objects.get_or_create(name='Seller')
        self.cashier_group, _ = Group.objects.get_or_create(name='Cashier')

        # Membuat pengguna dengan peran berbeda
        self.admin_user = User.objects.create_user(username='admin', password='password123', is_staff=True)
        self.admin_user.groups.add(self.admin_group)

        self.seller_user = User.objects.create_user(username='seller', password='password123')
        self.seller_user.groups.add(self.seller_group)

        self.cashier_user = User.objects.create_user(username='cashier', password='password123')
        self.cashier_user.groups.add(self.cashier_group)

        # URL untuk UserViewSet
        self.list_url = reverse('users:user-list')
        self.detail_url_seller = reverse('users:user-detail', kwargs={'pk': self.seller_user.pk})
        
        # URL untuk Login
        self.login_url = reverse('users:login')

    # --- Tes untuk Aksi 'list' ---
    def test_list_users_as_admin(self):
        """Tes: Admin dapat melihat daftar semua pengguna."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 3) # Ada 3 user yang dibuat

    def test_list_users_as_non_admin(self):
        """Tes: Pengguna non-admin tidak dapat melihat daftar semua pengguna."""
        self.client.force_authenticate(user=self.seller_user)
        response = self.client.get(self.list_url)
        # Harusnya 403 Forbidden karena permission IsAdminUser gagal
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --- Tes untuk Aksi 'retrieve' ---
    def test_retrieve_own_profile(self):
        """Tes: Pengguna dapat melihat profilnya sendiri."""
        self.client.force_authenticate(user=self.seller_user)
        response = self.client.get(self.detail_url_seller)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['username'], self.seller_user.username)

    def test_retrieve_other_profile_as_non_admin(self):
        """Tes: Pengguna non-admin tidak dapat melihat profil pengguna lain."""
        self.client.force_authenticate(user=self.cashier_user) # Login sebagai kasir
        response = self.client.get(self.detail_url_seller) # Mencoba lihat profil seller
        # Harusnya 404 Not Found karena queryset difilter hanya untuk user.pk
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_retrieve_other_profile_as_admin(self):
        """Tes: Admin dapat melihat profil pengguna lain."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.detail_url_seller)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['username'], self.seller_user.username)

    # --- Tes untuk Aksi 'update' ---
    def test_update_own_profile(self):
        """Tes: Pengguna dapat memperbarui profilnya sendiri."""
        self.client.force_authenticate(user=self.seller_user)
        data = {'first_name': 'Seller', 'last_name': 'Satu'}
        response = self.client.patch(self.detail_url_seller, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['first_name'], 'Seller')

    def test_update_other_profile_as_non_admin(self):
        """Tes: Pengguna non-admin tidak dapat memperbarui profil pengguna lain."""
        self.client.force_authenticate(user=self.cashier_user)
        data = {'first_name': 'New Name'}
        response = self.client.patch(self.detail_url_seller, data)
        # Harusnya 404 Not Found karena queryset difilter
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # --- Tes untuk Aksi 'create' ---
    def test_create_user_as_admin(self):
        """Tes: Admin dapat membuat pengguna baru."""
        self.client.force_authenticate(user=self.admin_user)
        data = {
            'username': 'newuser',
            'password': 'newpassword123',
            'email': 'new@example.com',
            'role': 'Cashier'
        }
        response = self.client.post(self.list_url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(username='newuser').exists())

    def test_create_user_as_non_admin(self):
        """Tes: Pengguna non-admin tidak dapat membuat pengguna baru."""
        self.client.force_authenticate(user=self.seller_user)
        data = {
            'username': 'newuser',
            'password': 'newpassword123',
            'email': 'new@example.com',
            'role': 'Cashier'
        }
        response = self.client.post(self.list_url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --- Tes untuk Aksi 'destroy' ---
    def test_destroy_user_as_admin(self):
        """Tes: Admin dapat menghapus pengguna."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.delete(self.detail_url_seller)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(User.objects.filter(pk=self.seller_user.pk).exists())

    def test_destroy_user_as_non_admin(self):
        """Tes: Pengguna non-admin tidak dapat menghapus pengguna."""
        self.client.force_authenticate(user=self.cashier_user)
        response = self.client.delete(self.detail_url_seller)
        # Harusnya 403 Forbidden karena permission IsAdminUser gagal
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --- Tes untuk Aksi 'summary' ---
    def test_summary_as_admin(self):
        """Tes: Admin dapat mengakses endpoint summary."""
        self.client.force_authenticate(user=self.admin_user)
        summary_url = reverse('users:user-summary')
        response = self.client.get(summary_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['admins']['count'], 1)
        self.assertEqual(response.data['sellers']['count'], 1)
        self.assertEqual(response.data['cashiers']['count'], 1)

    def test_summary_as_non_admin(self):
        """Tes: Pengguna non-admin tidak dapat mengakses endpoint summary."""
        self.client.force_authenticate(user=self.seller_user)
        summary_url = reverse('users:user-summary')
        response = self.client.get(summary_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --- Tes untuk Login Response dengan Role ---
    def test_login_response_includes_admin_role(self):
        """Tes: Respons login untuk admin menyertakan peran 'admin'."""
        data = {'username': 'admin', 'password': 'password123'}
        response = self.client.post(self.login_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user']['role'], 'admin')
        self.assertEqual(response.data['user']['initial_dashboard'], '/admin-dashboard')

    def test_login_response_includes_seller_role(self):
        """Tes: Respons login untuk seller menyertakan peran 'seller'."""
        data = {'username': 'seller', 'password': 'password123'}
        response = self.client.post(self.login_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user']['role'], 'seller')
        self.assertEqual(response.data['user']['initial_dashboard'], '/seller-dashboard')

    def test_login_response_includes_cashier_role(self):
        """Tes: Respons login untuk kasir menyertakan peran 'cashier'."""
        data = {'username': 'cashier', 'password': 'password123'}
        response = self.client.post(self.login_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user']['role'], 'cashier')
        self.assertEqual(response.data['user']['initial_dashboard'], '/cashier-dashboard')