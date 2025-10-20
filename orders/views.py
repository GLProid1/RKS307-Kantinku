from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from django.db import transaction
from django.db import models
from django.db.models import Sum, Count, Avg, Q
from django.db.models.functions import TruncHour
from django.contrib.auth.models import User, Group
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions, generics, viewsets, serializers
from rest_framework.decorators import action

from .models import Order, OrderItem, Customer, MenuItem, Tenant, Table, VariantOption
from .serializers import (
    OrderSerializer, OrderCreateSerializer, MenuItemSerializer, UserSerializer,
    UserCreateSerializer, StandSerializer
)
# --- PERUBAHAN ---
# Impor izin baru kita dan OR operator
from .permissions import IsKasir, IsTenantOwner, IsGuestOrderOwner
from rest_framework.permissions import OR
# --- AKHIR PERUBAHAN ---
from .tasks import send_order_paid_notification

import qrcode
import io


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
      
    try:
      with transaction.atomic():
        # 1. Kunci baris menu item yang akan di-update untuk mencegah race condition
        items_data = data['items']
        menu_item_ids = [item['menu_item'] for item in items_data]
        menu_items_to_update = MenuItem.objects.select_for_update().filter(pk__in=menu_item_ids, tenant=tenant)
        
        menu_items_map = {item.pk: item for item in menu_items_to_update}

        # 2. Validasi stok sebelum membuat order
        for item_data in items_data:
            menu_item = menu_items_map.get(item_data['menu_item'])
            if not menu_item or not menu_item.available or menu_item.stock < item_data['qty']:
                raise serializers.ValidationError(f"Stok untuk '{menu_item.name if menu_item else 'item'}' tidak mencukupi atau tidak tersedia.")

        # 3. Buat Order
        order = Order.objects.create(
          tenant=tenant, table=table, customer=customer,
          payment_method=data['payment_method'],
          status = 'AWAITING_PAYMENT',
          expired_at = timezone.now() + timezone.timedelta(minutes=10)
        )

        # 4. Buat OrderItem dan kurangi stok
        order_items_to_create = []
        total = 0
        for item_data in items_data:
            menu_item = menu_items_map[item_data['menu_item']]
            
            # A. Hitung harga varian
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

            # B. Hitung harga final per item
            item_final_price = menu_item.price + total_variant_price
            
            # C. Buat objek OrderItem
            order_item_obj = OrderItem(
                order=order,
                menu_item=menu_item,
                qty=item_data['qty'],
                price=item_final_price, # <-- SIMPAN HARGA FINAL
                note=item_data.get('note', '')
            )
            
            order_items_to_create.append(order_item_obj)
            
            # D. Tambahkan ke total order
            total += item_final_price * item_data['qty']
            
            # E. Kurangi stok
            menu_item.stock -= item_data['qty']
        
        # 5. Simpan perubahan stok dan buat OrderItem secara bulk
        MenuItem.objects.bulk_update(menu_items_to_update, ['stock'])
        created_items = OrderItem.objects.bulk_create(order_items_to_create)

        # 6. Hubungkan varian ke OrderItem
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
    
    # If payment_methods == TRANSFER -> initiate payment (VA/link) and return instructions
    payment_info = None
    if order.payment_method == 'TRANSFER':
      payment_info = initiate_payment_for_order(order)
    else:
      # CASH: client gets references_code and must pay to kasih
      pass

    # --- PERUBAHAN ---
    # Simpan UUID order di session jika user adalah guest
    if not request.user.is_authenticated:
        guest_uuids = request.session.get('guest_order_uuids', [])
        if str(order.uuid) not in guest_uuids:
            guest_uuids.append(str(order.uuid))
            request.session['guest_order_uuids'] = guest_uuids
            # Optional: Anda bisa menambahkan logic untuk membatasi jumlah UUID di session
    # --- AKHIR PERUBAHAN ---
    
    resp = {
      'order': OrderSerializer(order, context={'request': request}).data,
      'payment': payment_info
    }
    return Response(resp, status=status.HTTP_201_CREATED)
  
class MidtransWehboohView(APIView):
    """
    Skeleton webhook for payment gateway notifications.
    """
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
      payload = request.data
      # Validate signature here (gateway specific)
      external_id = payload.get("external_id") or payload.get("order_id") or None
      status_code = payload.get("transaction_status") or payload.get('status')
      
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
        transaction.on_commit(lambda: send_order_paid_notification.delay(order.id))
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
  # --- PERUBAHAN ---
  # Menggunakan IsTenantOwner agar hanya staff tenant yg relevan yg bisa konfirmasi
  permission_classes = [IsTenantOwner]
  
  def post(self, request, order_uuid): # -> Menggunakan order_uuid
    order = get_object_or_404(Order, uuid=order_uuid) # -> Mencari berdasarkan uuid
    self.check_object_permission(request, order) # -> Menjalankan cek object permission
    # --- AKHIR PERUBAHAN ---
    
    if order.status.upper() == 'EXPIRED':
      return Response({"detail": "Order sudah kadaluarsa, tidak bisa dikonfirmasi"}, status=status.HTTP_400_BAD_REQUEST)

    if order.expired_at and timezone.now() > order.expired_at:
      order.status = "EXPIRED"
      order.save(update_fields=['status'])
      return Response({"detail": "Order sudah kadaluarsa, silahkan buat order baru"}, status=status.HTTP_400_BAD_REQUEST)

    if order.payment_method != 'CASH':
      return Response({"detail": f"Metode pembayaran ini bukan CASH"}, status=status.HTTP_400_BAD_REQUEST)

    if order.status.upper() == 'PAID':
      return Response({"detail": "Order sudah dibayar"}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
      order.refresh_from_db()
      
      if order.expired_at and timezone.now() > order.expired_at:
        order.status = "EXPIRED"
        order.save(update_fields=['status'])
        return Response({"detail": "Order sudah kadaluarsa, silahkan buat order baru"}, status=status.HTTP_400_BAD_REQUEST)
      
      if order.status.upper() == "PAID":
        return Response({"detail": "Order sudah dibayar"}, status=status.HTTP_400_BAD_REQUEST)
      
      order.status = "PAID"
      order.paid_at = timezone.now()
      meta = order.meta or {}
      meta.setdefault("payments", []).append({
        "method":"CASH",
        "confirmed_by": request.user.username if request.user.is_authenticated else "anonymous",
        "confirmed_at": order.paid_at.isoformat()
      })
      order.meta = meta
      order.save(update_fields=['status', 'paid_at', 'meta'])
      
      transaction.on_commit(lambda: send_order_paid_notification.delay(order.id))
      
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
  # --- PERUBAHAN ---
  # Mengizinkan staff tenant ATAU guest pemilik order
  permission_classes = [IsTenantOwner | IsGuestOrderOwner]
  
  def get(self, request, order_uuid): # -> Menggunakan order_uuid
    order = get_object_or_404(Order, uuid=order_uuid) # -> Mencari berdasarkan uuid
    self.check_object_permission(request, order) # -> Menjalankan cek object permission
    # --- AKHIR PERUBAHAN ---
      
    # cek expired
    if order.expired_at and timezone.now() > order.expired_at and order.status != 'EXPIRED':
      order.status = 'EXPIRED'
      order.save(update_fields=['status'])
      
    serializer = OrderSerializer(order, context={'request': request})
    return Response(serializer.data, status=status.HTTP_200_OK)
  
class CancelOrderView(APIView):
  """
    Endpoint untuk costomer atau kasir yang membatalakn order.
  """
  # --- PERUBAHAN ---
  # Mengizinkan staff tenant ATAU guest pemilik order
  permission_classes = [IsTenantOwner | IsGuestOrderOwner]
  
  def post(self, request, order_uuid): # -> Menggunakan order_uuid
    order = get_object_or_404(Order, uuid=order_uuid) # -> Mencari berdasarkan uuid
    self.check_object_permission(request, order) # -> Menjalankan cek object permission
    # --- AKHIR PERUBAHAN ---
    
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
  # --- PERUBAHAN ---
  # Menggunakan IsTenantOwner agar hanya staff tenant yg relevan yg bisa update
  permission_classes = [IsTenantOwner]
  # --- AKHIR PERUBAHAN ---
  
  """
    Endpoint untuk Tenant mengubah status order. ...
  """
  VALID_TRANSITIONS = {
    'PAID': ['PROCESSING'],
    'PROCESSING': ['READY'],
    'READY': ['COMPLETED']
  }
  
  # --- PERUBAHAN ---
  def patch(self, request, order_uuid): # -> Menggunakan order_uuid
    order = get_object_or_404(Order, uuid=order_uuid) # -> Mencari berdasarkan uuid
    self.check_object_permission(request, order) # -> Menjalankan cek object permission
  # --- AKHIR PERUBAHAN ---
    
    new_status = request.data.get('status')
    
    if not new_status:
      return Response({"detail": "Field 'status' diperlukan"}, status=status.HTTP_400_BAD_REQUEST)
    current_status = order.status
    allowed_next_statues = self.VALID_TRANSITIONS.get(current_status)
    if not allowed_next_statues or new_status not in allowed_next_statues:
      return Response({"detail": f"Perubahan dari status '{current_status}' ke '{new_status}' tidak diperbolehkan"})
    order.status = new_status
    order.save(update_fields=['status'])
    
    return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)
  
class OrderCreateView(generics.CreateAPIView):
    # Catatan: View ini sepertinya tidak digunakan oleh urls.py Anda, 
    # CreateOrderView (APIView) yang digunakan.
    # Namun, logikanya tetap disertakan di sini.
    serializer_class = OrderCreateSerializer

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
                    f"Stok untuk '{menu_item_obj.name}' tidak mencukupi. Sisa: {menu_item_obj.stock}."
                )
            
            menu_item_obj.stock -= item_data['qty']

        MenuItem.objects.bulk_update(menu_items_map.values(), ['stock'])
        
        return super().create(request, *args, **kwargs)
    
class OrderListView(generics.ListAPIView):
    """
    View untuk menampilkan daftar semua pesanan.
    Endpoint ini dilindungi dan hanya bisa diakses oleh Kasir atau Admin.
    """
    serializer_class = OrderSerializer
    permission_classes = [IsKasir] # -> Memastikan user adalah Kasir/Staff global

    # --- PERUBAHAN ---
    # Memfilter queryset berdasarkan tenant staff
    def get_queryset(self):
        user = self.request.user
        base_qs = Order.objects.prefetch_related(
            'items', 'items__menu_item', 'tenant', 'table'
        ).order_by('-created_at')
        
        # Jika user bukan staff global (superadmin),
        # filter hanya order dari tenant tempat dia terdaftar sebagai staff
        if not user.is_staff:
            base_qs = base_qs.filter(tenant__staff=user)
            
        return base_qs
    # --- AKHIR PERUBAHAN ---

class TableQRCodeView(APIView):
    """
    Menghasilkan gambar QR Code untuk sebuah meja spesifik.
    """
    permission_classes = [permissions.AllowAny] 

    def get(self, request, table_code):
        table = get_object_or_404(Table, code=table_code)
        
        # Ganti 'https://yourfrontend.com/order' dengan URL aplikasi frontend Anda.
        frontend_url = request.build_absolute_uri(reverse('create-order')) + f"?table={table.code}"
        
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(frontend_url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        
        buffer = io.BytesIO()
        img.save(buffer, "PNG")
        buffer.seek(0)
        
        return HttpResponse(buffer, content_type="image/png")

class TakeawayQRCodeView(APIView):
    """
    Menghasilkan gambar QR Code untuk pesanan Takeaway per Tenant.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, tenant_id):
        tenant = get_object_or_404(Tenant, pk=tenant_id)
        
        # Ganti 'https://yourfrontend.com/order' dengan URL aplikasi frontend Anda.
        frontend_url = request.build_absolute_uri(reverse('create-order')) + f"?tenant={tenant.id}&order_type=TAKEAWAY"
        
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(frontend_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        buffer = io.BytesIO()
        img.save(buffer, "PNG")
        buffer.seek(0)
        
        return HttpResponse(buffer, content_type="image/png")
    
class ManageMenuItemView(generics.UpdateAPIView):
  # Catatan: View ini sepertinya tidak digunakan oleh urls.py Anda,
  # MenuItemViewSet yang digunakan.
  queryset = MenuItem.objects.all()
  serializer_class = MenuItemSerializer
  permission_classes = [IsTenantOwner] # Ini adalah permission yg lama, perlu disesuaikan

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by('username')
    permission_classes = [permissions.AllowAny] # Harap pertimbangkan untuk mengubah ini ke IsAdminUser

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        return UserSerializer

    @action(detail=False, methods=['get'])
    def summary(self, request):
        admin_count = User.objects.filter(groups__name='Admin').count()
        seller_count = User.objects.filter(groups__name='Seller').count()
        cashier_count = User.objects.filter(groups__name='Cashier').count()
        
        summary_data = {
            'admins': {'count': admin_count, 'description': 'Full system access'},
            'sellers': {'count': seller_count, 'description': 'Manage stands & menus'},
            'cashiers': {'count': cashier_count, 'description': 'Process payments'},
        }
        return Response(summary_data)
    
class StandViewSet(viewsets.ModelViewSet):
    queryset = Tenant.objects.all()
    serializer_class = StandSerializer
    permission_classes = [permissions.AllowAny] # Harap pertimbangkan keamanannya
    parser_classes = (MultiPartParser, FormParser)

class MenuItemViewSet(viewsets.ModelViewSet):
    serializer_class = MenuItemSerializer
    permission_classes = [permissions.AllowAny] # Harap pertimbangkan keamanannya
    parser_classes = (MultiPartParser, FormParser,JSONParser)

    def get_queryset(self):
        stand_pk = self.kwargs.get('stand_pk')
        return MenuItem.objects.filter(tenant_id=stand_pk)

    def perform_create(self, serializer):
        stand_pk = self.kwargs.get('stand_pk')
        stand = Tenant.objects.get(pk=stand_pk)
        # TODO: Tambahkan cek izin apakah user boleh menambah menu ke stand ini
        serializer.save(tenant=stand)

class ReportDashboardAPIView(APIView):
    # --- PERUBAHAN ---
    # Mengamankan endpoint laporan
    permission_classes = [IsKasir] # -> Hanya Kasir/Staff yg bisa lihat
    # --- AKHIR PERUBAHAN ---

    def get(self, request, *args, **kwargs):
        one_week_ago = timezone.now() - timedelta(days=7)
        user = request.user # -> Ambil user
        
        # Statistik All-Time
        # TODO: Ini masih mengambil data global, perlu difilter jika kasir non-admin
        total_revenue = Order.objects.filter(status='PAID').aggregate(total=Sum('total'))['total'] or 0
        total_orders = Order.objects.count()
        avg_order_value = Order.objects.filter(status='PAID').aggregate(avg=Avg('total'))['avg'] or 0
        active_customers = Order.objects.filter(created_at__gte=one_week_ago).values('customer').distinct().count()

        # Statistik Hari Ini
        today = timezone.now().date()
        today_orders_qs = Order.objects.filter(created_at__date=today)
        # Filter jika bukan admin
        if not user.is_staff:
            today_orders_qs = today_orders_qs.filter(tenant__staff=user)
        
        stats_today = {
            'total': today_orders_qs.count(),
            'pending': today_orders_qs.filter(status='AWAITING_PAYMENT').count(),
            'preparing': today_orders_qs.filter(Q(status='PAID') | Q(status='PROCESSING')).count(),
            'completed': today_orders_qs.filter(status='COMPLETED').count()
        }

        # Sales by Hour
        sales_by_hour_qs = Order.objects.filter(created_at__gte=timezone.now() - timedelta(days=1))
        if not user.is_staff:
            sales_by_hour_qs = sales_by_hour_qs.filter(tenant__staff=user)
            
        sales_by_hour = sales_by_hour_qs.annotate(hour=TruncHour('created_at')) \
            .values('hour') \
            .annotate(orders=Count('id')) \
            .order_by('hour')
        
        formatted_sales_by_hour = [
            {'hour': item['hour'].strftime('%H'), 'orders': item['orders']}
            for item in sales_by_hour
        ]

        # Top Selling Products
        top_selling_qs = OrderItem.objects.all()
        if not user.is_staff:
            top_selling_qs = top_selling_qs.filter(order__tenant__staff=user)
            
        top_selling_products = top_selling_qs.values('menu_item__name') \
            .annotate(total_sold=Sum('qty'), total_revenue=Sum('price')) \
            .order_by('-total_sold')[:5]

        # --- PERUBAHAN ---
        # Memfilter performa stand jika user bukan staff global
        stand_performance_qs = Tenant.objects.all()
        if not user.is_staff:
            stand_performance_qs = stand_performance_qs.filter(staff=user)

        stand_performance = stand_performance_qs.annotate(
            total_orders_today=Count('orders', filter=models.Q(orders__created_at__date=timezone.now().date())),
            total_revenue_today=Sum('orders__total', filter=models.Q(orders__status='PAID', orders__created_at__date=timezone.now().date()))
        ).order_by('-total_revenue_today')
        # --- AKHIR PERUBAHAN ---

        formatted_stand_performance = [
            {'name': stand.name, 'orders': stand.total_orders_today, 'revenue': stand.total_revenue_today or 0}
            for stand in stand_performance
        ]

        data = {
            'main_stats': { 
                'total_revenue': total_revenue, 'total_orders': total_orders,
                'avg_order_value': avg_order_value, 'active_customers': active_customers
            },
            'stats_today': stats_today, 
            'sales_by_hour': formatted_sales_by_hour,
            'top_selling_products': list(top_selling_products),
            'stand_performance': formatted_stand_performance,
        }
        return Response(data, status=status.HTTP_200_OK)