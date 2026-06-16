import hmac
import hashlib
import logging
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from django.db import transaction
from django.db import models
from django.db.models import Sum, Count, Avg, Q, OuterRef, Subquery, IntegerField
from django.db.models.functions import TruncHour
from django.contrib.auth.models import User, Group
from rest_framework import status, permissions, generics, viewsets, serializers
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle
from decimal import Decimal
from rest_framework.throttling import AnonRateThrottle

from django.contrib.auth.hashers import make_password
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions, generics, viewsets, serializers
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated, OR
from rest_framework.throttling import AnonRateThrottle

from .models import Order, OrderItem, Customer, MenuItem, Tenant, Table, generate_order_pin, PaymentWebhookLog
from .serializers import (
    OrderSerializer, OrderCreateSerializer
)
from .permissions import (
    IsOrderTenantStaff, IsGuestOrderOwner
)
from .tasks import send_order_paid_notification, send_cash_order_invoice
from tenants.models import Tenant, MenuItem, VariantOption
from tenants.serializers import MenuItemSerializer
import qrcode
import io

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
            "first_name": order.customer.name,
            "email": order.customer.email,
        }
    }

    transaction = snap.create_transaction(param)
    return transaction

class PopularMenusView(generics.ListAPIView):
    """
    Mengembalikan daftar menu yang paling banyak dipesan (populer)
    dari semua stand yang aktif dan menu yang tersedia.
    (Versi query yang sudah dioptimalkan)
    """
    serializer_class = MenuItemSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        # 1. Hitung 10 menu_item_id terlaris dari tabel OrderItem
        # Ini adalah query pertama (cepat)
        top_menu_item_ids = OrderItem.objects.values('menu_item_id') \
            .annotate(total_sold=Sum('qty')) \
            .filter(total_sold__gt=0) \
            .order_by('-total_sold') \
            .values_list('menu_item_id', flat=True)[:10]

        # 2. Ambil objek MenuItem yang lengkap berdasarkan 10 ID teratas
        #    Pastikan juga tenant-nya aktif & item-nya available
        # Ini adalah query kedua (cepat)
        top_menu_items = MenuItem.objects.filter(
            pk__in=list(top_menu_item_ids), # Ambil hanya yang ID-nya ada di daftar
            available=True,
            tenant__active=True
        ).prefetch_related('tenant') # Optimalisasi

        # 3. Buat dictionary untuk memetakan id -> item
        items_map = {item.id: item for item in top_menu_items}
        
        # 4. Kembalikan daftar yang sudah terurut berdasarkan 'top_menu_item_ids'
        #    (karena 'pk__in' tidak menjamin urutan)
        sorted_items = [items_map[item_id] for item_id in top_menu_item_ids if item_id in items_map]
        
        return sorted_items



class CreateOrderView(APIView):
  permission_classes = [permissions.AllowAny]
  throttle_classes = [ScopedRateThrottle] # Gunakan Scoped global
  throttle_scope = 'burst'

  def post(self, request):
    serializer = OrderCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    data = serializer.validated_data
    tenant = get_object_or_404(Tenant, pk=data['tenant'], active=True)
    table = None
    if data.get('table'):
      table,_ = Table.objects.get_or_create(code=data['table'])

    customer = None
    name = data.get('name')
    email = data.get('email')
    phone = data.get('phone')
    if email:
      customer, _ = Customer.objects.get_or_create(email=email, defaults={'name': name, 'phone': phone})
      
    try:
      with transaction.atomic():
        items_data = data['items']
        menu_item_ids = [item['menu_item'] for item in items_data]
        menu_items_to_update = MenuItem.objects.select_for_update().filter(pk__in=menu_item_ids, tenant=tenant)
        
        menu_items_map = {item.pk: item for item in menu_items_to_update}

        for item_data in items_data:
            menu_item = menu_items_map.get(item_data['menu_item'])
            if not menu_item or not menu_item.available or menu_item.stock < item_data['qty']:
                raise serializers.ValidationError(f"Stok untuk '{menu_item.name if menu_item else 'item'}' tidak mencukupi atau tidak tersedia.")

        cashier_pin_db = None
        plain_pin_for_email = None 

        if data['payment_method'] == 'CASH':
            while True:
                pin = generate_order_pin() # PIN Asli (contoh: 123456)
                
                # Buat Hash SHA-256 dari PIN untuk disimpan di DB
                hashed_pin = make_password(pin)
                
                if not Order.objects.filter(cashier_pin=hashed_pin, status__in=['AWAITING_PAYMENT', 'PAID']).exists():
                    cashier_pin_db = hashed_pin     # Simpan Hash ke DB
                    plain_pin_for_email = pin       # Simpan Asli untuk Email & Respons Frontend
                    break

        order = Order.objects.create(
          tenant=tenant, table=table, customer=customer,
          payment_method=data['payment_method'],
          status = 'AWAITING_PAYMENT',
          cashier_pin=cashier_pin_db, # Simpan HASH di database
          expired_at = timezone.now() + timezone.timedelta(minutes=10)
        )

        order_items_to_create = []
        total = 0
        for item_data in items_data:
            menu_item = menu_items_map[item_data['menu_item']]
            
            variant_ids = item_data.get('variants', [])
            total_variant_price = 0
            if variant_ids:
                valid_variants = VariantOption.objects.filter(
                    id__in=variant_ids,
                    group__menu_items=menu_item
                )
                if len(valid_variants) != len(variant_ids):
                    raise serializers.ValidationError("Terdapat varian yang tidak valid untuk menu yang dipilih.")
                
                for variant in valid_variants:
                    total_variant_price += variant.price

            item_final_price = menu_item.price + total_variant_price
            
            order_item_obj = OrderItem(
                order=order,
                menu_item=menu_item,
                qty=item_data['qty'],
                price=item_final_price,
                note=item_data.get('note', '')
            )
            
            order_items_to_create.append(order_item_obj)
            total += item_final_price * item_data['qty']
            menu_item.stock -= item_data['qty']
        
        MenuItem.objects.bulk_update(menu_items_to_update, ['stock'])
        created_items = OrderItem.objects.bulk_create(order_items_to_create)

        item_variant_relations = []
        for i, item_data in enumerate(items_data):
            variant_ids = item_data.get('variants', [])
            if variant_ids:
                order_item_id = created_items[i].id
                for variant_id in variant_ids:
                    item_variant_relations.append(
                        OrderItem.selected_variants.through(
                            orderitem_id=order_item_id,
                            variantoption_id=variant_id
                        )
                    )
                
        if item_variant_relations:
            OrderItem.selected_variants.through.objects.bulk_create(item_variant_relations)
        
        order.total = total
        order.save(update_fields=['total'])

    except serializers.ValidationError as e:
        return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)
    
    payment_info = None
    if order.payment_method.strip().upper() == 'TRANSFER':
        payment_info = initiate_payment_for_order(order)
    elif order.payment_method.strip().upper() == 'CASH':
        transaction.on_commit(lambda: send_cash_order_invoice.delay(order.pk, plain_pin_for_email))
            
    if not request.user.is_authenticated:
        guest_uuids = request.session.get('guest_order_uuids', [])
        if str(order.uuid) not in guest_uuids:
            guest_uuids.append(str(order.uuid))
            request.session['guest_order_uuids'] = guest_uuids
        
    guest_token = hmac.new(
        settings.SECRET_KEY.encode(),
        str(order.uuid).encode(),
        hashlib.sha256
    ).hexdigest()
        
    order_response_data = OrderSerializer(order, context={'request': request}).data
        
    if plain_pin_for_email:
        order_response_data['cashier_pin'] = plain_pin_for_email

    # PERBAIKAN 2: Tambahkan 'snap_token' agar bisa dibaca oleh Frontend
    resp = {
        'order': order_response_data,
        'payment': payment_info,
        'token': guest_token,
        'snap_token': payment_info.get('token') if payment_info else None
    }
    return Response(resp, status=status.HTTP_201_CREATED)


security_logger = logging.getLogger('security')

    
class MidtransWehboohView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'webhook' # Batasi spam rate

    def post(self, request):
        payload = request.data
        order_id = payload.get("order_id")
        transaction_status = payload.get("transaction_status")
        gross_amount = payload.get("gross_amount")
        transaction_id = payload.get("transaction_id")
        signature_key = payload.get("signature_key")

        # 1. Sanitasi Payload (Poin 7)
        safe_payload = payload.copy()
        sensitive_keys = ['customer_details', 'va_numbers', 'bca_va_number', 'payment_amounts']
        for key in sensitive_keys:
            if key in safe_payload:
                safe_payload[key] = "***REDACTED***"

        # 2. Validasi Signature (Hmac Compare Digest)
        server_key = settings.MIDTRANS_SERVER_KEY
        raw_signature = f"{order_id}{payload.get('status_code')}{gross_amount}{server_key}"
        calculated_signature = hashlib.sha512(raw_signature.encode()).hexdigest()
        
        if not hmac.compare_digest(str(signature_key), calculated_signature):
            # Hook untuk Wazuh (Poin 8 - Warning/High)
            security_logger.warning(f"SECURITY_ALERT: Invalid Signature detected for Order {order_id}. Possible spoofing.")
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        # 3. Idempotency Key Kuat (Poin 1)
        # Kombinasi transaction_id + status agar callback update (ex: pending -> settlement) tetap masuk
        log_qs = PaymentWebhookLog.objects.filter(transaction_id=transaction_id, status=transaction_status)
        if log_qs.exists():
            return Response({"detail": "Idempotency: Already processed"}, status=200)

        try:
            with transaction.atomic():
                order = Order.objects.select_for_update().get(references_code=order_id)
                
                # 4. Validasi Gross Amount (Poin 10 - CRITICAL)
                # Gunakan Decimal agar tidak ada presisi float yang meleset
                if Decimal(str(gross_amount)) != order.total:
                    security_logger.critical(f"SECURITY_ALERT: Amount Mismatch! Order {order_id} total is {order.total}, but webhook sent {gross_amount}.")
                    return Response({"detail": "Amount Mismatch"}, status=status.HTTP_400_BAD_REQUEST)

                # Simpan Log dengan payload tersanitasi
                PaymentWebhookLog.objects.create(
                    order=order,
                    transaction_id=transaction_id,
                    payload=safe_payload,
                    status=transaction_status,
                    signature_valid=True
                )

                if order.status == 'PAID':
                    # Replay detected logic (Poin 8)
                    security_logger.info(f"Replay/Late callback detected for already PAID order {order_id}.")
                    return Response({"detail": "Already PAID"}, status=200)

                # --- Lanjutkan logika update status settlement/cancel seperti biasa ---
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

class OrderDetailView(generics.RetrieveAPIView):
    # Menggunakan select_related agar data customer tersedia saat pengecekan permission
    queryset = Order.objects.all().select_related('customer', 'tenant')
    serializer_class = OrderSerializer
    permission_classes = [IsOrderTenantStaff | IsGuestOrderOwner]
    lookup_field = 'uuid'
    lookup_url_kwarg = 'order_uuid'

    def get_object(self):
        obj = super().get_object()
        
        # Logika Update Status Expired tetap bisa ditaruh di sini
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
  
class OrderCreateView(generics.CreateAPIView):
    serializer_class = OrderCreateSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'burst'

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        items_data = serializer.validated_data['items']
        tenant = serializer.validated_data['tenant']
        
        menu_item_ids = [item['menu_item'] for item in items_data]
        
        menu_items = MenuItem.objects.select_for_update().filter(
            id__in=menu_item_ids, 
            tenant_id=tenant
        )
        
        menu_items_map = {item.id: item for item in menu_items}

        for item_data in items_data:
            menu_item_id = item_data['menu_item']
            menu_item_obj = menu_items_map.get(menu_item_id)
            
            if not menu_item_obj:
                raise serializers.ValidationError(
                    f"Menu item dengan ID {menu_item_id} tidak ditemukan untuk tenant ini."
                )
            
            if not menu_item_obj.available:
                 raise serializers.ValidationError(f"'{menu_item_obj.name}' sedang tidak tersedia.")

            if menu_item_obj.stock < item_data['qty']:
                raise serializers.ValidationError(
                    f"Stok untuk '{menu_item_obj.name}' tidak mencukupi. Sisa: {menu_items_map[menu_item_id].stock}."
                )
            
            menu_item_obj.stock -= item_data['qty']

        MenuItem.objects.bulk_update(menu_items_map.values(), ['stock'])
        
        return super().create(request, *args, **kwargs)

# --- PERBAIKAN TOTAL UNTUK MASALAH DUPLIKAT DAN ASSERTIONERROR ---
class OrderListView(generics.ListAPIView):
    """
    View untuk menampilkan daftar semua pesanan.
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

        # --- PERBAIKAN LOGIKA IZIN ---
        # Jika user BUKAN Admin (is_staff) DAN BUKAN Kasir
       if not user.is_staff and not user.groups.filter(name='Cashier').exists():
            user_tenant_ids = user.tenants.values_list('id', flat=True)
            # PERBAIKAN: Pastikan status PAID diizinkan untuk dilihat Tenant
            # Tambahkan filter agar Tenant hanya melihat pesanan yang belum selesai
            base_qs = base_qs.filter(tenant_id__in=user_tenant_ids)
        
            # JANGAN EXCLUDE 'PAID', karena Kanban Tenant butuh status PAID untuk "Pesanan Baru"
            base_qs = base_qs.exclude(status__in=['EXPIRED', 'CANCELED', 'COMPLETED'])
        return base_qs.order_by('-created_at')
        # Admin dan Kasir akan melewati 'if' dan mendapatkan Order.objects.all()
        
        # --- TAMBAHAN: TERAPKAN FILTER DARI URL ---
        status = self.request.query_params.get('status')
        payment_method = self.request.query_params.get('payment_method')

        if status:
            base_qs = base_qs.filter(status=status)
        if payment_method:
            base_qs = base_qs.filter(payment_method=payment_method)
        # --- AKHIR TAMBAHAN ---

        # 4. Lakukan prefetch dan order_by SETELAH filter
        return base_qs.prefetch_related(
            'items', 'items__menu_item', 'tenant', 'table'
        ).order_by('-created_at')

class TableQRCodeView(APIView):
    permission_classes = [permissions.AllowAny] 

    def get(self, request, table_code):
        table = get_object_or_404(Table, code=table_code)
        frontend_url = request.build_absolute_uri(reverse('create-order')) + f"?table={table.code}"
        
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
        qr.add_data(frontend_url)
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
        frontend_url = request.build_absolute_uri(reverse('create-order')) + f"?tenant={tenant.pk}&order_type=TAKEAWAY"
        
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(frontend_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        buffer = io.BytesIO()
        img.save(buffer, "PNG")
        buffer.seek(0)
        
        return HttpResponse(buffer, content_type="image/png")

# --- PERBAIKAN TOTAL UNTUK MASALAH DUPLIKAT ---
class ReportDashboardAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        one_week_ago = timezone.now() - timedelta(days=7)
        user = request.user 
        
        # Buat filter dasar untuk digunakan kembali
        tenant_filter = models.Q()
        if not user.is_staff:
            user_tenant_ids = user.tenants.values_list('id', flat=True)
            tenant_filter = models.Q(tenant_id__in=user_tenant_ids)
        
        # Hanya admin yang bisa melihat statistik utama (total revenue, dll)
        main_stats = {'total_revenue': 0, 'total_orders': 0, 'avg_order_value': 0, 'active_customers': 0 }
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

        top_selling_products = OrderItem.objects.filter(order__tenant_id__in=user.tenants.values_list(
            'id', flat=True) if not user.is_staff else Tenant.objects.values_list('id', flat=True)) \
            .values('menu_item__name') \
            .annotate(total_sold=Sum('qty'), total_revenue=Sum('price')) \
            .order_by('-total_sold')[:5]

        stand_performance_qs = Tenant.objects.all()
        if not user.is_staff:
            stand_performance_qs = stand_performance_qs.filter(id__in=user_tenant_ids)

        stand_performance = stand_performance_qs.annotate(
            total_orders_today=Count('orders', filter=models.Q(orders__created_at__date=timezone.now().date())),
            total_revenue_today=Sum('orders__total', filter=models.Q(orders__status='PAID', orders__created_at__date=timezone.now().date()))
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
