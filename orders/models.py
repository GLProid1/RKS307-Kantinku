from django.db import models
from django.utils import timezone
from datetime import timedelta
import uuid
import random
import string

def generate_references_code(prefix="KNT"):
  ts = timezone.now().strftime("%Y%m%d%H%M%S")
  rand = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
  return f"{prefix}-{ts}-{rand}"

class Tenant(models.Model):
  name = models.CharField(max_length=50)
  description = models.TextField(blank=True, null=True)
  active = models.BooleanField(default=True)
  
  def __str__(self):
    return self.name
  
class MenuItem(models.Model):
  tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='menu_items')
  name = models.CharField(max_length=50)
  price = models.DecimalField(max_digits=12, decimal_places=2)
  available = models.BooleanField(default=True)
  description = models.TextField(blank=True, null=True)
  
  def __str__(self):
    return f"{self.name} ({self.tenant.name})"
  
class Table(models.Model):
  code = models.CharField(max_length=10, unique=True) # di pasang di QR
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
  STATUS_CHOICES = [
    ('AWAITING_PAYMENT', 'Awaiting Payment'),
    ('PAID', 'Paid'),
    ('PROCESSING', 'Processing'),
    ('READY', 'Ready'),
    ('COMPLETED', 'Completed'),
    ('CANCELLED', 'Cancelled'),
    ('EXPIRED', 'Expired'),
  ]
  PAYMENT_METHOD_CHOICES = [
    ('CASH', 'Cash'),
    ('TRANSFER', 'Transfer'),
  ]
  
  uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
  references_code = models.CharField(max_length=50, default=generate_references_code, unique=True)
  table = models.ForeignKey(Table, on_delete=models.SET_NULL, null=True, blank=True)
  tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name='orders')
  customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
  status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='AWAITING_PAYMENT')
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
  
class OrderItem(models.Model):
  order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
  menu_item = models.ForeignKey(MenuItem, on_delete=models.PROTECT)
  qty = models.PositiveIntegerField(default=1)
  price = models.DecimalField(max_digits=12, decimal_places=2) # snapshot price
  note = models.CharField(max_length=255, blank=True, null=True)
  
  def __str__(self):
    return f"{self.menu_item.name} x{self.qty} ({self.order.references_code})"
  
  def save(self, *args, **kwargs):
    if not self.price:
      self.price = self.menu_item.price
    super().save(*args, **kwargs)