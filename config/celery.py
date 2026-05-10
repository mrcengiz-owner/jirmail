import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('jirmail')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

app.conf.beat_schedule = {
    'check-alert-thresholds-every-5-minutes': {
        'task': 'alerts.tasks.evaluate_all_thresholds',
        'schedule': 300.0,
    },
    'check-mail-queue-every-1-minute': {
        'task': 'alerts.tasks.check_mail_queue_status',
        'schedule': 60.0,
    },
    'cleanup-old-alerts-daily': {
        'task': 'alerts.tasks.cleanup_resolved_alerts',
        'schedule': 86400.0,
    },
}