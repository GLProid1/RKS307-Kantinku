from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from .models import Tenant, MenuItem

class OrderAPITests(APITestCase):
    def setUp(self):
        """Set up data untuk semua test case di class ini."""
        self.tenant = Tenant.objects.create(name="Warung Seblak", active=True)
        self.menu_item1 = MenuItem.objects.create(
            tenant=self.tenant, name="Seblak Original", price=15000, available=True
        )
        self.menu_item2 = MenuItem.objects.create(
            tenant=self.tenant, name="Es Teh Manis", price=5000, available=True
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
