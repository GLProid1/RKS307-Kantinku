from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
  re_path(r'ws/tenant/(?P<tenant_id>\d+)/notifications/$', consumers.TenantNotificationConsumer.as_asgi()),
]