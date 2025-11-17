# orders/urls.py
from rest_framework.authtoken.views import obtain_auth_token 
from django.urls import path, include
from rest_framework_nested import routers
from django.conf import settings
from django.conf.urls.static import static
from .views import (
    # View yang sudah ada
    CashConfirmView, CreateOrderView, MidtransWehboohView, 
    OrderDetailView, UpdateOrderStatusView, CancelOrderView, OrderListView,
    TableQRCodeView, TakeawayQRCodeView,
    
    # ViewSet Anda
    UserViewSet, 
    StandViewSet, 
    MenuItemViewSet,
    ReportDashboardAPIView,
    VariantGroupViewSet,
    VariantOptionViewSet,
     
    LoginView,
    LogoutView,
    CheckAuthView # <-- Impor ViewSet baru
)

# --- BAGIAN ROUTER (Gabungan) ---
# Router ini sudah benar karena tidak menambahkan prefiks 'orders/'
router = routers.DefaultRouter()
router.register(r'users', UserViewSet, basename='user')
router.register(r'stands', StandViewSet, basename='stand')

stands_router = routers.NestedDefaultRouter(router, r'stands', lookup='stand')
stands_router.register(r'menus', MenuItemViewSet, basename='stand-menus')
stands_router.register(r'variant-groups', VariantGroupViewSet, basename='stand-variant-groups')

groups_router = routers.NestedDefaultRouter(stands_router, r'variant-groups', lookup='group')
groups_router.register(r'options', VariantOptionViewSet, basename='group-options')


# --- DAFTAR URL PATTERN (Gabungan) ---

urlpatterns = [
    path('auth/login/', LoginView.as_view(), name='auth-login'),
    path('auth/logout/', LogoutView.as_view(), name='auth-logout'),
    path('auth/user/', CheckAuthView.as_view(), name='auth-check'),
    
    path('reports/summary/', ReportDashboardAPIView.as_view(), name='reports-summary'),
    
    # --- PERBAIKAN: Hapus prefiks "orders/" ---
    path("create/", CreateOrderView.as_view(), name='create-order'),
    path("all/", OrderListView.as_view(), name='order-list'),
    
    path("<uuid:order_uuid>/", OrderDetailView.as_view(), name='order-detail'),
    path("<uuid:order_uuid>/confirm-cash/", CashConfirmView.as_view(), name='confirm-cash'),
    path("<uuid:order_uuid>/cancel/", CancelOrderView.as_view(), name='cancel-order'),
    path("<uuid:order_uuid>/update-status/", UpdateOrderStatusView.as_view(), name='update-order-status'),
    # --- AKHIR PERBAIKAN ---
    
    path("webhooks/payment/", MidtransWehboohView.as_view(), name='payment-webhooks'),
    path("tables/<str:table_code>/qr/", TableQRCodeView.as_view(), name='table-qr-code'),
    path('token-auth/', obtain_auth_token, name='api_token_auth'),
    path("tenants/<int:tenant_id>/takeaway-qr/", TakeawayQRCodeView.as_view(), name='takeaway-qr-code'),

    # Daftarkan semua URL router
    path('', include(router.urls)),
    path('', include(stands_router.urls)),
    path('', include(groups_router.urls)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)