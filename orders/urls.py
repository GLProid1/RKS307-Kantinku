# Lokasi: orders/urls.py

from django.urls import path
from .views import (
    CashConfirmView, CreateOrderView, MidtransWehboohView, 
    OrderDetailView, UpdateOrderStatusView, CancelOrderView, OrderListView,TableQRCodeView, TakeawayQRCodeView
)

urlpatterns = [
    path('', OrderListView.as_view(), name='order-list'),
    path("create/", CreateOrderView.as_view(), name='create-order'),
    path("<int:order_pk>/", OrderDetailView.as_view(), name='order-detail'),
    path("<int:order_pk>/confirm-cash/", CashConfirmView.as_view(), name='confirm-cash'),
    path('<int:order_pk>/cancel/', CancelOrderView.as_view(), name='cancel-order'),
    path('<int:order_pk>/update-status/', UpdateOrderStatusView.as_view(), name='update-order-status'),
    path("webhooks/payment/", MidtransWehboohView.as_view(), name='payment-webhooks'),path("tables/<str:table_code>/qr/", TableQRCodeView.as_view(), name='table-qr-code'),
    path("tenants/<int:tenant_id>/takeaway-qr/", TakeawayQRCodeView.as_view(), name='takeaway-qr-code'),
]