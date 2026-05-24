#!/bin/sh
# Her başlangıçta pgsql map doğrula; bozuksa yeniden yaz
set -e

. /docker-init.d/_jirmail-common.sh

DB_NAME="${DB_NAME:-${POSTGRES_DB:-jir_mail_prod}}"

_strip_legacy_pgsql_port_lines

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
  if grep -q '^port = ' "$_f" 2>/dev/null; then
    return 1
  fi
  return 0
}

PGSQL_FILES="/etc/postfix/pgsql-virtual-mailboxes.cf /etc/postfix/pgsql-virtual-domains.cf /etc/postfix/pgsql-transport-maps.cf"

regen_inbound=0
regen_transport=0
for _f in /etc/postfix/pgsql-virtual-mailboxes.cf /etc/postfix/pgsql-virtual-domains.cf; do
  if ! _check_file "$_f"; then
    regen_inbound=1
    break
  fi
done
if _jir_pgsql_map_needs_upgrade /etc/postfix/pgsql-virtual-domains.cf virtual-domains; then
  echo "[jirmail-postfix] pgsql virtual-domains eski sürüm — yeniden yazılacak"
  regen_inbound=1
fi
if [ ! -f /etc/postfix/pgsql-transport-maps.cf ] || ! _check_file /etc/postfix/pgsql-transport-maps.cf; then
  regen_transport=1
fi
if _jir_pgsql_map_needs_upgrade /etc/postfix/pgsql-transport-maps.cf transport-maps; then
  echo "[jirmail-postfix] pgsql transport-maps eski sürüm — yeniden yazılacak"
  regen_transport=1
fi

if [ "$regen_inbound" = 1 ]; then
  echo "[jirmail-postfix] pgsql virtual map bozuk/eksik — yeniden yazılıyor"
  sh /docker-init.d/10-jirmail-inbound.sh
fi
if [ "$regen_transport" = 1 ]; then
  echo "[jirmail-postfix] pgsql transport map bozuk/eksik — yeniden yazılıyor"
  sh /docker-init.d/31-jirmail-transport-maps.sh
fi

for _f in $PGSQL_FILES; do
  _check_file "$_f" || _fail "$_f geçersiz (dbname yok veya port= satırı var)"
done

if command -v psql >/dev/null 2>&1 && [ -n "$DB_PASS" ]; then
  if ! PGPASSWORD="$DB_PASS" psql -h "${DB_HOST:-postgres}" -p "${DB_PORT:-5432}" \
    -U "${DB_USER:-postgres}" -d "$DB_NAME" -c 'SELECT 1' >/dev/null 2>&1; then
    echo "[jirmail-postfix] UYARI: Postgres bağlantısı başarısız (dbname=${DB_NAME}) — init devam ediyor" >&2
  fi
fi

if ! postconf -h daemon_directory >/dev/null 2>&1; then
  _fail "postconf okunamıyor — pgsql map dosyalarını kontrol edin"
fi

echo "[jirmail-postfix] pgsql map doğrulandı (dbname=${DB_NAME})"
