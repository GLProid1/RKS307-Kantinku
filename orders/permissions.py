import hmac
import hashlib
from django.conf import settings
from rest_framework import permissions

class IsOrderTenantStaff(permissions.BasePermission):
    """
    Izin untuk Admin atau Seller (staf) yang terdaftar 
    di tenant pemilik Order.
    """
    message = "Anda tidak memiliki izin untuk mengakses order dari tenant ini."

    def has_object_permission(self, request, view, obj):
        # 1. Cek 'is_staff' (Superuser) atau grup Admin
        if request.user.is_staff or request.user.groups.filter(name='Admin').exists():
            return True
        
        # 2. Cek apakah user adalah staff di tenant tersebut
        # Import lokal untuk menghindari circular import jika perlu
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
        token = (
            request.query_params.get('token') or 
            request.data.get('token') or 
            request.GET.get('token')
        )
        
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
