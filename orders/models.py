from django.db import models
from django.utils import timezone
from datetime import timedelta
from django.db import transaction
import uuid
import random
import string
from django.conf import settings

def generate_references_code(prefix="KNT"):
  ts = timezone.now().strftime("%Y%m%d%H%M%S")
  rand = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
  return f"{prefix}-{ts}-{rand}"

class Tenant(models.Model):
  name = models.CharField(max_length=50)
  description = models.TextField(blank=True, null=True)
  staff = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='tenants', blank=True)
  active = models.BooleanField(default=True)
  image = models.ImageField(upload_to='stand_images/', default='stand_images/default.png', blank=True)
  
  def __str__(self):
    return self.name
  
class MenuItem(models.Model):
  CATEGORY_CHOICES = [
        ('FOOD', 'Makanan'),
        ('DRINK', 'Minuman'),
    ]
  tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='menu_items')
  name = models.CharField(max_length=50)
  price = models.DecimalField(max_digits=12, decimal_places=2)
  category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, default='FOOD')
  available = models.BooleanField(default=True)
  stock = models.PositiveIntegerField(default=0, help_text="Jumlah stok tersedia. 0 berarti habis.")
  description = models.TextField(blank=True, null=True)
  image = models.ImageField(upload_to='menu_images/', default='menu_images/default.png', blank=True)
  variant_groups = models.ManyToManyField('VariantGroup', blank=True, related_name='menu_items')
  
  def __str__(self):
    return f"{self.name} ({self.tenant.name})"
  
class VariantGroup(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='variant_groups')
    name = models.CharField(max_length=50)

    def __str__(self):
        return f"{self.name} - ({self.tenant.name})"

class VariantOption(models.Model):
    group = models.ForeignKey(VariantGroup, on_delete=models.CASCADE, related_name='options')
    name = models.CharField(max_length=50)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Harga tambahan untuk opsi ini")

    def __str__(self):
        return f"{self.name} (+{self.price})"
  
class Table(models.Model):
  code = models.CharField(max_length=10, unique=True)
  label = models.CharField(max_length=50, blank=True)
  
  def __str__(self):
    return self.code or self.label
  
class Customer(models.Model):
  phone = models.CharField(max_length=15, unique=True)
  name = models.CharField(max_length=100, blank=True, null=True)
  created_at = models.DateTimeField(auto_now_add=True)
  
  def __str__(self):
    return self.phone
  
class Order(models.Model):
  ORDER_TYPE_CHOICES = [('DINE_IN', 'Dine-In'), ('TAKEAWAY', 'Takeaway')]
  STATUS_CHOICES = [
    ('AWAITING_PAYMENT', 'Awaiting Payment'), ('PAID', 'Paid'), ('PROCESSING', 'Processing'),
    ('READY', 'Ready'), ('COMPLETED', 'Completed'), ('CANCELLED', 'Cancelled'), ('EXPIRED', 'Expired'),
  ]
  PAYMENT_METHOD_CHOICES = [('CASH', 'Cash'), ('TRANSFER', 'Transfer')]
  
  uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
  references_code = models.CharField(max_length=50, default=generate_references_code, unique=True)
  table = models.ForeignKey(Table, on_delete=models.SET_NULL, null=True, blank=True)
  tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name='orders')
  customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
  status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='AWAITING_PAYMENT')
  order_type = models.CharField(max_length=10, choices=ORDER_TYPE_CHOICES, default='DINE_IN')
  expired_at = models.DateTimeField(null=True, blank=True)
  payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
  total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
  created_at = models.DateTimeField(auto_now_add=True)
  paid_at = models.DateTimeField(null=True, blank=True)
  meta = models.JSONField(default=dict, blank=True)
  
  class Meta:
    ordering = ['-created_at']
    
  def __str__(self):
    return f"{self.references_code} ({self.tenant.name})"
  
  def calculate_total(self):
    total = sum([item.price * item.qty for item in self.items.all()])
    self.total = total
    self.save(update_fields=['total'])
    return self.total

  def cancel_and_restock(self):
    if self.status not in ['AWAITING_PAYMENT', 'EXPIRED']:
      return False
    with transaction.atomic():
      order_items = self.items.select_related('menu_item').all()
      menu_items_to_restock = {item.menu_item.id: item.menu_item for item in order_items}
      for item in order_items:
        menu_items_to_restock[item.menu_item.id].stock += item.qty
      MenuItem.objects.bulk_update(menu_items_to_restock.values(), ['stock'])
      self.status = 'CANCELLED'
      self.save(update_fields=['status'])
    return True
  
class OrderItem(models.Model):
  order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
  menu_item = models.ForeignKey(MenuItem, on_delete=models.PROTECT)
  qty = models.PositiveIntegerField(default=1)
  price = models.DecimalField(max_digits=12, decimal_places=2)
  note = models.CharField(max_length=255, blank=True, null=True)
  selected_variants = models.ManyToManyField('VariantOption', blank=True)
  
  def __str__(self):
    return f"{self.menu_item.name} x{self.qty} ({self.order.references_code})"
  
  def save(self, *args, **kwargs):
    if not self.price:
      self.price = self.menu_item.price
    super().save(*args, **kwargs)
  
  def get_subtotal(self):
    total_variant_price = sum(variant.price for variant in self.selected_variants.all())
    return (self.price + total_variant_price) * self.qty