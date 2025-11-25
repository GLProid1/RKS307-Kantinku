import hmac
import hashlib
from django.conf import settings
from rest_framework import permissions
from .models import Order

class IsOrderTenantStaff(permissions.BasePermission):
    """
    Izin untuk Admin atau Seller (staf) yang terdaftar 
    di tenant pemilik Order.
    """
    message = "Anda tidak memiliki izin untuk mengakses order dari tenant ini."

    def has_object_permission(self, request, view, obj):
        # --- PERBAIKAN: Cek 'is_staff' (Superuser) ---
        if request.user.is_staff or request.user.groups.filter(name='Admin').exists():
            return True
        
        if isinstance(obj, Order):
            return obj.tenant.staff.filter(pk=request.user.pk).exists()
        
        return False

class IsGuestOrderOwner(permissions.BasePermission):
  message = "Anda tidak memiliki izin untuk mengakses order ini."

  def has_permission(self, request, view):
    return True 

  def has_object_permission(self, request, view, obj):
    if request.user.is_authenticated:
      return obj.tenant in request.user.tenants.all()
  
    # Verifikasi dengan signed token
    guest_token = request.GET.get('token') or request.data.get('token')
    if not guest_token:
      return False
    
    expected_token = self.generate_order_token(str(obj.uuid))
    return hmac.compare_digest(guest_token, expected_token)

  def generate_order_token(self, order_uuid):
      """Generate secure token untuk guest order"""
      return hmac.new(
          settings.SECRET_KEY.encode(),
          order_uuid.encode(),
          hashlib.sha256,
      ).hexdigest()