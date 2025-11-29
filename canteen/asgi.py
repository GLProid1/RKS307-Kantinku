"""
ASGI config for canteen project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import tenants.routing

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'canteen.settings')

# Aplikasi ASGI utama
application = ProtocolTypeRouter({
  # Rute HTTP akan ditangani oleh aplikasi Django standart
  "http": get_asgi_application(),
  
  # Rute WebSocket akan ditangani oleh URLRouter
  "websocket": AuthMiddlewareStack(
    URLRouter(
      tenants.routing.websocket_urlpatterns
    ))
})
