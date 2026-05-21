import logging
import pyotp
import qrcode
import base64
from io import BytesIO
import random
import string
from .models import UserMFA, BackupCode
from django.core.signing import TimestampSigner, SignatureExpired, BadSignature
from django.contrib.auth.hashers import make_password, check_password
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
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from axes.helpers import get_client_ip_address
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from .serializers import UserSerializer, UserCreateSerializer, UpdateUserSerializer, ChangePasswordSerializer
from .permissions import IsAdminUser, IsAdminOrSelf

mfa_signer = TimestampSigner()
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
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")
        client_ip = get_client_ip_address(request)

        user = authenticate(request=request, username=username, password=password)
        
        if not user:
            audit_logger.warning(f"[AUTH FAILED] Login attempt/lockout for user: {username} from IP: {client_ip}")
            return Response({"detail": "Username/password salah atau akun terkunci."}, status=status.HTTP_401_UNAUTHORIZED)

        # CEK APAKAH MFA AKTIF
        if hasattr(user, 'usermfa') and user.usermfa.is_enabled:
            # Buat token sementara yang valid selama 5 menit (300 detik)
            temp_token = mfa_signer.sign_object({'user_id': user.id})
            audit_logger.info(f"[MFA REQUIRED] User: {username} needs to provide OTP from IP: {client_ip}")
            
            return Response({
                "detail": "MFA Required. Silakan masukkan kode OTP.",
                "mfa_required": True,
                "temp_token": temp_token
            }, status=status.HTTP_200_OK)

        # JIKA MFA TIDAK AKTIF, LAKUKAN LOGIN NORMAL SEPERTI BIASA
        return self._generate_jwt_response(user, client_ip)
        
    def _generate_jwt_response(self, user, client_ip):
        """Helper method untuk generate JWT (Bisa dipakai juga nanti setelah lolos MFA)"""
        refresh = RefreshToken.for_user(user)
        role = 'customer'
        
        # --- PERBAIKAN DI SINI ---
        # Tambahkan pengecekan user.is_superuser
        if user.is_superuser or user.groups.filter(name__iexact='Admin').exists(): 
            role = 'admin'
        elif user.groups.filter(name__iexact='Seller').exists(): 
            role = 'seller'
        elif user.groups.filter(name__iexact='Cashier').exists(): 
            role = 'cashier'
        # -------------------------

        audit_logger.info(f"[AUTH SUCCESS] User: {user.username} logged in successfully from IP: {client_ip}")

        response = Response({
            "access": str(refresh.access_token),
            "user": {**UserSerializer(user).data, "role": role},
            "message": "Login berhasil"
        }, status=status.HTTP_200_OK)

        response.set_cookie(
            key='refresh_token', value=str(refresh), httponly=True,
            secure=settings.SESSION_COOKIE_SECURE, samesite='Lax', max_age=timedelta(days=1)
        )
        return response
class VerifyMFALoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle] # Mencegah Brute Force kode OTP

    def post(self, request):
        temp_token = request.data.get('temp_token')
        otp_code = request.data.get('otp_code')
        client_ip = get_client_ip_address(request)

        if not temp_token or not otp_code:
            return Response({"detail": "Token sementara dan OTP wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Unsign data, maksimal umur token 5 menit (300 detik)
            data = mfa_signer.unsign_object(temp_token, max_age=300)
            user = User.objects.get(id=data['user_id'])
        except (SignatureExpired, BadSignature):
            return Response({"detail": "Token kadaluarsa atau tidak valid. Silakan login ulang."}, status=status.HTTP_401_UNAUTHORIZED)
        except User.DoesNotExist:
            return Response({"detail": "User tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)

        mfa = user.usermfa
        totp = pyotp.TOTP(mfa.secret_key)

        # 1. Cek apakah itu kode OTP dari Authenticator
        is_valid = totp.verify(otp_code)

        # 2. Jika bukan OTP, cek apakah itu Backup Code
        if not is_valid:
            for backup in mfa.backup_codes.filter(is_used=False):
                if check_password(otp_code, backup.code_hash):
                    is_valid = True
                    backup.is_used = True # Tandai backup code sudah dipakai
                    backup.save()
                    audit_logger.info(f"[MFA BACKUP USED] User: {user.username} logged in using backup code.")
                    break

        if is_valid:
            # Sukses lolos MFA, generate Token Sesungguhnya
            login_view = LoginView()
            return login_view._generate_jwt_response(user, client_ip)
        else:
            audit_logger.warning(f"[MFA FAILED] User: {user.username} failed OTP verification from IP: {client_ip}")
            return Response({"detail": "Kode OTP atau Backup Code salah."}, status=status.HTTP_400_BAD_REQUEST)


class GenerateMFASetupView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        mfa, created = UserMFA.objects.get_or_create(user=user)
        
        # Selalu generate secret baru saat setup ulang
        secret = mfa.generate_secret()
        mfa.is_enabled = False # Jangan aktifkan dulu sebelum di-verify
        mfa.save()

        # Generate URI untuk aplikasi Authenticator
        totp = pyotp.TOTP(secret)
        uri = totp.provisioning_uri(name=user.email or user.username, issuer_name='Kantinku App')

        # Generate QR Code Image dalam Base64
        qr = qrcode.make(uri)
        buffer = BytesIO()
        qr.save(buffer, format="PNG")
        qr_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        return Response({
            "detail": "Silakan scan QR Code ini dengan Google/Microsoft Authenticator Anda.",
            "qr_code_base64": f"data:image/png;base64,{qr_base64}",
            "secret_key": secret # Opsional: Diberikan jika user ingin input manual di HP
        })


class VerifyMFASetupView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        otp_code = request.data.get('otp_code')
        
        try:
            mfa = user.usermfa
        except UserMFA.DoesNotExist:
            return Response({"detail": "Silakan generate MFA terlebih dahulu."}, status=status.HTTP_400_BAD_REQUEST)

        totp = pyotp.TOTP(mfa.secret_key)
        
        if totp.verify(otp_code):
            # OTP Benar, Aktifkan MFA!
            mfa.is_enabled = True
            mfa.save()

            # Hapus backup code lama (jika ada) dan buat 5 backup code baru
            mfa.backup_codes.all().delete()
            raw_backup_codes = []
            
            for _ in range(5):
                # Generate 8 karakter random (huruf besar + angka)
                code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                raw_backup_codes.append(code)
                BackupCode.objects.create(mfa=mfa, code_hash=make_password(code))

            audit_logger.info(f"[MFA ENABLED] User: {user.username} successfully enabled MFA.")

            return Response({
                "detail": "MFA berhasil diaktifkan!",
                "backup_codes": raw_backup_codes,
                "warning": "SIMPAN BACKUP CODES INI DI TEMPAT AMAN! Hanya ditampilkan 1 kali."
            }, status=status.HTTP_200_OK)
            
        return Response({"detail": "Kode OTP tidak valid."}, status=status.HTTP_400_BAD_REQUEST)

class CookieTokenObtainPairView(TokenObtainPairView):
    """
    View khusus untuk Login. Mengembalikan access_token di JSON,
    tapi melempar refresh_token ke HttpOnly Cookie.
    """
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        
        if response.status_code == 200:
            refresh_token = response.data.get('refresh')
            
            # SECURE CODING: Set ke HttpOnly Cookie
            response.set_cookie(
                key='refresh_token',
                value=refresh_token,
                httponly=True,
                secure=settings.SESSION_COOKIE_SECURE, # True di Production
                samesite='Lax',
                max_age=24 * 60 * 60 # 1 hari (sesuai setting SimpleJWT)
            )
            
            # Hapus refresh dari body JSON agar JS frontend tidak bisa membacanya
            if 'refresh' in response.data:
                del response.data['refresh']
                
        return response

class CookieTokenRefreshView(TokenRefreshView):
    """
    View khusus untuk Refresh. Mengambil refresh_token dari Cookie,
    bukan dari body JSON.
    """
    def post(self, request, *args, **kwargs):
        # Ambil token dari cookie
        refresh_token = request.COOKIES.get('refresh_token')
        
        if refresh_token:
            # Karena request.data di DRF bisa immutable, kita buat salinan mutable
            data = request.data.copy() if hasattr(request.data, 'copy') else request.data
            data['refresh'] = refresh_token
            request._full_data = data # Inject data yang sudah ditambahkan refresh token
            
        response = super().post(request, *args, **kwargs)
        
        # Jika ROTATE_REFRESH_TOKENS = True, backend akan men-generate refresh token baru.
        # Kita harus update cookie-nya.
        if response.status_code == 200 and 'refresh' in response.data:
            response.set_cookie(
                key='refresh_token',
                value=response.data.get('refresh'),
                httponly=True,
                secure=settings.SESSION_COOKIE_SECURE,
                samesite='Lax',
                max_age=24 * 60 * 60
            )
            del response.data['refresh']
            
        return response
    


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
