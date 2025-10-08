from rest_framework import permissions
from .models import Order

class IsKasir(permissions.BasePermission):
  """
  Izin akses hanya untuk user dengan status 
  is_staff atau tergabung di group 'Kasir
  """
  def has_permission(self, request, view):
    user = request.user
    if not user or not user.is_authenticated:
      return False
    
    # Opsi 1: Cek apakah user adalah staff
    if getattr(user, 'is_staff', False):
      return True
    
    # Opsi 2 : Cek apakah user tergabung di group 'Kasir
    try:
      return user.groups.filter(name='kasir').exists()
    except Exception:
      return False
    
class IsTenantOwner(permissions.BasePermission):
  """
    Izin yang hanya dimiliki pemilik tenant untuk mengakses atau mengubah order
    milik tenantnya
  """
  message = "Anda tidak memiliki izin untuk mengakses order dari tenant ini"
  
  def has_permission(self, request, view):
    user = request.user
    if not user or not user.is_authenticated:
      return False
    
    order_pk = view.kwargs.get('order_pk')
    if not order_pk:
      return False # Harus ada order_pk dari endpoint
    
    # Cek apakah user ada di dalam staff tenant
    return Order.objects.filter(pk=order_pk, tenant__staff=user).exists()