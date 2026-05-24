#!/bin/bash
# Yalnızca jir_postfix — sistem/dokploy/traefik/firewall'a dokunmaz.
set -euo pipefail

PF="${JIR_CONTAINER_POSTFIX:-jir_postfix}"
DJ="${JIR_CONTAINER_DJANGO:-jir_django}"

echo "=== Jir-Mail Postfix kurtarma (minimal) ==="

if ! docker ps --format '{{.Names}}' | grep -qx "$PF"; then
  echo "HATA: $PF konteyneri çalışmıyor."
  docker ps -a --filter "name=$PF"
  exit 1
fi

echo "--- pgsql map temizliği ---"
docker exec "$PF" sh -c "sed -i '/^port = /d' /etc/postfix/pgsql-*.cf 2>/dev/null; true"

for s in 10-jirmail-inbound.sh 31-jirmail-transport-maps.sh 11-validate-pgsql.sh; do
  echo ">> $s"
  docker exec "$PF" sh "/docker-init.d/$s" || true
done

echo "--- postconf ---"
docker exec "$PF" postconf -h daemon_directory 2>&1 || true

echo "--- postfix start ---"
docker exec "$PF" postfix start 2>&1 || true
sleep 3

if docker exec "$PF" postfix status 2>&1 | grep -qi running; then
  echo "OK: Postfix çalışıyor."
  docker exec "$PF" postfix status
else
  echo "postfix start yetersiz — konteyner restart..."
  docker restart "$PF"
  sleep 25
  docker exec "$PF" postfix status 2>&1 || true
fi

if docker ps --format '{{.Names}}' | grep -qx "$DJ"; then
  echo "--- API durumu ---"
  docker exec "$DJ" curl -s http://127.0.0.1:8000/api/installer/mail-stack-status 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print('smtp_ok:', d.get('smtp_ok'), 'postfix_running:', d.get('postfix_running'), 'mail_ready:', d.get('mail_ready'))" 2>/dev/null \
    || echo "(API kontrol atlandı)"
fi

echo "=== Bitti ==="
