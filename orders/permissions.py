# permissions.py
<<<<<<< HEAD
=======
from rest_framework import permissions
from .models import Order
>>>>>>> c558d1661182783cef3bc0dcc9c31381c0ddd666

from rest_framework import permissions
from .models import Order, Tenant, MenuItem # Tambahkan import

# ...
# IsKasir (dengan perbaikan 'Cashier')
class IsKasir(permissions.BasePermission):
  """
  Izin akses hanya untuk user dengan status 
  is_staff atau tergabung di group 'Cashier'
  """
  def has_permission(self, request, view):
    user = request.user
    if not user or not user.is_authenticated:
      return False
    
<<<<<<< HEAD
    if getattr(user, 'is_staff', False):
      return True
    
    try:
      return user.groups.filter(name='Cashier').exists() # <-- SUDAH DIPERBAIKI
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


# KELAS BARU 1: Untuk Stand (Tenant) dan Menu
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

# KELAS BARU 2: Untuk Order
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
=======
    # Opsi 1: Cek apakah user adalah staff (superadmin)
    if getattr(user, 'is_staff', False):
      return True
    
    # Opsi 2 : Cek apakah user tergabung di group 'Kasir'
    try:
      # --- PERUBAHAN ---
      # Menggunakan 'Kasir' (Kapital) sesuai dengan UserCreateSerializer
      return user.groups.filter(name='Cashier').exists()
      # --- AKHIR PERUBAHAN ---
    except Exception:
      return False

# --- PERUBAHAN ---
# IsTenantOwner diubah untuk memeriksa object permission
class IsTenantOwner(permissions.BasePermission):
  """
    Izin yang hanya dimiliki pemilik tenant untuk mengakses atau mengubah order
    milik tenantnya. Ini adalah object-level permission.
  """
  message = "Anda tidak memiliki izin untuk mengakses order dari tenant ini."
  
  def has_permission(self, request, view):
    # Memastikan user harus login untuk menggunakan permission ini
    return request.user and request.user.is_authenticated
  
  def has_object_permission(self, request, view, obj):
    # obj adalah instance Order
    user = request.user

    # Jika user adalah staff global (superadmin), izinkan
    if user.is_staff:
      return True
    
    # Cek apakah user (yang sudah login) ada di dalam staff tenant dari order tsb
    return obj.tenant.staff.filter(pk=user.pk).exists()
# --- AKHIR PERUBAHAN ---


# --- PERUBAHAN BARU ---
# Menambahkan Izin untuk Guest (Pelanggan Non-Login)
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
    # Jika user sudah login, biarkan permission lain (IsTenantOwner) yg menangani
    if user.is_authenticated:
      return False 
    
    # Jika user adalah guest, cek session
    # Kita akan menyimpan 'guest_order_uuids' di session saat membuat order
    guest_uuids = request.session.get('guest_order_uuids', [])
    return str(obj.uuid) in guest_uuids
# --- AKHIR PERUBAHAN BARU ---
>>>>>>> c558d1661182783cef3bc0dcc9c31381c0ddd666
