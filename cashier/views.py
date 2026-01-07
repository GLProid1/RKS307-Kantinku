from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework import status, generics
from orders.models import Order
from orders.tasks import send_order_paid_notification
from orders.serializers import OrderSerializer
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from .permissions import IsCashierUser
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import logging
security_logger = logging.getLogger('security')


class CashConfirmView(APIView):
  authentication_classes = [TokenAuthentication]
  permission_classes = [IsAuthenticated, IsCashierUser]
  
  def post(self, request, order_uuid):
    order = get_object_or_404(Order, uuid=order_uuid)
    
    # Log security event
    security_logger.warning(
        f"Cash confirmation attempt by user {request.user.username}"
        f"for order {order.references_code}"
    )
    
    # Validasi awal: Cek status, metode pembayaran, dan kadaluwarsa
    if order.expired_at and timezone.now() > order.expired_at:
      if order.status != "EXPIRED":
        order.status = "EXPIRED"
        order.save(update_fields=['status'])
      return Response({"detail": "Order sudah kadaluarsa, silahkan buat order baru"}, status=status.HTTP_400_BAD_REQUEST)

    if order.payment_method != 'CASH':
      return Response({"detail": "Metode pembayaran ini bukan CASH"}, status=status.HTTP_400_BAD_REQUEST)

    if order.status.upper() == 'PAID':
      return Response({"detail": "Order sudah dibayar"}, status=status.HTTP_400_BAD_REQUEST)
    
    # Transaksi atomik untuk memastikan integritas data
    with transaction.atomic():
      # Kunci order untuk mencegah race condition (SELECT FOR UPDATE)
      order = Order.objects.select_for_update().get(pk=order.pk)
      # Validasi ulang di dalam transaksi untuk keamanan
      if order.status.upper() != "AWAITING_PAYMENT":
        return Response({"detail": "Order sudah dibayar"}, status=status.HTTP_400_BAD_REQUEST)
      
      confirmation_time = timezone.now()
      order.status = "PAID"
      order.paid_at = confirmation_time
      meta = order.meta or {}
      meta.setdefault("payments", []).append({
        "method":"CASH",
        "confirmed_by": request.user.username if request.user.is_authenticated else "anonymous",
        "confirmed_at": confirmation_time.isoformat()
      })
      order.meta = meta
      order.save(update_fields=['status', 'paid_at', 'meta'])

      # Panggil Celery task setelah transaksi berhasil lakukan
      transaction.on_commit(lambda: send_order_paid_notification.delay(order.id))

    return Response({
      "detail": "Order dikonfirmasi lunas.",
      "order": OrderSerializer(order).data,
    }, status=status.HTTP_200_OK)

class VerifyPinThrottle(UserRateThrottle):
    scope = 'burst' # Gunakan limit misal 5 kali per menit

class VerifyOrderByPinView(APIView):
    """
    Endpoint untuk kasir memverifikasi order berdasarkan PIN dari pelanggan.
    """
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated, IsCashierUser]
    throttle_classes = [VerifyPinThrottle]
    def post(self, request):
      pin = request.data.get('pin')
      if not pin:
        return Response({'detail': "PIN diperlukan"}, status=status.HTTP_400_BAD_REQUEST)
      
      try:
        # Cari order yang masing menunggu pembayaran, metode CASH, dan cocok dengan PIN-nya
        order = Order.objects.get(
          cashier_pin=pin,
          status='AWAITING_PAYMENT',
          payment_method="CASH"
        )
      except Order.DoesNotExist:
        return Response({'detail': 'PIN tidak valid atau pesanan tidak tersedia.'}, status=status.HTTP_404_NOT_FOUND)
      return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)
