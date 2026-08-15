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


# ─── DNS Auto-Check Task ──────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=2)
def check_domain_dns(self, domain_name: str):
    """
    Belirtilen domain için DNS kayıtlarını (SPF, DKIM, DMARC, MX) kontrol eder.
    Sonucu MailDomain.verification_status alanına yazar.
    """
    try:
        import dns.resolver
        from core.models import MailDomain
        from django.utils import timezone

        domain = MailDomain.objects.filter(name=domain_name).first()
        if not domain:
            return {"status": "error", "message": f"Domain bulunamadı: {domain_name}"}

        results = {
            "spf": False,
            "dkim": False,
            "dmarc": False,
            "mx": False,
        }
        errors = []

        resolver = dns.resolver.Resolver()
        resolver.timeout = 5
        resolver.lifetime = 10

        # MX kontrolü
        try:
            mx_records = resolver.resolve(domain_name, 'MX')
            results["mx"] = len(list(mx_records)) > 0
        except Exception as e:
            errors.append(f"MX: {str(e)}")

        # SPF kontrolü (TXT @ kaydında v=spf1 içermeli)
        try:
            txt_records = resolver.resolve(domain_name, 'TXT')
            for record in txt_records:
                txt = record.to_text().strip('"')
                if txt.startswith('v=spf1'):
                    results["spf"] = True
                    break
        except Exception as e:
            errors.append(f"SPF: {str(e)}")

        # DMARC kontrolü (_dmarc.domain TXT kaydı)
        try:
            dmarc_records = resolver.resolve(f'_dmarc.{domain_name}', 'TXT')
            for record in dmarc_records:
                txt = record.to_text().strip('"')
                if txt.startswith('v=DMARC1'):
                    results["dmarc"] = True
                    break
        except Exception as e:
            errors.append(f"DMARC: {str(e)}")

        # DKIM kontrolü — selector MailDomain.dkim_record'dan (mail-xxxx._domainkey)
        try:
            from dns_providers.records import parse_dkim_dns

            dkim_parts = parse_dkim_dns(domain)
            dkim_name = None
            if dkim_parts:
                dkim_name = f'{dkim_parts[0]}.{domain_name}'
            else:
                dkim_name = f'mail._domainkey.{domain_name}'
            dkim_records = resolver.resolve(dkim_name, 'TXT')
            for record in dkim_records:
                txt = record.to_text().strip('"')
                if 'v=DKIM1' in txt or 'p=' in txt:
                    results["dkim"] = True
                    break
        except Exception as e:
            errors.append(f"DKIM: {str(e)}")

        # Genel durum: MX + SPF + DKIM + DMARC
        all_ok = results["mx"] and results["spf"] and results["dmarc"] and results["dkim"]
        domain.verification_status = 'verified' if all_ok else 'failed'
        if all_ok:
            domain.verified_at = timezone.now()
        domain.save(update_fields=['verification_status', 'verified_at'])

        return {
            "domain": domain_name,
            "status": "verified" if all_ok else "failed",
            "checks": results,
            "errors": errors,
        }

    except ImportError:
        return {"status": "error", "message": "dnspython kurulu değil: pip install dnspython"}
    except Exception as exc:
        self.retry(exc=exc, countdown=60)


@shared_task
def check_all_domains_dns():
    """
    Tüm aktif domainlerin DNS durumunu kontrol eder.
    Celery Beat tarafından periyodik olarak çalıştırılır.
    """
    from core.models import MailDomain

    domains = MailDomain.objects.filter(is_active=True)
    results = []

    for domain in domains:
        result = check_domain_dns.delay(domain.name)
        results.append({"domain": domain.name, "task_id": str(result.id)})

    return {"checked": len(results), "domains": results}
