from celery import shared_task
from .models import Order

@shared_task
def send_order_paid_notification(order_id):
    """
    contoh tugas: kirim notifikasi ke tenant (dashboard push via websockets)
    dan kirim WhatsApp/Email ke customer.
    Implementasikan integrasi WhatsApp di sini (Twilio / WA Cloud API).
    """
    try:
      order = Order.objects.get(pk=order_id)
    except Order.DoesNotExist:
      return False
    
    # TODO: kirim notifikasi ke tenant dashboard (ws/post)
    # TODO: kirim WhatsApp message ke order.customer.phone jika ada
    return True