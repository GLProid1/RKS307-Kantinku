from rest_framework import serializers
from tenants.serializers import MenuItemSerializer, StandSerializer, VariantOptionSerializer
from .models import Customer, MenuItem, Order, OrderItem, Tenant, Table
from django.contrib.auth.models import User, Group
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