from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.shortcuts import get_object_or_404
from .models import Tenant, MenuItem, VariantGroup, VariantOption
from .serializers import StandSerializer, MenuItemSerializer, VariantGroupSerializer, VariantGroupCreateSerializer, VariantOptionSerializer, VariantOptionCreateSerializer
from .permissions import IsTenantStaff, IsTenantStaffForNestedViews
from django.contrib.auth.models import User
from rest_framework.response import Response
from users.permissions import IsAdminUser
from rest_framework import generics

class StandViewSet(viewsets.ModelViewSet):
    serializer_class = StandSerializer
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated:
            if user.is_staff:
                return Tenant.objects.all()
            else:
                return user.tenants.all()
        return Tenant.objects.filter(active=True)

    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser], url_path='manage-staff')
    def manage_staff(self, request, pk=None):
        tenant = self.get_object()
        user_id = request.data.get('user_id')
        action = request.data.get('action')

        if not user_id or not action:
            return Response({"error": "user_id dan action diperlukan"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(pk=user_id, groups__name='Seller')
        except User.DoesNotExist:
            return Response({"error": "User Seller tidak ditemukan"}, status=status.HTTP_404_NOT_FOUND)

        if action == 'add':
            tenant.staff.add(user)
            return Response({"status": f"User {user.username} ditambahkan ke {tenant.name}"}, status=status.HTTP_200_OK)
        elif action == 'remove':
            tenant.staff.remove(user)
            return Response({"status": f"User {user.username} dihapus dari {tenant.name}"}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Action tidak valid (gunakan 'add' atau 'remove')"}, status=status.HTTP_400_BAD_REQUEST)

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            permission_classes = [AllowAny]
        elif self.action in ['create', 'destroy']:
            permission_classes = [IsAdminUser]
        elif self.action in ['update', 'partial_update']:
            permission_classes = [IsTenantStaff]
        elif self.action == 'manage_staff':
            permission_classes = [IsAdminUser]
        else:
            permission_classes = [IsAuthenticated]
        
        return [permission() for permission in permission_classes]

class MenuItemViewSet(viewsets.ModelViewSet):
    serializer_class = MenuItemSerializer
    parser_classes = (MultiPartParser, FormParser,JSONParser)

    def get_queryset(self):
        stand_pk = self.kwargs.get('stand_pk')
        return MenuItem.objects.filter(tenant_id=stand_pk)

    def get_tenant(self):
        stand_pk = self.kwargs.get('stand_pk')
        return get_object_or_404(Tenant, pk=stand_pk)

    def get_permissions(self):
        """
        Menggunakan AllowAny untuk melihat, dan IsTenantStaffForNestedViews untuk semua aksi tulis.
        Izin ini memeriksa kepemilikan tenant dari URL, yang lebih aman untuk create/list.
        """
        if self.action in ['list', 'retrieve']:
            self.permission_classes = [permissions.AllowAny]
        else:
            self.permission_classes = [IsAuthenticated, IsTenantStaffForNestedViews] 
        return super().get_permissions()

    def perform_create(self, serializer):
        tenant = self.get_tenant()
        serializer.save(tenant=tenant)

class VariantGroupViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsTenantStaffForNestedViews]

    def get_queryset(self):
        stand_pk = self.kwargs.get('stand_pk')
        return VariantGroup.objects.filter(tenant_id=stand_pk)

    def get_serializer_class(self):
        if self.action == 'create':
            return VariantGroupCreateSerializer
        return VariantGroupSerializer

    def perform_create(self, serializer):
        tenant = get_object_or_404(Tenant, pk=self.kwargs.get('stand_pk'))
        serializer.save(tenant=tenant)

class VariantOptionViewSet(viewsets.ModelViewSet):
    serializer_class = VariantOptionSerializer
    permission_classes = [IsAuthenticated, IsTenantStaffForNestedViews]

    def get_queryset(self):
        group_pk = self.kwargs.get('group_pk')
        stand_pk = self.kwargs.get('stand_pk')
        return VariantGroup.objects.filter(group_id=group_pk, group__tenant_id=stand_pk)
    
    def get_serializer_class(self):
        if self.action == 'create':
            return VariantOptionCreateSerializer
        return VariantOptionSerializer

    def perform_create(self, serializer):
        group = get_object_or_404(VariantGroup, pk=self.kwargs.get('group_pk'), tenant_id=self.kwargs.get('stand_pk'))
        serializer.save(group=group)