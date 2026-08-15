"""Oturumda hassas alanların şifrelenmesi (mail_password vb.)."""
from __future__ import annotations

import base64
import hashlib
import time
from typing import Any

from django.conf import settings


def _fernet():
    from cryptography.fernet import Fernet

    digest = hashlib.sha256(settings.SECRET_KEY.encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode('utf-8')).decode('ascii')


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode('ascii')).decode('utf-8')


def mail_password_ttl_seconds() -> int:
    return int(getattr(settings, 'MAIL_PASSWORD_SESSION_TTL', 14400) or 14400)


def store_mail_password(session: Any, password: str) -> None:
    """Düz metin yerine şifreli + zaman damgası; eski anahtarı sil."""
    session['mail_password_enc'] = encrypt_secret(password)
    session['mail_password_at'] = time.time()
    if 'mail_password' in session:
        del session['mail_password']


def get_mail_password(session: Any) -> str:
    """
    IMAP/SMTP için parola.
    TTL dolmuşsa boş döner (yeniden giriş gerekir).
    Eski düz metin anahtarı bir kez okunup şifrelenir (geçiş).
    """
    ttl = mail_password_ttl_seconds()
    stamped = session.get('mail_password_at')
    if stamped is not None:
        try:
            if time.time() - float(stamped) > ttl:
                clear_mail_password(session)
                return ''
        except (TypeError, ValueError):
            clear_mail_password(session)
            return ''

    enc = session.get('mail_password_enc')
    if enc:
        try:
            return decrypt_secret(str(enc))
        except Exception:
            clear_mail_password(session)
            return ''

    # Geçiş: eski plaintext
    legacy = session.get('mail_password')
    if legacy:
        try:
            store_mail_password(session, str(legacy))
            session.modified = True
            return str(legacy)
        except Exception:
            clear_mail_password(session)
            return ''
    return ''


def clear_mail_password(session: Any) -> None:
    for key in ('mail_password', 'mail_password_enc', 'mail_password_at'):
        if key in session:
            del session[key]
