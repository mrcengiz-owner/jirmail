"""Türkçe doğal dil posta komutları — hızlı regex yolu + yürütme."""
from __future__ import annotations

import re
from typing import Any

from django.db.models import Q

_FOLDER_STD = {
    'gelen kutusu': 'INBOX',
    'gelen kutusuna': 'INBOX',
    'inbox': 'INBOX',
    'arşiv': 'Archive',
    'arsiv': 'Archive',
    'spam': 'Junk',
    'çöp': 'Trash',
    'cop': 'Trash',
    'taslaklar': 'Drafts',
    'gönderilen': 'Sent',
    'gonderilen': 'Sent',
}

# Gönderen + hedef klasör: "paribu maillerini finans klasörüne taşı"
_RE_MOVE_SENDER = re.compile(
    r'(?P<sender>.+?)\s+'
    r'(?:maillerini|mail(?:erini|leri)?|iletilerini|postalarını|e-?postalarını)\s+'
    r'(?P<target>.+?)\s+'
    r'(?:klasör(?:üne|e|une)|klasöre|folder(?:\'?a)?)\s+taşı',
    re.I,
)
# "... dan gelen mailleri finans klasörüne taşı"
_RE_MOVE_FROM = re.compile(
    r'(?P<sender>.+?)\s+(?:dan|den|\'dan|\'den)\s+'
    r'gel(?:en|diği)?\s+(?:mailleri|postaları|iletileri)\s+'
    r'(?P<target>.+?)\s+(?:klasör(?:üne|e)|klasöre)\s+taşı',
    re.I,
)
# Seçili mail: "bunu finans klasörüne taşı"
_RE_MOVE_SELECTED = re.compile(
    r'(?:bunu|seçili(?:yi| mail(?:i)?)?|bu\s+mail(?:i)?)\s+'
    r'(?P<target>.+?)\s+(?:klasör(?:üne|e)|klasöre)\s+taşı',
    re.I,
)
_RE_ARCHIVE_SEL = re.compile(
    r'(?:bunu|seçili(?:yi| mail(?:i)?)?|bu\s+mail(?:i)?)\s+arşivle',
    re.I,
)
_RE_SPAM_SEL = re.compile(
    r'(?:bunu|seçili(?:yi| mail(?:i)?)?|bu\s+mail(?:i)?)\s+spam(?:\'?a)?(?:\s+(?:at|yap|gönder))?',
    re.I,
)
_RE_CREATE_FOLDER = re.compile(
    r'(?:(?P<a>.+?)\s+klasör(?:ü|u)\s+(?:oluştur|aç|yarat|ekle)|'
    r'yeni\s+klasör\s+(?:aç|oluştur|ekle)\s*[:\-]?\s*(?P<b>.+))',
    re.I,
)
_RE_ORGANIZE = re.compile(
    r'(?:gelen\s+kutusunu|inbox(?:\'?u)?)\s+(?:düzenle|duzenle|organize\s*et|temizle|ayıkla)',
    re.I,
)
_RE_TRIAGE = re.compile(
    r'(?:gelen\s+kutusunu|inbox(?:\'?u)?)?\s*(?:sınıflandır|siniflandir|triage|kategorize\s*et)',
    re.I,
)
_RE_AGENT = re.compile(
    r'(?:tam\s+döngü|tam\s+dongu|ajan(?:ı|i)?\s+çalıştır|full\s+agent|postalarımı\s+yönet)',
    re.I,
)
_RE_RULE = re.compile(
    r'(?P<sender>.+?)\s+(?:maillerini|mail(?:erini|leri)?)\s+'
    r'(?:her\s+zaman|hep|otomatik(?:\s+olarak)?|bundan\s+sonra)\s+'
    r'(?P<target>.+?)\s+(?:klasör(?:üne|e)|klasöre)\s+(?:taşı|at|koy)',
    re.I,
)


def _clean(text: str) -> str:
    t = re.sub(r'\s+', ' ', (text or '').strip())
    return t.strip('"\'“”‘’.').strip()


def resolve_folder_label(account, label: str, *, create_if_missing: bool = False, password: str = '') -> str | None:
    """Kullanıcı etiketini IMAP klasör adına çöz."""
    from webmail.imap_client import create_imap_folder, folder_display_name, is_standard_folder_name
    from webmail.models import MailFolder

    raw = _clean(label)
    if not raw:
        return None
    low = raw.lower()
    if low in _FOLDER_STD:
        return _FOLDER_STD[low]
    if low.endswith(' klasörü') or low.endswith(' klasörune') or low.endswith(' klasörüne'):
        low = re.sub(r'\s+klasör(?:üne|u|e)?$', '', low).strip()

    rows = list(MailFolder.objects.filter(account=account).order_by('name'))
    for row in rows:
        disp = (row.display_name or folder_display_name(row.name)).lower()
        if row.name.lower() == low or disp == low:
            return row.name
        short = folder_display_name(row.name).lower()
        if short == low:
            return row.name
        if low in row.name.lower() or low in disp:
            return row.name

    if create_if_missing and password:
        try:
            return create_imap_folder(account, password, raw)
        except ValueError:
            return None
    return None


def find_messages_by_criteria(
    account,
    *,
    folder: str = 'INBOX',
    match_from: str = '',
    match_subject: str = '',
    limit: int = 50,
) -> list[tuple[int, str]]:
    """Eşleşen (uid, folder) listesi."""
    from webmail.imap_client import resolve_imap_folder
    from webmail.models import MailFolder, MailMessageCache

    folder_name = folder or 'INBOX'
    folder_obj = MailFolder.objects.filter(account=account, name__iexact=folder_name).first()
    if not folder_obj:
        folder_obj = MailFolder.objects.filter(account=account, name__icontains=folder_name).first()
    if not folder_obj:
        return []

    qs = MailMessageCache.objects.filter(folder=folder_obj, is_deleted=False).order_by('-date')
    mf = (match_from or '').strip().lower()
    ms = (match_subject or '').strip().lower()
    if mf:
        qs = qs.filter(
            Q(from_addr__icontains=mf)
            | Q(from_name__icontains=mf)
            | Q(snippet__icontains=mf)
        )
    if ms:
        qs = qs.filter(subject__icontains=ms)

    out = []
    for row in qs[:limit]:
        out.append((row.uid, folder_obj.name))
    return out


def batch_move_messages(account, password: str, action: dict[str, Any]) -> dict[str, Any]:
    from webmail.ai.agent import execute_imap_action

    match_from = (action.get('match_from') or '').strip()
    match_subject = (action.get('match_subject') or '').strip()
    folder = action.get('folder') or 'INBOX'
    target_label = action.get('move_to') or action.get('action_target') or ''
    limit = int(action.get('limit') or 50)
    create = bool(action.get('create_folder'))

    target = resolve_folder_label(account, target_label, create_if_missing=create, password=password)
    if not target:
        return {'success': False, 'message': f'Klasör bulunamadı: {target_label}'}

    pairs = find_messages_by_criteria(
        account,
        folder=folder,
        match_from=match_from,
        match_subject=match_subject,
        limit=limit,
    )
    if not pairs:
        return {'success': False, 'message': f'“{match_from or match_subject}” ile eşleşen mail yok.'}

    moved = 0
    errors = []
    for uid, src_folder in pairs:
        res = execute_imap_action(
            account,
            password,
            folder=src_folder,
            uid=uid,
            action_type='move_folder',
            action_target=target,
        )
        if res.get('success'):
            moved += 1
        else:
            errors.append(res.get('message') or 'hata')

    msg = f'{moved} mail “{target_label}” klasörüne taşındı.'
    if errors and moved == 0:
        return {'success': False, 'message': errors[0]}
    return {
        'success': True,
        'intent': 'batch_move',
        'message': msg,
        'moved': moved,
        'target': target,
    }


def parse_nl_command(message: str, context: dict | None = None) -> dict[str, Any] | None:
    """Türkçe komutu intent JSON'a çevir; eşleşme yoksa None."""
    ctx = context or {}
    text = (message or '').strip()
    if not text:
        return None
    low = text.lower()

    m = _RE_RULE.search(text)
    if m:
        sender = _clean(m.group('sender'))
        target = _clean(m.group('target'))
        return {
            'intent': 'create_rule',
            'rule_name': f'{sender} → {target}',
            'match_from': sender,
            'action_type': 'move_folder',
            'action_target': target,
            'move_to': target,
            'also_batch_move': True,
        }

    for pattern, kind in (
        (_RE_MOVE_SENDER, 'sender'),
        (_RE_MOVE_FROM, 'sender'),
    ):
        m = pattern.search(text)
        if m:
            sender = _clean(m.group('sender'))
            target = _clean(m.group('target'))
            action = {
                'intent': 'batch_move',
                'match_from': sender,
                'move_to': target,
                'action_target': target,
                'folder': ctx.get('selected_folder') or 'INBOX',
                'create_folder': True,
            }
            if 'otomatik' in low or 'hep' in low or 'her zaman' in low:
                action['also_create_rule'] = True
                action['rule_name'] = f'{sender} → {target}'
            return action

    m = _RE_MOVE_SELECTED.search(text)
    if m:
        target = _clean(m.group('target'))
        uid = int(ctx.get('selected_uid') or 0)
        if not uid:
            return {
                'intent': 'chat',
                'needs_selection': True,
                '_hint': 'move_selected',
                'move_to': target,
            }
        return {
            'intent': 'move',
            'uid': uid,
            'folder': ctx.get('selected_folder') or 'INBOX',
            'move_to': target,
            'action_target': target,
            'create_folder': True,
        }

    if _RE_ARCHIVE_SEL.search(text):
        uid = int(ctx.get('selected_uid') or 0)
        if not uid:
            return {'intent': 'chat', 'needs_selection': True, '_hint': 'archive'}
        return {'intent': 'archive', 'uid': uid, 'folder': ctx.get('selected_folder') or 'INBOX'}

    if _RE_SPAM_SEL.search(text):
        uid = int(ctx.get('selected_uid') or 0)
        if not uid:
            return {'intent': 'chat', 'needs_selection': True, '_hint': 'spam'}
        return {'intent': 'spam', 'uid': uid, 'folder': ctx.get('selected_folder') or 'INBOX'}

    m = _RE_CREATE_FOLDER.search(text)
    if m:
        name = _clean(m.group('a') or m.group('b') or '')
        if name:
            return {'intent': 'create_folder', 'name': name}

    if _RE_ORGANIZE.search(text):
        return {'intent': 'organize_inbox'}

    if _RE_TRIAGE.search(text) and 'özet' not in low:
        return {'intent': 'triage_inbox'}

    if _RE_AGENT.search(text):
        return {'intent': 'run_agent'}

    return None


def _selection_hint(hint: str, ctx: dict) -> str:
    if hint == 'move_selected' and ctx.get('move_to'):
        return f'Önce taşımak istediğiniz maili seçin, sonra “bunu {ctx["move_to"]} klasörüne taşı” deyin.'
    if hint == 'archive':
        return 'Arşivlemek için önce bir mail seçin.'
    if hint == 'spam':
        return 'Spam için önce bir mail seçin.'
    return 'Bu işlem için önce bir mail seçin.'


def try_nl_command(
    account,
    message: str,
    *,
    context: dict | None = None,
    password: str = '',
) -> dict[str, Any] | None:
    """Komutu tanı, mümkünse uygula; yanıt dict döndür."""
    from webmail.ai.service import execute_ai_action

    ctx = dict(context or {})
    action = parse_nl_command(message, ctx)
    if not action:
        return None

    if action.get('needs_selection'):
        hint = action.get('_hint') or ''
        reply = _selection_hint(hint, action)
        return {'handled': True, 'reply': reply, 'action': {'intent': 'chat'}}

    intent = (action.get('intent') or 'chat').lower()

    if intent == 'chat':
        return None

    if not password and intent not in ('chat', 'analyze'):
        return {
            'handled': True,
            'reply': 'Bu komut için oturum parolası gerekli — webmail’den yeniden giriş yapın.',
            'action': action,
        }

    # Klasör hedefini çöz (move / batch)
    if intent in ('move', 'batch_move') and action.get('create_folder'):
        label = action.get('move_to') or action.get('action_target') or ''
        resolved = resolve_folder_label(account, label, create_if_missing=True, password=password)
        if resolved:
            action['move_to'] = resolved
            action['action_target'] = resolved

    if intent == 'create_rule' and action.pop('also_batch_move', False):
        rule_res = execute_ai_action(account, password, action)
        batch = {
            'intent': 'batch_move',
            'match_from': action.get('match_from') or '',
            'move_to': action.get('action_target') or action.get('move_to') or '',
            'action_target': action.get('action_target') or '',
            'create_folder': True,
        }
        move_res = batch_move_messages(account, password, batch)
        parts = []
        if rule_res.get('success'):
            parts.append(rule_res.get('message') or 'Kural oluşturuldu.')
        if move_res.get('success'):
            parts.append(move_res.get('message') or '')
        reply = ' '.join(p for p in parts if p) or 'İşlem tamamlandı.'
        return {
            'handled': True,
            'reply': reply,
            'action': action,
            'executed': move_res if move_res.get('success') else rule_res,
        }

    if action.pop('also_create_rule', False):
        rule_action = {
            'intent': 'create_rule',
            'rule_name': action.get('rule_name') or f'{action.get("match_from")} kuralı',
            'match_from': action.get('match_from') or '',
            'action_type': 'move_folder',
            'action_target': action.get('move_to') or '',
        }
        execute_ai_action(account, password, rule_action)

    executed = execute_ai_action(account, password, action)
    reply = executed.get('message') or _default_reply(intent, action, executed)

    if not executed.get('success'):
        return {
            'handled': True,
            'reply': executed.get('message') or 'Komut uygulanamadı.',
            'action': action,
            'executed': executed,
        }

    return {
        'handled': True,
        'reply': reply,
        'action': action,
        'executed': executed,
    }


def _default_reply(intent: str, action: dict, executed: dict) -> str:
    if intent == 'organize_inbox':
        n = len(executed.get('applied') or [])
        q = len(executed.get('queued') or [])
        if n or q:
            return f'Gelen kutusu düzenlendi: {n} uygulandı, {q} onay kuyruğunda.'
        return 'Gelen kutusu incelendi — uygulanacak öneri bulunamadı.'
    if intent == 'triage_inbox':
        return f'{executed.get("triaged", 0)} mail sınıflandırıldı.'
    if intent == 'run_agent':
        return 'AI ajan döngüsü başlatıldı.'
    if intent == 'create_folder':
        return f'Klasör oluşturuldu: {executed.get("folder") or action.get("name")}'
    if intent == 'move':
        return 'Mail klasöre taşındı.'
    if intent == 'archive':
        return 'Mail arşive taşındı.'
    if intent == 'spam':
        return 'Mail spam klasörüne taşındı.'
    if intent == 'batch_move':
        return executed.get('message') or 'Mailler taşındı.'
    if intent == 'create_rule':
        return executed.get('message') or 'Kural kaydedildi.'
    return 'Tamamlandı.'
