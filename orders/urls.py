from django.urls import path
from .views import CashConfirmView, CreateOrderView, MidtransWehboohView, OrderDetailView, CancelOrderView

urlpatterns = [
  path("orders/create/", CreateOrderView.as_view(), name='create-order'),
  path("orders/<int:order_pk>/confirm-cash/", CashConfirmView.as_view(), name='confirm-cash'),
  path("webhooks/payment/", MidtransWehboohView.as_view(), name='payment-webhooks'),
  path('orders/<int:order_pk>/', OrderDetailView.as_view(), name='order-detail'),
  path('orders/<int:order_pk>/cancel/', CancelOrderView.as_view(), name='cancel-order')
]