from rest_framework import permissions

class IsAdminUser(permissions.BasePermission):
    """Hanya memperbolehkan akses ke Admin (Grup 'Admin' ATAU Superuser/is_staff)."""
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and (
            request.user.is_staff or request.user.groups.filter(name='Admin').exists()
        )
        
class IsAdminOrSelf(permissions.BasePermission):
  """
  Memperbolehkan akses jika user adalah Admin atau jika user adalah objek yang sedang diakses.
  """
  message = "Anda tidak memiliki izin untuk mengakses atau mengubah profil ini."
  
  def has_permission(self, request, view):
    # Izinkan akses jika pengguna terautentikasi. Izin tingkat objek akan menangani pemeriksaan lebih lanjut.
     return request.user and request.user.is_authenticated

  def has_object_permission(self, request, view, obj):
    # Admin bisa melakukan apapun
    if request.user.is_staff or request.user.groups.filter(name='Admin').exists():
      return True
    # Pengguna yang bukan admin hanya bisa mengakses/mengubah profil mereka sendiri
    return obj == request.user