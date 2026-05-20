"""Gönderim öncesi alıcı ve rol doğrulaması."""
from __future__ import annotations

from django.conf import settings

from core.mail_domains import domain_hosting_error, is_reserved_public_domain, normalize_domain
from core.models import MailAccount, MailDomain, MailRole
from webmail.recipients import parse_recipient_list


def active_local_domains() -> set[str]:
    """Sunucuda gerçekten barındırılan domainler (harici sağlayıcılar hariç)."""
    names = set(
        MailDomain.objects.filter(is_active=True).values_list('name', flat=True)
    )
    extra = (getattr(settings, 'MAIL_DOMAIN', '') or '').strip().lower()
    if extra:
        names.add(extra.lower())
    return {
        normalize_domain(n)
        for n in names
        if n and not is_reserved_public_domain(n)
    }


def misconfigured_hosted_domains() -> list[str]:
    """Panelde yanlışlıkla eklenmiş harici sağlayıcı domainleri."""
    return sorted(
        normalize_domain(n)
        for n in MailDomain.objects.filter(is_active=True).values_list('name', flat=True)
        if n and is_reserved_public_domain(n)
    )


def _domain_of(email: str) -> str:
    return email.rsplit('@', 1)[-1].lower()


def validate_outbound_recipients(account, raw_to: str, raw_cc: str = '', raw_bcc: str = '') -> dict:
    """Gönderimden önce alıcıları kontrol et.

    Returns: {ok: bool, message: str, invalid: list[str], warnings: list[str]}
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

    misconfigured = misconfigured_hosted_domains()
    if misconfigured:
        return {
            'ok': False,
            'message': (
                'Posta sunucusu yanlış yapılandırılmış: panelde harici sağlayıcı domain(ler) '
                f'kayıtlı ({", ".join(misconfigured[:3])}). '
                'Yönetim → Domainler bölümünden bu kayıtları silin veya pasifleştirin; '
                'ardından `docker exec jir_postfix sh /docker-init.d/31-jirmail-transport-maps.sh` çalıştırın.'
            ),
            'invalid': [],
            'warnings': [],
            'misconfigured_domains': misconfigured,
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
                f'Yerel posta kutusu bulunamadı: {sample}{more}. '
                'Yönetim panelinden hesabın aktif olduğunu doğrulayın.'
            ),
            'invalid': invalid,
            'warnings': [],
        }

    external = [a for a in recipients if _domain_of(a) not in local_domains]
    if external:
        relay = (getattr(settings, 'SMTP_RELAYHOST', '') or '').strip()
        if not relay:
            warnings.append(
                'Dış adrese gönderim yapıyorsunuz. Sunucuda çıkış portu (25) kapalıysa '
                'birkaç dakika içinde “Undelivered Mail” geri dönüşü alabilirsiniz. '
                'Kalıcı çözüm: .env içinde SMTP_RELAYHOST (ör. [smtp.provider.com]:587) tanımlayın.'
            )

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
        if "user doesn't exist" in low and '@' in low:
            return (
                line.strip()[:500]
                + ' — Bu adres sunucuda yerel kutu olarak arandı. Panelde harici domain '
                '(ör. proton.me) yanlışlıkla eklenmiş olabilir; domaini silin ve dış adrese tekrar gönderin.'
            )
        if any(k in low for k in ('550', '553', '554', 'user unknown', 'mailbox', 'relay', 'refused', 'timed out')):
            return line.strip()[:500]

    return 'Alıcıya teslim edilemedi. Tam hata metni aşağıdaki iletide yer alır.'
