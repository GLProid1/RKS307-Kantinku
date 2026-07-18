from rest_framework import serializers
from tenants.serializers import MenuItemSerializer, StandSerializer, VariantOptionSerializer
from .models import Customer, MenuItem, Order, OrderItem, Tenant, Table
from django.contrib.auth.models import User, Group
from django.db import transaction
import random 
import string 

class TableSerializer(serializers.ModelSerializer):
    class Meta:
        model = Table
        fields = ['id', 'code', 'label']
    
class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ['id', 'name', 'phone', 'email']
    
class OrderItemCreateSerializer(serializers.Serializer):
    menu_item = serializers.IntegerField()
    qty = serializers.IntegerField(min_value=1)
    note = serializers.CharField(required=False, allow_blank=True)
    variants = serializers.ListField(child=serializers.IntegerField(), required=False)
  
class OrderCreateSerializer(serializers.Serializer):
    tenant = serializers.IntegerField()
    table = serializers.CharField(required=False, allow_blank=True)
    token = serializers.CharField(required=False, allow_blank=True)
    name = serializers.CharField(max_length=100, required=True)
    email = serializers.EmailField(required=True)
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
        
    def create(self, validated_data):
        items_data = validated_data.pop('items')
        
        # 1. Ambil data customer dari INPUT FORM FRONTEND ("virrel yaw")
        name = validated_data.pop('name')
        email = validated_data.pop('email')
        phone = validated_data.pop('phone', None)
        
        # 2. Cari atau buat Customer baru berdasarkan Email
        customer, created = Customer.objects.get_or_create(
            email=email,
            defaults={'name': name, 'phone': phone}
        )
        
        # Jika customer lama memesan tapi memakai nama baru di form ("virrel yaw"),
        # kita perbarui namanya di database!
        if not created and customer.name != name:
            customer.name = name
            if phone:
                customer.phone = phone
            customer.save(update_fields=['name', 'phone'])

        # 3. Handle Tabel (Jika ada input kode tabel)
        table_code = validated_data.pop('table', None)
        table_obj = None
        if table_code:
            table_obj = Table.objects.filter(code=table_code).first()

        # 4. Buat Order Baru (Tanpa mengaitkan ke request.user)
        order = Order.objects.create(
            customer=customer,
            table=table_obj,
            **validated_data
        )

        # 5. Buat OrderItem beserta Varian-nya
        for item_data in items_data:
            variants = item_data.pop('variants', [])
            menu_item_id = item_data.pop('menu_item')
            
            # Ambil object menu
            menu_item = MenuItem.objects.get(id=menu_item_id)
            
            order_item = OrderItem.objects.create(
                order=order,
                menu_item=menu_item,
                price=menu_item.price, # Simpan harga saat transaksi terjadi
                **item_data
            )
            
            # Daftarkan varian jika ada
            if variants:
                order_item.selected_variants.set(variants)

        # 6. Hitung total akhir (Termasuk harga varian)
        order.calculate_total()
        
        return order
  
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
        fields = ['id','uuid','cashier_pin', 'references_code', 'tenant', 'table', 'customer', 'status','order_type', 'payment_method', 'total', 'items', 'created_at', 'paid_at', 'meta']
