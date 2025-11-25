from django.contrib import admin
from .models import Customer, Order, OrderItem, Table
from django.urls import reverse  
from django.utils.html import format_html
  
@admin.register(Table)
class TableAdminSite(admin.ModelAdmin):
  list_display = ('code', 'label','qr_code_link')
  search_fields = ('code',)
  list_filter = ('code',)

  def qr_code_link(self, obj):
    # This creates the URL to your QR code endpoint
    url = reverse('table-qr-code', args=[obj.code])
    # This creates a safe HTML link
    return format_html('<a href="{}" target="_blank">Lihat QR</a>', url)
  
  # This sets the column header text
  qr_code_link.short_description = 'QR Code Meja'
  
  
@admin.register(Order)
class OrderAdminSite(admin.ModelAdmin):
  list_display = ('uuid', 'references_code', 'table', 'tenant', 'customer', 'status', 'total', 'payment_method', 'created_at')
  readonly_fields = ('uuid', 'references_code', 'created_at', 'paid_at')
  search_fields = ('uuid', 'references_code', 'table__code')