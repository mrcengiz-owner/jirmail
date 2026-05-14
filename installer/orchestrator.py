"""Docker SDK üzerinden mail server stack'ini orkestre eden modül.

Sırayla (Docker erişilebiliyorsa):
  1. Docker daemon erişimini doğrular
  2. Gerekli network'ü oluşturur
  3. Gerekli volume'ları oluşturur
  4. Image'ları çeker
  5. Container'ları başlatır (healthcheck bekler)
  6. Django migrate çalıştırır
  7. Admin hesabı ve SystemConfig oluşturur

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
from .sse import publish_event


logger = logging.getLogger(__name__)


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


def _start_container(client, spec: ServiceSpec, recorder: StepRecorder) -> None:
    recorder.start()
    try:
        try:
            existing = client.containers.get(spec.name)
            recorder.log(f'Container {spec.name} mevcut (status: {existing.status}).')
            if existing.status != 'running':
                existing.start()
                recorder.log(f'Container {spec.name} başlatıldı.')
            else:
                recorder.log(f'Container {spec.name} zaten çalışıyor.')
        except Exception:
            container_kwargs = {
                'image': spec.image,
                'name': spec.name,
                'detach': True,
                'restart_policy': {'Name': spec.restart_policy},
                'network': spec.network,
                'environment': spec.environment,
                'volumes': spec.volumes,
                'ports': spec.ports,
            }
            if spec.command:
                container_kwargs['command'] = spec.command
            if spec.hostname:
                container_kwargs['hostname'] = spec.hostname
            if spec.healthcheck:
                container_kwargs['healthcheck'] = spec.healthcheck

            container = client.containers.run(**container_kwargs)
            recorder.log(f'Container {spec.name} oluşturuldu ve başlatıldı (id: {container.short_id}).')

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
                    return
            except Exception as exc:
                recorder.log(f'Health kontrol hatası: {exc}')

            time.sleep(2)

        recorder.log(f'{container_name} zaman aşımı içinde hazır olmadı.')
        recorder.finish(success=False, message='Timeout')
    except Exception as exc:
        recorder.finish(success=False, message=str(exc))


def _run_migrations(recorder: StepRecorder) -> None:
    recorder.start()
    try:
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
    """SystemConfig veritabanı alanları: DATABASE_URL öncelikli, yoksa compose varsayılanı."""
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
        client = _get_docker_client_optional()

        if client is None:
            if not os.getenv('DATABASE_URL', '').strip():
                raise RuntimeError(
                    'Docker API kullanılamıyor ve DATABASE_URL tanımlı değil. '
                    "Coolify'da PostgreSQL ekleyip DATABASE_URL verin veya Docker soketini mount edin."
                )

            order = 0
            order += 1
            managed_rec = _make_step(
                run, order, 'Yönetilen ortam',
                'Docker yok — migrasyon ve hesap kurulumu (Coolify / PaaS)',
            )
            managed_rec.start()
            managed_rec.log(
                'Docker soketi veya API erişilemedi. Postfix/Dovecot vb. konteynerleri '
                'platformunuzda ayrı tanımlamanız gerekir; bu adım yalnızca veritabanı ve '
                'panel hesabını tamamlar.'
            )
            managed_rec.finish(success=True)

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
        else:
            specs = order_specs(build_specs(config))

            order = 0
            order += 1
            _ensure_network(client, _make_step(run, order, 'Docker network',
                                               f'Bridge network {JIR_NETWORK} oluştur'))

            order += 1
            _ensure_volumes(client, specs, _make_step(run, order, 'Volume hazırlığı',
                                                       'Persistent volume\'lar oluştur'))

            for spec in specs:
                order += 1
                _pull_image(client, spec.image, _make_step(
                    run, order, f'Image: {spec.image}', f'Pull {spec.image}'))

            for spec in specs:
                order += 1
                _start_container(client, spec, _make_step(
                    run, order, f'Container: {spec.name}', f'Start {spec.name}'))

                if spec.healthcheck:
                    order += 1
                    _wait_for_healthy(client, spec.name, _make_step(
                        run, order, f'Healthcheck: {spec.name}', f'{spec.name} hazır olana kadar bekle'))

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
