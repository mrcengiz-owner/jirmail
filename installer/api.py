"""Installer için django-ninja router.

Endpoint'ler:
    GET  /api/installer/bootstrap           Ortam yetenekleri + install_modes + önerilen profil
    POST /api/installer/test-db           PostgreSQL bağlantı testi (kurulum öncesi)
    GET  /api/installer/mail-stack-status Mail SMTP/IMAP + Docker durumu (sihirbaz)
    POST /api/installer/mail-auto-setup        Postfix+Dovecot + panel ağı (otomatik)
    POST /api/installer/mail-stack-provision   (mail-auto-setup ile aynı)
    POST /api/installer/start             Kurulum çalışmasını başlatır (run_id döner)
    ...

install_profile: canonical değerler docker_stack | platform_env | platform_manual
veya alias (ör. coolify, dokploy, cpanel → aynı canonical yollara normalize edilir).
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
from .mail_connectivity import auto_setup_mail_services
from .mail_stack import collect_installer_mail_stack_status, provision_mail_stack_docker
from .port_check import scan_mail_stack_ports
from .profiles import (
    PROFILE_DOCKER_STACK,
    PROFILE_PLATFORM_MANUAL,
    install_modes_for_ui,
    normalize_install_profile,
    probe_capabilities,
    suggested_profile_from_capabilities,
    validate_manual_db_connection,
)
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
    install_profile: str = Field(
        default='docker_stack',
        description=(
            'Canonical: docker_stack | platform_env | platform_manual. '
            'Alias örnekleri: coolify, dokploy, railway → platform_env; '
            'cpanel, plesk, external_postgres → platform_manual; compose, docker → docker_stack.'
        ),
    )
    db_manual: Optional[DbManualSchema] = None
    # docker_stack: servisleri sırayla kur; smart = uyumsuz/hasta ise konteyneri sil-yenile, force = her zaman sil-yenile
    stack_service_policy: str = Field(
        default='smart',
        description='docker_stack için: smart | force_recreate',
    )
    stack_skip_busy_host_ports: bool = Field(
        default=True,
        description='docker_stack: 25/587/993/143 hostta doluysa publish etme (kurulum devam eder)',
    )


class TestDbSchema(Schema):
    host: str
    port: int = 5432
    name: str
    user: str
    password: str = ''


@router.get('/bootstrap', summary='Kurulum sihirbazı ortam bilgisi')
def installer_bootstrap(request: HttpRequest):
    """Docker / DATABASE_URL yetenekleri, önerilen profil ve UI mod listesi."""
    cap = probe_capabilities()
    url = os.getenv('DATABASE_URL', '').strip()
    out: Dict[str, Any] = {
        'has_database_url': cap['has_database_url'],
        'docker_available': cap['docker_available'],
        'managed_install_forced': cap.get('managed_install_forced', False),
        'suggested_profile': suggested_profile_from_capabilities(cap),
        'install_modes': install_modes_for_ui(cap),
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
    else:
        out['database_host_hint'] = ''
        out['database_name_hint'] = ''
    if cap.get('docker_available'):
        out['host_mail_ports'] = scan_mail_stack_ports()
    else:
        out['host_mail_ports'] = None
    try:
        from management.deploy_readiness import collect_deploy_readiness

        dr = collect_deploy_readiness()
        out['deploy_readiness'] = {
            'status': dr.get('status'),
            'deployment': dr.get('deployment'),
            'summary_lines': dr.get('summary_lines', []),
            'checks': [
                {k: c[k] for k in ('id', 'title', 'status', 'message', 'hint')}
                for c in (dr.get('checks') or [])
                if c.get('status') != 'ok'
            ],
        }
    except Exception as exc:
        out['deploy_readiness'] = {'status': 'warning', 'message': str(exc)}
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


@router.get('/mail-stack-status', summary='Mail servisleri durumu (sihirbaz)')
def mail_stack_status(request: HttpRequest, domain: str = '', install_profile: str = ''):
    """SMTP/IMAP kontrolü, Docker konteyner durumu ve otomatik kurulum uygunluğu."""
    try:
        canonical = normalize_install_profile(install_profile or 'docker_stack')
    except ValueError:
        canonical = 'docker_stack'
    return collect_installer_mail_stack_status(
        wizard_domain=domain.strip(),
        install_profile=canonical,
    )


class MailStackProvisionSchema(Schema):
    domain: str = ''
    mail_hostname: str = ''
    docker_network: str = ''
    skip_busy_ports: bool = True


@router.post('/mail-stack-provision', summary='Postfix+Dovecot kur (Docker)')
@csrf_exempt
def mail_stack_provision(request: HttpRequest, data: MailStackProvisionSchema):
    dom = (data.domain or '').strip()
    mh = (data.mail_hostname or '').strip() or (f'mail.{dom}' if dom else '')
    cfg = {
        'domain': dom,
        'mail_hostname': mh,
        'stack_skip_busy_host_ports': bool(data.skip_busy_ports),
    }
    if (data.docker_network or '').strip():
        os.environ['MAIL_STACK_DOCKER_NETWORK'] = data.docker_network.strip()
    return auto_setup_mail_services(cfg, skip_busy_ports=bool(data.skip_busy_ports))


class MailAutoSetupSchema(Schema):
    domain: str = ''
    mail_hostname: str = ''
    install_profile: str = 'platform_env'
    skip_busy_ports: bool = True


@router.post('/mail-auto-setup', summary='Mail stack + panel ağı (sihirbaz, otomatik)')
@csrf_exempt
def mail_auto_setup(request: HttpRequest, data: MailAutoSetupSchema):
    """Postfix/Dovecot kur, paneli jir_network'e bağla, TCP doğrula."""
    dom = (data.domain or '').strip()
    mh = (data.mail_hostname or '').strip() or (f'mail.{dom}' if dom else '')
    cfg = {
        'domain': dom,
        'mail_hostname': mh,
        'install_profile': data.install_profile,
        'stack_skip_busy_host_ports': bool(data.skip_busy_ports),
    }
    return auto_setup_mail_services(cfg, skip_busy_ports=bool(data.skip_busy_ports))


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

    try:
        canonical_profile = normalize_install_profile(data.install_profile or 'docker_stack')
    except ValueError as exc:
        return {'status': 'error', 'message': str(exc)}

    stack_policy = (data.stack_service_policy or 'smart').strip().lower()
    if stack_policy not in ('smart', 'force_recreate'):
        return {'status': 'error', 'message': 'stack_service_policy: smart veya force_recreate olmalı.'}

    if canonical_profile == PROFILE_PLATFORM_MANUAL:
        ok, msg = validate_manual_db_connection(db_manual_dict)
        if not ok:
            return {'status': 'error', 'message': f'PostgreSQL bağlantısı doğrulanamadı: {msg}'}

    pre_cfg = {
        'install_profile': canonical_profile,
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
        'install_profile': canonical_profile,
        'db_manual': db_manual_dict,
        'stack_service_policy': stack_policy if canonical_profile == PROFILE_DOCKER_STACK else 'smart',
        'stack_skip_busy_host_ports': bool(data.stack_skip_busy_host_ports)
        if canonical_profile == PROFILE_DOCKER_STACK
        else True,
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
