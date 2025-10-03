from rest_framework import permissions

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