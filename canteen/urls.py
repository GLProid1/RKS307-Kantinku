"""
URL configuration for canteen project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
# Lokasi: canteen/urls.py

from django.contrib import admin
from django.urls import path, include # Pastikan 'include' sudah di-import
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Semua endpoint API di bawah prefix 'api/
    path('api/', include('orders.urls')), # orders.urls tidak perlu diubah
    path('api/tenants/', include('tenants.urls')),  # Pindahkan tenants ke dalam /api/
    path('api/cashier/', include(('cashier.urls', 'cashier'))),  # Tambahkan ini untuk meng-include URL dari aplikasi cashier
    path('api/users/', include(('users.urls', 'users'))), # Tambahkan ini untuk meng-include URL dari aplikasi users')
    path('api/reports/', include('reports.urls')),  
    


    # URL Dokumentasi API
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    # Tampilan UI dokumentasi
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc')
    
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
