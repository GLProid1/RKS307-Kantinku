# users/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    UserViewSet, LoginView, LogoutView, CheckAuthView, 
    EditView, ChangePasswordView, CookieTokenRefreshView,
    VerifyMFALoginView, GenerateMFASetupView, VerifyMFASetupView,
)

app_name = 'users'
router = DefaultRouter()
router.register(r'', UserViewSet, basename='user')

urlpatterns = [
    # URL Autentikasi
    path('login/', LoginView.as_view(), name='login'),
    path('login/mfa/verify/', VerifyMFALoginView.as_view(), name='mfa-login-verify'),
    
    path('mfa/setup/generate/', GenerateMFASetupView.as_view(), name='mfa-setup-generate'),
    path('mfa/setup/verify/', VerifyMFASetupView.as_view(), name='mfa-setup-verify'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('check-auth/', CheckAuthView.as_view(), name='check-auth'),
    path('edit-profile/', EditView.as_view(), name='edit-profile'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),
    # URL Refresh Token JWT Baru
    path('token/refresh/', CookieTokenRefreshView.as_view(), name='token_refresh'),
    path('', include(router.urls)),
    
]