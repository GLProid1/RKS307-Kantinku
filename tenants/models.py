from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator,ValidationError
from django.core.exceptions import ValidationError

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

class SystemSettings(models.Model):
    # Pengaturan Waktu Operasional
    open_hour = models.TimeField(default='07:00:00', help_text="Jam buka kantin")
    close_hour = models.TimeField(default='23:00:00', help_text="Jam tutup kantin")
    
    # Pengaturan Lokasi (Titik Pusat Kantin)
    canteen_lat = models.FloatField(default=1.1187, help_text="Latitude pusat kantin")
    canteen_lon = models.FloatField(default=104.0485, help_text="Longitude pusat kantin")
    max_radius_meters = models.IntegerField(default=100, help_text="Batas radius maksimal (dalam meter)")

    class Meta:
        verbose_name = "System Setting"
        verbose_name_plural = "System Settings"

    def save(self, *args, **kwargs):
        # Mencegah pembuatan baris baru, hanya boleh ada 1 record (Singleton)
        if not self.pk and SystemSettings.objects.exists():
            raise ValidationError('Hanya boleh ada satu pengaturan sistem (Singleton).')
        return super(SystemSettings, self).save(*args, **kwargs)

    @classmethod
    def get_settings(cls):
        # Mengambil data pengaturan, jika belum ada otomatis dibuat dengan nilai default
        obj, created = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Pengaturan ABAC Kantin Global"

class SystemSettings(models.Model):
    # Waktu Operasional
    open_hour = models.IntegerField(
        default=7,
        validators=[MinValueValidator(0), MaxValueValidator(23)],
        help_text="Jam buka (contoh: 7 untuk 07:00)"
    )
    close_hour = models.IntegerField(
        default=16,
        validators=[MinValueValidator(0), MaxValueValidator(23)],
        help_text="Jam tutup (contoh: 16 untuk 16:00)"
    )
    
    # Lokasi Kantin
    canteen_lat = models.FloatField(default=1.1187, help_text="Latitude pusat kantin")
    canteen_lon = models.FloatField(default=104.0485, help_text="Longitude pusat kantin")
    max_radius_meters = models.IntegerField(default=10000, help_text="Batas radius maksimal (dalam meter)")

    class Meta:
        verbose_name = "System Setting"
        verbose_name_plural = "System Settings"

    def save(self, *args, **kwargs):
        # Mencegah pembuatan baris baru, menjamin ini adalah Singleton
        if self.__class__.objects.count() > 0 and self.pk != self.__class__.objects.first().pk:
            raise ValidationError('Hanya boleh ada satu pengaturan sistem (Singleton).')
        super().save(*args, **kwargs)

    @classmethod
    def get_settings(cls):
        # Jika data belum ada di database, otomatis dibuat dengan nilai default
        obj, created = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Pengaturan Sistem ABAC Global"
