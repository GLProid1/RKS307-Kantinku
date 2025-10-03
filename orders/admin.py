from django.contrib import admin
from .models import Customer, MenuItem, Order, OrderItem, Table, Tenant

@admin.register(Tenant)
class TenantAdminSite(admin.ModelAdmin):
  list_display = ('name', 'description', 'active')
  search_fields = ('name',)
  list_filter = ('active',)
  
@admin.register(Table)
class TableAdminSite(admin.ModelAdmin):
  list_display = ('code', 'label')
  search_fields = ('code',)
  list_filter = ('code',)
  
@admin.register(MenuItem)
class TenantAdminSite(admin.ModelAdmin):
  list_display = ('tenant', 'name', 'price', 'available')
  search_fields = ('tenant', 'name')
  list_filter = ('tenant', 'price',)
  
@admin.register(Order)
class OrderAdminSite(admin.ModelAdmin):
  list_display = ('uuid', 'references_code', 'table', 'tenant', 'customer', 'status', 'total', 'payment_method', 'created_at')
  readonly_fields = ('uuid', 'references_code', 'created_at', 'paid_at')
  search_fields = ('uuid', 'references_code', 'table__code')