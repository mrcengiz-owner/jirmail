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


def admin_panel_domain_issues() -> list[dict[str, str]]:
    """Panelde hesapsız veya sağlayıcı domain — gönderimi engellemez, yönetici uyarısı."""
    from core.models import MailDomain

    issues: list[dict[str, str]] = []
    for dom in MailDomain.objects.filter(is_active=True):
        name = normalize_domain(dom.name)
        if not name:
            continue
        if is_reserved_public_domain(name):
            issues.append(
                {
                    'domain': name,
                    'kind': 'reserved',
                    'message': (
                        f'"{name}" panelde kayıtlı (e-posta sağlayıcısı; silinmeli). '
                        'Alıcılara göndermek için domain eklemeniz gerekmez.'
                    ),
                    'fix': 'python manage.py fix_reserved_mail_domains',
                }
            )
            continue
        if not MailAccount.objects.filter(domain=dom, is_active=True).exists():
            issues.append(
                {
                    'domain': name,
                    'kind': 'orphan',
                    'message': f'"{name}" için aktif posta hesabı yok.',
                    'fix': (
                        f'Panel → Domainler → {name} → posta hesabı oluşturun '
                        'veya domaini pasifleştirin/silin.'
                    ),
                }
            )
    return issues


def admin_stale_domain_warnings() -> list[str]:
    return [item['message'] for item in admin_panel_domain_issues()]


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


_BOUNCE_HINTS = (
    ('remote-mta: dns; dovecot', (
        'Postfix Gmail/dış alıcıyı yerel Dovecot\'a yönlendirdi. '
        'Sunucuda: docker exec jir_postfix sh /docker-init.d/10-jirmail-inbound.sh && '
        'docker exec jir_postfix sh /docker-init.d/31-jirmail-transport-maps.sh && '
        'docker exec jir_django python manage.py fix_reserved_mail_domains'
    )),
    ('host dovecot[', (
        'Alıcı internet adresi (Gmail vb.) yanlışlıkla Dovecot\'a gitti — Postfix haritaları güncellenmeli. '
        'Webmail → bounce → Sunucu tanılaması çalıştır veya fix_reserved_mail_domains.'
    )),
    ('lmtp:inet:dovecot', (
        'Postfix dış alıcıyı yerel Dovecot\'a yönlendirdi — panelde gmail.com kayıtlı olabilir. '
        'python manage.py fix_reserved_mail_domains'
    )),
    ('lmtp:', 'Yerel LMTP teslimatı — alıcı domaini panelde yanlış kayıtlı olabilir (fix_reserved_mail_domains).'),
    ('network is unreachable', 'Sunucudan internete TCP çıkışı engelli. Sistem otomatik relay yapılandırmaya çalışır; .env içinde SMTP_RELAYHOST tanımlayın.'),
    ('connection timed out', 'Alıcı MX sunucusuna bağlanılamadı (port 25 engelli olabilir). SMTP relay otomatik uygulanır; yoksa .env ile tanımlayın.'),
    ('connection refused', 'Alıcı MX bağlantıyı reddetti — IP itibarı/PTR sorunu olabilir. SMTP relay önerilir.'),
    ('blocked using ', 'IP itibar listesinde — RBL engellemesi. Yeni IP veya kimliği doğrulanmış relay gerekir.'),
    ('client host rejected', 'Alıcı sunucu IP/PTR doğrulamasında reddetti. Reverse DNS (PTR) ve SPF/DKIM kayıtlarını ekleyin.'),
    ('access denied', 'Alıcı erişimi reddetti — RBL/SPF/DKIM kontrolü.'),
    ('user unknown', 'Alıcı adresi mevcut değil — adresi kontrol edin.'),
    ("user doesn't exist", 'Alıcı kutusu yok — adresi kontrol edin.'),
    ('mailbox unavailable', 'Alıcı kutusu kullanılamıyor.'),
    ('helo command rejected', 'EHLO/HELO kimliği reddedildi — mail hostname FQDN ve PTR olmalı.'),
    ('relay access denied', 'Relay engellendi — sunucu MX olarak tanınmıyor.'),
    ('does not resolve to an address', 'Mail hostname DNS\'te yok (A/AAAA).'),
    ('host or domain name not found', 'Alıcı domaininin MX kaydı çözülemedi.'),
    ('record not found', 'Alıcı domaininin MX kaydı yok.'),
    ('greylisted', 'Greylisting — birkaç dakika sonra otomatik yeniden denenecek.'),
    ('spam', 'Alıcı spam olarak işaretledi. SPF/DKIM/DMARC ve IP itibarı kontrol edin.'),
)


def _looks_like_bounce(text: str) -> bool:
    low = (text or '').lower()
    return (
        'undelivered mail' in low
        or 'returned to sender' in low
        or 'delivery status notification' in low
        or 'mail delivery failed' in low
        or 'failure notice' in low
        or 'this is the mail system at host' in low
    )


def parse_bounce_report(body_html: str, body_plain: str = '') -> dict:
    """Bounce gövdesini yapısal olarak ayrıştır.

    Döndürür: {is_bounce, recipient, status, action, diagnostic_code, mta, reason,
               suggested_fix, raw_excerpt}
    """
    import re

    text = body_plain or ''
    if not text.strip() and body_html:
        text = re.sub(r'<[^>]+>', ' ', body_html)
    text = text.replace('\r', '\n')

    if not _looks_like_bounce(text):
        return {'is_bounce': False}

    def first(pattern: str) -> str:
        m = re.search(pattern, text, re.IGNORECASE)
        return (m.group(1).strip() if m else '')[:500]

    recipient = first(r'Final-Recipient:\s*[^;]+;\s*([^\n]+)') or first(r'<([^>]+@[^>\s]+)>:')
    status = first(r'Status:\s*([0-9.]+)')
    action = first(r'Action:\s*([^\n]+)')
    diag = first(r'Diagnostic-Code:\s*([^\n]+(?:\n[ \t][^\n]+)*)')
    diag = re.sub(r'\s+', ' ', diag).strip()
    mta = first(r'Remote-MTA:\s*[^;]+;\s*([^\n]+)')

    said = first(r'said:\s*([^\n]+)')
    smtp_code = first(r'\b(5\d\d[ -]\d\.\d\.\d[^\n]*)') or first(r'\b(4\d\d[ -]\d\.\d\.\d[^\n]*)')

    reason = diag or said or smtp_code

    suggested = ''
    haystack = (diag + ' ' + said + ' ' + mta + ' ' + text).lower()
    for needle, fix in _BOUNCE_HINTS:
        if needle in haystack:
            suggested = fix
            break

    recip_low = (recipient or '').lower()
    if not suggested and 'dovecot' in haystack and (
        '@gmail.com' in recip_low
        or '@googlemail.com' in recip_low
        or '@outlook.com' in recip_low
        or '@proton.' in recip_low
    ):
        suggested = (
            'Dış alıcı (Gmail vb.) yerel Dovecot\'a yönlendirildi — Postfix pgsql haritaları hatalı. '
            'Sunucu tanılaması çalıştırın veya postfix init script\'lerini uygulayın.'
        )

    if not suggested and ("user doesn't exist" in haystack or 'user unknown' in haystack):
        if '@gmail.com' in recip_low or '@googlemail.com' in recip_low:
            suggested = (
                'Gmail adresine gönderim Dovecot üzerinden reddedilmiş olabilir (550). '
                'postmap -q gmail.com pgsql:/etc/postfix/pgsql-virtual-domains.cf boş olmalı.'
            )

    if not suggested and ('5.4.' in status or 'timed out' in haystack or 'unreachable' in haystack):
        suggested = (
            'Sunucudan dış MX sunuculara doğrudan erişim yok — büyük olasılıkla port 25 engelli. '
            'Kalıcı çözüm: SMTP_RELAYHOST ile gönderim relay\'i tanımlayın.'
        )

    # Ham özet — yapısal alanlar yoksa
    if not reason:
        for line in text.split('\n'):
            low = line.lower()
            if any(k in low for k in ('550', '553', '554', 'user unknown', 'mailbox', 'relay', 'refused', 'timed out')):
                reason = line.strip()[:500]
                break

    excerpt = ''
    # Postfix human-readable header bloku
    m = re.search(
        r'(This is the mail system at host[\s\S]+?(?:Action:|Diagnostic-Code:|Status:).+?)\n\n',
        text,
        re.IGNORECASE,
    )
    if m:
        excerpt = m.group(1).strip()[:2000]

    return {
        'is_bounce': True,
        'recipient': recipient,
        'status': status,
        'action': action,
        'diagnostic_code': diag,
        'mta': mta,
        'reason': reason or 'Alıcıya teslim edilemedi (ayrıntı çıkarılamadı).',
        'suggested_fix': suggested,
        'raw_excerpt': excerpt,
    }


def extract_bounce_summary(body_html: str, body_plain: str = '') -> str:
    """Geriye dönük tek satır özet."""
    report = parse_bounce_report(body_html, body_plain)
    if not report.get('is_bounce'):
        return ''
    bits = []
    if report.get('recipient'):
        bits.append(report['recipient'])
    if report.get('reason'):
        bits.append(report['reason'])
    return (' — '.join(bits))[:500] or 'Alıcıya teslim edilemedi.'
