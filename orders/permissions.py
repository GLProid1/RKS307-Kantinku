# permissions.py
from rest_framework import permissions
from .models import Order, Tenant, MenuItem # <-- Menggabungkan import

# ...
# IsKasir (Gabungan)
class IsKasir(permissions.BasePermission):
  """
  Izin akses hanya untuk user dengan status 
  is_staff atau tergabung di group 'Cashier'
  """
  def has_permission(self, request, view):
    user = request.user
    if not user or not user.is_authenticated:
      return False
    
    if getattr(user, 'is_staff', False):
      return True
    
    try:
      return user.groups.filter(name='Cashier').exists()
    except Exception:
      return False
# ...

# ...
# IsAdminUser (Sudah Benar)
class IsAdminUser(permissions.BasePermission):
    """Hanya memperbolehkan akses ke Admin."""
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.groups.filter(name='Admin').exists()
# ...


# KELAS DARI BRANCH 1: Untuk Stand (Tenant) dan Menu
class IsTenantStaff(permissions.BasePermission):
    """
    Izin untuk Admin atau Seller (staf) yang terdaftar di Tenant.
    Digunakan untuk view Tenant (Stand) dan MenuItem.
    """
    message = "Anda bukan staf dari tenant ini."

    def has_object_permission(self, request, view, obj):
        # Admin boleh melakukan apa saja
        if request.user.groups.filter(name='Admin').exists():
            return True
        
        # 'obj' bisa berupa Tenant atau MenuItem
        tenant = None
        if isinstance(obj, Tenant):
            tenant = obj
        elif isinstance(obj, MenuItem):
            tenant = obj.tenant
        
        if tenant:
            # Cek apakah user ada di daftar 'staff' tenant ini
            return tenant.staff.filter(pk=request.user.pk).exists()
        
        return False

# KELAS DARI BRANCH 1: Untuk Order (Menggantikan IsTenantOwner)
class IsOrderTenantStaff(permissions.BasePermission):
    """
    Izin untuk Admin atau Seller (staf) yang terdaftar 
    di tenant pemilik Order.
    """
    message = "Anda tidak memiliki izin untuk mengakses order dari tenant ini."

    def has_object_permission(self, request, view, obj):
        # Admin boleh melakukan apa saja
        if request.user.groups.filter(name='Admin').exists():
            return True
        
        # 'obj' di sini adalah instance Order
        if isinstance(obj, Order):
            return obj.tenant.staff.filter(pk=request.user.pk).exists()
        
        return False

# KELAS DARI BRANCH 2: Untuk Guest (Pelanggan Non-Login)
class IsGuestOrderOwner(permissions.BasePermission):
  """
  Izin untuk guest (non-login) yang memiliki UUID order di session.
  """
  message = "Anda tidak memiliki izin untuk mengakses order ini."

  def has_permission(self, request, view):
    # Selalu izinkan akses ke view, pengecekan sebenarnya ada di object-level
    return True 

  def has_object_permission(self, request, view, obj):
    # obj adalah instance Order
    user = request.user
    
    # Permission ini HANYA untuk guest. 
    # Jika user sudah login, biarkan permission lain (IsOrderTenantStaff) yg menangani
    if user.is_authenticated:
      return False 
    
    # Jika user adalah guest, cek session
    guest_uuids = request.session.get('guest_order_uuids', [])
    return str(obj.uuid) in guest_uuids