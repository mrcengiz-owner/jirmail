"""Gönderen başlık ayrıştırma ve sahte gönderen (spoof) tespiti."""
from __future__ import annotations

from email.header import decode_header, make_header
from email.utils import parseaddr, getaddresses

# Bilinen dolandırıcılık kalıpları (içerik / konu)
_SCAM_BODY_MARKERS = (
    'remote administration tool',
    'private trojan',
    'i recorded you',
    'masturbating',
    'bitcoin (btc)',
    'wallet address',
    'some bad news for you',
    'infected with my',
)
_SCAM_SUBJECT_MARKERS = (
    'urgent',
    'account suspended',
    'verify your account',
)


def _decode_header(value: str) -> str:
    if not value:
        return ''
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value).strip()


def parse_address_field(raw: str) -> tuple[str, str]:
    """Tek From/Sender satırından (ad, e-posta) döner."""
    name, addr = parseaddr(raw or '')
    return _decode_header(name), (addr or '').strip().lower()


def parse_all_addresses(raw: str) -> list[tuple[str, str]]:
    if not raw:
        return []
    out = []
    for name, addr in getaddresses([raw]):
        email = (addr or '').strip().lower()
        if email:
            out.append((_decode_header(name), email))
    return out


def format_sender_display(name: str, email: str) -> str:
    email = (email or '').strip()
    name = (name or '').strip()
    if name and email and name.lower() != email.lower():
        return f'{name} <{email}>'
    return email or name or 'Bilinmeyen gönderen'


def _normalize_email(email: str) -> str:
    return (email or '').strip().lower()


def _account_matches(email: str, account_email: str) -> bool:
    if not email or not account_email:
        return False
    a = _normalize_email(account_email)
    e = _normalize_email(email)
    if e == a:
        return True
    # local@domain vs domain eşleşmesi
    if '@' in a and '@' in e:
        return e.split('@', 1)[1] == a.split('@', 1)[1] and e.split('@')[0] in ('mailer-daemon', 'postmaster')
    return False


def build_sender_info(
    *,
    from_raw: str = '',
    sender_raw: str = '',
    reply_to_raw: str = '',
    return_path_raw: str = '',
    account_email: str = '',
    is_inbound: bool = True,
    subject: str = '',
    snippet: str = '',
) -> dict:
    """
    IMAP / RFC822 başlıklarından gönderen özeti.

    is_inbound: Gelen kutusu vb. — From alanı hesap adresiyle aynıysa spoof uyarısı.
    """
    from_name, from_email = parse_address_field(from_raw)
    sender_name, sender_email = parse_address_field(sender_raw)
    _, reply_to = parse_address_field(reply_to_raw)
    _, return_path = parse_address_field(return_path_raw)

    # Gerçek kaynak: Return-Path > Sender > From
    real_email = return_path or sender_email or from_email
    real_name = sender_name or from_name

    is_spoofed = False
    warning = None

    if is_inbound and from_email:
        if _account_matches(from_email, account_email):
            is_spoofed = True
            warning = (
                'Bu ileti sizin e-posta adresinizden gönderilmiş gibi görünüyor. '
                'Gelen kutusuna dışarıdan gelen sahte (spoof) posta olabilir — yanıtlamayın, '
                'Bitcoin veya ödeme taleplerine güvenmeyin.'
            )
        elif sender_email and sender_email != from_email:
            is_spoofed = True
            warning = (
                f'Görünen gönderen ({from_email}) ile teknik gönderen ({sender_email}) farklı.'
            )
        elif return_path and return_path != from_email:
            is_spoofed = True
            warning = (
                f'Görünen gönderen ({from_email}) ile posta yolu ({return_path}) uyuşmuyor.'
            )

    is_probable_scam = False
    blob = f'{subject}\n{snippet}'.lower()
    if any(m in blob for m in _SCAM_BODY_MARKERS) or any(m in subject.lower() for m in _SCAM_SUBJECT_MARKERS):
        is_probable_scam = True
        if not warning:
            warning = 'Bu mesaj bilinen dolandırıcılık kalıplarına benziyor.'

    return {
        'from_name': from_name,
        'from_email': from_email,
        'sender_email': sender_email or None,
        'reply_to': reply_to or None,
        'return_path': return_path or None,
        'real_email': real_email or from_email,
        'real_name': real_name,
        'display': format_sender_display(from_name, from_email),
        'real_display': format_sender_display(real_name, real_email),
        'is_spoofed': is_spoofed,
        'is_probable_scam': is_probable_scam,
        'warning': warning,
    }


def sender_info_from_message(msg, account_email: str, *, is_inbound: bool = True) -> dict:
    """email.message.Message nesnesinden gönderen bilgisi."""
    subject = _decode_header(msg.get('Subject', '') or '')
    snippet = (msg.get('Subject', '') or '')[:200]
    return build_sender_info(
        from_raw=msg.get('From', '') or '',
        sender_raw=msg.get('Sender', '') or '',
        reply_to_raw=msg.get('Reply-To', '') or '',
        return_path_raw=msg.get('Return-Path', '') or '',
        account_email=account_email,
        is_inbound=is_inbound,
        subject=subject,
        snippet=snippet,
    )


def sender_info_from_imap_headers(raw_headers: bytes, account_email: str, *, is_inbound: bool = True) -> dict:
    import email
    if not raw_headers:
        return build_sender_info(account_email=account_email, is_inbound=is_inbound)
    msg = email.message_from_bytes(raw_headers.rstrip() + b'\r\n\r\n')
    return sender_info_from_message(msg, account_email, is_inbound=is_inbound)


def sender_info_from_cache_row(row, account_email: str, *, is_inbound: bool = True) -> dict:
    """DB satırı + sender_meta JSON."""
    meta = getattr(row, 'sender_meta', None) or {}
    if isinstance(meta, dict) and meta.get('from_email'):
        info = dict(meta)
        info.setdefault(
            'display',
            format_sender_display(info.get('from_name', ''), info.get('from_email', '')),
        )
        info.setdefault('real_display', format_sender_display(
            info.get('real_name', ''), info.get('real_email', ''),
        ))
        return info
    from_raw = row.from_addr or ''
    if row.from_name and row.from_addr:
        from_raw = f'{row.from_name} <{row.from_addr}>'
    elif row.from_name:
        from_raw = row.from_name
    return build_sender_info(
        from_raw=from_raw,
        account_email=account_email,
        is_inbound=is_inbound,
        subject=row.subject or '',
        snippet=row.snippet or '',
    )
