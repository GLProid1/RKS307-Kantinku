from rest_framework import permissions
from tenants.models import Tenant, MenuItem
from django.shortcuts import get_object_or_404

class IsTenantStaff(permissions.BasePermission):
    message = "Anda bukan staf dari tenant ini."

    def has_object_permission(self, request, view, obj):
        # Cek Superuser/Admin
        if request.user.is_staff or request.user.groups.filter(name='Admin').exists():
            return True
        
        tenant = None
        if isinstance(obj, Tenant):
            tenant = obj
        elif isinstance(obj, MenuItem):
            tenant = obj.tenant
        
        if tenant:
            # --- MULAI DEBUG PRINT (Cek Log Docker Nanti) ---
            print(f"--- DEBUG PERMISSION ---")
            print(f"User Login: {request.user} (ID: {request.user.id})")
            print(f"Target Tenant: {tenant.name} (ID: {tenant.id})")
            
            # Cek apakah user ada di list staff
            is_member = tenant.staff.filter(pk=request.user.pk).exists()
            
            # Print semua staff yang terdaftar di tenant ini
            all_staff = list(tenant.staff.all().values_list('username', flat=True))
            print(f"Daftar Staff di Database: {all_staff}")
            print(f"Apakah User Member? {is_member}")
            print(f"------------------------")
            # --- SELESAI DEBUG ---

            return is_member
        
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
