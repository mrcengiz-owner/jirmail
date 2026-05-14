"""Installer için django-ninja router.

Endpoint'ler:
    GET  /api/installer/bootstrap      Ortam DATABASE_URL ipucu + önerilen profil
    POST /api/installer/test-db        PostgreSQL bağlantı testi (kurulum öncesi)
    POST /api/installer/start          Kurulum çalışmasını başlatır (run_id döner)
    GET  /api/installer/status         Mevcut run'ın durumu (polling fallback)
    GET  /api/installer/stream         SSE event stream (tarayıcıdan açılır)
    GET  /api/installer/dns-records    Domain için önerilen DNS kayıtları
    POST /api/installer/dns-apply      DNS kayıtlarını provider üzerinden uygula
    POST /api/installer/tls-request    Let's Encrypt sertifikası iste
"""
import os
import secrets
import threading
from typing import Any, Dict, Optional

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from ninja import Router, Schema
from pydantic import Field

from .models import InstallationRun, InstallationStep
from .orchestrator import _resolve_profile_and_client, run_installation
from .sse import sse_response


router = Router()


class DbManualSchema(Schema):
    host: str = ''
    port: int = 5432
    name: str = ''
    user: str = ''
    password: str = ''


class StartInstallSchema(Schema):
    domain: str
    admin_email: str
    admin_password: str
    instance_id: str
    jir_local_key: str
    postgres_password: str = ''
    postgres_db: str = 'jir_mail_prod'
    postgres_user: str = 'postgres'
    mail_hostname: str = ''
    dns_provider: str = 'manual'
    dns_credentials: Dict[str, Any] = Field(default_factory=dict)
    install_profile: str = 'docker_stack'
    db_manual: Optional[DbManualSchema] = None


class TestDbSchema(Schema):
    host: str
    port: int = 5432
    name: str
    user: str
    password: str = ''


@router.get('/bootstrap', summary='Kurulum sihirbazı ortam bilgisi')
def installer_bootstrap(request: HttpRequest):
    """DATABASE_URL var mı (maskeli ipucu) ve önerilen kurulum profili."""
    url = os.getenv('DATABASE_URL', '').strip()
    out: Dict[str, Any] = {
        'has_database_url': bool(url),
        'suggested_profile': 'platform_env' if url else 'docker_stack',
    }
    if url:
        try:
            from urllib.parse import urlparse

            p = urlparse(url)
            dbname = (p.path or '').lstrip('/') or ''
            out['database_host_hint'] = p.hostname or ''
            out['database_name_hint'] = (dbname[:24] + '...') if len(dbname) > 24 else dbname
        except Exception:
            out['database_host_hint'] = ''
            out['database_name_hint'] = ''
    return out


@router.post('/test-db', summary='PostgreSQL bağlantı testi')
@csrf_exempt
def test_db_connection(request: HttpRequest, data: TestDbSchema):
    try:
        import psycopg2

        conn = psycopg2.connect(
            host=data.host,
            port=data.port or 5432,
            dbname=data.name,
            user=data.user,
            password=data.password or '',
            connect_timeout=10,
        )
        cur = conn.cursor()
        cur.execute('SELECT 1')
        cur.close()
        conn.close()
        return {'success': True, 'message': 'Bağlantı başarılı.'}
    except Exception as exc:
        return {'success': False, 'message': str(exc)}


@router.post('/start', summary='Kurulumu başlat')
@csrf_exempt
def start_install(request: HttpRequest, data: StartInstallSchema):
    """Yeni bir InstallationRun yaratıp orchestrator'u arkaplan thread'inde çalıştırır."""
    if InstallationRun.objects.filter(status__in=['running', 'pending']).exists():
        active = InstallationRun.objects.filter(status__in=['running', 'pending']).first()
        return {
            'status': 'error',
            'message': 'Aktif bir kurulum çalışması zaten var.',
            'run_id': str(active.run_id),
        }

    db_manual_dict: Dict[str, Any] = {}
    if data.db_manual is not None:
        if hasattr(data.db_manual, 'model_dump'):
            db_manual_dict = data.db_manual.model_dump(exclude_none=True)
        else:
            db_manual_dict = data.db_manual.dict(exclude_none=True)

    pre_cfg = {
        'install_profile': data.install_profile or 'docker_stack',
        'db_manual': db_manual_dict,
    }
    try:
        _resolve_profile_and_client(pre_cfg)
    except RuntimeError as exc:
        return {'status': 'error', 'message': str(exc)}

    pg_password = data.postgres_password or secrets.token_urlsafe(24)
    mail_hostname = data.mail_hostname or f'mail.{data.domain}'

    config = {
        'domain': data.domain,
        'admin_email': data.admin_email,
        'admin_password': data.admin_password,
        'instance_id': data.instance_id,
        'jir_local_key': data.jir_local_key,
        'postgres_password': pg_password,
        'postgres_db': data.postgres_db,
        'postgres_user': data.postgres_user,
        'mail_hostname': mail_hostname,
        'dns_provider': data.dns_provider,
        'dns_credentials': data.dns_credentials,
        'install_profile': data.install_profile or 'docker_stack',
        'db_manual': db_manual_dict,
    }

    run = InstallationRun.objects.create(config_snapshot=config, status='pending')

    thread = threading.Thread(
        target=run_installation,
        args=(str(run.run_id),),
        daemon=True,
        name=f'installer-{run.run_id}',
    )
    thread.start()

    return {
        'status': 'success',
        'run_id': str(run.run_id),
        'message': 'Kurulum başlatıldı.',
    }


@router.get('/status', summary='Aktif kurulumun durumu')
def install_status(request: HttpRequest, run_id: Optional[str] = None):
    """SSE bağlantısı kuramayan istemciler için polling fallback."""
    if run_id:
        run = InstallationRun.objects.filter(run_id=run_id).first()
    else:
        run = InstallationRun.objects.order_by('-started_at').first()

    if not run:
        return {'status': 'idle', 'run': None, 'steps': []}

    steps = [
        {
            'id': s.id,
            'order': s.order,
            'name': s.name,
            'description': s.description,
            'status': s.status,
            'progress_percent': s.progress_percent,
            'log_tail': s.log[-1000:] if s.log else '',
            'duration_seconds': s.duration_seconds,
        }
        for s in run.steps.all()
    ]

    return {
        'status': run.status,
        'run': {
            'run_id': str(run.run_id),
            'status': run.status,
            'started_at': run.started_at.isoformat() if run.started_at else None,
            'finished_at': run.finished_at.isoformat() if run.finished_at else None,
            'error_message': run.error_message,
        },
        'steps': steps,
    }


def install_stream(request: HttpRequest, run_id: str):
    """SSE endpoint — text/event-stream akışı.

    django-ninja yerine doğrudan Django view: streaming için en sade yol.
    """
    return sse_response(run_id)


class DNSRecordsQuery(Schema):
    domain: str
    server_ip: str = ''


def _recommended_records(domain: str, server_ip: str) -> list[dict]:
    """Mail için önerilen DNS kayıtlarını üretir."""
    from core.models import MailDomain

    mail_host = f'mail.{domain}'
    records = [
        {'name': 'mail', 'type': 'A', 'content': server_ip or 'SUNUCU_IP', 'ttl': 3600,
         'description': 'Mail sunucusu A kaydı'},
        {'name': '@', 'type': 'MX', 'content': mail_host, 'priority': 10, 'ttl': 3600,
         'description': 'MX kaydı — mail server adresi'},
        {'name': '@', 'type': 'TXT', 'content': 'v=spf1 mx a -all', 'ttl': 3600,
         'description': 'SPF — sadece MX/A kayıtları gönderim yapabilir'},
        {'name': '_dmarc', 'type': 'TXT', 'content': f'v=DMARC1; p=quarantine; rua=mailto:dmarc@{domain}',
         'ttl': 3600, 'description': 'DMARC politikası'},
    ]

    md = MailDomain.objects.filter(name=domain).first()
    if md and md.dkim_record:
        record_text = md.dkim_record.split('IN TXT', 1)[-1].strip().strip('"')
        selector = md.dkim_record.split('._domainkey', 1)[0].strip()
        records.append({
            'name': f'{selector}._domainkey',
            'type': 'TXT',
            'content': record_text,
            'ttl': 3600,
            'description': 'DKIM public key',
        })

    return records


@router.get('/dns-records', summary='Önerilen DNS kayıtları')
def dns_records(request: HttpRequest, domain: str, server_ip: str = ''):
    return {'domain': domain, 'records': _recommended_records(domain, server_ip)}


class DNSApplySchema(Schema):
    domain: str
    provider: str = 'manual'
    credentials: Dict[str, Any] = Field(default_factory=dict)
    server_ip: str = ''


@router.post('/dns-apply', summary='DNS kayıtlarını otomatik uygula')
@csrf_exempt
def dns_apply(request: HttpRequest, data: DNSApplySchema):
    from dns_providers import get_provider, DNSRecord

    try:
        provider = get_provider(data.provider, data.credentials)
    except Exception as exc:
        return {'success': False, 'message': str(exc)}

    if not provider.is_configured():
        return {'success': False, 'message': f'{data.provider} için kimlik bilgileri eksik'}

    results: list[dict] = []
    for rec in _recommended_records(data.domain, data.server_ip):
        dns_rec = DNSRecord(
            name=rec['name'],
            type=rec['type'],
            content=rec['content'],
            ttl=rec.get('ttl', 3600),
            priority=rec.get('priority'),
        )
        outcome = provider.create_record(data.domain, dns_rec)
        results.append({'record': rec, 'result': outcome})

    success_count = sum(1 for r in results if r['result'].get('success'))
    return {
        'success': success_count > 0,
        'total': len(results),
        'created': success_count,
        'results': results,
    }


class TLSRequestSchema(Schema):
    domain: str
    email: str
    staging: bool = False


@router.post('/tls-request', summary='Let\'s Encrypt sertifikası iste')
@csrf_exempt
def tls_request(request: HttpRequest, data: TLSRequestSchema):
    try:
        from tls.certbot_manager import request_certificate
        from core.models import MailDomain
        from django.utils import timezone

        result = request_certificate(data.domain, data.email, staging=data.staging)

        if result.get('success'):
            md = MailDomain.objects.filter(name=data.domain).first()
            if md:
                md.tls_cert_path = f'/etc/letsencrypt/live/mail.{data.domain}/fullchain.pem'
                md.tls_key_path = f'/etc/letsencrypt/live/mail.{data.domain}/privkey.pem'
                md.tls_issued_at = timezone.now()
                md.save(update_fields=['tls_cert_path', 'tls_key_path', 'tls_issued_at'])

        return result
    except Exception as exc:
        return {'success': False, 'message': str(exc)}
