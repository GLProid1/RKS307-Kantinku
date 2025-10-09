from django.urls import path
from .views import CashConfirmView, CreateOrderView, MidtransWehboohView, OrderDetailView, UpdateOrderStatusView, CancelOrderView, OrderListView

urlpatterns = [
  path("orders/create/", CreateOrderView.as_view(), name='create-order'),
  path("orders/<int:order_pk>/confirm-cash/", CashConfirmView.as_view(), name='confirm-cash'),
   path('', OrderListView.as_view(), name='order-list'),
  path("webhooks/payment/", MidtransWehboohView.as_view(), name='payment-webhooks'),
  path('orders/<int:order_pk>/', OrderDetailView.as_view(), name='order-detail'),
  path('orders/<int:order_pk>/cancel/', CancelOrderView.as_view(), name='cancel-order'),
  path('orders/<int:order_pk>/update-status/' , UpdateOrderStatusView.as_view(), name='update-order-status')
]