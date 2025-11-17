# views.py
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
from django.contrib.auth import login, logout, authenticate
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework import status, permissions, generics, viewsets, serializers

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions, generics, viewsets, serializers
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated, OR

from .models import Order, OrderItem, Customer, MenuItem, Tenant, Table, VariantOption, VariantGroup
from .serializers import (
    OrderSerializer, OrderCreateSerializer, MenuItemSerializer, UserSerializer, 
    UserCreateSerializer, StandSerializer, VariantGroupSerializer, 
    VariantGroupCreateSerializer, VariantOptionSerializer
)
from .permissions import (
    IsAdminUser, IsTenantStaff, 
    IsOrderTenantStaff, IsGuestOrderOwner,IsCashierUser
)
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
        items_data = data['items']
        menu_item_ids = [item['menu_item'] for item in items_data]
        menu_items_to_update = MenuItem.objects.select_for_update().filter(pk__in=menu_item_ids, tenant=tenant)
        
        menu_items_map = {item.pk: item for item in menu_items_to_update}

        for item_data in items_data:
            menu_item = menu_items_map.get(item_data['menu_item'])
            if not menu_item or not menu_item.available or menu_item.stock < item_data['qty']:
                raise serializers.ValidationError(f"Stok untuk '{menu_item.name if menu_item else 'item'}' tidak mencukupi atau tidak tersedia.")

        order = Order.objects.create(
          tenant=tenant, table=table, customer=customer,
          payment_method=data['payment_method'],
          status = 'AWAITING_PAYMENT',
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
    if order.payment_method == 'TRANSFER':
      payment_info = initiate_payment_for_order(order)
    
    if not request.user.is_authenticated:
        guest_uuids = request.session.get('guest_order_uuids', [])
        if str(order.uuid) not in guest_uuids:
            guest_uuids.append(str(order.uuid))
            request.session['guest_order_uuids'] = guest_uuids
    
    resp = {
      'order': OrderSerializer(order, context={'request': request}).data,
      'payment': payment_info
    }
    return Response(resp, status=status.HTTP_201_CREATED)
  
class MidtransWehboohView(APIView):
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
      payload = request.data
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

      
      if status_code in ['settlement', 'paid', 'success']:
        order.status = "PAID"
        order.paid_at = timezone.now()
        order.meta.setdefault('gateway_notification', []).append(payload)
        order.save(update_fields=['status', 'paid_at', 'meta'])
        
        # --- PERBAIKAN: Nonaktifkan Celery untuk sementara ---
        # transaction.on_commit(lambda: send_order_paid_notification.delay(order.id))
        
        return Response({'detail': 'Order marked paid'}, status=200)
      
      if status_code in ['expire', 'expired', 'cancel']:
        order.status = "CANCELLED"
        order.meta.setdefault('gateway_notification', []).append(payload)
        order.save(update_fields=['status', 'meta'])
        return Response({"detail": "Order Cancelled"}, status=200)
      
      order.meta.setdefault("gateway_notification", []).append(payload)
      order.save(update_fields=['meta'])
      return Response({"detail": "Ok"}, status=200)
    
class CashConfirmView(APIView):
  permission_classes = [IsCashierUser]
  
  def post(self, request, order_uuid):
    order = get_object_or_404(Order, uuid=order_uuid)
    
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
        order.save(update_fields=['status']) # BUGFIX: Menghapus paid_at, meta
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
      
      # --- PERBAIKAN: Nonaktifkan Celery untuk sementara ---
      # transaction.on_commit(lambda: send_order_paid_notification.delay(order.id))
      
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
  permission_classes = [IsOrderTenantStaff | IsGuestOrderOwner]
  
  def get(self, request, order_uuid):
    order = get_object_or_404(Order, uuid=order_uuid)
    self.check_object_permissions(request, order)
      
    if order.expired_at and timezone.now() > order.expired_at and order.status != 'EXPIRED':
      order.status = 'EXPIRED'
      order.save(update_fields=['status'])
      
    serializer = OrderSerializer(order, context={'request': request})
    return Response(serializer.data, status=status.HTTP_200_OK)
  
class CancelOrderView(APIView):
  permission_classes = [IsOrderTenantStaff | IsGuestOrderOwner]
  
  def post(self, request, order_uuid):
    order = get_object_or_404(Order, uuid=order_uuid)
    self.check_object_permission(request, order)
    
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
    permission_classes = [IsOrderTenantStaff]

    VALID_TRANSITIONS = {
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
        
        current_status = order.status
        allowed_next_statues = self.VALID_TRANSITIONS.get(current_status)
        
        if not allowed_next_statues or new_status not in allowed_next_statues:
            return Response({"detail": f"Perubahan dari status '{current_status}' ke '{new_status}' tidak diperbolehkan"})
        
        order.status = new_status
        order.save(update_fields=['status'])
        
        return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)
  
class OrderCreateView(generics.CreateAPIView):
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
        base_qs = Order.objects.all()

        # --- PERBAIKAN LOGIKA IZIN ---
        # Jika user BUKAN Admin (is_staff) DAN BUKAN Kasir
        if not user.is_staff and not user.groups.filter(name='Cashier').exists():
            # Maka dia adalah Seller, filter berdasarkan tenant-nya
            user_tenant_ids = user.tenants.values_list('id', flat=True)
            base_qs = base_qs.filter(tenant_id__in=user_tenant_ids)
        
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
  queryset = MenuItem.objects.all()
  serializer_class = MenuItemSerializer
  permission_classes = [IsTenantStaff]

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by('username')

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        return UserSerializer

    def get_permissions(self):
        permission_classes = [IsAdminUser]
        return [permission() for permission in permission_classes]
    
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        
        # 1. Hapus relasi ManyToMany DULU.
        #    Kita gunakan 'instance.tenants' karena related_name='tenants'
        #    pada model Tenant.
        instance.tenants.clear() 
        
        # 2. Sekarang, aman untuk menghapus User
        self.perform_destroy(instance)
        
        # 3. Kembalikan respons sukses
        return Response(status=status.HTTP_204_NO_CONTENT)

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
    serializer_class = StandSerializer
    parser_classes = (MultiPartParser, FormParser)

    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated:
            # Jika user adalah Admin (is_staff) ATAU ada di grup 'Cashier',
            # tampilkan SEMUA tenant.
            if user.is_staff or user.groups.filter(name='Cashier').exists():
                return Tenant.objects.all()
            else:
                # Jika bukan (berarti dia Seller), tampilkan hanya tenant miliknya.
                return user.tenants.all()

        # Jika tidak login sama sekali, tampilkan tenant yang aktif saja.
        return Tenant.objects.filter(active=True)

    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser], url_path='manage-staff')
    def manage_staff(self, request, pk=None):
        tenant = self.get_object()
        user_id = request.data.get('user_id')
        action = request.data.get('action')

        if not user_id or not action:
            return Response({"error": "user_id dan action diperlukan"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(pk=user_id, groups__name='Seller')
        except User.DoesNotExist:
            return Response({"error": "User Seller tidak ditemukan"}, status=status.HTTP_44_NOT_FOUND)

        if action == 'add':
            tenant.staff.add(user)
            return Response({"status": f"User {user.username} ditambahkan ke {tenant.name}"}, status=status.HTTP_200_OK)
        elif action == 'remove':
            tenant.staff.remove(user)
            return Response({"status": f"User {user.username} dihapus dari {tenant.name}"}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Action tidak valid (gunakan 'add' atau 'remove')"}, status=status.HTTP_400_BAD_REQUEST)

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            permission_classes = [AllowAny]
        elif self.action in ['create', 'destroy']:
            permission_classes = [IsAdminUser]
        elif self.action in ['update', 'partial_update']:
            permission_classes = [IsTenantStaff]
        elif self.action == 'manage_staff':
            permission_classes = [IsAdminUser]
        else:
            permission_classes = [IsAuthenticated]
        
        return [permission() for permission in permission_classes]

class MenuItemViewSet(viewsets.ModelViewSet):
    serializer_class = MenuItemSerializer
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get_queryset(self):
        stand_pk = self.kwargs.get('stand_pk')
        
        # +++ INI ADALAH PERBAIKANNYA +++
        # Kita prefetch semua data terkait (varian dan opsi) dalam satu query
        return MenuItem.objects.filter(
            tenant_id=stand_pk
        ).prefetch_related(
            'variant_groups', 
            'variant_groups__options')

    def get_tenant(self):
        stand_pk = self.kwargs.get('stand_pk')
        return get_object_or_404(Tenant, pk=stand_pk)

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            permission_classes = [permissions.AllowAny]
        else:
            permission_classes = [IsTenantStaff] 
            
        return [permission() for permission in permission_classes]

    def check_object_permissions(self, request, obj):
        if self.action not in ['list', 'retrieve']:
            tenant = self.get_tenant()
            for permission in self.get_permissions():
                if not permission.has_object_permission(request, self, tenant):
                    self.permission_denied(request)
        
    def perform_create(self, serializer):
        tenant = self.get_tenant()
        self.check_object_permissions(self.request, tenant)
        serializer.save(tenant=tenant)

    def perform_update(self, serializer):
        self.check_object_permissions(self.request, serializer.instance.tenant)
        serializer.save()

    def perform_destroy(self, instance):
        self.check_object_permissions(self.request, instance.tenant)
        instance.delete()

# --- PERBAIKAN TOTAL UNTUK MASALAH DUPLIKAT ---
class ReportDashboardAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        one_week_ago = timezone.now() - timedelta(days=7)
        user = request.user 
        
        user_tenant_ids = []
        if not user.is_staff:
            user_tenant_ids = user.tenants.values_list('id', flat=True)
        
        total_revenue = 0
        total_orders = 0
        avg_order_value = 0
        active_customers = 0
        
        if user.is_staff:
            total_revenue = Order.objects.filter(status='PAID').aggregate(total=Sum('total'))['total'] or 0
            total_orders = Order.objects.count()
            avg_order_value = Order.objects.filter(status='PAID').aggregate(avg=Avg('total'))['avg'] or 0
            active_customers = Order.objects.filter(created_at__gte=one_week_ago).values('customer').distinct().count()

        today = timezone.now().date()
        today_orders_qs = Order.objects.filter(created_at__date=today)
        if not user.is_staff:
            today_orders_qs = today_orders_qs.filter(tenant_id__in=user_tenant_ids)
        
        stats_today = {
            'total': today_orders_qs.count(),
            'pending': today_orders_qs.filter(status='AWAITING_PAYMENT').count(),
            'preparing': today_orders_qs.filter(Q(status='PAID') | Q(status='PROCESSING')).count(),
            'completed': today_orders_qs.filter(status='COMPLETED').count()
        }

        sales_by_hour_qs = Order.objects.filter(created_at__gte=timezone.now() - timedelta(days=1))
        if not user.is_staff:
            sales_by_hour_qs = sales_by_hour_qs.filter(tenant_id__in=user_tenant_ids)
            
        sales_by_hour = sales_by_hour_qs.annotate(hour=TruncHour('created_at')) \
            .values('hour') \
            .annotate(orders=Count('id')) \
            .order_by('hour')
        
        formatted_sales_by_hour = [
            {'hour': item['hour'].strftime('%H'), 'orders': item['orders']}
            for item in sales_by_hour
        ]

        top_selling_qs = OrderItem.objects.all()
        if not user.is_staff:
            top_selling_qs = top_selling_qs.filter(order__tenant_id__in=user_tenant_ids)
            
        top_selling_products = top_selling_qs.values('menu_item__name') \
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
# --- AKHIR PERBAIKAN TOTAL ---
    
class VariantGroupViewSet(viewsets.ModelViewSet):
    serializer_class = VariantGroupSerializer

    def get_queryset(self):
        stand_pk = self.kwargs.get('stand_pk')
        return VariantGroup.objects.filter(tenant_id=stand_pk)

    def get_tenant(self):
        stand_pk = self.kwargs.get('stand_pk')
        return get_object_or_404(Tenant, pk=stand_pk)

    def get_permissions(self):
        tenant = self.get_tenant()
        
        if not (IsAdminUser().has_permission(self.request, self) or 
                IsTenantStaff().has_object_permission(self.request, self, tenant)):
            self.permission_denied(self.request)
            
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == 'create':
            return VariantGroupCreateSerializer
        return VariantGroupSerializer

    def perform_create(self, serializer):
        serializer.save(tenant=self.get_tenant())

class VariantOptionViewSet(viewsets.ModelViewSet):
    serializer_class = VariantOptionSerializer

    def get_group(self):
        stand_pk = self.kwargs.get('stand_pk')
        group_pk = self.kwargs.get('group_pk')
        
        return get_object_or_404(VariantGroup, pk=group_pk, tenant_id=stand_pk)

    def get_queryset(self):
        group = self.get_group()
        return VariantOption.objects.filter(group=group)

    def get_permissions(self):
        tenant = self.get_group().tenant
        
        if not (IsAdminUser().has_permission(self.request, self) or 
                IsTenantStaff().has_object_permission(self.request, self, tenant)):
            self.permission_denied(self.request)
            
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        group = self.get_group()
        serializer.save(group=group)

class LoginView(APIView):
    """
    View untuk login. Menggunakan username & password,
    mengembalikan data user dan men-set httpOnly session cookie.
    """
    permission_classes = [AllowAny] # WAJIB, karena default sekarang IsAuthenticated

    def post(self, request, format=None):
        username = request.data.get('username')
        password = request.data.get('password')
        
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user) # Django akan otomatis men-set cookie
            return Response(UserSerializer(user).data)
        else:
            return Response(
                {"detail": "Username atau password salah."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

class LogoutView(APIView):
    """
    View untuk logout. Menghapus session cookie.
    """
    permission_classes = [IsAuthenticated] # Harus login untuk bisa logout

    def post(self, request, format=None):
        logout(request) # Django akan otomatis menghapus cookie
        return Response(status=status.HTTP_204_NO_CONTENT)

class CheckAuthView(APIView):
    """
    View untuk mengecek status login (cookie).
    """
    permission_classes = [IsAuthenticated] # Hanya user terautentikasi yang bisa lolos

    def get(self, request, format=None):
        # Jika sampai sini (lolos permission), berarti cookie valid
        return Response(UserSerializer(request.user).data)
    
class LaporanKeuanganAPIView(APIView):
    """
    View khusus untuk Laporan Keuangan Kasir.
    Menerima filter: ?periode= & ?stand_id=
    """
    permission_classes = [IsCashierUser] # Hanya Kasir & Admin

    def get(self, request, *args, **kwargs):
        periode = request.query_params.get('periode', 'hari-ini')
        stand_id = request.query_params.get('stand_id')

        # Tentukan rentang tanggal berdasarkan filter periode
        today = timezone.now().date()
        start_date = today
        end_date = today + timedelta(days=1) # Sampai awal hari berikutnya

        if periode == 'kemarin':
            start_date = today - timedelta(days=1)
            end_date = today
        elif periode == '7-hari':
            start_date = today - timedelta(days=6)
        
        # Kustom tidak diimplementasikan dulu, bisa ditambahkan nanti
        
        # Filter dasar untuk semua order yang SUDAH LUNAS
        qs = Order.objects.filter(
            status__in=['PAID', 'PROCESSING', 'READY', 'COMPLETED'],
            created_at__gte=start_date,
            created_at__lt=end_date
        )

        # Filter berdasarkan stand jika dipilih
        if stand_id and stand_id != 'semua':
            qs = qs.filter(tenant_id=stand_id)

        # 1. Hitung Stats
        stats = qs.aggregate(
            totalPendapatanTunai=Sum('total', filter=Q(payment_method='CASH')),
            totalPendapatanTransfer=Sum('total', filter=Q(payment_method='TRANSFER')),
            totalTransaksi=Count('id')
        )

        # 2. Siapkan data Transaksi untuk tabel
        # (Kita format agar cocok dengan TransactionTable.jsx)
        transactions_data = []
        for tx in qs.order_by('-created_at'):
            transactions_data.append({
                "id": tx.references_code,
                "waktu": tx.created_at.strftime('%d %b %Y, %H:%M'),
                "namaStand": tx.tenant.name,
                "metodeBayar": "Tunai" if tx.payment_method == 'CASH' else "Transfer",
                "total": tx.total
            })

        # 3. Siapkan data respons
        data = {
            "stats": {
                "totalPendapatanTunai": stats.get('totalPendapatanTunai') or 0,
                "totalPendapatanTransfer": stats.get('totalPendapatanTransfer') or 0,
                "totalTransaksi": stats.get('totalTransaksi') or 0,
            },
            "transactions": transactions_data
        }
        
        return Response(data, status=status.HTTP_200_OK)