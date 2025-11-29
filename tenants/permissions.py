from rest_framework import permissions
from tenants.models import Tenant, MenuItem
from django.shortcuts import get_object_or_404

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