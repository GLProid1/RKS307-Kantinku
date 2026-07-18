import hmac
import hashlib
import logging
import qrcode
import io
from decimal import Decimal
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.utils import timezone
from django.db import transaction, models
from django.db.models import Sum, Count, Avg, Q
from django.db.models.functions import TruncHour

from rest_framework import status, permissions, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle

from .models import Order, OrderItem, Customer, Table, PaymentWebhookLog
from .serializers import OrderSerializer, OrderCreateSerializer, TableSerializer
from .permissions import IsOrderTenantStaff, IsGuestOrderOwner, IsWithinOperationalHoursAndLocation
from .tasks import send_order_paid_notification, send_cash_order_invoice
from tenants.models import Tenant, MenuItem
from tenants.serializers import MenuItemSerializer

security_logger = logging.getLogger('security')

# Placeholder: dummy gateway payment
def initiate_payment_for_order(order: Order):
    import midtransclient
    snap = midtransclient.Snap(
        is_production=False,
        server_key=settings.MIDTRANS_SERVER_KEY,
        client_key=settings.MIDTRANS_CLIENT_KEY
    )

    param = {
        "transaction_details": {
            "order_id": order.references_code,
            "gross_amount": int(float(order.total))
        },
        "item_details": [{
            "id": item.menu_item.id,
            "price": int(float(item.price)),
            "quantity": item.qty,
            "name": item.menu_item.name
        } for item in order.items.all()],
        "customer_details": {
            "first_name": order.customer.name if order.customer else "Pelanggan",
            "email": order.customer.email if order.customer else "noemail@kantinku.com",
        }
    }

    transaction = snap.create_transaction(param)
    return transaction


class PopularMenusView(generics.ListAPIView):
    """
    Mengembalikan daftar menu yang paling banyak dipesan (populer)
    dari semua stand yang aktif dan menu yang tersedia.
    """
    serializer_class = MenuItemSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        top_menu_item_ids = OrderItem.objects.values('menu_item_id') \
            .annotate(total_sold=Sum('qty')) \
            .filter(total_sold__gt=0) \
            .order_by('-total_sold') \
            .values_list('menu_item_id', flat=True)[:10]

        top_menu_items = MenuItem.objects.filter(
            pk__in=list(top_menu_item_ids),
            available=True,
            tenant__active=True
        ).prefetch_related('tenant')

        items_map = {item.id: item for item in top_menu_items}
        sorted_items = [items_map[item_id] for item_id in top_menu_item_ids if item_id in items_map]
        
        return sorted_items


class OrderCreateAPIView(APIView):
    """
    Endpoint tunggal yang bersih untuk membuat pesanan (Dine-In & Takeaway).
    Logika database dan validasi ditangani oleh OrderCreateSerializer.create().
    """
    permission_classes = [IsWithinOperationalHoursAndLocation]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'burst'

    def post(self, request, *args, **kwargs):
        serializer = OrderCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        
        # Eksekusi method create() di serializer dengan Atomic Transaction
        order = serializer.save()

        # Handle Payment Gateway & Email Notifications
        payment_info = None
        if order.payment_method == 'TRANSFER':
            payment_info = initiate_payment_for_order(order)
        elif order.payment_method == 'CASH':
            # Kirim PIN asli ke email pembeli via Celery
            transaction.on_commit(lambda: send_cash_order_invoice.delay(order.pk, order.cashier_pin))

        # Handle Guest Session
        if not request.user.is_authenticated:
            guest_uuids = request.session.get('guest_order_uuids', [])
            if str(order.uuid) not in guest_uuids:
                guest_uuids.append(str(order.uuid))
                request.session['guest_order_uuids'] = guest_uuids

        # Buat HMAC Guest Token
        guest_token = hmac.new(
            settings.SECRET_KEY.encode(),
            str(order.uuid).encode(),
            hashlib.sha256
        ).hexdigest()

        order_response_data = OrderSerializer(order, context={'request': request}).data

        resp = {
            'order': order_response_data,
            'payment': payment_info,
            'token': guest_token,
            'snap_token': payment_info.get('token') if payment_info else None
        }
        return Response(resp, status=status.HTTP_201_CREATED)


class MidtransWebhookView(APIView):
    """
    Webhook untuk menerima callback pembayaran otomatis dari Midtrans.
    Dilengkapi dengan perlindungan HMAC Timing Attack dan Idempotency.
    """
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'webhook'

    def post(self, request):
        payload = request.data
        order_id = payload.get("order_id")
        transaction_status = payload.get("transaction_status")
        gross_amount = payload.get("gross_amount")
        transaction_id = payload.get("transaction_id")
        signature_key = payload.get("signature_key")

        safe_payload = payload.copy()
        sensitive_keys = ['customer_details', 'va_numbers', 'bca_va_number', 'payment_amounts']
        for key in sensitive_keys:
            if key in safe_payload:
                safe_payload[key] = "***REDACTED***"

        server_key = settings.MIDTRANS_SERVER_KEY
        raw_signature = f"{order_id}{payload.get('status_code')}{gross_amount}{server_key}"
        calculated_signature = hashlib.sha512(raw_signature.encode()).hexdigest()
        
        if not hmac.compare_digest(str(signature_key), calculated_signature):
            security_logger.warning(f"SECURITY_ALERT: Invalid Signature detected for Order {order_id}. Possible spoofing.")
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        log_qs = PaymentWebhookLog.objects.filter(transaction_id=transaction_id, status=transaction_status)
        if log_qs.exists():
            return Response({"detail": "Idempotency: Already processed"}, status=200)

        try:
            with transaction.atomic():
                order = Order.objects.select_for_update().get(references_code=order_id)
                
                if Decimal(str(gross_amount)) != order.total:
                    security_logger.critical(f"SECURITY_ALERT: Amount Mismatch! Order {order_id} total is {order.total}, but webhook sent {gross_amount}.")
                    return Response({"detail": "Amount Mismatch"}, status=status.HTTP_400_BAD_REQUEST)

                PaymentWebhookLog.objects.create(
                    order=order,
                    transaction_id=transaction_id,
                    payload=safe_payload,
                    status=transaction_status,
                    signature_valid=True
                )

                if order.status == 'PAID':
                    security_logger.info(f"Replay/Late callback detected for already PAID order {order_id}.")
                    return Response({"detail": "Already PAID"}, status=200)

                if transaction_status in ['settlement', 'capture']:
                    order.status = "PAID"
                    order.paid_at = timezone.now()
                    order.save(update_fields=['status', 'paid_at'])
                    transaction.on_commit(lambda: send_order_paid_notification.delay(order.pk))
                elif transaction_status in ['expire', 'cancel', 'deny']:
                    order.cancel_and_restock()

        except Order.DoesNotExist:
            return Response({"detail": "Not Found"}, status=404)
        
        return Response({"detail": "OK"}, status=200)


class OrderListView(generics.ListAPIView):
    """
    View untuk menampilkan daftar semua pesanan dengan filter status & tenant.
    """
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        Order.objects.filter(
            status='AWAITING_PAYMENT',
            expired_at__lt=timezone.now()
        ).update(status='EXPIRED')
        
        base_qs = Order.objects.all()
        satu_hari_lalu = timezone.now() - timedelta(days=1)
        base_qs = base_qs.exclude(
            status='EXPIRED',
            created_at__lt=satu_hari_lalu
        )

        if not user.is_staff and not user.groups.filter(name='Cashier').exists():
            user_tenant_ids = user.tenants.values_list('id', flat=True)
            base_qs = base_qs.filter(tenant_id__in=user_tenant_ids)
            base_qs = base_qs.exclude(status__in=['EXPIRED', 'CANCELED', 'COMPLETED'])
        
        status_param = self.request.query_params.get('status')
        payment_method = self.request.query_params.get('payment_method')

        if status_param:
            base_qs = base_qs.filter(status=status_param)
        if payment_method:
            base_qs = base_qs.filter(payment_method=payment_method)

        return base_qs.prefetch_related(
            'items', 'items__menu_item', 'tenant', 'table'
        ).order_by('-created_at')


class OrderDetailView(generics.RetrieveAPIView):
    queryset = Order.objects.all().select_related('customer', 'tenant')
    serializer_class = OrderSerializer
    permission_classes = [IsOrderTenantStaff | IsGuestOrderOwner]
    lookup_field = 'uuid'
    lookup_url_kwarg = 'order_uuid'

    def get_object(self):
        obj = super().get_object()
        if obj.expired_at and timezone.now() > obj.expired_at and obj.status != 'EXPIRED':
            obj.status = 'EXPIRED'
            obj.save(update_fields=['status'])
        return obj


class CancelOrderView(APIView):
    permission_classes = [IsOrderTenantStaff | IsGuestOrderOwner]
  
    def post(self, request, order_uuid):
        order = get_object_or_404(Order, uuid=order_uuid)
        self.check_object_permissions(request, order)
        
        if order.status.upper() == 'PAID':
            return Response({"detail": "Order sudah dibayar, tidak bisa dibatalkan"}, status=status.HTTP_400_BAD_REQUEST)

        if order.status == 'AWAITING_PAYMENT':
            if order.expired_at and timezone.now() > order.expired_at:
                order.status = 'EXPIRED'
                order.save(update_fields=['status'])
            order.cancel_and_restock()
            return Response({"detail": "Order berhasil dibatalkan"}, status=status.HTTP_200_OK)
        elif order.status == 'EXPIRED':
            order.status = 'EXPIRED'
            order.cancel_and_restock()
            return Response({"detail": "Order kedaluwarsa berhasil dibatalkan"}, status=status.HTTP_200_OK)

        return Response({"detail": f"Order dengan status {order.status} tidak dapat dibatalkan."}, status=status.HTTP_400_BAD_REQUEST)


class UpdateOrderStatusView(APIView):
    permission_classes = [IsAuthenticated, IsOrderTenantStaff]

    VALID_TRANSITIONS = {
        'AWAITING_PAYMENT': ['PAID'],
        'PAID': ['PROCESSING'],
        'PROCESSING': ['READY'],
        'READY': ['COMPLETED']
    }
    
    def patch(self, request, order_uuid):
        order = get_object_or_404(Order, uuid=order_uuid)
        self.check_object_permissions(request, order)
        
        new_status = request.data.get('status')
        if not new_status:
            return Response({"detail": "Field 'status' diperlukan"}, status=status.HTTP_400_BAD_REQUEST)
        if new_status == 'PAID' and order.payment_method == 'TRANSFER':
            return Response(
                {"detail": "Pesanan Transfer hanya bisa diubah menjadi LUNAS secara otomatis oleh Midtrans."}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        current_status = order.status
        allowed_next_statues = self.VALID_TRANSITIONS.get(current_status)
        
        if not allowed_next_statues or new_status not in allowed_next_statues:
            return Response({"detail": f"Perubahan dari status '{current_status}' ke '{new_status}' tidak diperbolehkan"})
        
        order.status = new_status
        order.save(update_fields=['status'])
        
        return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)


class TableQRCodeView(APIView):
    permission_classes = [permissions.AllowAny] 

    def get(self, request, table_code):
        table = get_object_or_404(Table, code=table_code)
        frontend_base_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')
        
        encrypted_token = signing.dumps({'table_code': table.code})
        qr_url = f"{frontend_base_url}/?token={encrypted_token}"
        
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
        qr.add_data(qr_url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, "PNG")
        buffer.seek(0)
        
        return HttpResponse(buffer, content_type="image/png")


class TakeawayQRCodeView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, tenant_id):
        tenant = get_object_or_404(Tenant, pk=tenant_id)
        frontend_base_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')
        frontend_url = f"{frontend_base_url}/?tenant={tenant.pk}&order_type=TAKEAWAY"
        
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(frontend_url)
        img = qr.make_image(fill_color="black", back_color="white")
        
        buffer = io.BytesIO()
        img.save(buffer, "PNG")
        buffer.seek(0)
        
        return HttpResponse(buffer, content_type="image/png")
        

class TableListCreateView(generics.ListCreateAPIView):
    queryset = Table.objects.all().order_by("code")
    serializer_class = TableSerializer
    permission_classes = [permissions.IsAdminUser]


class TableDetailView(generics.DestroyAPIView):
    queryset = Table.objects.all()
    serializer_class = TableSerializer
    permission_classes = [permissions.IsAdminUser]
    

class ReportDashboardAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        one_week_ago = timezone.now() - timedelta(days=7)
        user = request.user 
        
        tenant_filter = models.Q()
        user_tenant_ids = []
        if not user.is_staff:
            user_tenant_ids = user.tenants.values_list('id', flat=True)
            tenant_filter = models.Q(tenant_id__in=user_tenant_ids)
        
        main_stats = {'total_revenue': 0, 'total_orders': 0, 'avg_order_value': 0, 'active_customers': 0}
        if user.is_staff:
            total_revenue = Order.objects.filter(status='PAID').aggregate(total=Sum('total'))['total'] or 0
            total_orders = Order.objects.count()
            avg_order_value = Order.objects.filter(status='PAID').aggregate(avg=Avg('total'))['avg'] or 0
            active_customers = Order.objects.filter(created_at__gte=one_week_ago).values('customer').distinct().count()
            main_stats.update({
                'total_revenue': total_revenue, 'total_orders': total_orders, 
                'avg_order_value': avg_order_value, 'active_customers': active_customers
            })

        today = timezone.now().date()
        today_orders_qs = Order.objects.filter(tenant_filter, created_at__date=today)
        
        stats_today = {
            'total': today_orders_qs.count(),
            'pending': today_orders_qs.filter(status='AWAITING_PAYMENT').count(),
            'preparing': today_orders_qs.filter(Q(status='PAID') | Q(status='PROCESSING')).count(),
            'completed': today_orders_qs.filter(status='COMPLETED').count()
        }

        sales_by_hour = Order.objects.filter(tenant_filter, created_at__gte=timezone.now() - timedelta(days=1)) \
            .annotate(hour=TruncHour('created_at')) \
            .values('hour') \
            .annotate(orders=Count('id')) \
            .order_by('hour')

        # Optimasi Query: Tidak perlu filter jika yang login adalah Admin
        top_selling_qs = OrderItem.objects.all()
        if not user.is_staff:
            top_selling_qs = top_selling_qs.filter(order__tenant_id__in=user_tenant_ids)

        top_selling_products = top_selling_qs \
            .values('menu_item__name') \
            .annotate(total_sold=Sum('qty'), total_revenue=Sum('price')) \
            .order_by('-total_sold')[:5]

        stand_performance_qs = Tenant.objects.all()
        if not user.is_staff:
            stand_performance_qs = stand_performance_qs.filter(id__in=user_tenant_ids)

        stand_performance = stand_performance_qs.annotate(
            total_orders_today=Count('orders', filter=models.Q(orders__created_at__date=today)),
            total_revenue_today=Sum('orders__total', filter=models.Q(orders__status='PAID', orders__created_at__date=today))
        ).order_by('-total_revenue_today')

        formatted_stand_performance = [
            {'name': stand.name, 'orders': stand.total_orders_today, 'revenue': float(stand.total_revenue_today or 0)}
            for stand in stand_performance
        ]

        data = {
            'main_stats': main_stats,
            'stats_today': stats_today, 
            'sales_by_hour': [
                {'hour': item['hour'].strftime('%H'), 'orders': item['orders']}
                for item in sales_by_hour
            ],
            'top_selling_products': list(top_selling_products),
            'stand_performance': formatted_stand_performance,
        }
        return Response(data, status=status.HTTP_200_OK)
