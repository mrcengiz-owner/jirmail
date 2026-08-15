"""
Django settings for Jîr-Mail project.

Single Source of Truth: SystemConfig model (veritabanı)
Dynamic Service Discovery: Docker servis adları otomatik tespit edilir.
"""

import dotenv
from pathlib import Path
import os
import socket
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
dotenv.load_dotenv(BASE_DIR / '.env')

DEBUG = os.getenv('DEBUG', 'False').lower() in ('true', '1', 'yes')

_secret = (os.getenv('SECRET_KEY') or '').strip()
if not _secret:
    if DEBUG:
        _secret = 'django-insecure-dev-only-do-not-use-in-production'
    else:
        raise ImproperlyConfigured(
            'SECRET_KEY ortam değişkeni zorunludur (production).'
        )
SECRET_KEY = _secret

# ─── Dynamic Service Discovery ────────────────────────────────────────────────
# Docker içinde /.dockerenv dosyası bulunur; servis adları hostname olarak çözülür
IN_DOCKER = os.path.exists('/.dockerenv') or os.getenv('DOCKER_CONTAINER', '') == 'true'

def _resolve_service(docker_name: str, local_fallback: str) -> str:
    """Docker servis adını DNS ile çöz; başarısız olursa local fallback kullan."""
    if IN_DOCKER:
        try:
            socket.getaddrinfo(docker_name, None)
            return docker_name
        except socket.gaierror:
            pass
    return os.getenv(docker_name.upper() + '_HOST', local_fallback)

# Servis hostname'leri — Docker'da otomatik çözülür, lokalde env var veya fallback
REDIS_HOST    = os.getenv('REDIS_HOST',    _resolve_service('redis',    '127.0.0.1'))
POSTGRES_HOST = os.getenv('POSTGRES_HOST', _resolve_service('postgres', '127.0.0.1'))


def _resolve_mail_service_host(service_key: str, docker_default: str) -> str:
    """SMTP/IMAP: Docker ağında konteyner adı; host'ta `runserver` için localhost.

    `jir_postfix` / `jir_dovecot` yalnızca Docker DNS'te çözülür; host'tan
    bağlanırken [Errno -3] Temporary failure in name resolution oluşur.
    """
    env_primary = {'postfix': 'SMTP_HOST', 'dovecot': 'IMAP_HOST'}
    env_local = {'postfix': 'POSTFIX_SMTP_HOST', 'dovecot': 'DOVECOT_IMAP_HOST'}

    primary = os.getenv(env_primary.get(service_key, ''), '').strip()
    if primary:
        return primary

    if not IN_DOCKER:
        local = os.getenv(env_local.get(service_key, ''), '').strip()
        if local:
            return local
        return '127.0.0.1'

    try:
        from management.docker_containers import merged_container_name

        resolved = merged_container_name(service_key)
        if resolved:
            return resolved
    except Exception:
        pass
    return docker_default


# ──────────────────────────────────────────────────────────────────────────────

ALLOWED_HOSTS = [
    h.strip()
    for h in (os.getenv('ALLOWED_HOSTS', '*') or '*').split(',')
    if h.strip()
] or ['*']
# Üretimde ALLOWED_HOSTS=mail.ornek.com şeklinde daraltın; '*' yalnızca Traefik/PaaS uyumu için varsayılan.


def _origin_from_url(url: str) -> str | None:
    url = (url or '').strip()
    if not url:
        return None
    if not url.startswith(('http://', 'https://')):
        url = f'https://{url}'
    try:
        from urllib.parse import urlparse
        p = urlparse(url)
        if p.scheme and p.netloc:
            return f'{p.scheme}://{p.netloc}'
    except Exception:
        pass
    return None


def _build_trusted_origins() -> list[str]:
    """Traefik / Dokploy HTTPS — CSRF 403 önleme."""
    origins: list[str] = []
    seen: set[str] = set()

    def add(o: str | None) -> None:
        if not o or o in seen:
            return
        seen.add(o)
        origins.append(o)

    for item in (
        'http://localhost:3000',
        'http://localhost:8000',
        'http://127.0.0.1:3000',
        'http://127.0.0.1:8000',
        'http://0.0.0.0:3000',
        'http://0.0.0.0:8000',
    ):
        add(item)

    env_csv = os.getenv('CSRF_TRUSTED_ORIGINS', '') or os.getenv('CORS_ALLOWED_ORIGINS', '')
    for part in env_csv.replace(';', ',').split(','):
        add(_origin_from_url(part.strip()))

    for env_name in (
        'PUBLIC_URL',
        'SITE_URL',
        'APP_URL',
        'COOLIFY_FQDN',
        'COOLIFY_URL',
        'DOKPLOY_APP_URL',
        'TRAEFIK_HOST',
    ):
        raw = os.getenv(env_name, '').strip()
        if raw:
            add(_origin_from_url(raw))
            if not raw.startswith(('http://', 'https://')):
                add(f'https://{raw.split("/")[0]}')
                add(f'http://{raw.split("/")[0]}')

    mail_host = os.getenv('MAIL_HOSTNAME', '').strip()
    mail_domain = os.getenv('MAIL_DOMAIN', '').strip()
    for host in (mail_host, f'mail.{mail_domain}' if mail_domain else ''):
        if host and '.' in host:
            add(f'https://{host}')
            add(f'http://{host}')

    return origins


_TRUSTED_ORIGINS = _build_trusted_origins()


def _get_installation_status():
    """
    SystemConfig tablosundan is_installed durumunu al.
    Database bağlantısı kurulabilirse sorgula, yoksa False döndür.
    """
    try:
        from django.db import connection
        connection.ensure_connection()
        from saas.models import SystemConfig
        config = SystemConfig.objects.first()
        return config and config.is_installed
    except Exception:
        return False

class _InstallStatus:
    """
    Lazy loading installation status from database.
    Avoids database calls at import time.
    """
    _installed = None

    @property
    def INSTALLED(self):
        if self._installed is None:
            self._installed = _get_installation_status()
        return self._installed

    def refresh(self):
        """Force refresh of installation status from database."""
        self._installed = _get_installation_status()
        return self._installed

_install_status = _InstallStatus()

def get_installed_status():
    """Public function to check installation status."""
    return _install_status.INSTALLED

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'management',
    'saas',
    'core',
    'backup',
    'alerts',
    'installer',
    'webmail',
    'monitoring',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'jir_core.middleware.JirInstallMiddleware',
]

CORS_ALLOWED_ORIGINS = _TRUSTED_ORIGINS
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = _TRUSTED_ORIGINS

# Traefik / Dokploy arkasında HTTPS
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'

if DEBUG:
    CSRF_COOKIE_SECURE = False
    SESSION_COOKIE_SECURE = False
else:
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
    # HSTS: genelde Traefik/CDN yönetir; açıkça istenirse açın
    SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '0') or 0)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv('SECURE_HSTS_INCLUDE_SUBDOMAINS', 'false').lower() in (
        '1', 'true', 'yes',
    )
    SECURE_HSTS_PRELOAD = False

# Üretimde düz SMTP/IMAP (MAIL_TLS_MODE=off) yalnızca bilinçli opt-in
# Image build (collectstatic) sırasında atlanır.
if (
    not DEBUG
    and (os.getenv('SECRET_KEY') or '') != 'build-collectstatic-only'
    and os.getenv('MAIL_TLS_MODE', 'e2e').strip().lower() == 'off'
):
    if os.getenv('ALLOW_INSECURE_MAIL_TLS', '').lower() not in ('1', 'true', 'yes'):
        raise ImproperlyConfigured(
            'MAIL_TLS_MODE=off production’da yasak. Geçici olarak ALLOW_INSECURE_MAIL_TLS=1 kullanın.'
        )

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.template.context_processors.csrf',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

import tempfile
import os

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

_db_config = None

def _get_db_path():
    """Get database path - prefer temp directory to avoid WSL file locking issues."""
    temp_dir = tempfile.gettempdir()
    db_path = os.path.join(temp_dir, 'jirmail.db')
    return db_path

def _get_database_config():
    """
    Get database configuration from environment or SystemConfig.
    Supports both SQLite and PostgreSQL via DATABASE_URL.
    """
    database_url = os.getenv('DATABASE_URL')

    if database_url:
        import dj_database_url
        db_config = dj_database_url.parse(database_url, conn_max_age=600)
        return db_config

    db_path = os.path.join(tempfile.gettempdir(), 'jirmail.db')
    return {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': db_path,
        'ATOMIC_REQUESTS': False,
        'AUTOCOMMIT': True,
        'CONN_MAX_AGE': 0,
        'OPTIONS': {
            'timeout': 30,
        },
    }

DATABASES = {
    'default': _get_database_config()
}

def _load_db_config_from_system_config():
    """
    SystemConfig tablosundan veritabanı konfigürasyonunu al.
    Bu fonksiyon sadece gerektiğinde çağrılır (lazy loading).
    """
    global _db_config
    if _db_config is not None:
        return _db_config

    try:
        from django.db import connection
        connection.ensure_connection()
        from saas.models import SystemConfig
        config = SystemConfig.objects.first()
        if config and config.is_installed:
            db_conf = config.get_database_config()
            if db_conf:
                _db_config = db_conf
                return db_conf
    except Exception:
        pass
    return None

def get_db_config():
    """Public function to get database config with lazy loading."""
    return _load_db_config_from_system_config()

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'TR-tr'
TIME_ZONE = 'Europe/Istanbul'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_FINDERS = [
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
]

import os
if not DEBUG:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'
else:
    STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

WHITENOISE_USE_FINDERS = DEBUG
WHITENOISE_AUTOREFRESH = DEBUG
WHITENOISE_MAX_AGE = 31536000 if not DEBUG else 0

if not os.path.exists(STATIC_ROOT):
    os.makedirs(STATIC_ROOT, exist_ok=True)

def get_jir_path(path_type='mail_data'):
    """
    SystemConfig'ten path bilgisini al. Yoksa environment variable'a bak.
    Yoksa default değer döndür.
    """
    try:
        from saas.models import SystemConfig
        config = SystemConfig.objects.first()
        if config:
            if path_type == 'mail_data':
                return config.mail_data_path or os.getenv('POSTFIX_MAIL_ROOT', '/var/mail/vhosts')
            elif path_type == 'postfix_vmail':
                return config.postfix_vmail_path or os.getenv('POSTFIX_VMAIL_PATH', '/etc/postfix/vmail_accounts')
            elif path_type == 'dovecot_passdb':
                return config.dovecot_passdb_path or os.getenv('DOVECOT_PASSDB_PATH', '/etc/dovecot/userdb')
            elif path_type == 'backup':
                return config.backup_dir or os.getenv('BACKUP_DIR', '/var/backups/jirmail')
    except Exception:
        pass

    defaults = {
        'mail_data': '/var/mail/vhosts',
        'postfix_vmail': '/etc/postfix/vmail_accounts',
        'dovecot_passdb': '/etc/dovecot/userdb',
        'backup': '/var/backups/jirmail',
    }
    return os.getenv(f'{path_type.upper()}_PATH', defaults.get(path_type, '/var/mail/vhosts'))

POSTFIX_MAIL_ROOT = get_jir_path('mail_data')
POSTFIX_VMAIL_PATH = get_jir_path('postfix_vmail')
DOVECOT_PASSDB_PATH = get_jir_path('dovecot_passdb')
BACKUP_DIR = get_jir_path('backup')

CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', f'redis://{REDIS_HOST}:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', f'redis://{REDIS_HOST}:6379/0')

# Login throttle / kısa ömürlü cache — Redis varsa paylaşılır (çok worker)
_cache_redis = (CELERY_BROKER_URL or '').strip()
if _cache_redis.startswith('redis://'):
    # Aynı Redis, ayrı DB index (broker …/0 ise cache …/1)
    _base = _cache_redis.rstrip('/')
    if _base.endswith('/0'):
        _cache_loc = _base[:-2] + '/1'
    elif _base[-1:].isdigit() and '/' in _base:
        _cache_loc = _base.rsplit('/', 1)[0] + '/1'
    else:
        _cache_loc = _base + '/1'
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': _cache_loc,
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'jir-mail-throttle',
        }
    }

IMAP_HOST = _resolve_mail_service_host('dovecot', 'jir_dovecot')
IMAP_PORT = int(os.getenv('IMAP_PORT', '993'))
# Mail uçtan uca TLS: panel ↔ Postfix/Dovecot (dahili PKI). Kapatmak için yalnızca MAIL_TLS_MODE=off
MAIL_TLS_MODE = os.getenv('MAIL_TLS_MODE', 'e2e').strip().lower()
_MAIL_E2E = MAIL_TLS_MODE != 'off'
IMAP_SSL = os.getenv('IMAP_SSL', 'true').lower() == 'true'
IMAP_SSL_VERIFY = os.getenv('IMAP_SSL_VERIFY', 'true' if _MAIL_E2E else 'false').lower() == 'true'
SMTP_TLS_REQUIRED = os.getenv('SMTP_TLS_REQUIRED', 'true' if _MAIL_E2E else 'false').lower() == 'true'
MAIL_TLS_CA_FILE = os.getenv('MAIL_TLS_CA_FILE', '/etc/jir-mail/tls/ca.crt')
SMTP_HOST = _resolve_mail_service_host('postfix', 'jir_postfix')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_RELAYHOST = os.getenv('SMTP_RELAYHOST', '').strip()
SMTP_RELAY_HOST = os.getenv('SMTP_RELAY_HOST', '').strip()
SMTP_RELAY_PORT = os.getenv('SMTP_RELAY_PORT', '587').strip()
SMTP_RELAY_USER = os.getenv('SMTP_RELAY_USER', '').strip()
SMTP_RELAY_PASSWORD = os.getenv('SMTP_RELAY_PASSWORD', '').strip()
# Yerel compose: docker-compose.yml içinde DOCKER_HOST=tcp://docker-proxy:2375 verilir.
# Coolify / tek konteyner: soket mount edildiğinde unix soketi kullanılır (docker-proxy yok).
DOCKER_HOST = os.getenv('DOCKER_HOST', 'unix:///var/run/docker.sock')

# Docker servis konteyner adları (Coolify vb. farklı isimler için ortam değişkeni)
JIR_CONTAINER_POSTGRES = os.getenv('JIR_CONTAINER_POSTGRES', 'jir_postgres')
JIR_CONTAINER_POSTFIX = os.getenv('JIR_CONTAINER_POSTFIX', 'jir_postfix')
JIR_CONTAINER_DOVECOT = os.getenv('JIR_CONTAINER_DOVECOT', 'jir_dovecot')
JIR_CONTAINER_REDIS = os.getenv('JIR_CONTAINER_REDIS', 'jir_redis')
JIR_CONTAINER_DJANGO = os.getenv('JIR_CONTAINER_DJANGO', 'jir_django')
JIR_CONTAINER_CELERY = os.getenv('JIR_CONTAINER_CELERY', 'jir_celery')
JIR_CONTAINER_CELERY_BEAT = os.getenv('JIR_CONTAINER_CELERY_BEAT', 'jir_celery_beat')

SESSION_COOKIE_AGE = int(os.getenv('SESSION_COOKIE_AGE', '28800'))  # 8 saat
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = os.getenv('SESSION_COOKIE_SAMESITE', 'Lax')
SESSION_EXPIRE_AT_BROWSER_CLOSE = os.getenv('SESSION_EXPIRE_AT_BROWSER_CLOSE', 'false').lower() in (
    '1', 'true', 'yes',
)
SESSION_SAVE_EVERY_REQUEST = True
# IMAP/SMTP için session’daki şifreli parola ömrü (saniye); dolunca webmail yeniden giriş ister
MAIL_PASSWORD_SESSION_TTL = int(os.getenv('MAIL_PASSWORD_SESSION_TTL', '14400'))  # 4 saat
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = os.getenv('CSRF_COOKIE_SAMESITE', 'Lax')
SESSION_COOKIE_DOMAIN = os.getenv('SESSION_COOKIE_DOMAIN', '') or None
CSRF_COOKIE_DOMAIN = os.getenv('CSRF_COOKIE_DOMAIN', '') or None
# Django admin — varsayılan kapalı; ENABLE_DJANGO_ADMIN=1 ile açılır
ENABLE_DJANGO_ADMIN = (
    DEBUG
    or os.getenv('ENABLE_DJANGO_ADMIN', '').lower() in ('1', 'true', 'yes')
)