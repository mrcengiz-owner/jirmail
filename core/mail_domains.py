"""Panel domain kuralları — yalnızca barındırdığınız alan adları.

Alıcı Gmail/Proton/Outlook vb. olsa bile domain listesine EKLENMEZ;
dış gönderim Postfix internet SMTP (veya SMTP_RELAYHOST) ile yapılır.
"""
from __future__ import annotations

# Yönetim paneline eklenmemesi gereken (başkasının) sağlayıcı domainleri
RESERVED_PUBLIC_DOMAINS: frozenset[str] = frozenset({
    'gmail.com', 'googlemail.com',
    'proton.me', 'protonmail.com', 'pm.me',
    'outlook.com', 'hotmail.com', 'live.com', 'msn.com',
    'yahoo.com', 'yahoo.com.tr', 'yandex.com', 'yandex.com.tr',
    'icloud.com', 'me.com', 'mac.com',
    'aol.com', 'zoho.com', 'mail.ru', 'gmx.com', 'gmx.net',
    'tutanota.com', 'tuta.io',
})


def reserved_domains_sql_in_list() -> str:
    """Postfix pgsql sorguları için 'a.com', 'b.com' listesi."""
    return ', '.join(f"'{d}'" for d in sorted(RESERVED_PUBLIC_DOMAINS))


def reserved_domains_sql_and(alias: str = 'd.name') -> str:
    return f"AND {alias} NOT IN ({reserved_domains_sql_in_list()})"


# Postfix pgsql: yalnızca en az bir aktif posta hesabı olan domainler yerel (LMTP)
HOSTED_DOMAIN_SQL = (
    'SELECT 1 FROM core_maildomain d '
    'INNER JOIN core_mailaccount a ON a.domain_id = d.id AND a.is_active = true '
    "WHERE d.is_active = true AND d.name='%s' "
    f"{reserved_domains_sql_and('d.name')} LIMIT 1"
)

HOSTED_DOMAIN_TRANSPORT_SQL = (
    "SELECT 'lmtp:inet:dovecot:24' FROM core_maildomain d "
    'INNER JOIN core_mailaccount a ON a.domain_id = d.id AND a.is_active = true '
    f"WHERE d.is_active = true AND d.name='%d' {reserved_domains_sql_and('d.name')} LIMIT 1"
)


HOSTED_DOMAIN_NAMES_SQL = (
    'SELECT DISTINCT d.name FROM core_maildomain d '
    'INNER JOIN core_mailaccount a ON a.domain_id = d.id AND a.is_active = true '
    'WHERE d.is_active = true'
)


def normalize_domain(name: str) -> str:
    return (name or '').strip().lower().rstrip('.')


def is_reserved_public_domain(name: str) -> bool:
    return normalize_domain(name) in RESERVED_PUBLIC_DOMAINS


def domain_hosting_error(name: str) -> str | None:
    """Panelde yeni domain eklerken — alıcı domaini değil, barındırma domaini."""
    n = normalize_domain(name)
    if not n or '.' not in n:
        return 'Geçerli bir alan adı girin (ör. sirketim.com).'
    if is_reserved_public_domain(n):
        return (
            f'"{n}" bir e-posta sağlayıcısıdır; buraya eklenmez. '
            'Panele yalnızca DNS/MX kayıtlarını bu sunucuya yönlendirdiğiniz '
            'kendi alan adınızı ekleyin (ör. sirketim.com). '
            'Kullanıcılarınız @sirketim.com adresleriyle gönderir; alıcı @gmail.com, '
            '@proton.me vb. olabilir — alıcı domainini eklemeniz gerekmez.'
        )
    return None


def queryset_hosted_domains():
    """Aktif hesabı olan domainler (Django)."""
    from core.models import MailAccount, MailDomain

    return MailDomain.objects.filter(
        is_active=True,
        mailaccount__is_active=True,
    ).distinct()


def hosted_domain_names() -> set[str]:
    return {
        normalize_domain(n)
        for n in queryset_hosted_domains().values_list('name', flat=True)
        if n and not is_reserved_public_domain(n)
    }
