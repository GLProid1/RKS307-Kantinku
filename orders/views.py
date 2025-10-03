from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.shortcuts import get_object_or_404
from .models import Order, OrderItem, Customer, MenuItem, Tenant, Table
from .serializers import OrderSerializer, OrderCreateSerializer
from django.utils import timezone
from .permissions import IsKasir
from django.db import transaction
from .tasks import send_order_paid_notification

# Placeholder: dummy gateway payment
def initiate_payment_for_order(order: Order):
  payload = {
    'method': 'VA',
    'va_number': f'VA{order.references_code[-6:]}',
    'bank': 'EXAMPLEBANK',
    'expired_at': (timezone.now() + timezone.timedelta(hours=6)).isoformat()
  }
  order.meta.update({'payment': payload})
  order.save(update_fields=['meta'])
  return payload

class CreateOrderView(APIView):
  permission_classes = [permissions.AllowAny]

  def post(self, request):
    serializer = OrderCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    data = serializer.validated_data
    tenant = get_object_or_404(Tenant, pk=data['tenant'], active=True)
    table = None
    if data.get('table'):
      table,_ = Table.objects.get_or_create(code=data['table'])

    customer = None
    phone = data.get('phone')
    if phone:
      customer, _ = Customer.objects.get_or_create(phone=phone)
      

    # Create order
    order = Order.objects.create(
      tenant=tenant,
      table=table,
      customer=customer,
      payment_method=data['payment_method'],
      status = 'AWAITING_PAYMENT',
      expired_at = timezone.now() + timezone.timedelta(minutes=10)
    )
    
    # Create items and compute total
    total = 0
    for it in data['items']:
      menu = get_object_or_404(MenuItem, pk=it['menu_item'], tenant=tenant)
      io = OrderItem.objects.create(
        order=order,
        menu_item=menu,
        qty=it['qty'],
        price=menu.price,
        note=it.get('note', '')
      )
      total += io.price * io.qty
      
    order.total = total
    order.save()
    
    # If payment_methods == TRANSFER -> initiate payment (VA/link) and return instructions
    payment_info = None
    if order.payment_method == 'TRANSFER':
      payment_info = initiate_payment_for_order(order)
      # order remains AWAITING_PAYMENT until webhook or manual confirm
    else:
      # CASH: client gets references_code and must pay to kasih
      # Optionally, generate invoice or send notification via Celery task
      pass
    
    resp = {
      'order': OrderSerializer(order, context={'request': request}).data,
      'payment': payment_info
    }
    return Response(resp, status=status.HTTP_201_CREATED)
  
class MidtransWehboohView(APIView):
    """
    Skeleton webhook for payment gateway notifications.
    This endpoint must:
    - Validate signature/auth of the gateway
    - Find order based on metadata (external_id, order_id, VA number, etc.)
    - Update order.status -> PAID when settled
    """
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
      payload = request.data
      # Validate signature here (gateway specific)
      external_id = payload.get("external_id") or payload.get("order_id") or None
      status_code = payload.get("transaction_status") or payload.get('status')
      # Map to order; this depends on how you set external_id when creating charge
      if not external_id:
        return Response({"detail": 'tidak ada external_id'}, status=status.HTTP_404_NOT_FOUND)
      
      try:
        order = Order.objects.get(references_code=external_id)
      except Order.DoesNotExist:
        return Response({"detail": "Order tidak ditemukan"}, status=status.HTTP_404_NOT_FOUND)
      
      if order.expired_at and timezone.now() > order.expired_at:
        order.status = "EXPIRED"
        order.save(update_fields=["status"])
        return Response({"detail": "Order kadaluarsa, tidak bisa dibayar"}, status=400)

      
      # Gateway specific mapping: check settled/paid
      if status_code in ['settlement', 'paid', 'success']:
        order.status = "PAID"
        order.paid_at = timezone.now()
        order.meta.setdefault('gateway_notification', []).append(payload)
        order.save(update_fields=['status', 'paid_at', 'meta'])
        # enqueue notification to tenant/customer
        # send_order_paid_notification(order.id)
        return Response({'detail': 'Order marked paid'}, status=200)
      
      # Handle expired / canceled
      if status_code in ['expire', 'expired', 'cancel']:
        order.status = "CANCELLED"
        order.meta.setdefault('gateway_notification', []).append(payload)
        order.save(update_fields=['status', 'meta'])
        return Response({"detail": "Order Cancelled"}, status=200)
      
      # Else: keep pending and store payload
      order.meta.setdefault("gateway_notification", []).append(payload)
      order.save(update_fields=['meta'])
      return Response({"detail": "Ok"}, status=200)
    
class CashConfirmView(APIView):
  """ 
  Endpoint untuk Kasir mengkonfirmasi bahwa order CASH sudah dibayar.
  """
  permission_classes = [IsKasir]
  def post(self, request, order_pk):
    order = get_object_or_404(Order, pk=order_pk)
    
    if order.status.upper() == 'EXPIRED':
      return Response({"detail": "Order sudah kadaluarsa, tidak bisa dikonfirmasi"}, status=status.HTTP_400_BAD_REQUEST)

    # Jika sudah expired, maka pembayaran ditolak
    if order.expired_at and timezone.now() > order.expired_at:
      order.status = "EXPIRED"
      order.save(update_fields=['status'])
      return Response({"detail": "Order sudah kadaluarsa, silahkan buat order baru"}, status=status.HTTP_400_BAD_REQUEST)

    if order.payment_method != 'CASH':
      return Response({"detail": f"Metode pembayaran ini bukan CASH"}, status=status.HTTP_400_BAD_REQUEST)

    # Jika sudah dibayar, maka pembayaran ditolak
    if order.status.upper() == 'PAID':
      return Response({"detail": "Order sudah dibayar"}, status=status.HTTP_400_BAD_REQUEST)

    # Melakukan update secara atomik untuk menghindari race
    with transaction.atomic():
      # Refresh dari DB untuk memastikan status terbaru
      order.refresh_from_db()
      
      # Doubel check status expired and paid
      if order.expired_at and timezone.now() > order.expired_at:
        order.status = "EXPIRED"
        order.save(update_fields=['status'])
        return Response({"detail": "Order sudah kadaluarsa, silahkan buat order baru"}, status=status.HTTP_400_BAD_REQUEST)
      
      if order.status.upper() == "PAID":
        return Response({"detail": "Order sudah dibayar"}, status=status.HTTP_400_BAD_REQUEST)
      
      # Update status menjadi PAID
      order.status = "PAID"
      order.paid_at = timezone.now()
       # Simpan verifikasi pembayaran oleh kasir
      meta = order.meta or {}
      meta.setdefault("payments", []).append({
        "method":"CASH",
        "confirmed_by": request.user.username if request.user.is_authenticated else "anonymous",
        "confirmed_at": order.paid_at.isoformat()
      })
      order.meta = meta
      order.save(update_fields=['status', 'paid_at', 'meta'])
      
    return Response({
      "detail": "Order dikonfirmasi lunas.",
      "order": {
        "id": order.pk,
        "references_code": order.references_code,
        "status": order.status,
        "paid_at": order.paid_at,
      }
    }, status=status.HTTP_200_OK)
    
class OrderDetailView(APIView):
  # permission_classes = [permissions.IsAuthenticated]
  
  def get(self, request, order_pk):
    order = get_object_or_404(Order, pk=order_pk)
    
    # cek expired
    if order.expired_at and timezone.now() > order.expired_at and order.status != 'EXPIRED':
      order.status = 'EXPIRED'
      order.save(update_fields=['status'])
      
    serializer = OrderSerializer(order, context={'request': request})
    return Response(serializer.data, status=status.HTTP_200_OK)
  
class CancelOrderView(APIView):
  """
    Endpoint untuk costomer yang membatalakn order.
    berlaku untuk:
    - Order dengan status AWAITING_PAYMENT
    - Expired Order
    Jika sudah dibayar, maka tidak bisa dibatalkan
    dan dihapus secara otomatis
  """
  permission_classes = [permissions.AllowAny]
  
  def post(self, request, order_pk):
    order = get_object_or_404(Order, pk=order_pk)
    
    # Jika sudah dibayar, maka tidak bisa dibatalkan
    if order.status.upper() == 'PAID':
      return Response({"detail": "Order sudah dibayar, tidak bisa dibatalkan"}, status=status.HTTP_400_BAD_REQUEST)
    
    if order.expired_at and timezone.now() > order.expired_at:
      order.status = 'EXPIRED'
      order.save(update_fields=['status'])
      
    # Jika awaiting payment, maka bisa dibatalkan
    order.delete()
    return Response({"detail": "Order berhasil dibatalkan dan dihapus"}, status=status.HTTP_200_OK)
  