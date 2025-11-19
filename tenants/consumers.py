import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User

class TenantNotificationConsumer(AsyncWebsocketConsumer):
  async def connect(self):
    # Dapatkan ID tenant dari URL
    self.tenant_id = self.scope['url_route']['kwargs']['tenant_id']
    self.tenant_group_name = f"tenant_{self.tenant_id}"
    self.user = self.scope['user']
    
    # Periksa apakah user terautentikasi dan merupakan staff dari tenant ini
    if self.user.is_authenticated and await self.is_user_staff_of_tenant(self.user, self.tenant_id):
      # Bergabung ke grup channel tenant
      await self.channel_layer.group_add(
        self.tenant_group_name,
        self.channel_name
      )
      await self.accept()
    else:
      # Tolak koneksi jika tidak diizinkan
      await self.close()
      
  async def disconnect(self, close_code):
    # Keluar dari grup channel tenant
    await self.channel_layer.group_discard(
      self.tenant_group_name,
      self.channel_name
    )
    
  # Menerima pesan dari WebSocket (tidak kita gunakan, tapi bisa untuk komunikasi client->server)
  async def receive(self, text_data):
      pass

  # Menerima pesan dari grup channel (dari server-side) dan meneruskannya ke client
  async def order_notification(self, event):
    await self.send(text_data=json.dumps(event['message']))
    
  @database_sync_to_async
  def is_user_staff_of_tenant(self, user, tenant_id):
    return user.tenants.filter(id=tenant_id).exists()