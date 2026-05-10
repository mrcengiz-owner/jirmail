from celery import shared_task
from django.utils import timezone
import psutil
import subprocess
import os


@shared_task
def evaluate_all_thresholds():
    """
    Tüm alert threshold'larını kontrol et.
    Eşik aşıldığında Alert oluştur.
    """
    from saas.models import Alert, AlertThreshold
    from core.models import MailAccount

    thresholds = AlertThreshold.objects.filter(is_enabled=True)
    metrics = _get_current_metrics()

    for threshold in thresholds:
        current_value = _get_metric_value(metrics, threshold.metric)

        if threshold.metric == 'storage_quota':
            quota_warnings = _check_storage_quota()
            if len(quota_warnings) >= threshold.critical_threshold:
                if not Alert.objects.filter(
                    category='storage',
                    is_resolved=False,
                    current_value=str(len(quota_warnings))
                ).exists():
                    Alert.objects.create(
                        title="Depolama Kotası Aşıldı",
                        message=f"{len(quota_warnings)} kullanıcı depolama limitini aştı",
                        severity='critical',
                        category='storage',
                        threshold_value=str(threshold.critical_threshold),
                        current_value=str(len(quota_warnings))
                    )
        else:
            if current_value >= threshold.critical_threshold:
                if not Alert.objects.filter(
                    category=threshold.metric.replace('_usage', ''),
                    is_resolved=False
                ).exists():
                    Alert.objects.create(
                        title=f"{threshold.name} Kritik Seviyede",
                        message=f"{threshold.name}: {current_value}% (eşik: {threshold.critical_threshold}%)",
                        severity='critical' if current_value >= threshold.critical_threshold else 'warning',
                        category=threshold.metric.replace('_usage', ''),
                        threshold_value=str(threshold.critical_threshold),
                        current_value=str(current_value)
                    )
            elif current_value >= threshold.warning_threshold:
                if not Alert.objects.filter(
                    category=threshold.metric.replace('_usage', ''),
                    is_resolved=False,
                    severity='warning'
                ).exists():
                    Alert.objects.create(
                        title=f"{threshold.name} Uyarı Seviyesinde",
                        message=f"{threshold.name}: {current_value}% (eşik: {threshold.warning_threshold}%)",
                        severity='warning',
                        category=threshold.metric.replace('_usage', ''),
                        threshold_value=str(threshold.warning_threshold),
                        current_value=str(current_value)
                    )

        threshold.last_check = timezone.now()
        threshold.save()

    return f"Evaluated {thresholds.count()} thresholds"


@shared_task
def check_mail_queue_status():
    """
    Mail kuyruğunu kontrol et ve alert oluştur.
    """
    from saas.models import Alert, AlertThreshold

    count = _get_mail_queue_count()

    threshold = AlertThreshold.objects.filter(metric='mail_queue', is_enabled=True).first()
    if threshold and count >= threshold.critical_threshold:
        if not Alert.objects.filter(category='mail', is_resolved=False, current_value=str(count)).exists():
            Alert.objects.create(
                title="Mail Kuyruğu Kritik",
                message=f"{count} email kuyrukta bekliyor",
                severity='critical' if count >= threshold.critical_threshold else 'warning',
                category='mail',
                threshold_value=str(threshold.critical_threshold),
                current_value=str(count)
            )

    return f"Mail queue count: {count}"


@shared_task
def cleanup_resolved_alerts():
    """
    30 günden eski çözülmüş alert'leri sil.
    """
    from saas.models import Alert
    from datetime import timedelta

    threshold_date = timezone.now() - timedelta(days=30)
    deleted, _ = Alert.objects.filter(
        is_resolved=True,
        resolved_at__lt=threshold_date
    ).delete()

    return f"Deleted {deleted} old resolved alerts"


@shared_task
def create_scheduled_backup(backup_type='full', include_emails=False, include_configs=True, include_database=True):
    """
    Planlı yedekleme oluştur.
    """
    from backup.api import create_backup_logic
    return create_backup_logic(backup_type, include_emails, include_configs, include_database)


@shared_task
def check_failed_logins():
    """
    Başarısız giriş denemelerini kontrol et.
    """
    from saas.models import Alert, AlertThreshold

    count = _get_failed_login_count()
    threshold = AlertThreshold.objects.filter(metric='failed_logins', is_enabled=True).first()

    if threshold and count >= threshold.critical_threshold:
        if not Alert.objects.filter(category='security', is_resolved=False).exists():
            Alert.objects.create(
                title="Çok Fazla Başarısız Giriş",
                message=f"{count} başarısız giriş denemesi tespit edildi",
                severity='warning',
                category='security',
                threshold_value=str(threshold.critical_threshold),
                current_value=str(count)
            )

    return f"Failed logins: {count}"


def _get_current_metrics():
    """Sistem metriklerini al."""
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    return {
        'cpu_percent': psutil.cpu_percent(interval=0.1),
        'memory_percent': mem.percent,
        'disk_percent': disk.percent,
    }


def _get_metric_value(metrics, metric_name):
    """İstenen metrik değerini al."""
    mapping = {
        'cpu_usage': 'cpu_percent',
        'memory_usage': 'memory_percent',
        'disk_usage': 'disk_percent',
        'mail_queue': 'mail_queue',
        'failed_logins': 'failed_logins',
    }
    key = mapping.get(metric_name, metric_name)
    return metrics.get(key, 0)


def _get_mail_queue_count():
    """Mail kuyruğundaki mesaj sayısını al."""
    try:
        result = subprocess.run(
            ['mailq'], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            lines = result.stdout.split('\n')
            return len([l for l in lines if '<' in l and '>' in l])
    except Exception:
        pass
    return 0


def _get_failed_login_count():
    """Başarısız giriş sayısını al."""
    count = 0
    log_files = ['/var/log/auth.log', '/var/log/secure']
    for log_file in log_files:
        if os.path.exists(log_file):
            try:
                result = subprocess.run(
                    ['tail', '-n', '100', log_file],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    count += result.stdout.lower().count('failed')
            except Exception:
                pass
    return count


def _check_storage_quota():
    """Depolama kotası aşan kullanıcıları bul."""
    from core.models import MailAccount
    warnings = []
    try:
        for account in MailAccount.objects.all():
            storage_bytes = account.current_storage_bytes
            if account.quota_bytes > 0:
                usage_percent = (storage_bytes / account.quota_bytes) * 100
                if usage_percent > 80:
                    warnings.append({
                        'email': account.email,
                        'usage_percent': round(usage_percent, 1)
                    })
    except Exception:
        pass
    return warnings