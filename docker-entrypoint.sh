#!/bin/bash
set -e

CONFIG_FILE="/app/config/db_config.json"
INSTALLED_FLAG="/app/config/.installed"

# DB config varsa yükle
if [ -f "$CONFIG_FILE" ]; then
    echo "=== Loading persisted database config ==="
    python manage.py shell << 'EOF'
import json
from django.conf import settings
with open('/app/config/db_config.json') as f:
    db_conf = json.load(f)
    settings.DATABASES['default'] = db_conf
    print(f"DB config loaded: {db_conf.get('ENGINE')}")
EOF
fi

if [ "${JIR_COMPOSE_STACK}" = "1" ]; then
    echo "=== Compose stack: mail TLS (Postfix/Dovecot aynı ağda) ==="
    python manage.py init_mail_tls \
        --domain "${MAIL_DOMAIN:-mail.local}" \
        --hostname "${MAIL_HOSTNAME:-mail.${MAIL_DOMAIN:-mail.local}}" \
        2>/dev/null || true
fi

echo "=== Running migrations ==="
# Prod'da makemigrations çalıştırma — migration çakışması / 502 riski
python manage.py migrate --noinput

if [ "${JIR_COMPOSE_STACK}" = "1" ]; then
    echo "=== Mail kutuları (Maildir) + Postfix eşlemesi ==="
    python manage.py provision_mail_stack 2>/dev/null || true
    echo "=== Mail stack otomatik doğrulama ve onarım ==="
    python manage.py verify_and_heal_mail_stack --fix --quiet || true
    python manage.py verify_and_heal_mail_stack --self-test-only --quiet || true
fi

echo "=== Collecting static files ==="
mkdir -p /app/staticfiles
python manage.py collectstatic --noinput --clear
for rel in css/webmail.css js/webmail/core.js js/webmail/mail-app.js; do
    if [ -f "/app/staticfiles/$rel" ] || [ -f "/app/static/$rel" ]; then
        echo "  [ok] static $rel"
    else
        echo "  [WARN] Eksik: $rel — webmail /webmail/assets/ kaynaktan sunulur"
    fi
done

echo "=== Deploy readiness (Coolify / PaaS) ==="
python manage.py check_deploy || true

# Kurulum durumunu kontrol et
if [ -f "$INSTALLED_FLAG" ]; then
    echo "✓ System already installed (cached flag found)"
else
    echo "=== Checking database installation status ==="
    python manage.py shell << 'EOF'
from saas.models import SystemConfig
config = SystemConfig.objects.first()
if config and config.is_installed:
    print(f"✓ System already installed (Instance: {config.instance_id})")
    with open('/app/config/.installed', 'w') as f:
        f.write(str(config.instance_id))
else:
    print("⚠ System not yet installed - Setup wizard will appear")
EOF
fi

echo "=== Starting application ==="
exec "$@"
