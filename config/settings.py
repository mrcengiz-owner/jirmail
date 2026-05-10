"""
Django settings for Jîr-Mail project.

Single Source of Truth: SystemConfig model (veritabanı)
"""

from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-r%36n))g&hrl-di8^5$ni9(j5y@ovwju!(1q)ql*^%#9emwh_w')

DEBUG = os.getenv('DEBUG', 'False').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'management',
    'saas',
    'core',
    'backup',
    'alerts',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

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

_db_config = None

def _get_db_path():
    """Get database path - prefer temp directory to avoid WSL file locking issues."""
    temp_dir = tempfile.gettempdir()
    db_path = os.path.join(temp_dir, 'jirmail.db')
    return db_path

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': _get_db_path(),
        'ATOMIC_REQUESTS': False,
        'AUTOCOMMIT': True,
        'CONN_MAX_AGE': 0,
        'OPTIONS': {
            'timeout': 30,
        },
    }
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

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

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