"""Postfix + Dovecot kurulumu — harici PostgreSQL (DATABASE_URL) ile.

İki kullanım:
1) **Compose üretimi** (`render_mail_stack_compose_yaml`): Coolify / Docker Compose’a yapıştırılacak YAML.
2) **Docker SDK** (`provision_mail_stack_docker`): Sunucuda Docker soketi varsa konteynerleri oluşturur.

Coolify’da Django konteyneri genelde PostgreSQL’e konteyner adıyla bağlanır; Postfix/Dovecot’un aynı
Docker ağında olması için ortamda `MAIL_STACK_DOCKER_NETWORK` (örn. `coolify`) ayarlanmalıdır.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable

import dj_database_url

from installer.compose_builder import JIR_NETWORK, ServiceSpec
from installer.db_url import has_database_url, resolve_database_url
from installer.docker_images import JIR_DOVECOT_IMAGE, ensure_jir_dovecot_image
from installer.mail_pki import (
    ensure_mail_pki_volume,
    mail_tls_volume_mount,
    postfix_tls_environment,
)
from installer.port_check import filter_publish_ports

logger = logging.getLogger(__name__)


@dataclass
class MailStackParams:
    mail_domain: str
    mail_hostname: str
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    postfix_container: str
    dovecot_container: str
    docker_network: str


def _yaml_escape_double(value: str) -> str:
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


def resolve_mail_stack_params(
    *,
    mail_domain_override: str | None = None,
    mail_hostname_override: str | None = None,
    docker_network_override: str | None = None,
) -> MailStackParams:
    """DATABASE_URL (veya Django DATABASES) + MAIL_DOMAIN / SystemConfig."""
    url = resolve_database_url()
    parsed = dj_database_url.parse(url)
    host = (parsed.get('HOST') or 'localhost').strip()
    port = int(parsed.get('PORT') or 5432)
    name = (parsed.get('NAME') or '').strip()
    user = (parsed.get('USER') or '').strip()
    password = str(parsed.get('PASSWORD') or '')

    domain = (mail_domain_override or os.getenv('MAIL_DOMAIN') or '').strip()
    if not domain:
        try:
            from core.models import MailDomain

            md = MailDomain.objects.filter(is_active=True).order_by('id').first()
            if md:
                domain = md.name
        except Exception:
            pass
    if not domain:
        domain = 'example.local'
        logger.warning(
            'MAIL_DOMAIN yok; örnek %s kullanılıyor. Ortama MAIL_DOMAIN ekleyin.', domain
        )

    mail_hostname = (
        mail_hostname_override or os.getenv('MAIL_HOSTNAME') or f'mail.{domain}'
    ).strip()
    net = (docker_network_override or os.getenv('MAIL_STACK_DOCKER_NETWORK') or JIR_NETWORK).strip()
    pf = (os.getenv('JIR_MAIL_POSTFIX_NAME') or 'jir_postfix').strip()
    dv = (os.getenv('JIR_MAIL_DOVECOT_NAME') or 'jir_dovecot').strip()

    return MailStackParams(
        mail_domain=domain,
        mail_hostname=mail_hostname,
        db_host=host,
        db_port=port,
        db_name=name,
        db_user=user,
        db_password=password,
        postfix_container=pf,
        dovecot_container=dv,
        docker_network=net,
    )


def mail_stack_params_from_env() -> MailStackParams:
    """Env tabanlı parametreler."""
    return resolve_mail_stack_params()


def build_mail_only_specs(p: MailStackParams) -> list[ServiceSpec]:
    """Yalnızca Postfix + Dovecot (harici Postgres — depends_on boş)."""
    tls_mount = mail_tls_volume_mount(read_only=True)
    from installer.postfix_inbound import postfix_boky_base_environment, postfix_db_environment

    pf_env = postfix_boky_base_environment(p.mail_domain, p.mail_hostname)
    pf_env.update(postfix_db_environment())
    pf_env.update(postfix_tls_environment())

    postfix = ServiceSpec(
        key='postfix',
        name=p.postfix_container,
        image=os.getenv('JIR_POSTFIX_IMAGE', 'jir-postfix:latest'),
        hostname=p.mail_hostname,
        environment=pf_env,
        ports={
            '25/tcp': 25,
            '587/tcp': 587,
        },
        volumes={
            'jir_postfix_data': {'bind': '/etc/postfix', 'mode': 'rw'},
            'jir_mail_data': {'bind': '/var/mail', 'mode': 'rw'},
            **tls_mount,
        },
        depends_on=[],
        network=p.docker_network,
    )

    dovecot = ServiceSpec(
        key='dovecot',
        name=p.dovecot_container,
        image=JIR_DOVECOT_IMAGE,
        environment={
            'DB_HOST': p.db_host,
            'DB_PORT': str(p.db_port),
            'DB_NAME': p.db_name,
            'DB_USER': p.db_user,
            'DB_PASS': p.db_password,
            'MAIL_DOMAIN': p.mail_domain,
        },
        ports={
            '993/tcp': 993,
        },
        volumes={
            'jir_mail_data': {'bind': '/var/mail', 'mode': 'rw'},
            **tls_mount,
        },
        depends_on=[],
        network=p.docker_network,
    )
    return [postfix, dovecot]


def render_mail_stack_compose_yaml(p: MailStackParams, *, external_network: bool | None = None) -> str:
    """Coolify’da ikinci bir Compose kaynağı olarak yapıştırılabilir YAML."""
    ext = external_network
    if ext is None:
        ext = p.docker_network != JIR_NETWORK

    net_block = ''
    if ext:
        net_block = f"""
networks:
  {p.docker_network}:
    external: true
"""
    else:
        net_block = f"""
networks:
  {p.docker_network}:
    driver: bridge
"""

    q = _yaml_escape_double
    tls_env_lines = '\n'.join(
        f'      {k}: {q(v)}' for k, v in postfix_tls_environment().items()
    )

    return f"""# Jîr-Mail — Postfix + Dovecot (harici PostgreSQL)
# DATABASE_URL ile aynı DB: Dovecot passdb buradan okur.
# PostgreSQL konteyner adına göre DB_HOST kullanın; Postfix/Dovecot ile Postgres
# aynı Docker ağında olmalı. Gerekirse MAIL_STACK_DOCKER_NETWORK ile ağ adını ayarlayın.
#
# Django panelinde sonra şunu ekleyin:
#   JIR_CONTAINER_POSTFIX={p.postfix_container}
#   JIR_CONTAINER_DOVECOT={p.dovecot_container}

services:
  postfix:
    image: {os.getenv('JIR_POSTFIX_IMAGE', 'jir-postfix:latest')}
    build:
      context: ./postfix
    container_name: {p.postfix_container}
    restart: unless-stopped
    hostname: {p.mail_hostname}
    environment:
      ALLOWED_SENDER_DOMAINS: {q(p.mail_domain)}
      HOSTNAME: {q(p.mail_hostname)}
{tls_env_lines}
    volumes:
      - postfix_data:/etc/postfix
      - mail_data:/var/mail
      - jir_mail_tls:/etc/jir-mail/tls:ro
    ports:
      - "${{POSTFIX_PORT_25:-25}}:25"
      - "${{POSTFIX_PORT_587:-587}}:587"
    networks:
      - {p.docker_network}

  dovecot:
    image: {JIR_DOVECOT_IMAGE}
    build:
      context: ./dovecot
    container_name: {p.dovecot_container}
    restart: unless-stopped
    environment:
      DB_HOST: {q(p.db_host)}
      DB_PORT: "{p.db_port}"
      DB_NAME: {q(p.db_name)}
      DB_USER: {q(p.db_user)}
      DB_PASS: {q(p.db_password)}
      MAIL_DOMAIN: {q(p.mail_domain)}
    volumes:
      - mail_data:/var/mail
      - jir_mail_tls:/etc/jir-mail/tls:ro
    ports:
      - "${{DOVECOT_PORT_IMAP:-993}}:993"
    networks:
      - {p.docker_network}

volumes:
  postfix_data:
  mail_data:
  jir_mail_tls:
{net_block}"""


def _ensure_network_simple(client, network_name: str) -> None:
    import docker

    if not isinstance(network_name, str) or not network_name.strip():
        raise ValueError('docker_network boş')
    name = network_name.strip()
    try:
        client.networks.get(name)
        return
    except docker.errors.NotFound:
        pass
    if name != JIR_NETWORK:
        raise RuntimeError(
            f'Docker ağı {name!r} yok. Coolify’da `docker network ls` ile Postgres ile ortak ağı bulun '
            f've oluşturun — veya MAIL_STACK_DOCKER_NETWORK={JIR_NETWORK} ile yerel bridge kullanın '
            f'(bu durumda DATABASE_URL içindeki DB_HOST konteyner adına göre çözülemeyebilir).'
        )
    client.networks.create(JIR_NETWORK, driver='bridge')


def _ensure_volumes_simple(client, specs: list[ServiceSpec]) -> None:
    names: set[str] = set()
    for spec in specs:
        for vname in spec.volumes.keys():
            if not str(vname).startswith('/'):
                names.add(vname)
    for name in sorted(names):
        try:
            client.volumes.get(name)
        except Exception:
            client.volumes.create(name)


def _publish_ports_dict(spec: ServiceSpec, *, skip_busy: bool) -> dict[str, Any]:
    if not spec.ports:
        return {}
    filtered, _skipped = filter_publish_ports(spec.ports, skip_busy=skip_busy)
    return filtered


def _create_or_replace_container(
    client,
    spec: ServiceSpec,
    *,
    skip_busy_ports: bool,
    log: Callable[[str], None] | None = None,
) -> None:
    """İsim çakışırsa eskiyi kaldırıp yeniden oluşturur (basit kurulum)."""
    import docker

    publish_ports = _publish_ports_dict(spec, skip_busy=skip_busy_ports)
    image = spec.image
    if spec.key == 'dovecot':
        image = ensure_jir_dovecot_image(client, log=log)

    try:
        old = client.containers.get(spec.name)
        old.stop(timeout=10)
        old.remove(force=True)
    except docker.errors.NotFound:
        pass

    kwargs: dict[str, Any] = {
        'image': image,
        'name': spec.name,
        'detach': True,
        'restart_policy': {'Name': spec.restart_policy},
        'network': spec.network,
        'environment': spec.environment,
        'volumes': spec.volumes,
        'ports': publish_ports,
    }
    if spec.hostname:
        kwargs['hostname'] = spec.hostname
    client.containers.run(**kwargs)


def provision_mail_stack_docker(
    *,
    skip_busy_ports: bool = True,
    pull_images: bool = True,
    mail_domain_override: str | None = None,
    mail_hostname_override: str | None = None,
    docker_network_override: str | None = None,
    skip_pki_setup: bool = False,
) -> dict[str, Any]:
    """Docker SDK ile Postfix+Dovecot başlat. Soket yoksa success=False + compose metni döner."""
    from installer.orchestrator import _get_docker_client_optional

    messages: list[str] = []
    try:
        p = resolve_mail_stack_params(
            mail_domain_override=mail_domain_override,
            mail_hostname_override=mail_hostname_override,
            docker_network_override=docker_network_override,
        )
    except Exception as exc:
        return {'success': False, 'error': str(exc), 'messages': messages}

    yaml_text = render_mail_stack_compose_yaml(p)

    client = _get_docker_client_optional()
    if client is None:
        return {
            'success': False,
            'mode': 'no_docker',
            'error': 'Docker API yok (Coolify panel konteynerinde sık görülür).',
            'compose_yaml': yaml_text,
            'params': mail_stack_params_summary(p),
            'messages': messages + [
                'Compose YAML üretildi — Coolify’da yeni bir Docker Compose resource olarak ekleyin '
                'veya sunucuda docker compose ile çalıştırın.',
            ],
        }

    try:
        messages.append(f"Ağ: {p.docker_network}")
        _ensure_network_simple(client, p.docker_network)
        pki = None
        if skip_pki_setup:
            messages.append('PKI zaten hazır (atlandı).')
        else:
            messages.append('Dahili mail PKI (TLS) hazırlanıyor…')
            pki = ensure_mail_pki_volume(
                client,
                mail_hostname=p.mail_hostname,
                mail_domain=p.mail_domain,
                postfix_container=p.postfix_container,
                dovecot_container=p.dovecot_container,
                load_if_exists=False,
            )
        specs = build_mail_only_specs(p)
        _ensure_volumes_simple(client, specs)

        ensure_jir_dovecot_image(client, log=lambda m: messages.append(m))

        if pull_images:
            for spec in specs:
                if spec.key == 'dovecot':
                    continue
                messages.append(f"Pull: {spec.image}")
                client.images.pull(spec.image)

        for spec in specs:
            messages.append(f"Konteyner oluşturuluyor: {spec.name}")
            _create_or_replace_container(
                client,
                spec,
                skip_busy_ports=skip_busy_ports,
                log=lambda m: messages.append(m),
            )

        messages.append(
            f'Mail uçları otomatik kaydedilir (SMTP/IMAP). Konteyner adları: '
            f'{p.postfix_container}, {p.dovecot_container}'
        )
        return {
            'success': True,
            'mode': 'docker_sdk',
            'compose_yaml': yaml_text,
            'params': mail_stack_params_summary(p),
            'messages': messages,
            'tls_ca_pem': (pki.ca_cert_pem.decode('utf-8') if pki and pki.ca_cert_pem else None),
        }
    except Exception as exc:
        logger.exception('provision_mail_stack_docker')
        return {
            'success': False,
            'error': str(exc),
            'compose_yaml': yaml_text,
            'params': mail_stack_params_summary(p),
            'messages': messages,
        }
    finally:
        try:
            client.close()
        except Exception:
            pass


def _docker_container_running(client: Any, name: str) -> bool:
    try:
        c = client.containers.get(name)
        return getattr(c, 'status', '') == 'running'
    except Exception:
        return False


def collect_installer_mail_stack_status(
    *,
    wizard_domain: str = '',
    install_profile: str = '',
) -> dict[str, Any]:
    """Sihirbaz mail adımı: SMTP/IMAP erişimi, Docker ve otomatik kurulum uygunluğu."""
    from django.conf import settings

    from installer.compose_mode import is_compose_stack
    from installer.profiles import probe_capabilities
    from management.docker_containers import merged_container_name
    from management.mail_service_endpoint import resolve_mail_endpoint, tcp_reachable

    cap = probe_capabilities()
    compose_mode = bool(cap.get('compose_stack')) or is_compose_stack()
    docker_available = bool(cap.get('docker_available'))
    has_db_url = has_database_url()
    in_docker = bool(getattr(settings, 'IN_DOCKER', False))
    db_engine = str((settings.DATABASES.get('default') or {}).get('ENGINE') or '')
    django_uses_postgresql = 'postgresql' in db_engine

    smtp_host, smtp_port = resolve_mail_endpoint(
        'postfix', int(getattr(settings, 'SMTP_PORT', 587)), auth_submission=True
    )
    imap_host, imap_port = resolve_mail_endpoint(
        'dovecot', int(getattr(settings, 'IMAP_PORT', 993))
    )

    from management.mail_tls import bootstrap_mail_tls_ca_from_db, verify_imap_tls, verify_smtp_starttls

    bootstrap_mail_tls_ca_from_db()
    smtp_ok = False
    imap_ok = False
    if tcp_reachable(smtp_host, smtp_port, timeout=2.5):
        smtp_ok = verify_smtp_starttls(smtp_host, smtp_port, timeout=4.0)
    imap_timeout = 12.0 if compose_mode else 4.0
    if tcp_reachable(imap_host, imap_port, timeout=2.5):
        imap_ok = verify_imap_tls(imap_host, imap_port, timeout=imap_timeout, log_failure=compose_mode)

    pf_name = merged_container_name('postfix')
    dv_name = merged_container_name('dovecot')

    postfix_running = False
    dovecot_running = False
    if compose_mode:
        postfix_running = tcp_reachable(smtp_host, smtp_port, timeout=2.5)
        dovecot_running = tcp_reachable(imap_host, imap_port, timeout=2.5)
    elif docker_available:
        try:
            from installer.orchestrator import _get_docker_client_optional

            client = _get_docker_client_optional()
            if client:
                postfix_running = _docker_container_running(client, pf_name)
                dovecot_running = _docker_container_running(client, dv_name)
                try:
                    client.close()
                except Exception:
                    pass
        except Exception:
            pass

    mail_ready = bool(smtp_ok and imap_ok)

    prof = (install_profile or '').strip().lower()
    can_auto = False
    if not mail_ready:
        if compose_mode or prof == 'compose_stack':
            can_auto = False
        elif prof not in ('docker_stack', 'platform_manual'):
            can_auto = bool(docker_available and has_db_url)

    dom_override = (wizard_domain or '').strip() or None
    params_preview: dict[str, Any] = {}
    try:
        pp = resolve_mail_stack_params(mail_domain_override=dom_override)
        params_preview = mail_stack_params_summary(pp)
    except Exception as exc:
        params_preview = {'error': str(exc)}

    hints: list[str] = []
    if postfix_running and dovecot_running and not mail_ready:
        imap_tcp = tcp_reachable(imap_host, imap_port, timeout=2.5)
        if not imap_tcp:
            hints.append(
                f'jir_dovecot çalışıyor görünüyor ama {imap_host}:{imap_port} dinlemiyor — '
                'Dovecot şablonunda IMAPS 993 tanımlı olmalı; imajı yeniden derleyin.'
            )
        elif not imap_ok:
            hints.append(
                'IMAP portu açık ancak TLS/CA doğrulaması başarısız — mail PKI (jir_mail_tls) ve kurulum adımını tekrarlayın.'
            )
        hints.append(
            'Konteynerler çalışıyor ancak mail TLS doğrulaması tam değil — bootstrap-stack veya '
            'scripts/rebuild-dovecot-on-host.sh; panel jir_network ağında olmalı.'
        )
    if prof == 'docker_stack' and not mail_ready and not (postfix_running and dovecot_running):
        hints.append(
            'Bootstrap henüz tamamlanmadıysa adım 1 çıktısındaki hatayı giderin; ardından “Tekrar dene”.'
        )
    if in_docker and not (os.getenv('SMTP_HOST') or os.getenv('POSTFIX_SMTP_HOST') or '').strip():
        hints.append(
            f'SMTP/IMAP denemesi dahili servis adı ({smtp_host} / {imap_host}) üzerinden yapılır; '
            'konteynerler çalışmıyorsa veya farklı isimdeyse “erişilemiyor” normaldir.'
        )
    if compose_mode and not mail_ready:
        if not postfix_running and dovecot_running:
            hints.append(
                'Postfix (587) kapalı — jir_postfix loglarına bakın. Sihirbazda Postfix onar init script '
                'çalıştırır. Host: docker logs jir_postfix --tail 80'
            )
        hints.append(
            'Compose modu: servisler docker-compose.yml ile çalışıyor. IMAP kapalıysa: '
            'docker logs jir_dovecot — auth (pgsql) ve 993 dinleyici kontrol edin; ardından “Durumu yenile”.'
        )
    if not docker_available and in_docker and not compose_mode:
        hints.append(
            'Docker API bu konteynerde kapalı olabilir (Coolify’da soket mount edilmemiş). '
            'Otomatik mail kurulumu için Docker erişimi veya `provision_mail_stack --print-compose` ile ayrı stack gerekir.'
        )
    if prof == 'platform_env' and not mail_ready and not can_auto and not docker_available:
        hints.append(
            'Ortam veritabanı modunda otomatik Postfix/Dovecot için hem Docker API hem DATABASE_URL gerekir; '
            'biri eksikse kurulumdan sonra compose veya CLI ile mail stack ekleyin.'
        )
    if not has_db_url:
        if 'sqlite' in db_engine:
            hints.append(
                'Şu an SQLite kullanılıyor. Tek sunucu kurulumu bootstrap sonrası jir_postgres + DATABASE_URL '
                'ayarlar; adım 1 bootstrap başarılı olmalı.'
            )
        elif django_uses_postgresql:
            hints.append(
                'DATABASE_URL ortam değişkeninde yok; Django PostgreSQL ayarları kullanılıyor olabilir.'
            )

    return {
        'compose_stack': compose_mode,
        'smtp_host': smtp_host,
        'smtp_port': smtp_port,
        'smtp_ok': smtp_ok,
        'imap_host': imap_host,
        'imap_port': imap_port,
        'imap_ok': imap_ok,
        'docker_available': docker_available,
        'has_database_url': has_db_url,
        'django_uses_postgresql': django_uses_postgresql,
        'in_docker': in_docker,
        'postfix_container': pf_name,
        'dovecot_container': dv_name,
        'postfix_running': postfix_running,
        'dovecot_running': dovecot_running,
        'mail_ready': mail_ready,
        'can_auto_provision': can_auto,
        'install_profile': prof or install_profile,
        'params_preview': params_preview,
        'hints': hints,
    }


def mail_stack_params_summary(p: MailStackParams) -> dict[str, Any]:
    return {
        'mail_domain': p.mail_domain,
        'mail_hostname': p.mail_hostname,
        'db_host': p.db_host,
        'db_port': p.db_port,
        'db_name': p.db_name,
        'db_user': p.db_user,
        'postfix_container': p.postfix_container,
        'dovecot_container': p.dovecot_container,
        'docker_network': p.docker_network,
    }


def mail_stack_instructions_markdown() -> str:
    return """### Coolify özeti

1. `MAIL_STACK_DOCKER_NETWORK`: Postgres ile **aynı** bridge ağının adı (`docker network ls` / `docker inspect <postgres>`).
2. Bu YAML’ı veya `provision_mail_stack --print-compose` çıktısını **ayrı** bir Compose stack olarak deploy et.
3. Django uygulamasına `JIR_CONTAINER_POSTFIX`, `JIR_CONTAINER_DOVECOT` ve gerekirse `SMTP_HOST`/`IMAP_HOST` ekle.
"""
