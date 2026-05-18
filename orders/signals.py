from django.core.cache import cache
from django.db.models.signals import post_save
from django.dispatch import receiver
from orders.models import Order # Sesuaikan import model Order Anda

CACHE_VERSION = "v1"

@receiver(post_save, sender=Order)
def invalidate_dashboard_cache(sender, instance, created, **kwargs):
    """
    Fungsi ini akan otomatis terpanggil setiap kali ada Order baru (created)
    atau ketika status Order di-update (termasuk pembayaran sukses/batal).
    """
    stand_id = instance.tenant_id # Ambil ID stand dari pesanan terkait
    
    # Kumpulkan daftar keys yang mungkin perlu dihapus
    keys_to_delete = [
        f"{CACHE_VERSION}_dashboard_report_hari-ini_{stand_id}",
        f"{CACHE_VERSION}_dashboard_report_hari-ini_semua",
        f"{CACHE_VERSION}_dashboard_report_7-hari_{stand_id}",
        f"{CACHE_VERSION}_dashboard_report_7-hari_semua",
    ]
    
    # Hapus cache tersebut dari Redis
    cache.delete_many(keys_to_delete)