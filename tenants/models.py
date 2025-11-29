from django.db import models
from django.conf import settings

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