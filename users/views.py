import logging
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from rest_framework.views import APIView
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.decorators import action
from rest_framework_simplejwt.tokens import RefreshToken, OutstandingToken, BlacklistedToken
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from axes.helpers import get_client_ip_address
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from .serializers import UserSerializer, UserCreateSerializer, UpdateUserSerializer, ChangePasswordSerializer
from .permissions import IsAdminUser, IsAdminOrSelf

# Inisialisasi Audit Logger
audit_logger = logging.getLogger('security.audit')

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by('username') 

    def get_serializer_class(self):
        if self.action == 'create':
          return UserCreateSerializer
        elif self.action in ['update', 'partial_update']:
          return UpdateUserSerializer
        return UserSerializer

    def get_permissions(self):
      if self.action in ['list', 'create', 'destroy', 'summary']:
        return [IsAdminUser()]
      elif self.action in ['retrieve', 'update', 'partial_update']:
        return [IsAdminOrSelf()]
      return super().get_permissions()
    
    def get_queryset(self):
      user = self.request.user
      if user.is_authenticated and not (user.is_staff or user.groups.filter(name='Admin').exists()):
        return User.objects.filter(pk=user.pk)
      return super().get_queryset() 

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


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle] # Rate limiting untuk cegah brute-force IP

    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")
        client_ip = get_client_ip_address(request)

        user = authenticate(request=request, username=username, password=password)
        
        if not user:
            audit_logger.warning(f"[AUTH FAILED] Login attempt/lockout for user: {username} from IP: {client_ip}")
            return Response({"detail": "Username/password salah atau akun terkunci."}, status=status.HTTP_401_UNAUTHORIZED)

        # Gunakan JWT Refresh Token
        refresh = RefreshToken.for_user(user)
        
        role = 'customer'
        if user.groups.filter(name__iexact='Cashier').exists(): role = 'cashier'
        elif user.groups.filter(name__iexact='Seller').exists(): role = 'seller'
        elif user.groups.filter(name__iexact='Admin').exists(): role = 'admin'

        audit_logger.info(f"[AUTH SUCCESS] User: {username} logged in successfully from IP: {client_ip}")

        response = Response({
            "access": str(refresh.access_token),
            "user": {**UserSerializer(user).data, "role": role},
            "message": "Login berhasil"
        }, status=status.HTTP_200_OK)

        # Set Refresh Token ke HttpOnly Cookie
        response.set_cookie(
            key='refresh_token',
            value=str(refresh),
            httponly=True,
            secure=settings.SESSION_COOKIE_SECURE,
            samesite='Lax',
            max_age=timedelta(days=1)
        )
        return response


class CustomTokenRefreshView(TokenRefreshView):
    throttle_classes = [AnonRateThrottle, UserRateThrottle]

    def post(self, request, *args, **kwargs):
        refresh_token = request.COOKIES.get('refresh_token')
        
        # Buat copy dari request.data agar bisa disisipi token dari Cookie
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        
        if refresh_token and 'refresh' not in data:
            data['refresh'] = refresh_token
            
        serializer = TokenRefreshSerializer(data=data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise InvalidToken(e.args[0])
            
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request, *args, **kwargs):
        refresh_token = request.COOKIES.get('refresh_token') or request.data.get("refresh")
        
        if not refresh_token:
            return Response({"detail": "Refresh token tidak ditemukan."}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            token = RefreshToken(refresh_token)
            token.blacklist() # Matikan token
            logout(request)
            
            response = Response({"detail": "Logout Berhasil"}, status=status.HTTP_200_OK)
            response.delete_cookie('refresh_token') # Hapus cookie
            
            audit_logger.info(f"[LOGOUT] User: {request.user.username} logged out securely.")
            return response
        except Exception:
            audit_logger.warning(f"[LOGOUT ABUSE] Invalid token submitted by User: {request.user.username}.")
            return Response({"detail": "Token tidak valid."}, status=status.HTTP_400_BAD_REQUEST)


class EditView(APIView):
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
        
        # Blacklist SEMUA token lama agar perangkat lain ter-logout
        tokens = OutstandingToken.objects.filter(user=request.user)
        for token in tokens:
            BlacklistedToken.objects.get_or_create(token=token)
            
        audit_logger.info(f"[PASSWORD CHANGED] User: {request.user.username} changed password. Tokens revoked.")
        
        refresh = RefreshToken.for_user(request.user)
        response = Response({
            "detail": "Password diperbarui, perangkat lain otomatis ter-logout.", 
            "access": str(refresh.access_token)
        }, status=status.HTTP_200_OK)

        # Set cookie baru
        response.set_cookie(
            key='refresh_token', value=str(refresh), httponly=True,
            secure=settings.SESSION_COOKIE_SECURE, samesite='Lax', max_age=timedelta(days=1)
        )
        return response


class CheckAuthView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request, *args, **kwargs):
        user = request.user
        
        # Deteksi role ulang
        role = 'customer'
        if user.groups.filter(name__iexact='Cashier').exists(): role = 'cashier'
        elif user.groups.filter(name__iexact='Seller').exists(): role = 'seller'
        elif user.groups.filter(name__iexact='Admin').exists(): role = 'admin'
        
        return Response({
            "user": {**UserSerializer(user).data, "role": role},
            "message": "Pengguna terautentikasi"
        }, status=status.HTTP_200_OK)