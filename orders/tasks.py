from celery import shared_task
from .models import Order
from django.conf import settings
from .serializers import OrderSerializer
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.core.mail import send_mail
from django.template.loader import render_to_string

@shared_task
def send_order_paid_notification(order_id):
    """
    Kirim notifikasi ke tenant (dashboard push via websockets)
    dan kirim WhatsApp/Email ke customer.
    """
    try:
      order = Order.objects.select_related('tenant').get(pk=order_id)
    except Order.DoesNotExist:
      return False
    
    # Implementasi notifikasi realtime ke dashboard
    channel_layer = get_channel_layer()
    tenant_group_name = f'tenant_{order.tenant.pk}'
    # Siapkan data yang akan dikirim ke frontend
    notification_data = {
      'type': 'new_paid_order', # Tipe event untuk diidentifikasi oleh frontend
      'order': OrderSerializer(order).data
    }
    # Kirim pesan ke group tenant
    async_to_sync(channel_layer.group_send)(
      tenant_group_name,
      {'type': 'order.notification', 'message': notification_data}
    )
    return True
  
@shared_task
def send_cash_order_invoice(order_id):
  """
  Mengirim email invoice dan PIN untuk pesanana dengan metode pembayaran CASH.
  """
  try:
    order = Order.objects.select_related('customer', 'tenant').get(pk=order_id)
  except Order.DoesNotExist:
    return False
  
  # Hanya kirim jika ada customer, email, dan PIN
  if not (order.customer and order.customer.email and order.cashier_pin):
    return "No customer email or PIN found"
  
  subject = f"Instruksi Pembayaran Pesanana Anda #{order.references_code}"
  context = {
    'order': order,
    'pin': order.cashier_pin,
    'tenant': order.tenant.name,
  }
  try:
    html_message = render_to_string('emails/cash_invoice.html', context)
    plain_message = f"Terima kasih telah memesan. Tunjukkan PIN ini: {order.cashier_pin} ke kasir untuk pembayaran."
    from_email = settings.EMAIL_HOST_USER
    send_mail(subject, plain_message, from_email, [order.customer.email], html_message=html_message, fail_silently=False)
    return f"Invoice sent to {order.customer.email} for order {order.pk}"
  except Exception as e:
    print(f"Error, Gagal mengirim email: {e}")
    return f"Error mengirim email: {e}"