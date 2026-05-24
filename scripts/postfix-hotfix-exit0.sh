#!/bin/bash
# boky/postfix: 32-jirmail-relay-sasl.sh içindeki exit 0 entrypoint'i öldürür.
# Kullanım (repo kökünden): bash scripts/postfix-hotfix-exit0.sh
set -euo pipefail

PF="${JIR_CONTAINER_POSTFIX:-jir_postfix}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/postfix/docker-init.d/32-jirmail-relay-sasl.sh"

if [ ! -f "$SRC" ]; then
  echo "HATA: $SRC bulunamadı"
  exit 1
fi

if ! docker ps -a --format '{{.Names}}' | grep -qx "$PF"; then
  echo "HATA: $PF konteyneri yok"
  exit 1
fi

echo "=== Postfix exit0 hotfix: $PF ==="
docker cp "$SRC" "$PF:/docker-init.d/32-jirmail-relay-sasl.sh"
docker exec "$PF" chmod +x /docker-init.d/32-jirmail-relay-sasl.sh

echo "--- init doğrulama ---"
for s in 10-jirmail-inbound.sh 31-jirmail-transport-maps.sh 30-jirmail-outbound-smtp.sh 11-validate-pgsql.sh; do
  echo ">> $s"
  docker exec "$PF" sh "/docker-init.d/$s" || true
done

echo "--- postfix check / start ---"
docker exec "$PF" postfix check 2>&1 || true
docker exec "$PF" postfix start 2>&1 || true
sleep 2

if docker exec "$PF" postfix status 2>&1 | grep -qi running; then
  echo "OK: Postfix çalışıyor."
  docker exec "$PF" postfix status
  exit 0
fi

echo "Manuel start yetmedi — restart..."
docker restart "$PF"
sleep 15

if docker exec "$PF" postfix status 2>&1 | grep -qi running; then
  echo "OK: restart sonrası Postfix çalışıyor."
  docker exec "$PF" postfix status
  exit 0
fi

echo "HATA: Postfix hâlâ çalışmıyor."
docker exec "$PF" postfix check 2>&1 || true
docker logs "$PF" --tail 50
exit 1
