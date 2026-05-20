"""Gönderim öncesi alıcı ve rol doğrulaması."""
from __future__ import annotations

from django.conf import settings

from core.mail_domains import hosted_domain_names, is_reserved_public_domain, normalize_domain
from core.models import MailAccount, MailRole
from webmail.recipients import parse_recipient_list


def active_local_domains() -> set[str]:
    """Bu sunucuda posta kutusu barındırılan domainler (hesabı olanlar)."""
    names = hosted_domain_names()
    extra = (getattr(settings, 'MAIL_DOMAIN', '') or '').strip().lower()
    if extra and not is_reserved_public_domain(extra):
        names.add(normalize_domain(extra))
    return names


def admin_stale_domain_warnings() -> list[str]:
    """Panelde hesapsız veya sağlayıcı domain — gönderimi engellemez, yönetici uyarısı."""
    from core.models import MailDomain

    warnings: list[str] = []
    for dom in MailDomain.objects.filter(is_active=True):
        name = normalize_domain(dom.name)
        if not name:
            continue
        if is_reserved_public_domain(name):
            warnings.append(
                f'"{name}" panelde kayıtlı (e-posta sağlayıcısı; silinmeli). '
                'Alıcılara göndermek için domain eklemeniz gerekmez.'
            )
            continue
        if not MailAccount.objects.filter(domain=dom, is_active=True).exists():
            warnings.append(f'"{name}" için aktif posta hesabı yok.')
    return warnings


def _domain_of(email: str) -> str:
    return email.rsplit('@', 1)[-1].lower()


def validate_outbound_recipients(account, raw_to: str, raw_cc: str = '', raw_bcc: str = '') -> dict:
    """Gönderimden önce alıcıları kontrol et.

    Dünya genelindeki alıcılara izin verilir; yalnızca bu sunucuda barındırılan
    @domain adresleri için yerel kutu doğrulanır.
    """
    perms = account.permissions_summary()
    if not perms.get('can_send_mail'):
        return {
            'ok': False,
            'message': 'Bu hesabın gönderim yetkisi yok (yalnızca alma rolü).',
            'invalid': [],
            'warnings': [],
        }

    recipients = parse_recipient_list(raw_to)
    recipients.extend(parse_recipient_list(raw_cc))
    recipients.extend(parse_recipient_list(raw_bcc))

    if not recipients:
        return {
            'ok': False,
            'message': 'Geçerli en az bir alıcı gerekli (ör. isim@alanadi.com).',
            'invalid': [],
            'warnings': [],
        }

    local_domains = active_local_domains()
    warnings: list[str] = []
    invalid: list[str] = []

    if account.role == MailRole.EXTERNAL_BLOCK:
        for addr in recipients:
            if _domain_of(addr) not in local_domains:
                invalid.append(addr)
        if invalid:
            return {
                'ok': False,
                'message': (
                    'Bu hesap yalnızca şirket içi adreslere gönderebilir. '
                    f'Dış alıcı: {", ".join(invalid[:3])}'
                ),
                'invalid': invalid,
                'warnings': [],
            }

    if local_domains:
        local_addrs = [a for a in recipients if _domain_of(a) in local_domains]
        if local_addrs:
            existing = set(
                MailAccount.objects.filter(
                    is_active=True,
                    email__in=local_addrs,
                ).values_list('email', flat=True)
            )
            existing_lower = {e.lower() for e in existing}
            for addr in local_addrs:
                if addr.lower() not in existing_lower:
                    invalid.append(addr)

    if invalid:
        sample = ', '.join(invalid[:3])
        more = f' (+{len(invalid) - 3})' if len(invalid) > 3 else ''
        return {
            'ok': False,
            'message': (
                f'Bu sunucudaki posta kutusu bulunamadı: {sample}{more}. '
                'Yalnızca panelde oluşturduğunuz @alanadiniz.com hesaplarına yerel teslimat yapılır.'
            ),
            'invalid': invalid,
            'warnings': [],
        }

    return {'ok': True, 'message': '', 'invalid': [], 'warnings': warnings}


def extract_bounce_summary(body_html: str, body_plain: str = '') -> str:
    """Bounce gövdesinden kısa Türkçe özet çıkar."""
    import re

    text = body_plain or ''
    if not text.strip() and body_html:
        text = re.sub(r'<[^>]+>', ' ', body_html)
    text = text.replace('\r', '\n')
    if 'undelivered' not in text.lower() and 'returned to sender' not in text.lower():
        return ''

    patterns = [
        r'Diagnostic-Code:\s*([^\n]+)',
        r'Status:\s*([^\n]+)',
        r' said:\s*([^\n]+)',
        r'<([^>]+@[^>]+)>:\s*([^\n]+)',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            line = ' '.join(g.strip() for g in m.groups() if g).strip()
            if line and len(line) > 8:
                return line[:500]

    for line in text.split('\n'):
        low = line.lower()
        if any(k in low for k in ('550', '553', '554', 'user unknown', 'mailbox', 'relay', 'refused', 'timed out')):
            return line.strip()[:500]

    return 'Alıcıya teslim edilemedi. Tam hata metni aşağıdaki iletide yer alır.'
