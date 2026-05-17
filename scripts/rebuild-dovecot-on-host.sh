#!/bin/sh
# Host'ta (Coolify sunucusu) panel /app/dovecot kopyasından imaj derler.
# Kullanım: PANEL=y6171w3... ./scripts/rebuild-dovecot-on-host.sh
set -e

PANEL="${PANEL:-}"
if [ -z "$PANEL" ]; then
  PANEL=$(docker ps --format '{{.Names}}' | grep -E 'y6171|jir-mail|jir_mail' | grep -v jir_dovecot | grep -v jir_postfix | head -1)
fi
if [ -z "$PANEL" ]; then
  echo "PANEL konteyner adı bulunamadı. Örnek: PANEL=y6171w3... $0" >&2
  exit 1
fi

BUILD_DIR="${BUILD_DIR:-/tmp/jir-dovecot-build}"
DB_PASS="${DB_PASS:-$(docker exec jir_postgres printenv POSTGRES_PASSWORD 2>/dev/null || true)}"
DB_NAME="${DB_NAME:-$(docker exec jir_postgres printenv POSTGRES_DB 2>/dev/null || echo jir_mail_prod)}"
MAIL_DOMAIN="${MAIL_DOMAIN:-jircode.com}"

echo "Panel: $PANEL"
rm -rf "$BUILD_DIR"
docker cp "$PANEL:/app/dovecot" "$BUILD_DIR"

# Eski panel kodu: manage_sieve / submission
if [ -f "$BUILD_DIR/dovecot-sql.conf.ext.tpl" ]; then
  sed -i 's/^driver = postgres/driver = pgsql/' "$BUILD_DIR/dovecot-sql.conf.ext.tpl"
fi
if [ -f "$BUILD_DIR/dovecot.conf.tpl" ]; then
  sed -i '/manage_sieve/d' "$BUILD_DIR/dovecot.conf.tpl"
  sed -i 's/ lmtp submission/ lmtp/g; s/submission //g' "$BUILD_DIR/dovecot.conf.tpl"
  if ! grep -q 'inet_listener imaps' "$BUILD_DIR/dovecot.conf.tpl" 2>/dev/null; then
    echo "UYARI: Şablonda IMAPS 993 yok — panel kodunu deploy edin veya güncel dovecot.conf.tpl kopyalayın." >&2
  fi
fi

echo "Docker imajı derleniyor…"
docker build -t jir-mail-dovecot:latest "$BUILD_DIR"

docker rm -f jir_dovecot 2>/dev/null || true

if [ -z "$DB_PASS" ]; then
  echo "DB_PASS boş — jir_postgres çalışıyor mu?" >&2
  exit 1
fi

docker run -d --name jir_dovecot --network jir_network \
  -e DB_HOST=jir_postgres \
  -e DB_PORT=5432 \
  -e DB_NAME="$DB_NAME" \
  -e DB_USER=postgres \
  -e DB_PASS="$DB_PASS" \
  -e MAIL_DOMAIN="$MAIL_DOMAIN" \
  -v jir_mail_data:/var/mail \
  -v jir_mail_tls:/etc/jir-mail/tls:ro \
  jir-mail-dovecot:latest

sleep 2
docker logs jir_dovecot --tail 15
docker exec jir_dovecot doveconf -n >/dev/null && echo "doveconf OK"
docker exec jir_dovecot grep '^driver =' /etc/dovecot/dovecot-sql.conf.ext
