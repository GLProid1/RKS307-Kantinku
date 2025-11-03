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
    VariantOptionViewSet  # <-- Impor ViewSet baru
)

# --- BAGIAN ROUTER (Gabungan) ---

# Level 1: /api/
router = routers.DefaultRouter()
router.register(r'users', UserViewSet, basename='user')
router.register(r'stands', StandViewSet, basename='stand')

# Level 2: /api/stands/<stand_pk>/...
stands_router = routers.NestedSimpleRouter(router, r'stands', lookup='stand')
stands_router.register(r'menus', MenuItemViewSet, basename='stand-menus')
stands_router.register(r'variant-groups', VariantGroupViewSet, basename='stand-variant-groups')

# Level 3: /api/stands/<stand_pk>/variant-groups/<group_pk>/...
groups_router = routers.NestedSimpleRouter(stands_router, r'variant-groups', lookup='group')
groups_router.register(r'options', VariantOptionViewSet, basename='group-options')


# --- DAFTAR URL PATTERN (Gabungan) ---

urlpatterns = [
    path('reports/summary/', ReportDashboardAPIView.as_view(), name='reports-summary'),
    
    path("orders/create/", CreateOrderView.as_view(), name='create-order'),
    path("orders/all/", OrderListView.as_view(), name='order-list'),
    
    # --- PERUBAHAN (Menggunakan <uuid:order_uuid> dari Branch 2) ---
    path("orders/<uuid:order_uuid>/", OrderDetailView.as_view(), name='order-detail'),
    path("orders/<uuid:order_uuid>/confirm-cash/", CashConfirmView.as_view(), name='confirm-cash'),
    path("orders/<uuid:order_uuid>/cancel/", CancelOrderView.as_view(), name='cancel-order'),
    path("orders/<uuid:order_uuid>/update-status/", UpdateOrderStatusView.as_view(), name='update-order-status'),
    # --- AKHIR PERUBAHAN ---
    
    path("webhooks/payment/", MidtransWehboohView.as_view(), name='payment-webhooks'),
    path("tables/<str:table_code>/qr/", TableQRCodeView.as_view(), name='table-qr-code'),
    path('token-auth/', obtain_auth_token, name='api_token_auth'),
    path("tenants/<int:tenant_id>/takeaway-qr/", TakeawayQRCodeView.as_view(), name='takeaway-qr-code'),
    # Konflik (baris duplikat) di bawah ini telah dihapus

    # Daftarkan semua URL router
    path('', include(router.urls)),
    path('', include(stands_router.urls)),
    path('', include(groups_router.urls)),  # <-- Daftarkan router level 3
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)