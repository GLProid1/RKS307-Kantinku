import os
from celery import Celery

# Set default Django settings module ke 'canteen.settings'
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'canteen.settings')

app = Celery('canteen')

# Menggunakan string di sini agar worker tidak perlu serialize objek konfigurasi
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules dari semua registered Django apps
app.autodiscover_tasks()
from celery import Celery

# Set default Django settings module ke 'canteen.settings'
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'canteen.settings')

app = Celery('canteen')

# Menggunakan string di sini agar worker tidak perlu serialize objek konfigurasi
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules dari semua registered Django apps
app.autodiscover_tasks()