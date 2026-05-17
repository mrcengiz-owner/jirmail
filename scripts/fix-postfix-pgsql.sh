#!/bin/sh
# Sunucuda: Postfix pgsql map dosyalarını düzelt (Dokploy redeploy öncesi acil onarım)
# Kullanım: docker exec jir_postfix sh -s < scripts/fix-postfix-pgsql.sh
set -e

DB_HOST="${DB_HOST:-postgres}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-${POSTGRES_DB:-jir_mail_prod}}"
DB_USER="${DB_USER:-postgres}"

if [ -z "$DB_PASS" ]; then
  echo "DB_PASS boş — konteyner ortam değişkenlerini kontrol edin" >&2
  exit 1
fi

_write() {
  dest="$1"
  query="$2"
  {
    printf 'hosts = %s\n' "$DB_HOST"
    printf 'port = %s\n' "$DB_PORT"
    printf 'user = %s\n' "$DB_USER"
    printf 'password = %s\n' "$DB_PASS"
    printf 'dbname = %s\n' "$DB_NAME"
    printf 'query = %s\n' "$query"
  } >"$dest"
  chmod 600 "$dest"
}

_write /etc/postfix/pgsql-virtual-mailboxes.cf \
  "SELECT CONCAT(a.email, ' ', d.name, '/', a.username, '/') AS mailbox FROM core_mailaccount a INNER JOIN core_maildomain d ON d.id = a.domain_id WHERE a.is_active = true AND d.is_active = true"

_write /etc/postfix/pgsql-virtual-domains.cf \
  "SELECT name FROM core_maildomain WHERE is_active = true"

postfix reload
echo "OK: pgsql maps yenilendi (dbname=$DB_NAME)"
postmap -q admin@jircode.com pgsql:/etc/postfix/pgsql-virtual-mailboxes.cf 2>/dev/null || true
