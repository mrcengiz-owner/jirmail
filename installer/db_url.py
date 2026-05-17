"""PostgreSQL bağlantı URL'si — ortam veya Django settings."""
from __future__ import annotations

import os
from urllib.parse import quote_plus


def resolve_database_url() -> str:
    """DATABASE_URL ortamı yoksa Django DATABASES['default'] ile üret."""
    url = (os.getenv('DATABASE_URL') or '').strip()
    if url:
        return url

    try:
        from django.conf import settings

        db = settings.DATABASES.get('default') or {}
        engine = (db.get('ENGINE') or '').lower()
        if 'postgresql' not in engine and 'postgis' not in engine:
            raise RuntimeError(
                'PostgreSQL gerekli. Ortama DATABASE_URL ekleyin veya Django DATABASES ayarlayın.'
            )
        user = quote_plus(str(db.get('USER') or ''))
        password = quote_plus(str(db.get('PASSWORD') or ''))
        host = str(db.get('HOST') or 'localhost').strip()
        port = int(db.get('PORT') or 5432)
        name = str(db.get('NAME') or '').strip()
        if not name:
            raise RuntimeError('Veritabanı adı (NAME) boş.')
        return f'postgres://{user}:{password}@{host}:{port}/{name}'
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f'DATABASE_URL çözülemedi: {exc}') from exc


def has_database_url() -> bool:
    """Mail stack için kullanılabilir DB bağlantısı var mı."""
    if (os.getenv('DATABASE_URL') or '').strip():
        return True
    try:
        resolve_database_url()
        return True
    except Exception:
        return False
