"""AI onay kuyruğu — assist modunda aksiyonlar buraya düşer."""
from __future__ import annotations

from typing import Any

from django.utils import timezone

_RISKY = frozenset({'spam', 'delete', 'move_folder'})


def is_risky_action(action_type: str) -> bool:
    return (action_type or '').lower() in _RISKY


def create_pending_action(
    account,
    *,
    uid: int,
    folder: str,
    action_type: str,
    action_target: str = '',
    subject: str = '',
    from_addr: str = '',
    reason: str = '',
    source: str = 'ai',
) -> dict[str, Any]:
    from webmail.models import MailAiPendingAction

    existing = MailAiPendingAction.objects.filter(
        account=account,
        uid=uid,
        folder=folder,
        status=MailAiPendingAction.STATUS_PENDING,
    ).first()
    if existing:
        return {'success': True, 'id': existing.id, 'duplicate': True}

    row = MailAiPendingAction.objects.create(
        account=account,
        uid=uid,
        folder=folder,
        action_type=action_type,
        action_target=action_target,
        subject=subject[:998],
        from_addr=from_addr[:500],
        reason=reason[:2000],
        source=source,
    )
    from webmail.sse import publish_approval_update

    publish_approval_update(account.id, 'pending_created', {'id': row.id})
    return {'success': True, 'id': row.id}


def list_pending_actions(account, *, limit: int = 30) -> dict[str, Any]:
    from webmail.models import MailAiPendingAction

    rows = MailAiPendingAction.objects.filter(
        account=account,
        status=MailAiPendingAction.STATUS_PENDING,
    ).order_by('-created_at')[:limit]
    return {
        'success': True,
        'items': [_action_dict(r) for r in rows],
        'total': rows.count() if hasattr(rows, 'count') else len(list(rows)),
    }


def _action_dict(row) -> dict:
    return {
        'id': row.id,
        'uid': row.uid,
        'folder': row.folder,
        'action_type': row.action_type,
        'action_target': row.action_target,
        'subject': row.subject,
        'from_addr': row.from_addr,
        'reason': row.reason,
        'source': row.source,
        'status': row.status,
        'created_at': row.created_at.isoformat(),
    }


def approve_action(account, password: str, action_id: int) -> dict[str, Any]:
    from webmail.ai.agent import execute_imap_action
    from webmail.models import MailAiPendingAction

    row = MailAiPendingAction.objects.filter(
        account=account,
        pk=action_id,
        status=MailAiPendingAction.STATUS_PENDING,
    ).first()
    if not row:
        return {'success': False, 'message': 'Onay kaydı bulunamadı'}

    if not password:
        return {'success': False, 'message': 'Oturum parolası yok.'}

    res = execute_imap_action(
        account,
        password,
        folder=row.folder,
        uid=row.uid,
        action_type=row.action_type,
        action_target=row.action_target,
    )
    if not res.get('success'):
        return res

    row.status = MailAiPendingAction.STATUS_APPLIED
    row.resolved_at = timezone.now()
    row.save(update_fields=['status', 'resolved_at'])

    from webmail.sse import publish_approval_update

    publish_approval_update(account.id, 'pending_resolved', {'id': row.id, 'status': row.status})
    return {'success': True, 'message': 'Aksiyon uygulandı.', 'action': _action_dict(row)}


def reject_action(account, action_id: int) -> dict[str, Any]:
    from webmail.models import MailAiPendingAction

    row = MailAiPendingAction.objects.filter(
        account=account,
        pk=action_id,
        status=MailAiPendingAction.STATUS_PENDING,
    ).first()
    if not row:
        return {'success': False, 'message': 'Kayıt bulunamadı'}

    row.status = MailAiPendingAction.STATUS_REJECTED
    row.resolved_at = timezone.now()
    row.save(update_fields=['status', 'resolved_at'])

    from webmail.sse import publish_approval_update

    publish_approval_update(account.id, 'pending_resolved', {'id': row.id, 'status': row.status})
    return {'success': True, 'message': 'Reddedildi.'}


def agent_stats(account) -> dict[str, Any]:
    from webmail.ai.reply import list_needs_reply
    from webmail.models import MailAiPendingAction, MailFolder, MailMessageCache

    pending = MailAiPendingAction.objects.filter(
        account=account,
        status=MailAiPendingAction.STATUS_PENDING,
    ).count()
    nr = list_needs_reply(account, limit=50)
    triaged = 0
    inbox = MailFolder.objects.filter(account=account, name__iexact='INBOX').first()
    if inbox:
        for row in MailMessageCache.objects.filter(folder=inbox, is_deleted=False)[:200]:
            ai = row.ai_meta if isinstance(row.ai_meta, dict) else {}
            if ai.get('triaged_at'):
                triaged += 1
    return {
        'success': True,
        'pending_approvals': pending,
        'needs_reply': nr.get('total', 0),
        'triaged_in_cache': triaged,
    }
