<<<<<<< HEAD
import os
from celery import Celery

# Set default Django settings module ke 'canteen.settings'
=======
# canteen/celery.py
import os
from celery import Celery

# Set modul settings default Django untuk program 'celery'.
>>>>>>> f76e0c520b0b016941a8115ad81f3c0f312cf60f
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'canteen.settings')

app = Celery('canteen')

<<<<<<< HEAD
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
=======
# Menggunakan string di sini berarti worker tidak perlu pickle objek konfigurasi.
# Namespace='CELERY' berarti semua config celery di settings.py harus berawalan 'CELERY_'
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules dari semua app yang terdaftar (seperti orders/tasks.py)
app.autodiscover_tasks()

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
>>>>>>> f76e0c520b0b016941a8115ad81f3c0f312cf60f
