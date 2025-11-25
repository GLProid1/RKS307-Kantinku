from django.urls import path, include
from .views import CashConfirmView, VerifyOrderByPinView

urlpatterns = [
     path("orders/verify-pin/", VerifyOrderByPinView.as_view(), name='verify-order-by-pin'),
     path("orders/<uuid:order_uuid>/confirm-cash/", CashConfirmView.as_view(), name='confirm-cash'),
]
