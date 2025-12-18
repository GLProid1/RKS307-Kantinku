from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from .views import (
    # Orders Views
    CreateOrderView, MidtransWehboohView, 
    OrderDetailView, UpdateOrderStatusView, CancelOrderView, OrderListView,
    TableQRCodeView, TakeawayQRCodeView, PopularMenusView,
    
    # ViewSets / Dashboard
    ReportDashboardAPIView,
)

# Prefix 'api/orders/' sudah diatur di canteen/urls.py
# Jadi di sini kita hanya menentukan endpoint lanjutannya.

urlpatterns = [
    # 1. Report & Summary
    # Menghasilkan URL: /api/orders/reports/summary/
    path('reports/summary/', ReportDashboardAPIView.as_view(), name='reports-summary'),
    
    # 2. Menu Populer
    # Menghasilkan URL: /api/orders/popular-menus/
    path('popular-menus/', PopularMenusView.as_view(), name='popular-menus'),
    
    # 3. Order Management
    # Menghasilkan URL: /api/orders/all/ (Frontend memanggil ini untuk list pesanan)
    path('all/', OrderListView.as_view(), name='order-list'),
    
    # Menghasilkan URL: /api/orders/create/
    path('create/', CreateOrderView.as_view(), name='create-order'),
    
    # Menghasilkan URL: /api/orders/<uuid>/
    path('<uuid:order_uuid>/', OrderDetailView.as_view(), name='order-detail'),
    
    # Menghasilkan URL: /api/orders/<uuid>/cancel/
    path('<uuid:order_uuid>/cancel/', CancelOrderView.as_view(), name='cancel-order'),
    
    # Menghasilkan URL: /api/orders/<uuid>/status/ (Frontend memanggil ini untuk update status)
    path('<uuid:order_uuid>/status/', UpdateOrderStatusView.as_view(), name='update-order-status'),
    
    # 4. Webhooks (Payment)
    # Menghasilkan URL: /api/orders/webhooks/payment/
    path('webhooks/payment/', MidtransWehboohView.as_view(), name='payment-webhooks'),
    
    # 5. QR Code Generation
    path('tables/<str:table_code>/qr/', TableQRCodeView.as_view(), name='table-qr-code'),
    path('tenants/<int:tenant_id>/takeaway-qr/', TakeawayQRCodeView.as_view(), name='takeaway-qr-code'),
]

# Tambahkan static media jika dalam mode DEBUG
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)