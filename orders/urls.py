from rest_framework.authtoken.views import obtain_auth_token 
from django.urls import path, include
from rest_framework_nested import routers
from django.conf import settings
from django.conf.urls.static import static
from .views import (
    # Orders Views
    CreateOrderView, MidtransWehboohView, 
    OrderDetailView, UpdateOrderStatusView, CancelOrderView, OrderListView,
    TableQRCodeView, TakeawayQRCodeView,PopularMenusView,
    
    # ViewSets
    ReportDashboardAPIView,
)

# ===== URL Patterns =====
urlpatterns = [
    # Report
    path('reports/summary/', ReportDashboardAPIView.as_view(), name='reports-summary'),
    
    # Popular Menus (TAMBAHKAN INI)
    # Ini akan membuat URL: /api/orders/popular-menus/
    path('orders/popular-menus/', PopularMenusView.as_view(), name='popular-menus'),
    
    # Order URLs
    path('orders/', OrderListView.as_view(), name='order-list'), # GET untuk list
    path('orders/create/', CreateOrderView.as_view(), name='create-order'), # POST untuk create
    path("orders/<uuid:order_uuid>/", OrderDetailView.as_view(), name='order-detail'),
    path("orders/<uuid:order_uuid>/cancel/", CancelOrderView.as_view(), name='cancel-order'),
    path("orders/<uuid:order_uuid>/status/", UpdateOrderStatusView.as_view(), name='update-order-status'),
    
    # Webhooks
    path("webhooks/payment/", MidtransWehboohView.as_view(), name='payment-webhooks'),
    
    # QR Code URLs
    path("tables/<str:table_code>/qr/", TableQRCodeView.as_view(), name='table-qr-code'),
    path("tenants/<int:tenant_id>/takeaway-qr/", TakeawayQRCodeView.as_view(), name='takeaway-qr-code'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
