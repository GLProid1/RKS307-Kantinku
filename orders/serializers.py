from rest_framework import serializers
from .models import Customer, MenuItem, Order, OrderItem, Tenant, Table

class MenuItemSerializer(serializers.ModelSerializer):
  class Meta:
    model = MenuItem
    fields = ['id', 'name', 'price', 'available', 'description']
    
class TenantSerializer(serializers.ModelSerializer):
  menu_items = MenuItemSerializer(many=True, read_only=True)

  class Meta:
    model = Tenant
    fields = ['id', 'name', 'description', 'menu_items']
    
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
  
class OrderCreateSerializer(serializers.Serializer):
  tenant = serializers.IntegerField()
  table = serializers.CharField(required=False, allow_blank=True)
  phone = serializers.CharField(required=False, allow_blank=True)
  payment_method = serializers.ChoiceField(choices=Order.PAYMENT_METHOD_CHOICES)
  items = OrderItemCreateSerializer(many=True)
  
  def validate_tenant(self, value):
    from .models import Tenant
    if not Tenant.objects.filter(pk=value, active=True).exists():
      raise serializers.ValidationError("Tenant tidak ditemukan atau tidak aktif")
    return value
  
  def validate(self, data):
    if not data.get('items'):
      raise serializers.ValidationError("Item tidak boleh kosong")
    return data
  
class OrderItemSerializer(serializers.ModelSerializer):
  menu_item = MenuItemSerializer()
  
  class Meta:
    model = OrderItem
    fields = ['id', 'menu_item', 'qty', 'price', 'note']
    
class OrderSerializer(serializers.ModelSerializer):
  items = OrderItemSerializer(many=True, read_only=True)
  tenant = TenantSerializer()
  table = TableSerializer()
  customer = CustomerSerializer()
  
  class Meta:
    model = Order
    fields = ['uuid', 'references_code', 'tenant', 'table', 'customer', 'status', 'payment_method', 'total', 'items', 'created_at', 'paid_at', 'meta']