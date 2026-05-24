#!/bin/bash
# Yalnızca jir_postfix — sistem/dokploy/traefik/firewall'a dokunmaz.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PF="${JIR_CONTAINER_POSTFIX:-jir_postfix}"
DJ="${JIR_CONTAINER_DJANGO:-jir_django}"

echo "=== Jir-Mail Postfix kurtarma (Gmail routing dahil) ==="

if ! docker ps --format '{{.Names}}' | grep -qx "$PF"; then
  echo "HATA: $PF konteyneri çalışmıyor."
  docker ps -a --filter "name=$PF"
  exit 1
fi

echo "--- pgsql map onarımı (fix-postfix-pgsql.sh) ---"
docker exec -i "$PF" sh -s < "$ROOT/scripts/fix-postfix-pgsql.sh"

echo "--- postmap gmail.com (boş olmalı) ---"
docker exec "$PF" postmap -q gmail.com pgsql:/etc/postfix/pgsql-virtual-domains.cf 2>&1 || true
docker exec "$PF" postmap -q gmail.com pgsql:/etc/postfix/pgsql-transport-maps.cf 2>&1 || true

if docker ps --format '{{.Names}}' | grep -qx "$DJ"; then
  echo "--- Django routing onarımı (deploy sonrası) ---"
  docker exec "$DJ" curl -sS -m 120 -X POST http://127.0.0.1:8000/api/installer/fix-postfix-routing \
    -H 'Content-Type: application/json' -d '{}' 2>/dev/null \
    | python3 -m json.tool 2>/dev/null \
    || echo "(fix-postfix-routing API henüz deploy edilmemiş — pgsql map adımı yeterli olabilir)"
fi

echo "=== Bitti — Gmail'e test maili gönderin ==="
