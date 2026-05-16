"""Docker SDK üzerinden mail server stack'ini orkestre eden modül.

Sırayla (Docker erişilebiliyorsa):
  1. Docker daemon erişimini doğrular
  2. Gerekli network'ü oluşturur
  3. Gerekli volume'ları oluşturur
  4. Her servis için sırayla: image pull → (smart|force_recreate) konteyner
     kararı ve uygulama → çalışır/sağlıklı doğrulama
  5. Django migrate çalıştırır
  6. Admin hesabı ve SystemConfig oluşturur
  7. DNS kayıtları ve TLS sertifikası (yapılandırmaya göre)

Docker soketi / API yoksa (Coolify, yönetilen PaaS): yalnızca migrasyon,
admin hesabı, DNS/TLS adımları (TLS Docker gerektirirse adım atlanır)
çalışır; DATABASE_URL varsa SystemConfig DB alanları bundan doldurulur.

Tüm adımlar InstallationStep olarak persist edilir; ilerleme SSE üzerinden
real-time olarak istemciye stream edilir.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Callable

from django.conf import settings
from django.utils import timezone

from .compose_builder import JIR_NETWORK, ServiceSpec, build_specs, order_specs
from .models import InstallationRun, InstallationStep
from .port_check import filter_publish_ports
from .profiles import (
    PROFILE_DOCKER_STACK,
    PROFILE_PLATFORM_ENV,
    PROFILE_PLATFORM_MANUAL,
    normalize_install_profile,
)
from .sse import publish_event


logger = logging.getLogger(__name__)

STACK_POLICY_SMART = 'smart'
STACK_POLICY_FORCE_RECREATE = 'force_recreate'


def _image_matches_spec(cfg_image: str, want: str) -> bool:
    """Docker Config.Image ile compose spec.image gevşek eşleşme (repo/tag)."""
    if not cfg_image or not want:
        return False
    if cfg_image == want:
        return True
    if want in cfg_image:
        return True
    want_base = want.split('@')[0].rsplit(':', 1)[0].lower()
    cfg_base = cfg_image.split('@')[0].rsplit(':', 1)[0].lower()
    if want_base and cfg_base and (want_base in cfg_base or cfg_base in want_base):
        return True
    return False


def _remove_container_by_name(client, container_name: str) -> None:
    """Konteyneri durdur ve sil (named volume'lar korunur)."""
    try:
        c = client.containers.get(container_name)
    except Exception:
        return
    try:
        c.remove(force=True)
    except Exception:
        try:
            c.stop(timeout=15)
        except Exception:
            pass
        try:
            c.remove(force=True)
        except Exception:
            pass


def _stack_service_action(client, spec: ServiceSpec, policy: str) -> str:
    """skip | start | recreate — konteyner yoksa recreate (yeni oluştur)."""
    try:
        c = client.containers.get(spec.name)
    except Exception:
        return 'recreate'

    if policy == STACK_POLICY_FORCE_RECREATE:
        _remove_container_by_name(client, spec.name)
        return 'recreate'

    c.reload()
    cfg_img = (c.attrs.get('Config') or {}).get('Image') or ''
    if not _image_matches_spec(cfg_img, spec.image):
        _remove_container_by_name(client, spec.name)
        return 'recreate'

    state = c.attrs.get('State', {})
    health = (state.get('Health') or {}).get('Status') if state.get('Health') else None
    status = state.get('Status', getattr(c, 'status', ''))

    if health == 'unhealthy':
        _remove_container_by_name(client, spec.name)
        return 'recreate'

    if status == 'running' and health in (None, 'healthy', 'starting'):
        return 'skip'

    return 'start'


def _publish_ports_for_spec(spec: ServiceSpec, config: dict, recorder: StepRecorder) -> dict:
    """Host'ta dolu portları atla veya hata ver (config: stack_skip_busy_host_ports)."""
    if not spec.ports:
        return {}
    skip_busy = config.get('stack_skip_busy_host_ports', True)
    if isinstance(skip_busy, str):
        skip_busy = skip_busy.strip().lower() not in ('0', 'false', 'no', 'off')
    filtered, skipped = filter_publish_ports(spec.ports, skip_busy=bool(skip_busy))
    for p in skipped:
        recorder.log(
            f'UYARI: Host port {p} kullanımda — {spec.name} için dışarı publish edilmedi. '
            f'(Docker ağı içinden erişim devam eder; internetten gelen SMTP için portu boşaltın.)'
        )
    if spec.ports and not filtered and skipped:
        recorder.log(
            f'{spec.name}: Tüm istenen host portları dolu; konteyner yalnızca {spec.network} ağında çalışacak.'
        )
    return filtered


def _create_container_from_spec(
    client,
    spec: ServiceSpec,
    recorder: StepRecorder,
    *,
    config: dict | None = None,
) -> None:
    """Yeni konteyner oluştur ve başlat."""
    cfg = config or {}
    publish_ports = _publish_ports_for_spec(spec, cfg, recorder)
    container_kwargs = {
        'image': spec.image,
        'name': spec.name,
        'detach': True,
        'restart_policy': {'Name': spec.restart_policy},
        'network': spec.network,
        'environment': spec.environment,
        'volumes': spec.volumes,
        'ports': publish_ports,
    }
    if spec.command:
        container_kwargs['command'] = spec.command
    if spec.hostname:
        container_kwargs['hostname'] = spec.hostname
    if spec.healthcheck:
        container_kwargs['healthcheck'] = spec.healthcheck

    try:
        container = client.containers.run(**container_kwargs)
    except Exception as exc:
        err = str(exc).lower()
        if 'address already in use' in err or 'failed to bind host port' in err:
            raise RuntimeError(
                f'{spec.name} başlatılamadı: host portu dolu ({exc}). '
                'Sistemdeki postfix/sendmail servisini durdurun: '
                '`sudo systemctl stop postfix` veya `sudo ss -tlnp | grep :25` ile süreci bulun. '
                'Kurulum "dolu portları atla" ile yeniden denenebilir.'
            ) from exc
        raise
    recorder.log(f'Konteyner oluşturuldu: {spec.name} ({container.short_id}).')


def _apply_stack_service_step(
    client,
    spec: ServiceSpec,
    policy: str,
    recorder: StepRecorder,
    *,
    config: dict | None = None,
) -> str:
    """Politikaya göre skip | start | recreate uygula."""
    recorder.start()
    try:
        action = _stack_service_action(client, spec, policy)
        recorder.log(f'Politika={policy} → eylem={action}')
        if action == 'recreate':
            _remove_container_by_name(client, spec.name)
            _create_container_from_spec(client, spec, recorder, config=config)
        elif action == 'start':
            c = client.containers.get(spec.name)
            try:
                c.start()
            except Exception as start_exc:
                err = str(start_exc).lower()
                if 'address already in use' in err or 'failed to bind host port' in err:
                    recorder.log(
                        f'{spec.name} mevcut port eşlemesi host ile çakışıyor; konteyner yeniden oluşturuluyor…'
                    )
                    _remove_container_by_name(client, spec.name)
                    _create_container_from_spec(client, spec, recorder, config=config)
                else:
                    raise
            else:
                recorder.log(f'{spec.name} başlatıldı.')
        else:
            recorder.log(f'{spec.name} uyumlu ve çalışıyor — değiştirilmedi.')
        recorder.finish(success=True)
        return action
    except Exception as exc:
        recorder.log(f'HATA: {exc}')
        recorder.finish(success=False, message=str(exc))
        raise


def _unix_socket_path_from_docker_host(docker_host: str) -> str | None:
    """unix:///var/run/docker.sock -> /var/run/docker.sock (veya None)."""
    if not docker_host.startswith('unix://'):
        return None
    path = docker_host[len('unix://') :]
    if path.startswith('//'):
        path = path[1:]
    return path or '/var/run/docker.sock'


def _get_docker_client_optional():
    """Docker varsa client döndürür; yoksa None (yönetilen kurulum).

    JIR_MANAGED_INSTALL=1 ise Docker denenmez.
    """
    if os.getenv('JIR_MANAGED_INSTALL', '').lower() in ('1', 'true', 'yes'):
        logger.info('JIR_MANAGED_INSTALL: Docker orkestrasyonu atlanıyor.')
        return None

    import docker

    docker_host = getattr(settings, 'DOCKER_HOST', None) or 'unix:///var/run/docker.sock'
    unix_path = _unix_socket_path_from_docker_host(docker_host)
    if unix_path is not None and not os.path.exists(unix_path):
        logger.info('Docker unix socket yok (%s); yönetilen kurulum modu.', unix_path)
        return None

    try:
        client = docker.DockerClient(base_url=docker_host, timeout=20)
        client.ping()
        return client
    except Exception as exc:
        logger.info('Docker API kullanılamıyor (%s); yönetilen kurulum modu.', exc)
        return None


def _get_docker_client():
    """Docker SDK client — yoksa RuntimeError (geri uyumluluk)."""
    client = _get_docker_client_optional()
    if client is None:
        raise RuntimeError(
            'Docker daemon erişilemiyor. Coolify / PaaS için DATABASE_URL tanımlayın '
            '(yönetilen kurulum) veya /var/run/docker.sock mount edin / DOCKER_HOST ayarlayın.'
        )
    return client


def _resolve_profile_and_client(config: dict):
    """Sihirbaz install_profile + Docker client (yalnızca docker_stack için dolu)."""
    raw = config.get('install_profile')
    raw_s = str(raw).strip() if raw is not None else ''

    if not raw_s:
        # Eski run kayıtları: profil yoksa ortamdan çıkar
        c = _get_docker_client_optional()
        if c is not None:
            return PROFILE_DOCKER_STACK, c
        if os.getenv('DATABASE_URL', '').strip():
            return PROFILE_PLATFORM_ENV, None
        raise RuntimeError(
            'Kurulum profili yapılandırmada yok ve ortam hazır değil '
            '(Docker API yok, DATABASE_URL yok). Sihirbazı yeniden başlatın.'
        )

    try:
        p = normalize_install_profile(raw_s)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc

    if p == PROFILE_DOCKER_STACK:
        c = _get_docker_client_optional()
        if c is None:
            raise RuntimeError(
                '“Docker ile tam kurulum” seçildi ancak Docker API erişilemiyor. '
                'Docker soketini mount edin veya platform / ortam veritabanı modunu seçin.'
            )
        return PROFILE_DOCKER_STACK, c
    if p == PROFILE_PLATFORM_ENV:
        if not os.getenv('DATABASE_URL', '').strip():
            raise RuntimeError(
                '“Ortamdaki veritabanı” modu için sunucuda DATABASE_URL tanımlı olmalı '
                '(ör. Coolify PostgreSQL servisi).'
            )
        return PROFILE_PLATFORM_ENV, None
    if p == PROFILE_PLATFORM_MANUAL:
        dbm = config.get('db_manual') or {}
        if not (dbm.get('host') and dbm.get('name') and str(dbm.get('user', '')).strip()):
            raise RuntimeError('Manuel veritabanı: sunucu, veritabanı adı ve kullanıcı zorunludur.')
        return PROFILE_PLATFORM_MANUAL, None

    raise RuntimeError(f'Dahili hata: bilinmeyen profil {p!r}.')


class StepRecorder:
    """Adım kaydedici. InstallationStep'i günceller, SSE event'i yayar."""

    def __init__(self, run: InstallationRun, step: InstallationStep):
        self.run = run
        self.step = step

    def log(self, line: str, *, progress: int | None = None) -> None:
        self.step.log = (self.step.log + line + '\n')[-8000:]
        if progress is not None:
            self.step.progress_percent = max(0, min(100, progress))
        self.step.save(update_fields=['log', 'progress_percent'])
        publish_event(str(self.run.run_id), 'step_log', {
            'step_id': self.step.id,
            'order': self.step.order,
            'name': self.step.name,
            'log_line': line,
            'progress': self.step.progress_percent,
        })

    def start(self) -> None:
        self.step.status = 'running'
        self.step.started_at = timezone.now()
        self.step.save(update_fields=['status', 'started_at'])
        publish_event(str(self.run.run_id), 'step_start', {
            'step_id': self.step.id,
            'order': self.step.order,
            'name': self.step.name,
            'description': self.step.description,
        })

    def finish(self, *, success: bool = True, message: str = '') -> None:
        self.step.status = 'completed' if success else 'failed'
        self.step.finished_at = timezone.now()
        self.step.progress_percent = 100 if success else self.step.progress_percent
        if message:
            self.step.log = (self.step.log + message + '\n')[-8000:]
        self.step.save()
        publish_event(str(self.run.run_id), 'step_end', {
            'step_id': self.step.id,
            'order': self.step.order,
            'name': self.step.name,
            'status': self.step.status,
            'progress': self.step.progress_percent,
        })


def _make_step(run: InstallationRun, order: int, name: str, description: str = '') -> StepRecorder:
    step = InstallationStep.objects.create(
        run=run, order=order, name=name, description=description, status='pending',
    )
    publish_event(str(run.run_id), 'step_added', {
        'step_id': step.id, 'order': step.order, 'name': step.name, 'description': step.description,
    })
    return StepRecorder(run, step)


def _ensure_network(client, recorder: StepRecorder) -> None:
    recorder.start()
    try:
        existing = [n for n in client.networks.list(names=[JIR_NETWORK]) if n.name == JIR_NETWORK]
        if existing:
            recorder.log(f'Network {JIR_NETWORK} zaten mevcut.')
        else:
            client.networks.create(JIR_NETWORK, driver='bridge')
            recorder.log(f'Network {JIR_NETWORK} oluşturuldu.')
        recorder.finish(success=True)
    except Exception as exc:
        recorder.log(f'HATA: {exc}')
        recorder.finish(success=False, message=str(exc))
        raise


def _ensure_volumes(client, specs: list[ServiceSpec], recorder: StepRecorder) -> None:
    recorder.start()
    try:
        volume_names: set[str] = set()
        for spec in specs:
            for vname in spec.volumes.keys():
                if not vname.startswith('/'):
                    volume_names.add(vname)

        for name in sorted(volume_names):
            try:
                client.volumes.get(name)
                recorder.log(f'Volume {name} zaten mevcut.')
            except Exception:
                client.volumes.create(name)
                recorder.log(f'Volume {name} oluşturuldu.')

        recorder.finish(success=True)
    except Exception as exc:
        recorder.log(f'HATA: {exc}')
        recorder.finish(success=False, message=str(exc))
        raise


def _pull_image(client, image: str, recorder: StepRecorder) -> None:
    recorder.start()
    try:
        recorder.log(f'Image çekiliyor: {image}')
        try:
            client.images.get(image)
            recorder.log(f'Image {image} zaten mevcut, atlanıyor.')
            recorder.finish(success=True)
            return
        except Exception:
            pass

        try:
            for chunk in client.api.pull(image, stream=True, decode=True):
                status = chunk.get('status', '')
                progress = chunk.get('progress', '')
                if status:
                    line = status + ((' ' + progress) if progress else '')
                    recorder.log(line[:200])
        except Exception as pull_exc:
            recorder.log(f'Stream pull başarısız, fallback: {pull_exc}')
            client.images.pull(image)

        recorder.log(f'Image {image} indirildi.')
        recorder.finish(success=True)
    except Exception as exc:
        recorder.log(f'HATA: {exc}')
        recorder.finish(success=False, message=str(exc))
        raise


def _wait_for_healthy(client, container_name: str, recorder: StepRecorder, timeout: int = 90) -> None:
    recorder.start()
    deadline = time.time() + timeout
    last_status = None
    try:
        while time.time() < deadline:
            try:
                container = client.containers.get(container_name)
                container.reload()
                state = container.attrs.get('State', {})
                health = state.get('Health', {}).get('Status') if state.get('Health') else None
                status = state.get('Status')

                if health and health != last_status:
                    recorder.log(f'{container_name} health: {health}')
                    last_status = health

                if health == 'healthy' or (health is None and status == 'running'):
                    recorder.log(f'{container_name} hazır.')
                    recorder.finish(success=True)
                    return
                if health == 'unhealthy':
                    recorder.log(f'{container_name} unhealthy oldu.')
                    recorder.finish(success=False, message='Container unhealthy')
                    raise RuntimeError(f'{container_name}: healthcheck unhealthy')
            except RuntimeError:
                raise
            except Exception as exc:
                recorder.log(f'Health kontrol hatası: {exc}')

            time.sleep(2)

        recorder.log(f'{container_name} zaman aşımı içinde hazır olmadı.')
        recorder.finish(success=False, message='Timeout')
        raise RuntimeError(f'{container_name}: healthcheck zaman aşımı ({timeout}s)')
    except Exception as exc:
        if recorder.step.status != 'failed':
            recorder.finish(success=False, message=str(exc))
        raise


def _build_postgres_url_from_manual(dbm: dict) -> str:
    """PostgreSQL bağlantı URL'i (migrate alt süreci için)."""
    from urllib.parse import quote_plus

    user = quote_plus(str(dbm['user']))
    pw = quote_plus(str(dbm.get('password', '')))
    host = str(dbm['host'])
    port = int(dbm.get('port') or 5432)
    name = str(dbm['name']).lstrip('/')
    return f'postgresql://{user}:{pw}@{host}:{port}/{name}'


def _run_migrations(recorder: StepRecorder, *, subprocess_database_url: str | None = None) -> None:
    recorder.start()
    try:
        if subprocess_database_url:
            import subprocess
            import sys

            recorder.log('Veritabanı migration (manuel bağlantı ile alt süreç)...')
            env = os.environ.copy()
            env['DATABASE_URL'] = subprocess_database_url
            subprocess.check_call(
                [sys.executable, str(settings.BASE_DIR / 'manage.py'), 'migrate', '--noinput'],
                cwd=str(settings.BASE_DIR),
                env=env,
                timeout=600,
            )
            recorder.log('Migration tamamlandı (alt süreç).')
            recorder.finish(success=True)
            return

        from django.core.management import call_command

        recorder.log('makemigrations çalıştırılıyor...')
        try:
            call_command('makemigrations', verbosity=0, interactive=False)
            recorder.log('makemigrations tamamlandı.')
        except Exception as mm_exc:
            recorder.log(f'makemigrations uyarısı: {mm_exc}')

        recorder.log('migrate çalıştırılıyor...')
        call_command('migrate', verbosity=0, interactive=False)
        recorder.log('Migration tamamlandı.')
        recorder.finish(success=True)
    except Exception as exc:
        recorder.log(f'HATA: {exc}')
        recorder.finish(success=False, message=str(exc))
        raise


def _apply_dns_records(config: dict, recorder: StepRecorder) -> None:
    """DNS provider üzerinden kayıtları otomatik ekle. Manuel ise sadece logla."""
    recorder.start()
    try:
        from dns_providers import get_provider, DNSRecord
        from core.models import MailDomain

        provider_name = config.get('dns_provider', 'manual')
        credentials = config.get('dns_credentials', {}) or {}
        domain_name = config['domain']

        provider = get_provider(provider_name, credentials)
        if provider_name == 'manual' or not provider.is_configured():
            recorder.log(f'Provider: {provider_name} (manuel). Kayıtlar dashboard\'da gösterilecek.')
            recorder.finish(success=True)
            return

        domain_obj = MailDomain.objects.filter(name=domain_name).first()
        if domain_obj and not domain_obj.dkim_enabled:
            domain_obj.generate_dkim_keys()
            recorder.log('DKIM anahtar çifti üretildi.')

        mail_host = config.get('mail_hostname', f'mail.{domain_name}')
        records = [
            DNSRecord(name='mail', type='A', content='SUNUCU_IP'),
            DNSRecord(name='@', type='MX', content=mail_host, priority=10),
            DNSRecord(name='@', type='TXT', content='v=spf1 mx a -all'),
            DNSRecord(name='_dmarc', type='TXT',
                      content=f'v=DMARC1; p=quarantine; rua=mailto:dmarc@{domain_name}'),
        ]

        for r in records:
            outcome = provider.create_record(domain_name, r)
            if outcome.get('success'):
                recorder.log(f'OK   {r.type} {r.name} -> {r.content[:60]}')
            else:
                recorder.log(f'SKIP {r.type} {r.name}: {outcome.get("message", "")}')

        if domain_obj:
            domain_obj.dns_provider = provider_name
            domain_obj.dns_credentials = credentials
            domain_obj.save(update_fields=['dns_provider', 'dns_credentials'])

        recorder.finish(success=True)
    except Exception as exc:
        recorder.log(f'HATA: {exc}')
        recorder.finish(success=False, message=str(exc))


def _request_tls_certificate(config: dict, recorder: StepRecorder) -> None:
    """Let's Encrypt sertifikası al (best-effort; başarısız olursa adımı işaretler ama run'ı durdurmaz)."""
    recorder.start()
    try:
        from tls.certbot_manager import request_certificate
        from core.models import MailDomain
        from django.utils import timezone as tz

        domain_name = config['domain']
        admin_email = config['admin_email']

        recorder.log('Let\'s Encrypt sertifika talebi başlatılıyor (staging mode)...')
        result = request_certificate(domain_name, admin_email, staging=True)

        recorder.log((result.get('output') or '')[:500])

        if result.get('success'):
            md = MailDomain.objects.filter(name=domain_name).first()
            if md:
                md.tls_cert_path = f'/etc/letsencrypt/live/mail.{domain_name}/fullchain.pem'
                md.tls_key_path = f'/etc/letsencrypt/live/mail.{domain_name}/privkey.pem'
                md.tls_issued_at = tz.now()
                md.save(update_fields=['tls_cert_path', 'tls_key_path', 'tls_issued_at'])
            recorder.log('Sertifika alındı.')
            recorder.finish(success=True)
        else:
            recorder.log('Sertifika alınamadı; manuel olarak sonradan denenebilir.')
            recorder.step.status = 'skipped'
            recorder.step.finished_at = timezone.now()
            recorder.step.save()
            publish_event(str(recorder.run.run_id), 'step_end', {
                'step_id': recorder.step.id,
                'order': recorder.step.order,
                'name': recorder.step.name,
                'status': 'skipped',
                'progress': 100,
            })
    except Exception as exc:
        recorder.log(f'HATA (TLS atlandı): {exc}')
        recorder.step.status = 'skipped'
        recorder.step.finished_at = timezone.now()
        recorder.step.save()
        publish_event(str(recorder.run.run_id), 'step_end', {
            'step_id': recorder.step.id,
            'order': recorder.step.order,
            'name': recorder.step.name,
            'status': 'skipped',
            'progress': 100,
        })


def _apply_system_config_database(config_obj, config: dict, recorder: StepRecorder) -> None:
    """SystemConfig veritabanı alanları: sihirbaz manuel > DATABASE_URL > compose."""
    manual = config.get('db_manual') or {}
    if manual.get('host') and manual.get('name') and manual.get('user') is not None:
        config_obj.db_engine = 'django.db.backends.postgresql'
        config_obj.db_host = str(manual['host'])
        port = manual.get('port')
        config_obj.db_port = int(port) if port not in (None, '') else 5432
        config_obj.db_name = str(manual['name'])
        config_obj.db_user = str(manual['user'])
        config_obj.db_password = str(manual.get('password', ''))
        recorder.log('SystemConfig manuel girilen PostgreSQL bilgileriyle dolduruldu.')
        return

    database_url = os.getenv('DATABASE_URL', '').strip()
    if database_url:
        try:
            import dj_database_url

            dbc = dj_database_url.parse(database_url, conn_max_age=600)
        except Exception as exc:
            recorder.log(f'DATABASE_URL ayrıştırılamadı: {exc}')
            raise
        engine = (dbc.get('ENGINE') or '').lower()
        if 'sqlite' in engine:
            config_obj.db_engine = 'django.db.backends.sqlite3'
            config_obj.db_host = ''
            config_obj.db_port = None
            config_obj.db_name = str(dbc.get('NAME') or '')
            config_obj.db_user = ''
            config_obj.db_password = ''
        else:
            config_obj.db_engine = 'django.db.backends.postgresql'
            config_obj.db_host = str(dbc.get('HOST') or 'localhost')
            port = dbc.get('PORT')
            config_obj.db_port = int(port) if port not in (None, '') else 5432
            config_obj.db_name = str(dbc.get('NAME') or '')
            config_obj.db_user = str(dbc.get('USER') or '')
            config_obj.db_password = str(dbc.get('PASSWORD') or '')
        recorder.log('SystemConfig veritabanı alanları DATABASE_URL ile dolduruldu.')
        return

    config_obj.db_engine = 'django.db.backends.postgresql'
    config_obj.db_host = 'jir_postgres'
    config_obj.db_port = 5432
    config_obj.db_name = config.get('postgres_db', 'jir_mail_prod')
    config_obj.db_user = config.get('postgres_user', 'postgres')
    config_obj.db_password = config.get('postgres_password', '')
    recorder.log('SystemConfig veritabanı alanları Docker Compose (jir_postgres) için ayarlandı.')


def _create_admin_account(config: dict, recorder: StepRecorder) -> None:
    recorder.start()
    try:
        import bcrypt
        from core.models import MailDomain, MailAccount
        from saas.models import SystemConfig

        domain_name = config['domain']
        admin_email = config['admin_email'].lower()
        admin_password = config['admin_password']

        domain_obj, _ = MailDomain.objects.get_or_create(name=domain_name, defaults={'is_active': True})
        recorder.log(f'Domain {domain_name} hazırlandı.')

        salt = bcrypt.gensalt()
        hashed_pw = bcrypt.hashpw(admin_password.encode('utf-8'), salt).decode('utf-8')

        username = admin_email.split('@')[0]
        existing = MailAccount.objects.filter(email=admin_email).first()
        if existing:
            existing.password_hash = hashed_pw
            existing.role = 'FULL'
            existing.is_active = True
            existing.save()
            recorder.log(f'Admin hesabı {admin_email} güncellendi.')
        else:
            MailAccount.objects.create(
                domain=domain_obj,
                username=username,
                email=admin_email,
                password_hash=hashed_pw,
                role='FULL',
            )
            recorder.log(f'Admin hesabı {admin_email} oluşturuldu.')

        config_obj = SystemConfig.objects.first() or SystemConfig()
        config_obj.is_installed = True
        config_obj.instance_id = config.get('instance_id') or config_obj.instance_id
        config_obj.jir_local_key = config.get('jir_local_key', config_obj.jir_local_key)
        _apply_system_config_database(config_obj, config, recorder)
        config_obj.installation_log = {
            'run_id': str(recorder.run.run_id),
            'completed_at': timezone.now().isoformat(),
        }
        config_obj.save()
        recorder.log('SystemConfig kaydedildi (is_installed=True).')
        recorder.finish(success=True)
    except Exception as exc:
        recorder.log(f'HATA: {exc}')
        recorder.finish(success=False, message=str(exc))
        raise


def run_installation(run_id: str) -> None:
    """Tüm kurulum sürecini yürüten ana fonksiyon.

    Celery task'ı veya senkron olarak çağrılabilir. SSE üzerinden
    progress yayar; başarı/başarısızlık durumunda InstallationRun.status'u
    günceller.
    """
    try:
        run = InstallationRun.objects.get(run_id=run_id)
    except InstallationRun.DoesNotExist:
        logger.error('Run bulunamadı: %s', run_id)
        return

    run.status = 'running'
    run.save(update_fields=['status'])
    publish_event(str(run.run_id), 'run_start', {'run_id': str(run.run_id)})

    config = run.config_snapshot or {}

    try:
        profile, client = _resolve_profile_and_client(config)

        if profile == PROFILE_DOCKER_STACK:
            specs = order_specs(build_specs(config))

            order = 0
            order += 1
            _ensure_network(client, _make_step(run, order, 'Docker network',
                                               f'Bridge network {JIR_NETWORK} oluştur'))

            order += 1
            _ensure_volumes(client, specs, _make_step(run, order, 'Volume hazırlığı',
                                                       'Persistent volume\'lar oluştur'))

            policy_raw = (config.get('stack_service_policy') or STACK_POLICY_SMART).strip().lower()
            if policy_raw not in (STACK_POLICY_SMART, STACK_POLICY_FORCE_RECREATE):
                policy_raw = STACK_POLICY_SMART

            for spec in specs:
                order += 1
                _pull_image(client, spec.image, _make_step(
                    run, order, f'Image: {spec.image}', f'{spec.name} — pull'))

                order += 1
                _apply_stack_service_step(
                    client,
                    spec,
                    policy_raw,
                    _make_step(
                        run,
                        order,
                        f'Servis: {spec.name}',
                        f'Politika {policy_raw} — konteyner oluştur / güncelle / atla',
                    ),
                    config=config,
                )

                order += 1
                _wait_for_healthy(
                    client,
                    spec.name,
                    _make_step(
                        run,
                        order,
                        f'Sağlık: {spec.name}',
                        f'{spec.name} çalışır ve (varsa) health healthy olana kadar bekle',
                    ),
                    timeout=120,
                )

            order += 1
            _run_migrations(_make_step(run, order, 'Veritabanı migration',
                                        'Django migrate çalıştır'))

            order += 1
            _create_admin_account(config, _make_step(run, order, 'Admin hesabı',
                                                     'Admin kullanıcısı ve SystemConfig oluştur'))

            order += 1
            _apply_dns_records(config, _make_step(run, order, 'DNS kayıtları',
                                                 f'{config.get("dns_provider", "manual")} ile DNS yapılandırması'))

            order += 1
            _request_tls_certificate(config, _make_step(run, order, 'TLS sertifikası',
                                                         'Let\'s Encrypt sertifika talebi (staging)'))

            try:
                client.close()
            except Exception:
                pass
        else:
            order = 0
            order += 1
            managed_rec = _make_step(
                run, order, 'Platform kurulumu',
                'Docker orkestrasyonu yok — veritabanı ve panel',
            )
            managed_rec.start()
            if profile == PROFILE_PLATFORM_ENV:
                managed_rec.log(
                    'DATABASE_URL ile mevcut PostgreSQL kullanılıyor. '
                    'Postfix/Dovecot: `python manage.py provision_mail_stack --print-compose` veya '
                    '`provision_mail_stack --apply-docker` (Docker soketi varsa).'
                )
            else:
                managed_rec.log(
                    'Manuel girilen PostgreSQL ile migrate ayrı süreçte çalıştırılır. '
                    'Uygulama ortamındaki DATABASE_URL aynı veritabanına işaret etmelidir (Coolify).'
                )
            managed_rec.finish(success=True)

            order += 1
            sub_url = None
            if profile == PROFILE_PLATFORM_MANUAL:
                sub_url = _build_postgres_url_from_manual(config.get('db_manual') or {})
            _run_migrations(
                _make_step(run, order, 'Veritabanı migration', 'Django migrate'),
                subprocess_database_url=sub_url,
            )

            order += 1
            _create_admin_account(config, _make_step(run, order, 'Admin hesabı',
                                                     'Admin kullanıcısı ve SystemConfig oluştur'))

            order += 1
            _apply_dns_records(config, _make_step(run, order, 'DNS kayıtları',
                                                 f'{config.get("dns_provider", "manual")} ile DNS yapılandırması'))

            order += 1
            _request_tls_certificate(config, _make_step(run, order, 'TLS sertifikası',
                                                         'Let\'s Encrypt sertifika talebi (staging)'))

        run.status = 'completed'
        run.finished_at = timezone.now()
        run.save(update_fields=['status', 'finished_at'])

        publish_event(str(run.run_id), 'completed', {
            'run_id': str(run.run_id),
            'message': 'Kurulum başarıyla tamamlandı.',
        })
    except Exception as exc:
        logger.exception('Installation failed')
        run.status = 'failed'
        run.error_message = str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=['status', 'error_message', 'finished_at'])
        publish_event(str(run.run_id), 'failed', {
            'run_id': str(run.run_id),
            'message': str(exc),
        })
