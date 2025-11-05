# permissions.py
from rest_framework import permissions
from .models import Order, Tenant, MenuItem

# --- PERBAIKAN: Izin baru untuk KASIR ---
class IsCashierUser(permissions.BasePermission):
    """Hanya memperbolehkan akses ke Kasir atau Admin/Staff."""
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        
        # Superuser/Staff (Admin) Boleh
        if getattr(user, 'is_staff', False):
            return True
        
        # User di grup 'Cashier' Boleh
        return user.groups.filter(name='Cashier').exists()

class IsAdminUser(permissions.BasePermission):
    """Hanya memperbolehkan akses ke Admin (Grup 'Admin' ATAU Superuser/is_staff)."""
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and (
            request.user.is_staff or request.user.groups.filter(name='Admin').exists()
        )

class IsTenantStaff(permissions.BasePermission):
    """
    Izin untuk Admin atau Seller (staf) yang terdaftar di Tenant.
    Digunakan untuk view Tenant (Stand) dan MenuItem.
    """
    message = "Anda bukan staf dari tenant ini."

    def has_object_permission(self, request, view, obj):
        # --- PERBAIKAN: Cek 'is_staff' (Superuser) ---
        if request.user.is_staff or request.user.groups.filter(name='Admin').exists():
            return True
        
        tenant = None
        if isinstance(obj, Tenant):
            tenant = obj
        elif isinstance(obj, MenuItem):
            tenant = obj.tenant
        
        if tenant:
            return tenant.staff.filter(pk=request.user.pk).exists()
        
        return False

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
    user = request.user
    
    if user.is_authenticated:
      return False 
    
    guest_uuids = request.session.get('guest_order_uuids', [])
    return str(obj.uuid) in guest_uuids