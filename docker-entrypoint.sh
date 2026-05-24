#!/bin/bash
set -e

CONFIG_FILE="/app/config/db_config.json"
INSTALLED_FLAG="/app/config/.installed"
POST_DEPLOY_LOG="${JIR_POST_DEPLOY_LOG:-/tmp/jir-post-deploy.log}"

# DB config varsa yükle
if [ -f "$CONFIG_FILE" ]; then
    echo "=== Loading persisted database config ==="
    python manage.py shell << 'EOF' || true
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

echo "=== Collecting static files ==="
mkdir -p /app/staticfiles
python manage.py collectstatic --noinput --clear

_run_post_deploy_jobs() {
    echo "=== [bg] Deploy sonrası stack işleri başladı ===" >>"$POST_DEPLOY_LOG"
    if [ "${JIR_COMPOSE_STACK}" = "1" ]; then
        python manage.py restart_compose_stack_on_deploy --quiet >>"$POST_DEPLOY_LOG" 2>&1 || true
        python manage.py provision_mail_stack >>"$POST_DEPLOY_LOG" 2>&1 || true
        python manage.py verify_and_heal_mail_stack --fix --quiet >>"$POST_DEPLOY_LOG" 2>&1 || true
        python manage.py verify_and_heal_mail_stack --self-test-only --quiet >>"$POST_DEPLOY_LOG" 2>&1 || true
        python manage.py shell -c "from management.outbound_autoconfig import ensure_outbound_delivery; print(ensure_outbound_delivery(fix=True, full_heal=False).get('message',''))" >>"$POST_DEPLOY_LOG" 2>&1 || true
        python manage.py shell -c "from management.postfix_maps import force_fix_postfix_routing; print(force_fix_postfix_routing())" >>"$POST_DEPLOY_LOG" 2>&1 || true
    fi
    python manage.py check_deploy >>"$POST_DEPLOY_LOG" 2>&1 || true
    echo "=== [bg] Deploy sonrası stack işleri bitti ===" >>"$POST_DEPLOY_LOG"
}

if [ "${JIR_COMPOSE_STACK}" = "1" ] && [ "${JIR_SKIP_POST_DEPLOY_JOBS:-0}" != "1" ]; then
    echo "=== Post-deploy işleri arka planda (502 önleme) — log: $POST_DEPLOY_LOG ==="
    _run_post_deploy_jobs &
else
    echo "=== Post-deploy işleri atlandı (JIR_SKIP_POST_DEPLOY_JOBS=1) ==="
    python manage.py check_deploy || true
fi

for rel in css/webmail.css js/webmail/core.js js/webmail/mail-app.js; do
    if [ -f "/app/staticfiles/$rel" ] || [ -f "/app/static/$rel" ]; then
        echo "  [ok] static $rel"
    else
        echo "  [WARN] Eksik: $rel — webmail /webmail/assets/ kaynaktan sunulur"
    fi
done

# Kurulum durumunu kontrol et
if [ -f "$INSTALLED_FLAG" ]; then
    echo "✓ System already installed (cached flag found)"
else
    echo "=== Checking database installation status ==="
    python manage.py shell << 'EOF' || true
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
