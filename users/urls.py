# users/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework.authtoken.views import obtain_auth_token 
from .views import (
    UserViewSet, LoginView, LogoutView, CheckAuthView, EditView, ChangePasswordView
)
app_name = 'users'

router = DefaultRouter()
router.register(r'all', UserViewSet, basename='user') # Akan menjadi api/users/all/

urlpatterns = [
    path('', include(router.urls)),

    # URL Autentikasi
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('check-auth/', CheckAuthView.as_view(), name='check-auth'),
    path('edit-profile/', EditView.as_view(), name='edit-profile'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),

    # Ini adalah URL token-based, jika Anda masih mau pakai
    path('token/', obtain_auth_token, name='api_token_auth'),
]