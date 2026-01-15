from celery import shared_task
from .models import Order
from django.conf import settings
from .serializers import OrderSerializer
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
import socket

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

def is_disposable_email(email):
    """
    Memeriksa apakah domain email berasal dari penyedia email sementara (disposable).
    Membantu mencegah spam dan penyalahgunaan endpoint publik.
    """
    disposable_domains = [
        'mailinator.com', '10minutemail.com', 'tempmail.com', 
        'guerrillamail.com', 'sharklasers.com', 'dispostable.com'
    ]
    try:
        domain = email.split('@')[1].lower()
        return domain in disposable_domains
    except (IndexError, AttributeError):
        return True

@shared_task
def send_cash_order_invoice(order_id, pin=None): # <--- PERBAIKAN 1: Tambah parameter pin
    """
    Mengirim email invoice dan PIN untuk pesanan dengan metode pembayaran CASH.
    """
    try:
        order = Order.objects.select_related('customer', 'tenant').get(pk=order_id)
    except Order.DoesNotExist:
        return False
  
    # PERBAIKAN 2: Cek keberadaan parameter 'pin', jangan pakai order.cashier_pin (karena itu HASH)
    if not (order.customer and order.customer.email and pin):
        return "No customer email or PIN found"
  
    email_address = order.customer.email
    
    if is_disposable_email(email_address):
        return f"Blocked disposable email: {email_address}"

    try:
        validate_email(email_address)
        domain = email_address.split('@')[1]
        socket.gethostbyname(domain)
    except (ValidationError, socket.error):
        return f"Invalid email or domain: {email_address}"

    subject = f"Instruksi Pembayaran Pesanan Anda #{order.references_code}"
    
    # PERBAIKAN 3: Masukkan parameter 'pin' ke context, bukan order.cashier_pin
    context = {
        'order': order,
        'pin': pin, # <--- PIN Asli (123456)
        'tenant_name': order.tenant.name,
    }
    
    try:
        html_message = render_to_string('emails/cash_invoice.html', context)
        # PERBAIKAN 4: Pesan teks juga gunakan pin asli
        plain_message = f"Terima kasih telah memesan. Tunjukkan PIN ini: {pin} ke kasir untuk pembayaran."
        from_email = settings.EMAIL_HOST_USER
        
        send_mail(
            subject, 
            plain_message, 
            from_email, 
            [email_address], 
            html_message=html_message, 
            fail_silently=False
        )
        return f"Invoice sent to {email_address} for order {order.pk}"
    except Exception as e:
        return f"Error mengirim email: {str(e)}"
