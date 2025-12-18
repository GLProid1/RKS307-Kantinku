# canteen/celery.py
import os
from celery import Celery

# Set modul settings default Django untuk program 'celery'.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'canteen.settings')

app = Celery('canteen')

# Menggunakan string di sini berarti worker tidak perlu serialize objek konfigurasi.
# Namespace='CELERY' berarti semua config celery di settings.py harus berawalan 'CELERY_'
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules dari semua app yang terdaftar (seperti orders/tasks.py)
app.autodiscover_tasks()

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')