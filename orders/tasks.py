from celery import shared_task
from .models import Order
from django.core.mail import send_mail
from django.template.loader import render_to_string

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
  html_message = render_to_string('emails/cash_invoice.html', context)
  plain_message = f"Terima kasih telah memesan. Tunjukkan PIN ini: {order.cashier_pin} ke kasir untuk pembayaran."
  
  send_mail(subject, plain_message, 'riconatanael2212@gmail.com', [order.customer.email], html_message=html_message)
  return f"Invoice sent to {order.customer.email} for order {order.id}"