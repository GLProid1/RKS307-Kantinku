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
    queryset = User.objects.all().order_by('username') # Default queryset

    def get_serializer_class(self):
        if self.action == 'create':
          return UserCreateSerializer
        elif self.action in ['update', 'partial_update']:
          return UpdateUserSerializer
        return UserSerializer

    def get_permissions(self):
      if self.action in ['list', 'create', 'destroy', 'summary']:
        # Hanya admin yang boleh mengakses list, create, dan delete user
        return [IsAdminUser()]
      elif self.action in ['retrieve', 'update', 'partial_update']:
        # Admin hanya bisa melihat/mengedit user manapun. User biasa hanya bisa melihat/mengedit profilnya sendiri
        return [IsAdminOrSelf()]
      return super().get_permissions()
    
    def get_queryset(self):
      user = self.request.user
      if user.is_authenticated and not (user.is_staff or user.groups.filter(name='Admin').exists()):
        # Admin user yang bisa melihat profil sendiri
        return User.objects.filter(pk=user.pk)
      return super().get_queryset() # Admin akan mendapatkan queryset default

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
  permission_classes = [AllowAny]
  
  def post(self, request, *args, **kwargs):
    username = request.data.get('username')
    password = request.data.get('password')
    
    user = authenticate(request, username=username, password=password)
    
    if user:

      login(request, user)
      # --- LOGIKA BARU PENENTUAN ROLE ---
      role = 'customer' # Default role

      # 1. Prioritas: Jika Superuser atau Staff, otomatis jadi 'admin'
      if user.is_superuser or user.is_staff:
          role = 'admin'
      # 2. Jika bukan superuser, cek grupnya (Seller/Cashier)
      elif user.groups.exists():
          role = user.groups.first().name.lower()
      
      # --- AKHIR PERUBAHAN ---

      token, created = Token.objects.get_or_create(user=user)
      return Response({
        "token": token.key,
        "user": {
                **UserSerializer(user).data,
                "role" : role, # Backend sekarang akan mengirim 'admin'
                "initial_dashboard": f"/{role}-dashboard"
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