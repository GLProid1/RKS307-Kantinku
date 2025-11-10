from rest_framework import serializers
from .models import Customer, MenuItem, Order, OrderItem, Tenant, Table, VariantGroup, VariantOption
from django.contrib.auth.models import User, Group
import random # <-- TAMBAHKAN INI
import string # <-- TAMBAHKAN INI

class VariantGroupCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = VariantGroup
        fields = ['id', 'name']
        # 'tenant' akan di-set otomatis dari URL

class VariantOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = VariantOption
        fields = ['id', 'name', 'price']

class VariantGroupSerializer(serializers.ModelSerializer):
    options = VariantOptionSerializer(many=True, read_only=True)
    class Meta:
        model = VariantGroup
        fields = ['id', 'name', 'options']

class MenuItemSerializer(serializers.ModelSerializer):
    variant_groups = VariantGroupSerializer(many=True, read_only=True)
    tenant = serializers.PrimaryKeyRelatedField(read_only=True)
    
    # --- TAMBAHKAN BARIS INI ---
    imageUrl = serializers.URLField(source='image.url', read_only=True)
    # --- AKHIR TAMBAHAN ---

    class Meta:
        model = MenuItem
        fields = [
            'id', 'tenant', 'name', 'price', 'available', 'description', 
            'image', 'imageUrl', # <-- Tambahkan 'imageUrl' di sini
            'category', 'stock', 'variant_groups'
        ]
class StandSerializer(serializers.ModelSerializer):
    # Field baru untuk mencocokkan komponen frontend StandCard.jsx
    status = serializers.SerializerMethodField()
    seller = serializers.SerializerMethodField()
    imageUrl = serializers.URLField(source='image.url', read_only=True)

    class Meta:
        model = Tenant
        fields = ['id', 'name', 'description', 'active', 'image', 'imageUrl', 'status', 'seller']
        extra_kwargs = {
            # Membuat field 'image' tidak wajib saat melakukan update
            'image': {'required': False}
        }

    def get_status(self, obj):
        """Mengonversi boolean 'active' menjadi string 'Open'/'Closed'."""
        return "Open" if obj.active else "Closed"

    def get_seller(self, obj):
        """Mengambil nama staf pertama yang terkait, atau nilai default."""
        first_staff = obj.staff.first()
        return first_staff.username if first_staff else "N/A"

class TableSerializer(serializers.ModelSerializer):
    class Meta:
        model = Table
        fields = ['id', 'code', 'label']
    
class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ['id', 'phone', 'name']
    
class OrderItemCreateSerializer(serializers.Serializer):
    menu_item = serializers.IntegerField()
    qty = serializers.IntegerField(min_value=1)
    note = serializers.CharField(required=False, allow_blank=True)
    variants = serializers.ListField(child=serializers.IntegerField(), required=False)
  
class OrderCreateSerializer(serializers.Serializer):
    tenant = serializers.IntegerField()
    table = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True)
    payment_method = serializers.ChoiceField(choices=Order.PAYMENT_METHOD_CHOICES)
    items = OrderItemCreateSerializer(many=True)
  
    def validate_tenant(self, value):
        if not Tenant.objects.filter(pk=value, active=True).exists():
            raise serializers.ValidationError("Tenant tidak ditemukan atau tidak aktif")
        return value
  
    def validate(self, data):
        items = data.get('items')
        tenant_id = data.get('tenant')
        if not items:
            raise serializers.ValidationError("Item tidak boleh kosong")
        item_ids = [item['menu_item'] for item in items]
        valid_items_count = MenuItem.objects.filter(id__in=item_ids, tenant_id=tenant_id).count()
        if valid_items_count != len(item_ids):
            raise serializers.ValidationError("Terdapat satu atau lebih item yang bukan milik tenant ini.")
        return data
  
class OrderItemSerializer(serializers.ModelSerializer):
    menu_item = MenuItemSerializer()
    selected_variants = VariantOptionSerializer(many=True, read_only=True)
    class Meta:
        model = OrderItem
        fields = ['id', 'menu_item', 'qty', 'price', 'note', 'selected_variants']
    
class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    tenant = StandSerializer() 
    table = TableSerializer(allow_null=True)      # <-- TAMBAHKAN INI
    customer = CustomerSerializer(allow_null=True)  # <-- TAMBAHKAN INI
    class Meta:
        model = Order
        fields = ['id','uuid', 'references_code', 'tenant', 'table', 'customer', 'status', 'payment_method', 'total', 'items', 'created_at', 'paid_at', 'meta']

class UserSerializer(serializers.ModelSerializer):
    role = serializers.CharField(source='groups.first.name', read_only=True)
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'role', 'first_name', 'last_name']

class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    role = serializers.ChoiceField(choices=['Admin', 'Seller', 'Cashier'], write_only=True)
    
    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'role']

    def create(self, validated_data):
        role_name = validated_data.pop('role')
        user = User.objects.create_user(**validated_data)
        group, _ = Group.objects.get_or_create(name=role_name)
        user.groups.add(group)
        if role_name == 'Admin':
            user.is_staff = True
            user.save(update_fields=['is_staff'])
        
        # --- TAMBAHKAN LOGIKA INI ---
        if role_name == 'Seller':
            # 1. Buat nama stand random
            random_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            stand_name = f"Stand {user.username}-{random_suffix}"
            
            # 2. Buat Stand baru
            new_stand = Tenant.objects.create(name=stand_name, active=True)
            
            # 3. Hubungkan user ini ke stand tersebut
            new_stand.staff.add(user)
        # --- AKHIR TAMBAHAN ---
            
        return user