from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from django.db import transaction
from django.db import models # <-- IMPOR YANG HILANG DITAMBAHKAN
from django.db.models import Sum, Count, Avg
from django.db.models.functions import TruncHour
from django.contrib.auth.models import User, Group
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework import status, permissions, generics, viewsets, serializers

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions, generics, viewsets, serializers
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated

from .models import Order, OrderItem, Customer, MenuItem, Tenant, Table, VariantOption, VariantGroup
from .serializers import (
    OrderSerializer, OrderCreateSerializer, MenuItemSerializer, UserSerializer, 
    UserCreateSerializer, StandSerializer,VariantGroupSerializer, VariantGroupCreateSerializer, VariantOptionSerializer
)
from .permissions import IsKasir, IsTenantOwner, IsAdminUser, IsTenantStaff, IsOrderTenantStaff # <-- Ganti IsTenantOwner dengan 2 kelas baru
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

            order_item_obj = OrderItem(
                        order=order,
                        menu_item=menu_item,
                        qty=item_data['qty'],
                        price=menu_item.price, # Harga dasar
                        note=item_data.get('note', '')
                    )
            
            order_items_to_create.append(order_item_obj)
            variant_ids = item_data.get('variants', [])
            total_variant_price = 0
            if variant_ids:
                        # Validasi bahwa varian yang dipilih memang milik menu tersebut
                        valid_variants = VariantOption.objects.filter(
                            id__in=variant_ids,
                            group__menu_items=menu_item
                        )
                        if len(valid_variants) != len(variant_ids):
                            raise serializers.ValidationError("Terdapat varian yang tidak valid untuk menu yang dipilih.")
                        
                        for variant in valid_variants:
                            total_variant_price += variant.price
            total += menu_item.price * item_data['qty']
            
            # Kurangi stok
            menu_item.stock -= item_data['qty']

            
        
        # 5. Simpan perubahan stok dan buat OrderItem secara bulk
        MenuItem.objects.bulk_update(menu_items_to_update, ['stock'])
        created_items = OrderItem.objects.bulk_create(order_items_to_create)

        # 6. Hubungkan varian ke OrderItem yang baru dibuat
                # Ini perlu loop terpisah karena bulk_create tidak menangani relasi many-to-many
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
        # Enqueue notification only after the transaction is successfully committed
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
      
      # Kirim notifikasi setelah pembayaran cash dikonfirmasi dan transaksi DB berhasil.
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

    # Jika belum dibayar, batalkan dan kembalikan stok
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
  
# orders/views.py

class UpdateOrderStatusView(APIView):
    """
    Endpoint untuk Tenant mengubah status order. Hanya user yang memiliki hak
    yang bisa mengubah status tersebut
    """
    # TAMBAHKAN PERMISSION INI:
    permission_classes = [IsOrderTenantStaff] # Memastikan hanya Admin/Staf Tenant yg bisa akses

    # Aturan transisi status yang dimiliki tenant
    VALID_TRANSITIONS = {
        'PAID': ['PROCESSING'],
        'PROCESSING': ['READY'],
        'READY': ['COMPLETED']
    }
    
    def patch(self, request, order_pk):
        order = get_object_or_404(Order, pk=order_pk)
        
        # Cek izin objek secara manual
        self.check_object_permissions(request, order) # <-- PANGGIL CEK PERMISSION
        
        new_status = request.data.get('status')
        # ... (sisa logika Anda sudah benar)
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
    # ... permissions, queryset, dll.

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        items_data = serializer.validated_data['items']
        tenant = serializer.validated_data['tenant']
        
        # Ambil semua ID menu item untuk dicek sekaligus
        menu_item_ids = [item['menu_item'] for item in items_data]
        
        # Kunci baris menu item untuk mencegah race condition saat stok dikurangi
        menu_items = MenuItem.objects.select_for_update().filter(
            id__in=menu_item_ids, 
            tenant_id=tenant
        )
        
        menu_items_map = {item.id: item for item in menu_items}

        # Validasi stok dan ketersediaan
        for item_data in items_data:
            menu_item_id = item_data['menu_item']
            menu_item_obj = menu_items_map.get(menu_item_id)
            
            # Cek apakah item ada di tenant yang benar
            if not menu_item_obj:
                raise serializers.ValidationError(
                    f"Menu item dengan ID {menu_item_id} tidak ditemukan untuk tenant ini."
                )
            
            # Cek ketersediaan dan stok
            if not menu_item_obj.available:
                 raise serializers.ValidationError(f"'{menu_item_obj.name}' sedang tidak tersedia.")

            if menu_item_obj.stock < item_data['qty']:
                raise serializers.ValidationError(
                    f"Stok untuk '{menu_item_obj.name}' tidak mencukupi. Sisa: {menu_item_obj.stock}."
                )
            
            # Langsung kurangi stok di objek
            menu_item_obj.stock -= item_data['qty']

        # Simpan semua perubahan stok sekaligus
        MenuItem.objects.bulk_update(menu_items_map.values(), ['stock'])
        
        # Lanjutkan proses pembuatan order oleh DRF
        # self.perform_create(serializer) akan berjalan setelah ini
        # Pastikan perform_create Anda menangani penyimpanan order dan order items.
        
        return super().create(request, *args, **kwargs)
    
class OrderListView(generics.ListAPIView):
    """
    View untuk menampilkan daftar semua pesanan.
    Endpoint ini dilindungi dan hanya bisa diakses oleh Kasir atau Admin.
    """
    queryset = Order.objects.prefetch_related(
        'items', 'items__menu_item', 'tenant', 'table'
    ).order_by('-created_at')
    serializer_class = OrderSerializer
    permission_classes = [IsKasir]

class TableQRCodeView(APIView):
    """
    Menghasilkan gambar QR Code untuk sebuah meja spesifik.
    QR code ini berisi URL untuk frontend yang sudah diisi kode meja.
    """
    permission_classes = [permissions.AllowAny] # Bisa diubah sesuai kebutuhan, misal IsKasir

    def get(self, request, table_code):
        table = get_object_or_404(Table, code=table_code)
        
        # Asumsi URL frontend Anda adalah: https://yourfrontend.com/order?table_code=T01
        # Ganti 'https://yourfrontend.com/order' dengan URL aplikasi frontend Anda.
        frontend_url = request.build_absolute_uri(reverse('create-order')) + f"?table={table.code}"
        
        # Buat QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(frontend_url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        
        # Simpan gambar ke buffer di memori
        buffer = io.BytesIO()
        img.save(buffer, "PNG")
        buffer.seek(0)
        
        return HttpResponse(buffer, content_type="image/png")

class TakeawayQRCodeView(APIView):
    """
    Menghasilkan gambar QR Code untuk pesanan Takeaway per Tenant.
    QR code ini berisi URL untuk frontend yang sudah diisi ID tenant dan tipe order.
    """
    permission_classes = [permissions.AllowAny] # Bisa diubah sesuai kebutuhan

    def get(self, request, tenant_id):
        tenant = get_object_or_404(Tenant, pk=tenant_id)
        
        # Asumsi URL frontend Anda: https://yourfrontend.com/order?tenant=1&type=TAKEAWAY
        # Ganti 'https://yourfrontend.com/order' dengan URL aplikasi frontend Anda.
        frontend_url = request.build_absolute_uri(reverse('create-order')) + f"?tenant={tenant.id}&order_type=TAKEAWAY"
        
        # Buat QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(frontend_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Simpan gambar ke buffer di memori
        buffer = io.BytesIO()
        img.save(buffer, "PNG")
        buffer.seek(0)
        
        return HttpResponse(buffer, content_type="image/png")
    
# orders/views.py

class ManageMenuItemView(generics.UpdateAPIView):
  queryset = MenuItem.objects.all()
  serializer_class = MenuItemSerializer
  # GUNAKAN IsTenantStaff, BUKAN IsTenantOwner
  permission_classes = [IsTenantStaff]

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by('username')
    # permission_classes = [permissions.AllowAny] # <-- HAPUS INI

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        return UserSerializer

    def get_permissions(self):
        """
        Hanya Admin yang boleh melakukan apa pun pada user.
        """
        permission_classes = [IsAdminUser]
        return [permission() for permission in permission_classes]

    @action(detail=False, methods=['get'])
    def summary(self, request):
        # ... (fungsi summary Anda sudah bagus)
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
    parser_classes = (MultiPartParser, FormParser)

    # TAMBAHKAN DECORATOR INI
    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser], url_path='manage-staff')
    def manage_staff(self, request, pk=None):
        """
        Endpoint untuk Admin menambah atau menghapus staff (Seller) dari tenant.
        Body: { "user_id": <id_user>, "action": "add" | "remove" }
        """
        tenant = self.get_object()
        user_id = request.data.get('user_id')
        action = request.data.get('action')

        if not user_id or not action:
            return Response({"error": "user_id dan action diperlukan"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Pastikan user adalah Seller
            user = User.objects.get(pk=user_id, groups__name='Seller')
        except User.DoesNotExist:
            return Response({"error": "User Seller tidak ditemukan"}, status=status.HTTP_404_NOT_FOUND)

        if action == 'add':
            tenant.staff.add(user)
            return Response({"status": f"User {user.username} ditambahkan ke {tenant.name}"}, status=status.HTTP_200_OK)
        elif action == 'remove':
            tenant.staff.remove(user)
            return Response({"status": f"User {user.username} dihapus dari {tenant.name}"}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Action tidak valid (gunakan 'add' atau 'remove')"}, status=status.HTTP_400_BAD_REQUEST)

    def get_permissions(self):
        # ... (Logika get_permissions Anda di sini sudah benar)
        if self.action in ['list', 'retrieve']:
            permission_classes = [AllowAny]
        elif self.action in ['create', 'destroy']:
            permission_classes = [IsAdminUser]
        elif self.action in ['update', 'partial_update']:
            permission_classes = [IsTenantStaff]
        # Tambahkan permission untuk action baru Anda
        elif self.action == 'manage_staff':
            permission_classes = [IsAdminUser]
        else:
            permission_classes = [IsAuthenticated]
        
        return [permission() for permission in permission_classes]

# orders/views.py

class MenuItemViewSet(viewsets.ModelViewSet):
    serializer_class = MenuItemSerializer
    # permission_classes = [permissions.AllowAny] # <-- HAPUS INI
    parser_classes = (MultiPartParser, FormParser,JSONParser)

    def get_queryset(self):
        stand_pk = self.kwargs.get('stand_pk')
        return MenuItem.objects.filter(tenant_id=stand_pk)

    def get_tenant(self):
        """Helper untuk mendapatkan instance tenant."""
        stand_pk = self.kwargs.get('stand_pk')
        return get_object_or_404(Tenant, pk=stand_pk)

    def get_permissions(self):
        """
        Menetapkan izin berdasarkan aksi:
        - list, retrieve (GET): Boleh dilihat siapa saja.
        - create, update, destroy: Hanya Admin atau Seller pemilik tenant.
        """
        if self.action in ['list', 'retrieve']:
            permission_classes = [permissions.AllowAny]
        else:
            # Gunakan IsTenantStaff, bukan IsTenantOwner
            permission_classes = [IsTenantStaff] 
            
        return [permission() for permission in permission_classes]

    def check_object_permissions(self, request, obj):
        """
        Kita override check_object_permissions karena izin kita 
        perlu dicek terhadap 'tenant', bukan 'menu_item'
        """
        if self.action not in ['list', 'retrieve']:
            tenant = self.get_tenant()
            # Cek izin terhadap tenant-nya
            super(MenuItemViewSet, self).check_object_permissions(request, tenant)
        # Untuk list/retrieve, tidak perlu cek objek
        
    def perform_create(self, serializer):
        # Otomatis set tenant berdasarkan URL
        tenant = self.get_tenant()
        # Cek izin sebelum membuat
        self.check_object_permissions(self.request, tenant)
        serializer.save(tenant=tenant)

    def perform_update(self, serializer):
        self.check_object_permissions(self.request, serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        self.check_object_permissions(self.request, instance)
        instance.delete()

class ReportDashboardAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, *args, **kwargs):
        one_week_ago = timezone.now() - timedelta(days=7)
        
        total_revenue = Order.objects.filter(status='PAID').aggregate(total=Sum('total'))['total'] or 0
        total_orders = Order.objects.count()
        avg_order_value = Order.objects.filter(status='PAID').aggregate(avg=Avg('total'))['avg'] or 0
        active_customers = Order.objects.filter(created_at__gte=one_week_ago).values('customer').distinct().count()

        sales_by_hour = Order.objects.filter(created_at__gte=timezone.now() - timedelta(days=1)) \
            .annotate(hour=TruncHour('created_at')) \
            .values('hour') \
            .annotate(orders=Count('id')) \
            .order_by('hour')
        
        formatted_sales_by_hour = [
            {'hour': item['hour'].strftime('%H'), 'orders': item['orders']}
            for item in sales_by_hour
        ]

        top_selling_products = OrderItem.objects.values('menu_item__name') \
            .annotate(total_sold=Sum('qty'), total_revenue=Sum('price')) \
            .order_by('-total_sold')[:5]

        # Penggunaan 'models.Q' sekarang valid karena sudah diimpor
        stand_performance = Tenant.objects.annotate(
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
            'sales_by_hour': formatted_sales_by_hour,
            'top_selling_products': list(top_selling_products),
            'stand_performance': formatted_stand_performance,
        }
        return Response(data, status=status.HTTP_200_OK)
    

class VariantGroupViewSet(viewsets.ModelViewSet):
    """
    ViewSet untuk mengelola VariantGroup (misal: 'Ukuran', 'Level Pedas')
    Hanya bisa diakses oleh Admin atau Seller pemilik tenant.
    """
    serializer_class = VariantGroupSerializer

    def get_queryset(self):
        stand_pk = self.kwargs.get('stand_pk')
        return VariantGroup.objects.filter(tenant_id=stand_pk)

    def get_tenant(self):
        """Helper untuk mendapatkan instance tenant."""
        stand_pk = self.kwargs.get('stand_pk')
        return get_object_or_404(Tenant, pk=stand_pk)

    def get_permissions(self):
        """
        Hanya Admin atau Seller pemilik tenant yang boleh mengakses.
        """
        tenant = self.get_tenant()
        
        # GANTI IsTenantOwner MENJADI IsTenantStaff
        if not (IsAdminUser().has_permission(self.request, self) or 
                IsTenantStaff().has_object_permission(self.request, self, tenant)):
            self.permission_denied(self.request)
            
        return [IsAuthenticated()] # Jika lolos, cukup IsAuthenticated

    def get_serializer_class(self):
        if self.action == 'create':
            return VariantGroupCreateSerializer
        return VariantGroupSerializer

    def perform_create(self, serializer):
        serializer.save(tenant=self.get_tenant())

class VariantOptionViewSet(viewsets.ModelViewSet):
    """
    ViewSet untuk mengelola VariantOption (misal: 'Level 1', 'Level 2')
    Hanya bisa diakses oleh Admin atau Seller pemilik tenant.
    """
    serializer_class = VariantOptionSerializer

    def get_group(self):
        """Helper untuk mendapatkan instance VariantGroup induk."""
        stand_pk = self.kwargs.get('stand_pk')
        group_pk = self.kwargs.get('group_pk')
        
        # Filter berdasarkan tenant (stand_pk) dan grup (group_pk)
        return get_object_or_404(VariantGroup, pk=group_pk, tenant_id=stand_pk)

    def get_queryset(self):
        """Hanya tampilkan opsi milik grup yang spesifik."""
        group = self.get_group()
        return VariantOption.objects.filter(group=group)

    def get_permissions(self):
        """
        Izin dicek terhadap tenant pemilik grup.
        """
        # Dapatkan tenant dari grup induk
        tenant = self.get_group().tenant
        
        # Cek izin terhadap tenant tersebut
        if not (IsAdminUser().has_permission(self.request, self) or 
                IsTenantStaff().has_object_permission(self.request, self, tenant)):
            self.permission_denied(self.request)
            
        return [IsAuthenticated()] # Jika lolos, cukup terautentikasi

    def perform_create(self, serializer):
        """Otomatis set 'group' saat membuat opsi baru."""
        group = self.get_group()
        serializer.save(group=group)