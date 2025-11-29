from rest_framework import permissions

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
