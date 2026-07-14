from rest_framework import permissions
from tenants.models import Tenant, MenuItem
from django.shortcuts import get_object_or_404
from canteen.utils import calculate_haversine_distance
from django.utils import timezone

class IsTenantStaff(permissions.BasePermission):
    message = "Anda bukan staf dari tenant ini."

    def has_object_permission(self, request, view, obj):
        # Cek Superuser/Admin
        if request.user.is_staff or request.user.groups.filter(name='Admin').exists():
            return True
        
        tenant = None
        if isinstance(obj, Tenant):
            tenant = obj
        elif isinstance(obj, MenuItem):
            tenant = obj.tenant
        
        if tenant:
            
            
            # Cek apakah user ada di list staff
            is_member = tenant.staff.filter(pk=request.user.pk).exists()
            
            # Print semua staff yang terdaftar di tenant ini
            

            return is_member
        
        return False
    
class IsTenantStaffForNestedViews(permissions.BasePermission):
    """
    Izin untuk memeriksa apakah pengguna adalah staff dari tenant
    yang ID nya ada di URL (stand_pk)
    """
    message = "Anda bukan staff dari tenant ini"
    
    def has_permission(self, request, view):
        # Selalu beri izin kenapa Admin/Superuser
        if request.user.is_staff or request.user.groups.filter(name='Admin').exists():
            return True
        
        # Ambil stand_pk dari URL
        stand_pk = view.kwargs.get('stand_pk')
        if not stand_pk:
            return False
        
        # Periksa apakah pengguna yang terutentikasi ada didalam staff tenant tersebut
        return request.user.tenants.filter(pk=stand_pk).exists()


class IsWithinOperationalHoursAndLocation(permissions.BasePermission):
    message = "Akses ditolak: Lokasi atau jam operasional tidak sesuai."

    def has_permission(self, request, view):
        # 1. Identifikasi Tenant (karena setiap stand punya aturan sendiri)
        # Ambil stand_pk jika ada di URL, atau ambil dari objek jika itu detail view
        stand_pk = view.kwargs.get('stand_pk') or view.kwargs.get('pk')
        if not stand_pk:
            return True # Lewati jika bukan akses ke spesifik tenant
            
        tenant = Tenant.objects.get(pk=stand_pk)

        # 2. EVALUASI WAKTU (Time ABAC)
        current_time = timezone.localtime(timezone.now()).time()
        # Menggunakan field dari model Tenant
        if not (tenant.open_hour <= current_time.hour < tenant.close_hour):
            self.message = f"Kantin buka pukul {tenant.open_hour}:00 - {tenant.close_hour}:00 WIB."
            return False

        # 3. EVALUASI LOKASI (Location ABAC)
        user_lat = request.headers.get('X-User-Latitude')
        user_lon = request.headers.get('X-User-Longitude')

        if not user_lat or not user_lon:
            self.message = "Data geolokasi wajib diaktifkan."
            return False

        # Gunakan field dari model Tenant[cite: 7]
        distance = calculate_haversine_distance(
            float(user_lat), float(user_lon), 
            tenant.latitude, tenant.longitude
        )

        if distance > tenant.max_radius_meters:
            self.message = f"Anda berada di luar jangkauan area kantin ({distance:.0f}m)."
            return False

        return True
