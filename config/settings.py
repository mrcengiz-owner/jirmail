"""
Django settings for Jîr-Mail project.

Single Source of Truth: SystemConfig model (veritabanı)
"""

import dotenv
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent
dotenv.load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-r%36n))g&hrl-di8^5$ni9(j5y@ovwju!(1q)ql*^%#9emwh_w')

DEBUG = os.getenv('DEBUG', 'False').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = ['*']

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
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'jir_core.middleware.JirInstallMiddleware',
]

CORS_ALLOWED_ORIGINS = [
    'http://localhost:3000',
    'http://localhost:8000',
    'http://127.0.0.1:3000',
    'http://127.0.0.1:8000',
    'http://0.0.0.0:3000',
    'http://0.0.0.0:8000',
]

CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = [
    'http://localhost:3000',
    'http://localhost:8000',
    'http://127.0.0.1:3000',
    'http://127.0.0.1:8000',
    'http://0.0.0.0:3000',
    'http://0.0.0.0:8000',
]

if DEBUG:
    CSRF_COOKIE_SECURE = False
    SESSION_COOKIE_SECURE = False
else:
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
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

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_FINDERS = [
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
]

if DEBUG:
    STATICFILES_DIRS = [BASE_DIR / 'static']
    import os
    # Development modda static dosyaları doğrudan serve et
    import mimetypes
    mimetypes.add_type("text/css", ".css", True)
    mimetypes.add_type("application/javascript", ".js", True)

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

CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')

SESSION_COOKIE_AGE = 86400
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_EXPIRE_AT_BROWSER_CLOSE = False