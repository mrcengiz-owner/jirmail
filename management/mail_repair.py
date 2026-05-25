"""Dashboard onarım menüsü — whitelist işlemler, audit, rate limit."""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

FULL_REPAIR_RATE_LIMIT_SEC = 300
SINGLE_ACTION_RATE_LIMIT_SEC = 60

REPAIR_ACTION_LABELS: dict[str, str] = {
    'routing_fix': 'Postfix routing (Gmail → internet SMTP)',
    'pgsql_rewrite': 'Postfix pgsql haritaları yenile',
    'reserved_domains': 'Yanlış sağlayıcı domainlerini pasifleştir',
    'stack_verify': 'Mail stack doğrula ve onar',
    'outbound_probe': 'Dış gönderim tanılama',
    'dovecot_heal': 'Dovecot yapılandırma onarımı',
    'postfix_heal': 'Postfix konteyner onarımı',
    'full': 'Tam stack onarımı',
}


def _client_ip(request) -> str:
    forwarded = (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
    return forwarded or (request.META.get('REMOTE_ADDR') or '')[:64]


def _rate_limit_key(action: str, actor: str) -> str:
    return f'jir:mail-repair:{action}:{actor or "anon"}'


def check_rate_limit(action: str, actor_email: str) -> tuple[bool, int]:
    """True = izin var. İkinci değer kalan saniye (limit varsa)."""
    if action == 'full':
        limit = FULL_REPAIR_RATE_LIMIT_SEC
    else:
        limit = SINGLE_ACTION_RATE_LIMIT_SEC
    key = _rate_limit_key(action, actor_email)
    last = cache.get(key)
    if last is None:
        return True, 0
    elapsed = time.time() - float(last)
    if elapsed >= limit:
        return True, 0
    return False, int(limit - elapsed)


def _mark_rate_limit(action: str, actor_email: str) -> None:
    key = _rate_limit_key(action, actor_email)
    ttl = FULL_REPAIR_RATE_LIMIT_SEC if action == 'full' else SINGLE_ACTION_RATE_LIMIT_SEC
    cache.set(key, time.time(), timeout=ttl + 30)


def _sanitize_report(data: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return '…'
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            lk = str(k).lower()
            if any(x in lk for x in ('password', 'secret', 'token', 'passwd')):
                out[k] = '***'
            else:
                out[k] = _sanitize_report(v, depth=depth + 1)
        return out
    if isinstance(data, list):
        return [_sanitize_report(x, depth=depth + 1) for x in data[:50]]
    if isinstance(data, str) and len(data) > 2000:
        return data[:2000] + '…'
    return data


def record_repair_run(
    *,
    action: str,
    actor_email: str,
    ok: bool,
    summary: str,
    report: dict[str, Any] | None,
    ip_address: str = '',
) -> None:
    try:
        from management.models import MailRepairRun

        MailRepairRun.objects.create(
            action=action,
            actor_email=(actor_email or '')[:254],
            ok=bool(ok),
            summary=(summary or '')[:500],
            report=_sanitize_report(report or {}),
            ip_address=(ip_address or '')[:64],
        )
    except Exception as exc:
        logger.debug('repair audit kaydı yazılamadı: %s', exc)


def collect_repair_status() -> dict[str, Any]:
    """Onarım sayfası durum özeti — salt okuma."""
    out: dict[str, Any] = {
        'ok': True,
        'checks': [],
        'mail_stack': {},
        'routing': {},
        'outbound': {},
        'docker_available': False,
        'last_repair': None,
    }
    try:
        from installer.mail_stack import collect_installer_mail_stack_status

        out['mail_stack'] = collect_installer_mail_stack_status(
            wizard_domain='',
            install_profile='compose_stack',
        )
        out['docker_available'] = bool(out['mail_stack'].get('docker_available'))
        for key, label in (
            ('smtp_ok', 'SMTP (587)'),
            ('imap_ok', 'IMAP (993)'),
            ('postfix_running', 'Postfix konteyner'),
            ('dovecot_running', 'Dovecot konteyner'),
            ('mail_ready', 'Mail hazır'),
        ):
            val = out['mail_stack'].get(key)
            out['checks'].append({'id': key, 'label': label, 'ok': bool(val), 'value': val})
            if key in ('smtp_ok', 'imap_ok', 'mail_ready') and not val:
                out['ok'] = False
    except Exception as exc:
        out['ok'] = False
        out['checks'].append({'id': 'mail_stack', 'label': 'Mail stack', 'ok': False, 'error': str(exc)})

    try:
        from management.outbound_autoconfig import probe_postfix_recipient_routing

        out['routing'] = probe_postfix_recipient_routing(domain='gmail.com')
        routing_ok = bool(out['routing'].get('ok'))
        out['checks'].append({
            'id': 'gmail_routing',
            'label': 'Gmail routing (dış alıcı)',
            'ok': routing_ok,
            'message': out['routing'].get('message', ''),
        })
        if not routing_ok:
            out['ok'] = False
    except Exception as exc:
        out['routing'] = {'ok': False, 'error': str(exc)}
        out['checks'].append({'id': 'gmail_routing', 'label': 'Gmail routing', 'ok': False, 'error': str(exc)})
        out['ok'] = False

    try:
        from management.outbound_connectivity import check_outbound_smtp

        out['outbound'] = check_outbound_smtp(include_django_probe=False)
        outbound_ok = bool(out['outbound'].get('ok')) or out['outbound'].get('mode') == 'relay'
        out['checks'].append({
            'id': 'outbound_smtp',
            'label': 'Dış posta çıkışı',
            'ok': outbound_ok,
            'message': out['outbound'].get('message', ''),
        })
    except Exception as exc:
        out['outbound'] = {'ok': False, 'error': str(exc)}

    try:
        from management.models import MailRepairRun

        last = MailRepairRun.objects.order_by('-created_at').first()
        if last:
            out['last_repair'] = {
                'action': last.action,
                'action_label': REPAIR_ACTION_LABELS.get(last.action, last.action),
                'ok': last.ok,
                'summary': last.summary,
                'actor_email': last.actor_email,
                'created_at': last.created_at.isoformat(),
            }
    except Exception:
        pass

    return out


def _action_routing_fix() -> dict[str, Any]:
    from management.postfix_maps import force_fix_postfix_routing

    return force_fix_postfix_routing()


def _action_pgsql_rewrite() -> dict[str, Any]:
    from management.postfix_maps import rewrite_postfix_pgsql_maps

    return rewrite_postfix_pgsql_maps()


def _action_reserved_domains() -> dict[str, Any]:
    from management.outbound_autoconfig import _fix_reserved_domains

    fixed = _fix_reserved_domains()
    return {'ok': True, 'fixed_domains': fixed, 'message': f'{len(fixed)} domain pasifleştirildi'}


def _action_stack_verify() -> dict[str, Any]:
    from management.mail_stack_health import verify_mail_stack

    return verify_mail_stack(fix=True, healthcheck=True)


def _action_outbound_probe() -> dict[str, Any]:
    from management.outbound_autoconfig import probe_postfix_recipient_routing
    from management.outbound_connectivity import check_outbound_smtp

    routing = probe_postfix_recipient_routing(domain='gmail.com')
    outbound = check_outbound_smtp(include_django_probe=False)
    ok = bool(routing.get('ok')) and (bool(outbound.get('ok')) or outbound.get('mode') == 'relay')
    return {'ok': ok, 'routing': routing, 'outbound': outbound}


def _action_dovecot_heal() -> dict[str, Any]:
    from management.mail_stack_health import heal_dovecot_container

    return heal_dovecot_container()


def _action_postfix_heal() -> dict[str, Any]:
    from management.mail_stack_health import heal_postfix_container

    return heal_postfix_container()


def _action_full() -> dict[str, Any]:
    report: dict[str, Any] = {'ok': True, 'steps': []}

    for name, fn in (
        ('reserved_domains', _action_reserved_domains),
        ('routing_fix', _action_routing_fix),
        ('stack_verify', _action_stack_verify),
        ('outbound_probe', _action_outbound_probe),
    ):
        try:
            step = fn()
            step_ok = bool(step.get('ok', True))
            report['steps'].append({'action': name, 'ok': step_ok, 'result': step})
            if not step_ok:
                report['ok'] = False
        except Exception as exc:
            report['steps'].append({'action': name, 'ok': False, 'error': str(exc)})
            report['ok'] = False

    report['message'] = (
        'Tam stack onarımı tamamlandı.' if report['ok'] else 'Tam stack onarımı kısmen başarısız.'
    )
    return report


REPAIR_HANDLERS: dict[str, Callable[[], dict[str, Any]]] = {
    'routing_fix': _action_routing_fix,
    'pgsql_rewrite': _action_pgsql_rewrite,
    'reserved_domains': _action_reserved_domains,
    'stack_verify': _action_stack_verify,
    'outbound_probe': _action_outbound_probe,
    'dovecot_heal': _action_dovecot_heal,
    'postfix_heal': _action_postfix_heal,
    'full': _action_full,
}


def list_repair_actions() -> list[dict[str, str]]:
    return [{'id': k, 'label': v} for k, v in REPAIR_ACTION_LABELS.items()]


def run_repair_action(
    action: str,
    *,
    actor_email: str = '',
    ip_address: str = '',
    skip_rate_limit: bool = False,
) -> dict[str, Any]:
    action = (action or '').strip().lower()
    if action not in REPAIR_HANDLERS:
        return {
            'status': 'error',
            'ok': False,
            'message': f'Geçersiz işlem: {action}',
            'allowed_actions': list(REPAIR_HANDLERS.keys()),
        }

    if not skip_rate_limit:
        allowed, wait_sec = check_rate_limit(action, actor_email)
        if not allowed:
            return {
                'status': 'error',
                'ok': False,
                'message': f'Çok sık denendi. {wait_sec} saniye sonra tekrar deneyin.',
                'retry_after_sec': wait_sec,
            }

    label = REPAIR_ACTION_LABELS.get(action, action)
    try:
        result = REPAIR_HANDLERS[action]()
        ok = bool(result.get('ok', True))
        summary = result.get('message') or (f'{label}: {"OK" if ok else "HATA"}')
        if not skip_rate_limit:
            _mark_rate_limit(action, actor_email)
        record_repair_run(
            action=action,
            actor_email=actor_email,
            ok=ok,
            summary=str(summary)[:500],
            report=result,
            ip_address=ip_address,
        )
        return {
            'status': 'ok' if ok else 'warning',
            'ok': ok,
            'action': action,
            'action_label': label,
            'message': summary,
            'report': _sanitize_report(result),
            'finished_at': timezone.now().isoformat(),
        }
    except Exception as exc:
        logger.warning('mail repair %s: %s', action, exc)
        record_repair_run(
            action=action,
            actor_email=actor_email,
            ok=False,
            summary=str(exc)[:500],
            report={'error': str(exc)},
            ip_address=ip_address,
        )
        return {
            'status': 'error',
            'ok': False,
            'action': action,
            'message': f'{label} başarısız: {exc}',
        }


def list_repair_history(*, limit: int = 20) -> list[dict[str, Any]]:
    try:
        from management.models import MailRepairRun

        rows = MailRepairRun.objects.order_by('-created_at')[: max(1, min(limit, 50))]
        return [
            {
                'id': r.id,
                'action': r.action,
                'action_label': REPAIR_ACTION_LABELS.get(r.action, r.action),
                'ok': r.ok,
                'summary': r.summary,
                'actor_email': r.actor_email,
                'ip_address': r.ip_address,
                'created_at': r.created_at.isoformat(),
            }
            for r in rows
        ]
    except Exception as exc:
        logger.debug('repair history: %s', exc)
        return []
