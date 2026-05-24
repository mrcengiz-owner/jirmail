#!/bin/sh
# Postfix ayakta değilse kurtarma (host'tan: bash scripts/postfix-recover.sh)
set -e
PF="${JIR_CONTAINER_POSTFIX:-jir_postfix}"

echo "=== Postfix kurtarma: $PF ==="

if ! docker ps --format '{{.Names}}' | grep -qx "$PF"; then
  echo "Konteyner çalışmıyor. Başlatılıyor..."
  docker start "$PF" 2>/dev/null || docker compose up -d postfix
  sleep 5
fi

echo "--- pgsql map temizliği (port= satırı) ---"
docker exec "$PF" sh -c "sed -i '/^port = /d' /etc/postfix/pgsql-*.cf 2>/dev/null; true"

echo "--- init script'leri ---"
for s in 10-jirmail-inbound.sh 31-jirmail-transport-maps.sh 11-validate-pgsql.sh; do
  echo ">> $s"
  docker exec "$PF" sh "/docker-init.d/$s" || true
done

echo "--- postconf test ---"
if ! docker exec "$PF" postconf -h daemon_directory 2>/dev/null | grep -q .; then
  echo "HATA: postconf hâlâ bozuk. pgsql dosyaları:"
  docker exec "$PF" sh -c 'for f in /etc/postfix/pgsql-*.cf; do echo "=== $f ==="; cat "$f" 2>/dev/null | head -6; done'
  exit 1
fi
echo "daemon_directory OK: $(docker exec "$PF" postconf -h daemon_directory)"

echo "--- TLS dosyaları ---"
docker exec "$PF" sh -c 'ls -la /etc/jir-mail/tls/ 2>/dev/null || echo "TLS mount yok veya boş"'

echo "--- postfix start ---"
docker exec "$PF" postfix start 2>&1 || true
sleep 2

if docker exec "$PF" postfix status 2>/dev/null | grep -qi running; then
  echo "OK: Postfix çalışıyor."
  docker exec "$PF" postfix status
  exit 0
fi

echo "postfix start başarısız — konteyner yeniden başlatılıyor..."
docker restart "$PF"
sleep 20

if docker exec "$PF" postfix status 2>/dev/null | grep -qi running; then
  echo "OK: restart sonrası Postfix çalışıyor."
  docker exec "$PF" postfix status
  exit 0
fi

echo "HATA: Postfix hâlâ çalışmıyor. Son loglar:"
docker logs "$PF" --tail 60
exit 1
