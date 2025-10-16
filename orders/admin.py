from django.contrib import admin
from .models import Customer, MenuItem, Order, OrderItem, Table, Tenant,VariantGroup, VariantOption
from django.urls import reverse  
from django.utils.html import format_html

@admin.register(Tenant)
class TenantAdminSite(admin.ModelAdmin):
  list_display = ('name', 'description', 'active','image_tag')
  search_fields = ('name',)
  list_filter = ('active',)
  readonly_fields = ('image_tag',)

  def image_tag(self, obj):
    if obj.image:
      return format_html('<img src="{}" style="max-width:70px; max-height:70px;" />'.format(obj.image.url))
    return "No Image"
  image_tag.short_description = 'Gambar Stand'
  
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

class VariantOptionInline(admin.TabularInline):
    """Memungkinkan menambah Opsi Varian langsung di halaman Grup Varian."""
    model = VariantOption
    extra = 1 # Jumlah form kosong untuk opsi baru

@admin.register(VariantGroup)
class VariantGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant')
    list_filter = ('tenant',)
    search_fields = ('name', 'tenant__name')
    inlines = [VariantOptionInline] # Tampilkan form inline di atas

@admin.register(MenuItem)
class MenuItemAdminSite(admin.ModelAdmin):
    list_display = ('tenant', 'name', 'category', 'price', 'available', 'image_tag') # Tambahkan 'category'
    search_fields = ('tenant__name', 'name')
    list_filter = ('tenant', 'price', 'category') # Tambahkan 'category'
    readonly_fields = ('image_tag',)
    
    # Filter agar hanya grup varian milik tenant yang sama yang bisa dipilih
    filter_horizontal = ('variant_groups',)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "variant_groups":
            # Coba ambil tenant_id dari objek yang sedang diedit
            obj_id = request.resolver_match.kwargs.get('object_id')
            if obj_id:
                tenant = MenuItem.objects.get(pk=obj_id).tenant
                kwargs["queryset"] = VariantGroup.objects.filter(tenant=tenant)
        return super().formfield_for_manytomany(db_field, request, **kwargs)
    
    def image_tag(self, obj):
      if obj.image:
        return format_html('<img src="{}" style="max-width:70px; max-height:70px;" />'.format(obj.image.url))
      return "No Image"
    image_tag.short_description = 'Gambar'
    

