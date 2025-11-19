from django.contrib.auth.models import User
from rest_framework.views import APIView
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from .serializers import UserSerializer, UserCreateSerializer, UpdateUserSerializer, ChangePasswordSerializer
from rest_framework.authtoken.models import Token
from .permissions import IsAdminUser, IsAdminOrSelf
from django.contrib.auth.hashers import check_password
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.contrib.auth import authenticate, login, logout
from rest_framework.decorators import action
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
import re


# Create your views here.
class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by('username')

    def get_serializer_class(self):
        if self.action == 'create':
          return UserCreateSerializer
        elif self.action in ['update', 'partial_update']:
          return UpdateUserSerializer
        return UserSerializer

    def get_permissions(self):
      if self.action == 'list' or self.action == 'create' or self.action == 'destroy':
        # Hanya admin yang boleh mengakses list, create, dan delete user
        permissions_classes = [IsAdminUser]
      elif self.action == 'retrieve' or self.action == 'update' or self.action == 'partial_update':
        # Admin hanya bisa melihat/mengedit user manapun. User biasa hanya bisa melihat/mengedit profilnya sendiri
        permissions_classes = [IsAdminOrSelf]
      else:
        # Untuk aksi lain seperti 'summary', hanya admin yang boleh
        permissions_classes = [IsAdminUser]
      return [permission() for permission in permissions_classes]
    
    def get_queryset(self):
      user = self.request.user
      if user.is_authenticated and (user.is_staff or user.groups.filter(name='Admin').exists()):
        # Admin bisa melihat semua user
        return User.objects.all().order_by('username')
      elif user.is_authenticated:
        # User biasa hanya bisa melihat profilnya sendiri
        return User.objects.filter(pk=user.pk)
      return User.objects.none() # Tidak ada user untuk permintaan yang tidak terautentikasi

    @action(detail=False, methods=['get'])
    def summary(self, request):
        admin_count = User.objects.filter(groups__name='Admin').count()
        seller_count = User.objects.filter(groups__name='Seller').count()
        cashier_count = User.objects.filter(groups__name='Cashier').count()
        
        summary_data = {
            'admins': {'count': admin_count, 'description': 'Full system access'},
            'sellers': {'count': seller_count, 'description': 'Manage stands & menus'},
            'cashiers': {'count': cashier_count, 'description': 'Process payments'},
        }
        return Response(summary_data)
    
@method_decorator(csrf_exempt, name='dispatch')
class LoginView(APIView):
  """
  Menangani proses login pengguna. Mengembalikan data pengguna dan token autentikasi.
  """
  permission_classes = [AllowAny]
  
  def post(self, request, *args, **kwargs):
    username = request.data.get('username')
    password = request.data.get('password')
    
    user = authenticate(request, username=username, password=password)
    
    if user:
      # Untuk autentikasi token
      # Tentukan peran pengguna berdasarkan grub
      role = 'customer' # Default page, jika tidak ada grub spesifik
      if user.groups.filter(name='Admin').exists():
        role = 'admin'
      elif user.groups.filter(name='Seller').exists():
        role = 'seller'
      elif user.groups.filter(name='Cashier').exists():
        role = 'cashier'
      token, created = Token.objects.get_or_create(user=user)
      return Response({
        "token": token.key,
        "user": {
                **UserSerializer(user).data,
                "role" : role,
                "initial_dashboard": f"/{role}-dashboard" # URL untuk frontend
                },
        "message": f"Login Berhasil. Hi, {user.username}!"
      }, status=status.HTTP_200_OK)
    else:
      return Response({
        "detail": "Username atau Password yang anda masukkan salah. Silahkan coba lagi."
      }, status=status.HTTP_401_UNAUTHORIZED)

class LogoutView(APIView):
  """
  Menangani proses logout pengguna. Menghapus token autentkasi dan mengakhiri sesi.
  """
  permission_classes = [IsAuthenticated]
  
  def post(self, request, *args, **kwargs):
    # Batalkan token jika ada
    if hasattr(request.user, 'auth_token'):
       request.user.auth_token.delete()
    # Hapus sesi
    logout(request)
    return Response({
      "detail": "Logout Berhasil"
    }, status=status.HTTP_200_OK)
    
class EditView(APIView):
  """
  Menangani proses edit profile pengguna
  """
  permission_classes = [IsAuthenticated]
  def post(self, request, *args, **kwargs):
    user = request.user
    serializer = UpdateUserSerializer(user, data=request.data, partial=True)
    
    if serializer.is_valid():
      serializer.save()
      return Response({"detail": "Profil berhasil diperbarui", "user": UserSerializer(user).data}, status=status.HTTP_200_OK)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
  
class ChangePasswordView(APIView):
  permission_classes = [IsAuthenticated]
  
  def post(self, request, *args, **kwargs):
    serializer = ChangePasswordSerializer(data=request.data, context={'request':request})
    if not serializer.is_valid():
      return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    serializer.save()
    from rest_framework.authtoken.models import Token
    Token.objects.filter(user=request.user).delete()
    new_token = Token.objects.create(user=request.user)
    return Response({"detail": "Password berhasil diperbarui", "new_token": new_token.key}, status=status.HTTP_200_OK)
    
class CheckAuthView(APIView):
  """
  Memeriksa apakah pengguna terautentikasi dan mengembalikan detailnya.
  """
  permission_classes = [IsAuthenticated]
  
  def get(self, request, *args, **kwargs):
    return Response({
      "user": UserSerializer(request.user).data,
      "message": "Pengguna teruatentikasi"
    }, status=status.HTTP_200_OK)