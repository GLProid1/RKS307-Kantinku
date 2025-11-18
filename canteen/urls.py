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

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Semua endpoint API di bawah prefix 'api/
    path('api/', include('orders.urls')),
    path('tenants/', include('tenants.urls')),  # Tambahkan ini untuk meng-include URL dari aplikasi tenants
    path('api/cashier/', include(('cashier.urls', 'cashier'))),  # Tambahkan ini untuk meng-include URL dari aplikasi cashier
    path('api/users/', include(('users.urls', 'users'))),  # Tambahkan ini untuk meng-include URL dari aplikasi users')
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
