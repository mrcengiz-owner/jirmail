#!/bin/sh
# Her başlangıçta pgsql map doğrula; bozuksa 10-jirmail-inbound.sh tekrar çalıştır
set -e

DB_NAME="${DB_NAME:-${POSTGRES_DB:-jir_mail_prod}}"

_fail() {
  echo "[jirmail-postfix] HATA: $1" >&2
  exit 1
}

_check_file() {
  _f="$1"
  if [ ! -f "$_f" ]; then
    return 1
  fi
  if ! grep -q '^dbname = ' "$_f" 2>/dev/null; then
    return 1
  fi
  if grep -q 'hosts = host=.*password=' "$_f" 2>/dev/null; then
    return 1
  fi
  return 0
}

regen=0
for _f in /etc/postfix/pgsql-virtual-mailboxes.cf /etc/postfix/pgsql-virtual-domains.cf; do
  if ! _check_file "$_f"; then
    regen=1
    break
  fi
done

if [ "$regen" = 1 ]; then
  echo "[jirmail-postfix] pgsql map bozuk/eksik — yeniden yazılıyor"
  sh /docker-init.d/10-jirmail-inbound.sh
fi

for _f in /etc/postfix/pgsql-virtual-mailboxes.cf /etc/postfix/pgsql-virtual-domains.cf; do
  _check_file "$_f" || _fail "$_f geçersiz (dbname satırı yok)"
done

if command -v psql >/dev/null 2>&1 && [ -n "$DB_PASS" ]; then
  PGPASSWORD="$DB_PASS" psql -h "${DB_HOST:-postgres}" -p "${DB_PORT:-5432}" \
    -U "${DB_USER:-postgres}" -d "$DB_NAME" -c 'SELECT 1' >/dev/null 2>&1 \
    || _fail "Postgres bağlantısı başarısız (dbname=${DB_NAME})"
fi

echo "[jirmail-postfix] pgsql map doğrulandı (dbname=${DB_NAME})"
