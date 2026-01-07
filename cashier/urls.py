from django.urls import path, include
from .views import CashConfirmView, VerifyOrderByPinView

urlpatterns = [
     path("orders/verify-pin/", VerifyOrderByPinView.as_view(), name='verify-order-by-pin'),
     path("cash/confirm/<uuid:order_uuid>/", CashConfirmView.as_view(), name="cash-confirm")),
]
