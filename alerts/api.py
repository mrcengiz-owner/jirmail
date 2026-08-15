from ninja import Router, Schema
from ninja.errors import HttpError
from jir_core.dashboard_auth import require_panel_api
from django.conf import settings
from saas.models import Alert, AlertThreshold
from core.models import MailAccount
from datetime import datetime, timedelta
import psutil
import subprocess
import os

router = Router()


def _require_panel(request):
    denied = require_panel_api(request)
    if denied:
        raise HttpError(403, denied.get('message', 'Yetkisiz'))



class AlertSchema(Schema):
    id: int
    title: str
    message: str
    severity: str
    category: str
    is_read: bool
    is_resolved: bool
    created_at: str
    threshold_value: str
    current_value: str


class AlertThresholdSchema(Schema):
    id: int
    name: str
    metric: str
    warning_threshold: float
    critical_threshold: float
    is_enabled: bool
    check_interval_minutes: int


class SystemMetricsSchema(Schema):
    cpu_percent: float
    ram_percent: float
    disk_percent: float
    mail_queue_count: int
    active_alerts: int
    status: str


def check_disk_usage():
    try:
        usage = psutil.disk_usage('/')
        return {
            'percent': usage.percent,
            'total_gb': round(usage.total / (1024**3), 2),
            'free_gb': round(usage.free / (1024**3), 2)
        }
    except Exception:
        return {'percent': 0, 'total_gb': 0, 'free_gb': 0}


def check_memory_usage():
    try:
        mem = psutil.virtual_memory()
        return {
            'percent': mem.percent,
            'total_gb': round(mem.total / (1024**3), 2),
            'available_gb': round(mem.available / (1024**3), 2)
        }
    except Exception:
        return {'percent': 0, 'total_gb': 0, 'available_gb': 0}


def check_cpu_usage():
    try:
        return {'percent': psutil.cpu_percent(interval=1)}
    except Exception:
        return {'percent': 0}


def check_mail_queue():
    try:
        result = subprocess.run(
            ['mailq'], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            lines = result.stdout.split('\n')
            return {'count': len([l for l in lines if '<' in l and '>' in l])}
    except Exception:
        pass
    return {'count': 0}


def check_failed_logins():
    try:
        log_files = ['/var/log/auth.log', '/var/log/secure']
        count = 0
        for log_file in log_files:
            if os.path.exists(log_file):
                result = subprocess.run(
                    ['tail', '-n', '100', log_file],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    count += result.stdout.lower().count('failed')
        return {'count': count}
    except Exception:
        return {'count': 0}


def check_storage_quota():
    try:
        accounts = MailAccount.objects.all()
        quota_warnings = []
        for account in accounts:
            storage_bytes = account.current_storage_bytes
            if account.quota_bytes > 0:
                usage_percent = (storage_bytes / account.quota_bytes) * 100
                if usage_percent > 80:
                    quota_warnings.append({
                        'email': account.email,
                        'usage_percent': round(usage_percent, 1)
                    })
        return {'warnings': quota_warnings}
    except Exception:
        return {'warnings': []}


def evaluate_thresholds(metrics):
    alerts_created = []

    thresholds = AlertThreshold.objects.filter(is_enabled=True)

    threshold_map = {
        'disk_usage': metrics.get('disk', {}).get('percent', 0),
        'memory_usage': metrics.get('memory', {}).get('percent', 0),
        'cpu_usage': metrics.get('cpu', {}).get('percent', 0),
        'mail_queue': metrics.get('mail_queue', {}).get('count', 0),
        'failed_logins': metrics.get('failed_logins', {}).get('count', 0),
        'storage_quota': metrics.get('storage_quota', {}).get('warnings', []),
    }

    for threshold in thresholds:
        current_value = threshold_map.get(threshold.metric, 0)

        if threshold.metric == 'storage_quota':
            if len(current_value) >= threshold.critical_threshold:
                existing = Alert.objects.filter(
                    category='storage',
                    is_resolved=False,
                    metric=threshold.metric
                ).exists()

                if not existing:
                    Alert.objects.create(
                        title="Depolama Kotası Aşıldı",
                        message=f"{len(current_value)} kullanıcı depolama limitini aştı",
                        severity='critical',
                        category='storage',
                        threshold_value=str(threshold.critical_threshold),
                        current_value=str(len(current_value))
                    )
                    alerts_created.append(threshold.metric)
        else:
            if current_value >= threshold.critical_threshold:
                existing = Alert.objects.filter(
                    category=threshold.metric.replace('_usage', ''),
                    is_resolved=False
                ).exists()

                if not existing:
                    severity = 'critical' if current_value >= threshold.critical_threshold else 'warning'
                    Alert.objects.create(
                        title=f"{threshold.name} Kritik Seviyede",
                        message=f"{threshold.name}: {current_value}% (eşik: {threshold.critical_threshold}%)",
                        severity=severity,
                        category=threshold.metric.replace('_usage', ''),
                        threshold_value=str(threshold.critical_threshold),
                        current_value=str(current_value)
                    )
                    alerts_created.append(threshold.metric)

    return alerts_created


@router.get("/metrics", response={200: SystemMetricsSchema}, summary="Sistem Metrikleri")
def get_system_metrics(request):
    _require_panel(request)
    disk = check_disk_usage()
    memory = check_memory_usage()
    cpu = check_cpu_usage()
    mail_queue = check_mail_queue()
    failed_logins = check_failed_logins()
    storage_quota = check_storage_quota()

    active_alerts = Alert.objects.filter(is_resolved=False).count()

    metrics = {
        'disk': disk,
        'memory': memory,
        'cpu': cpu,
        'mail_queue': mail_queue,
        'failed_logins': failed_logins,
        'storage_quota': storage_quota
    }

    evaluate_thresholds(metrics)

    status = 'healthy'
    if disk['percent'] > 90 or memory['percent'] > 90 or cpu['percent'] > 90:
        status = 'critical'
    elif disk['percent'] > 70 or memory['percent'] > 70 or cpu['percent'] > 70:
        status = 'warning'

    return {
        'cpu_percent': round(cpu['percent'], 1),
        'ram_percent': round(memory['percent'], 1),
        'disk_percent': round(disk['percent'], 1),
        'mail_queue_count': mail_queue['count'],
        'active_alerts': active_alerts,
        'status': status
    }


@router.get("/alerts", response={200: list[AlertSchema]}, summary="Uyarıları Getir")
def get_alerts(request, severity: str = None, category: str = None, unread_only: bool = False):
    _require_panel(request)
    queryset = Alert.objects.all()

    if severity:
        queryset = queryset.filter(severity=severity)
    if category:
        queryset = queryset.filter(category=category)
    if unread_only:
        queryset = queryset.filter(is_read=False)

    alerts = queryset[:100]
    return [
        {
            "id": a.id,
            "title": a.title,
            "message": a.message,
            "severity": a.severity,
            "category": a.category,
            "is_read": a.is_read,
            "is_resolved": a.is_resolved,
            "created_at": a.created_at.isoformat(),
            "threshold_value": a.threshold_value,
            "current_value": a.current_value
        }
        for a in alerts
    ]


@router.post("/alerts/{alert_id}/read", summary="Uyarıyı Okundu İşaretle")
def mark_alert_read(request, alert_id: int):
    _require_panel(request)
    try:
        alert = Alert.objects.get(id=alert_id)
        alert.is_read = True
        alert.save()
        return {"status": "success", "message": "Uyarı okundu"}
    except Alert.DoesNotExist:
        return {"status": "error", "message": "Uyarı bulunamadı"}


@router.post("/alerts/{alert_id}/resolve", summary="Uyarıyı Çöz")
def resolve_alert(request, alert_id: int):
    _require_panel(request)
    try:
        alert = Alert.objects.get(id=alert_id)
        alert.is_resolved = True
        alert.resolved_at = datetime.now()
        alert.save()
        return {"status": "success", "message": "Uyarı çözüldü"}
    except Alert.DoesNotExist:
        return {"status": "error", "message": "Uyarı bulunamadı"}


@router.post("/alerts/resolve-all", summary="Tüm Uyarıları Çöz")
def resolve_all_alerts(request):
    _require_panel(request)
    Alert.objects.filter(is_resolved=False).update(
        is_resolved=True,
        resolved_at=datetime.now()
    )
    return {"status": "success", "message": "Tüm uyarılar çözüldü"}


@router.post("/mark-all-read", summary="Tüm Uyarıları Okundu İşaretle")
def mark_all_read(request):
    _require_panel(request)
    Alert.objects.filter(is_read=False).update(is_read=True)
    return {"status": "success", "message": "Tüm uyarılar okundu işaretlendi"}


@router.get("/thresholds", response={200: list[AlertThresholdSchema]}, summary="Uyarı Eşiklerini Getir")
def get_thresholds(request):
    _require_panel(request)
    thresholds = AlertThreshold.objects.all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "metric": t.metric,
            "warning_threshold": t.warning_threshold,
            "critical_threshold": t.critical_threshold,
            "is_enabled": t.is_enabled,
            "check_interval_minutes": t.check_interval_minutes
        }
        for t in thresholds
    ]


@router.post("/thresholds", summary="Uyarı Eşiği Oluştur")
def create_threshold(request, data: AlertThresholdSchema):
    _require_panel(request)
    try:
        threshold = AlertThreshold.objects.create(
            name=data.name,
            metric=data.metric,
            warning_threshold=data.warning_threshold,
            critical_threshold=data.critical_threshold,
            is_enabled=data.is_enabled,
            check_interval_minutes=data.check_interval_minutes
        )
        return {"status": "success", "id": threshold.id}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.put("/thresholds/{threshold_id}", summary="Uyarı Eşiği Güncelle")
def update_threshold(request, threshold_id: int, data: AlertThresholdSchema):
    _require_panel(request)
    try:
        threshold = AlertThreshold.objects.get(id=threshold_id)
        threshold.name = data.name
        threshold.metric = data.metric
        threshold.warning_threshold = data.warning_threshold
        threshold.critical_threshold = data.critical_threshold
        threshold.is_enabled = data.is_enabled
        threshold.check_interval_minutes = data.check_interval_minutes
        threshold.save()
        return {"status": "success", "message": "Eşik güncellendi"}
    except AlertThreshold.DoesNotExist:
        return {"status": "error", "message": "Eşik bulunamadı"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.delete("/thresholds/{threshold_id}", summary="Uyarı Eşiği Sil")
def delete_threshold(request, threshold_id: int):
    _require_panel(request)
    try:
        threshold = AlertThreshold.objects.get(id=threshold_id)
        threshold.delete()
        return {"status": "success", "message": "Eşik silindi"}
    except AlertThreshold.DoesNotExist:
        return {"status": "error", "message": "Eşik bulunamadı"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─── DNS Check Endpoints ──────────────────────────────────────────────────────

@router.post("/dns-check/{domain_name}", summary="Domain DNS Kontrolü Başlat")
def trigger_dns_check(request, domain_name: str):
    _require_panel(request)
    """
    Belirtilen domain için DNS kontrolünü Celery task olarak başlatır.
    Sonuç asenkron olarak MailDomain.verification_status'a yazılır.
    """
    try:
        from alerts.tasks import check_domain_dns
        task = check_domain_dns.delay(domain_name)
        return {
            "status": "queued",
            "domain": domain_name,
            "task_id": str(task.id),
            "message": f"DNS kontrolü başlatıldı. Task ID: {task.id}"
        }
    except Exception as e:
        # Celery çalışmıyorsa senkron çalıştır
        try:
            from alerts.tasks import check_domain_dns
            result = check_domain_dns(domain_name)
            return {"status": "completed", "domain": domain_name, "result": result}
        except Exception as e2:
            return {"status": "error", "message": str(e2)}


@router.post("/dns-check-all", summary="Tüm Domainlerin DNS Kontrolü")
def trigger_all_dns_checks(request):
    _require_panel(request)
    """Tüm aktif domainlerin DNS kontrolünü başlatır."""
    try:
        from alerts.tasks import check_all_domains_dns
        task = check_all_domains_dns.delay()
        return {
            "status": "queued",
            "task_id": str(task.id),
            "message": "Tüm domainler için DNS kontrolü başlatıldı."
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/dns-status", summary="Tüm Domainlerin DNS Durumu")
def get_dns_status(request):
    _require_panel(request)
    """Tüm domainlerin mevcut DNS doğrulama durumunu döndürür."""
    from core.models import MailDomain
    domains = MailDomain.objects.filter(is_active=True).values(
        'name', 'verification_status', 'verified_at',
        'spf_record', 'dkim_record', 'dmarc_record'
    )
    return {
        "status": "success",
        "domains": [
            {
                "name": d['name'],
                "verification_status": d['verification_status'] or 'pending',
                "verified_at": d['verified_at'].isoformat() if d['verified_at'] else None,
                "has_spf": bool(d['spf_record']),
                "has_dkim": bool(d['dkim_record']),
                "has_dmarc": bool(d['dmarc_record']),
            }
            for d in domains
        ]
    }
