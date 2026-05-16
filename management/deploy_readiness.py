"""Coolify / PaaS deploy öncesi ve sonrası ortam doğrulama."""
from __future__ import annotations

import logging
import os
import socket
from typing import Any

from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)

CHECK_OK = 'ok'
CHECK_WARN = 'warning'
CHECK_ERR = 'error'


def detect_deployment_platform() -> str:
    if os.getenv('COOLIFY_FQDN') or os.getenv('COOLIFY_RESOURCE_UUID') or os.getenv('COOLIFY_CONTAINER_NAME'):
        return 'coolify'
    if os.getenv('RAILWAY_ENVIRONMENT') or os.getenv('RAILWAY_PROJECT_ID'):
        return 'railway'
    if os.getenv('RENDER') or os.getenv('RENDER_SERVICE_ID'):
        return 'render'
    if os.getenv('FLY_APP_NAME'):
        return 'fly'
    if os.getenv('DOKPLOY_ENV'):
        return 'dokploy'
    if getattr(settings, 'IN_DOCKER', False):
        return 'docker'
    return 'local'


def _check_item(
    check_id: str,
    title: str,
    status: str,
    message: str,
    *,
    hint: str = '',
    details: dict | None = None,
) -> dict[str, Any]:
    return {
        'id': check_id,
        'title': title,
        'status': status,
        'message': message,
        'hint': hint,
        'details': details or {},
    }


def _worst_status(current: str, new: str) -> str:
    order = {CHECK_OK: 0, CHECK_WARN: 1, CHECK_ERR: 2}
    return new if order.get(new, 0) > order.get(current, 0) else current


def _configured_install_profile() -> str | None:
    try:
        from installer.models import InstallationRun

        run = (
            InstallationRun.objects.filter(status='completed')
            .order_by('-finished_at')
            .first()
        )
        if run and isinstance(run.config_snapshot, dict):
            p = run.config_snapshot.get('install_profile')
            if p:
                return str(p).strip()
    except Exception as exc:
        logger.debug('install_profile okunamadı: %s', exc)
    return os.getenv('JIR_INSTALL_PROFILE', '').strip() or None


def _mail_containers_on_daemon() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        import docker

        dh = getattr(settings, 'DOCKER_HOST', None) or 'unix:///var/run/docker.sock'
        client = docker.DockerClient(base_url=dh, timeout=8)
        client.ping()
        for c in client.containers.list(all=True):
            nm = (c.name or '').lower()
            img = ''
            try:
                img = (((c.attrs or {}).get('Config') or {}).get('Image') or '').lower()
            except Exception:
                pass
            if any(x in nm or x in img for x in ('postfix', 'dovecot', 'smtp', 'imap', 'jir_')):
                out.append({
                    'name': c.name,
                    'status': getattr(c, 'status', ''),
                    'image': img[:120],
                })
        client.close()
    except Exception:
        pass
    return out


def collect_deploy_readiness(*, session_role: str | None = None) -> dict[str, Any]:
    """Deploy / Coolify uyumluluk raporu (API, CLI, entrypoint)."""
    from installer.port_check import scan_mail_stack_ports
    from installer.profiles import (
        PROFILE_DOCKER_STACK,
        PROFILE_PLATFORM_ENV,
        PROFILE_PLATFORM_MANUAL,
        probe_capabilities,
        suggested_profile_from_capabilities,
    )
    from management.docker_containers import merged_container_name, read_stored_container_map
    from management.mail_service_endpoint import resolve_mail_endpoint, tcp_reachable

    cap = probe_capabilities()
    platform = detect_deployment_platform()
    in_docker = bool(getattr(settings, 'IN_DOCKER', False))
    recommended = suggested_profile_from_capabilities(cap)
    configured = _configured_install_profile()

    checks: list[dict[str, Any]] = []
    overall = CHECK_OK

    # —— Bağlam ——
    checks.append(_check_item(
        'deployment_platform',
        'Dağıtım ortamı',
        CHECK_OK,
        f'Algılanan platform: {platform}' + (' (konteyner içi)' if in_docker else ' (host)'),
        hint='Coolify’da panel servisi ile Postfix/Dovecot ayrı resource olabilir.',
        details={'platform': platform, 'in_docker': in_docker},
    ))

    # —— Veritabanı ——
    db_status, db_msg = CHECK_OK, 'Veritabanı bağlantısı başarılı.'
    try:
        connection.ensure_connection()
        with connection.cursor() as cur:
            cur.execute('SELECT 1')
    except Exception as exc:
        db_status, db_msg = CHECK_ERR, f'Veritabanına bağlanılamıyor: {exc}'
    if not cap.get('has_database_url') and db_status == CHECK_OK:
        db_msg += ' (DATABASE_URL ortamda yok; settings.sqlite veya SystemConfig kullanılıyor olabilir.)'
    if not cap.get('has_database_url') and platform == 'coolify':
        db_status = _worst_status(db_status, CHECK_WARN)
        db_msg += ' Coolify’da genelde DATABASE_URL tanımlı olmalı.'
    checks.append(_check_item('database', 'Veritabanı', db_status, db_msg))
    overall = _worst_status(overall, db_status)

    # —— Kurulum profili uyumu ——
    prof_status, prof_msg = CHECK_OK, f'Önerilen profil: {recommended}.'
    if configured:
        prof_msg += f' Son kurulum profili: {configured}.'
    if platform == 'coolify' and recommended == PROFILE_PLATFORM_ENV and configured == PROFILE_DOCKER_STACK:
        prof_status = CHECK_ERR
        prof_msg = (
            'Sunucuda Docker tam stack kurulamaz (Coolify tek uygulama konteyneri). '
            'Lokalde "Docker ile tam kurulum" seçilmiş; sunucuda **Ortam veritabanı (DATABASE_URL)** '
            'kullanın ve Postfix/Dovecot’u ayrı Coolify servisleri olarak deploy edin.'
        )
    elif configured == PROFILE_DOCKER_STACK and not cap.get('docker_available'):
        prof_status = CHECK_ERR
        prof_msg = (
            f'Kurulum profili {PROFILE_DOCKER_STACK} ancak bu ortamda Docker API yok. '
            f'Postfix/Dovecot panel tarafından oluşturulamaz. Önerilen: {PROFILE_PLATFORM_ENV}.'
        )
    elif configured and configured != recommended:
        prof_status = CHECK_WARN
        prof_msg += f' Profil uyumsuzluğu: yapılandırılmış={configured}, önerilen={recommended}.'
    checks.append(_check_item(
        'install_profile',
        'Kurulum profili',
        prof_status,
        prof_msg,
        hint='Setup’ta Coolify için "Ortam veritabanı" seçin; mail servislerini ayrı deploy edin.',
        details={'configured': configured, 'recommended': recommended},
    ))
    overall = _worst_status(overall, prof_status)

    # —— Docker API ——
    if cap.get('managed_install_forced'):
        d_st, d_msg = CHECK_WARN, 'JIR_MANAGED_INSTALL=1 — Docker orkestrasyonu kapalı (bilinçli).'
    elif cap.get('docker_available'):
        mail_ct = _mail_containers_on_daemon()
        d_st, d_msg = CHECK_OK, f'Docker API erişilebilir ({len(mail_ct)} mail ile ilgili konteyner listelendi).'
        if configured == PROFILE_DOCKER_STACK and not any('postfix' in (c['name'] or '').lower() for c in mail_ct):
            d_st = CHECK_WARN
            d_msg += ' jir_postfix benzeri konteyner görünmüyor — kurulum tamamlanmamış veya farklı isim.'
    else:
        d_st = CHECK_WARN if recommended != PROFILE_DOCKER_STACK else CHECK_ERR
        d_msg = (
            'Docker API erişilemiyor. Coolify panel konteynerinde genelde soket mount yoktur; '
            'tam stack kurulumu bu sunucuda çalışmaz.'
        )
    checks.append(_check_item('docker_api', 'Docker API', d_st, d_msg))
    overall = _worst_status(overall, d_st)

    # —— Coolify ortam değişkenleri ——
    env_needed = {
        'DATABASE_URL': bool(os.getenv('DATABASE_URL', '').strip()),
        'JIR_CONTAINER_POSTFIX': bool(os.getenv('JIR_CONTAINER_POSTFIX', '').strip()),
        'JIR_CONTAINER_DOVECOT': bool(os.getenv('JIR_CONTAINER_DOVECOT', '').strip()),
    }
    if platform == 'coolify' or recommended == PROFILE_PLATFORM_ENV:
        missing = [k for k, v in env_needed.items() if not v and k != 'DATABASE_URL']
        if not env_needed['DATABASE_URL']:
            missing.insert(0, 'DATABASE_URL')
        if missing:
            e_st = CHECK_WARN
            e_msg = f'Eksik önerilen env: {", ".join(missing)}.'
        else:
            e_st, e_msg = CHECK_OK, 'Temel Coolify env değişkenleri tanımlı.'
        checks.append(_check_item(
            'coolify_env',
            'Coolify / PaaS env',
            e_st,
            e_msg,
            hint='Coolify → Application → Environment: JIR_CONTAINER_POSTFIX, JIR_CONTAINER_DOVECOT (tam konteyner adları).',
            details=env_needed,
        ))
        overall = _worst_status(overall, e_st)

    # —— Konteyner adları (çözülen) ——
    resolved = {sk: merged_container_name(sk) for sk in ('postfix', 'dovecot', 'postgres', 'redis')}
    map_st = CHECK_OK
    map_msg = f'Postfix→{resolved["postfix"]}, Dovecot→{resolved["dovecot"]}'
    stored = read_stored_container_map()
    if platform == 'coolify' and resolved.get('postfix', '').startswith('jir_') and not env_needed.get('JIR_CONTAINER_POSTFIX'):
        map_st = CHECK_WARN
        map_msg += ' Varsayılan jir_* adları kullanılıyor; Coolify’da gerçek adları env veya Ayarlar sayfasından girin.'
    checks.append(_check_item(
        'container_names',
        'Konteyner ad çözümlemesi',
        map_st,
        map_msg,
        details={'resolved': resolved, 'stored_map': stored},
    ))
    overall = _worst_status(overall, map_st)

    # —— Host mail portları (tam stack / lokal) ——
    ports_info = scan_mail_stack_ports()
    if recommended == PROFILE_DOCKER_STACK or platform == 'local':
        p_st = CHECK_OK if ports_info.get('all_mail_ports_free') else CHECK_WARN
        busy = ports_info.get('busy') or []
        p_msg = 'Mail portları host’ta uygun.' if not busy else f'Dolu portlar: {", ".join(str(b["port"]) for b in busy)}'
        checks.append(_check_item('host_ports', 'Host mail portları', p_st, p_msg, details=ports_info))
        overall = _worst_status(overall, p_st)

    # —— SMTP / IMAP erişilebilirlik ——
    for sk, label, default_port, kw in (
        ('postfix', 'SMTP submission (Postfix 587)', int(getattr(settings, 'SMTP_PORT', 587)), {'auth_submission': True}),
        ('dovecot', 'IMAP (Dovecot)', int(getattr(settings, 'IMAP_PORT', 993)), {}),
    ):
        host, port = resolve_mail_endpoint(sk, default_port, **kw)
        reachable = tcp_reachable(host, port, timeout=2.0)
        m_st = CHECK_OK if reachable else CHECK_ERR
        m_msg = f'{label}: {host}:{port} — {"erişilebilir" if reachable else "erişilemiyor"}.'
        if not reachable and platform == 'coolify':
            m_msg += ' Panel ile Postfix/Dovecot aynı Docker ağında değilse SMTP_HOST / JIR_CONTAINER_* gerekir.'
        checks.append(_check_item(f'mail_{sk}', label, m_st, m_msg, details={'host': host, 'port': port}))
        overall = _worst_status(overall, m_st)

    # —— Kurulum tamamlandı mı ——
    try:
        from saas.models import SystemConfig

        conf = SystemConfig.objects.first()
        installed = bool(conf and conf.is_installed)
    except Exception:
        installed = False
    i_st = CHECK_OK if installed else CHECK_WARN
    i_msg = 'Sistem kurulu (is_installed=True).' if installed else 'Henüz kurulum tamamlanmamış — /setup/ çalıştırın.'
    checks.append(_check_item('is_installed', 'Kurulum durumu', i_st, i_msg))
    overall = _worst_status(overall, i_st)

    summary_lines = [
        f'Platform: {platform} | Önerilen kurulum: {recommended}',
        f'Docker API: {"var" if cap.get("docker_available") else "yok"} | DATABASE_URL: {"var" if cap.get("has_database_url") else "yok"}',
    ]
    if configured == PROFILE_DOCKER_STACK and not cap.get('docker_available'):
        summary_lines.append(
            'KRİTİK: Lokal tam stack kurulumu sunucuda geçerli değil — Coolify’da platform_env + ayrı mail servisleri kullanın.'
        )

    return {
        'status': overall,
        'deployment': {
            'platform': platform,
            'in_docker': in_docker,
            'recommended_install_profile': recommended,
            'configured_install_profile': configured,
        },
        'capabilities': cap,
        'checks': checks,
        'summary_lines': summary_lines,
        'coolify_checklist_url': '/docs/coolify-kontrol-listesi.md',
    }
