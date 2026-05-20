"""Barındırılabilir domain kuralları — Gmail/Proton vb. yerel domain olamaz."""
from __future__ import annotations

# Bu alan adları bu sunucuda posta kutusu barındırmaz; panele eklenirse
# dış adreslere gönderim Dovecot LMTP'ye düşer ve bounce oluşur.
RESERVED_PUBLIC_DOMAINS: frozenset[str] = frozenset({
    'gmail.com', 'googlemail.com',
    'proton.me', 'protonmail.com', 'pm.me',
    'outlook.com', 'hotmail.com', 'live.com', 'msn.com',
    'yahoo.com', 'yahoo.com.tr', 'yandex.com', 'yandex.com.tr',
    'icloud.com', 'me.com', 'mac.com',
    'aol.com', 'zoho.com', 'mail.ru', 'gmx.com', 'gmx.net',
    'tutanota.com', 'tuta.io',
})


def normalize_domain(name: str) -> str:
    return (name or '').strip().lower().rstrip('.')


def is_reserved_public_domain(name: str) -> bool:
    return normalize_domain(name) in RESERVED_PUBLIC_DOMAINS


def domain_hosting_error(name: str) -> str | None:
    """Domain bu sunucuda barındırılamazsa Türkçe hata metni."""
    n = normalize_domain(name)
    if not n or '.' not in n:
        return 'Geçerli bir alan adı girin (ör. sirketim.com).'
    if is_reserved_public_domain(n):
        return (
            f'"{n}" harici bir e-posta sağlayıcısıdır; bu sunucuda barındırılamaz. '
            'Yalnızca size ait (DNS/MX bu sunucuya işaret eden) alan adlarını ekleyin. '
            'Dış adrese posta göndermek için alıcı adresini doğrudan yazmanız yeterlidir; '
            'domain listesine eklemeyin.'
        )
    return None
