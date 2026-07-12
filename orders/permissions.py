import hmac
import hashlib
import logging
from django.utils import timezone
from django.conf import settings
from rest_framework import permissions
from canteen.utils import calculate_haversine_distance


logger = logging.getLogger('abac_audit')

class IsWithinOperationalHoursAndLocation(permissions.BasePermission):
    message = "Akses ditolak oleh kebijakan ABAC (Waktu atau Lokasi tidak sesuai)."

    def has_permission(self, request, view):
        # 1. EVALUASI WAKTU (Time ABAC)
        # Menggunakan timezone lokal yang dikonfigurasi di Django settings (WIB)
        current_time = timezone.localtime(timezone.now())
        current_hour = current_time.hour

        # Misalnya kita ambil spesifikasi waktu dari setting umum atau tenant
        # Contoh jika default jam 07:00 sd 16:00:
        open_hour = 7
        close_hour = 16

        if not (open_hour <= current_hour < close_hour):
            self.message = f"ABAC DENY [TIME]: Kantin hanya beroperasi pukul {open_hour}:00 - {close_hour}:00 WIB. Waktu saat ini: {current_time.strftime('%H:%M')} WIB."
            logger.warning(f"{self.message} | User: {request.user} | IP: {request.META.get('REMOTE_ADDR')}")
            return False

        # 2. EVALUASI LOKASI (Location ABAC / Geofencing)
        # Kita ambil koordinat user dari Custom Headers (dikirim oleh frontend)
        # Contoh header: X-User-Latitude & X-User-Longitude
        user_lat_str = request.headers.get('X-User-Latitude') or request.query_params.get('lat')
        user_lon_str = request.headers.get('X-User-Longitude') or request.query_params.get('lng')

        if not user_lat_str or not user_lon_str:
            self.message = "ABAC DENY [LOCATION]: Data geolokasi (GPS) wajib dikirimkan untuk mengakses layanan ini."
            logger.warning(f"{self.message} | User: {request.user}")
            return False

        try:
            user_lat = float(user_lat_str)
            user_lon = float(user_lon_str)
        except ValueError:
            self.message = "ABAC DENY [LOCATION]: Format koordinat GPS tidak valid."
            return False

        # Koordinat Pusat Kantin (Bisa diambil dari database Tenant/Canteen)
        # Contoh konfigurasi koordinat:
        CANTEEN_LAT = 1.1187  # Sesuaikan dengan koordinat lokasi kantin
        CANTEEN_LON = 104.0485
        MAX_RADIUS_METERS = 100 # Batas toleransi 100 meter

        distance = calculate_haversine_distance(user_lat, user_lon, CANTEEN_LAT, CANTEEN_LON)

        if distance > MAX_RADIUS_METERS:
            self.message = f"ABAC DENY [GEOFENCE]: Lokasi Anda ({distance:.1f}m) berada di luar jangkauan area kantin (Maks. {MAX_RADIUS_METERS}m)."
            logger.warning(f"{self.message} | User: {request.user} | Distance: {distance:.2f}m")
            return False

        # Jika lolos semua evaluasi atribut lingkungan:
        logger.info(f"ABAC ALLOW | User: {request.user} | Distance: {distance:.2f}m | Time: {current_time.strftime('%H:%M')}")
        return True
        
class IsOrderTenantStaff(permissions.BasePermission):
    """
    Izin untuk Admin, Kasir, atau Seller yang terdaftar 
    di tenant pemilik Order.
    """
    message = "Anda tidak memiliki izin untuk mengakses order dari tenant ini."

    def has_object_permission(self, request, view, obj):
        # 1. Izinkan Admin ATAU Cashier (Kasir butuh akses untuk memproses pembayaran)
        if request.user.is_staff or request.user.groups.filter(name__in=['Admin', 'Cashier']).exists():
            return True
        
        # 2. Cek apakah user adalah Seller (staff) di tenant tersebut
        from .models import Order
        if isinstance(obj, Order):
            return obj.tenant.staff.filter(pk=request.user.pk).exists()
        
        return False
class IsGuestOrderOwner(permissions.BasePermission):
    message = "Anda tidak memiliki izin untuk mengakses order ini."

    def has_permission(self, request, view):
        return True 

    def has_object_permission(self, request, view, obj):
        # 1. AMBIL TOKEN (Prioritas Utama untuk Guest)
        # TOKEN DIAMBIL DARI HEADER ATAU BODY, BUKAN DARI URL
        token = request.headers.get('X-Order-Token') or request.data.get('token')
        
        if token:
            expected_token = self.generate_order_token(str(obj.uuid))
            if hmac.compare_digest(token, expected_token):
                return True

        # 2. Jika User Login (Tanpa membawa token)
        if request.user.is_authenticated:
            # A. Cek Customer pemilik order (berdasarkan email)
            if obj.customer and obj.customer.email == request.user.email:
                return True
                
            # B. Cek Staff Tenant pemilik order
            if hasattr(request.user, 'tenants') and obj.tenant in request.user.tenants.all():
                return True
                
            # C. Cek Admin Django
            if request.user.is_staff:
                return True
          
        return False

    def generate_order_token(self, order_uuid):
        """
        Helper method untuk generate HMAC token. 
        Sekarang sudah berada di dalam class IsGuestOrderOwner.
        """
        return hmac.new(
            settings.SECRET_KEY.encode(),
            order_uuid.encode(),
            hashlib.sha256,
        ).hexdigest()
