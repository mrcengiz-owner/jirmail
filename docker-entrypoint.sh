#!/bin/bash
set -e

CONFIG_FILE="/app/config/db_config.json"

if [ -f "$CONFIG_FILE" ]; then
    echo "=== Loading persisted database config ==="
    python manage.py shell << 'EOF'
import json
import django
django.setup()
from django.conf import settings

with open('/app/config/db_config.json') as f:
    db_conf = json.load(f)
    settings.DATABASES['default'] = db_conf
    print(f"DB config loaded: {db_conf.get('ENGINE')}")
EOF
fi

echo "=== Running migrations ==="
python manage.py migrate --noinput

echo "=== Verifying installation status ==="
python manage.py shell << 'EOF'
import django
django.setup()
from saas.models import SystemConfig

config = SystemConfig.objects.first()
if config and config.is_installed:
    print(f"✓ System already installed (Instance: {config.instance_id})")
else:
    print("⚠ System not yet installed - Setup wizard will appear")
EOF

exec "$@"