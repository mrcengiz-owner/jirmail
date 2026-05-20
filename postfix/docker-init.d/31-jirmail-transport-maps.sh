#!/bin/sh
# Virtual domainler → Dovecot LMTP; diğer tüm alan adları → varsayılan internet SMTP.
set -e

DB_HOST="${DB_HOST:-postgres}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-${POSTGRES_DB:-jir_mail_prod}}"
DB_USER="${DB_USER:-postgres}"
export DB_HOST DB_PORT DB_NAME DB_USER DB_PASS

_write_pgsql_cf() {
  _dest="$1"
  _query="$2"
  {
    printf 'hosts = %s\n' "$DB_HOST"
    printf 'port = %s\n' "$DB_PORT"
    printf 'user = %s\n' "$DB_USER"
    printf 'password = %s\n' "$DB_PASS"
    printf 'dbname = %s\n' "$DB_NAME"
    printf 'query = %s\n' "$_query"
  } >"$_dest"
  chmod 600 "$_dest"
}

_write_pgsql_cf /etc/postfix/pgsql-transport-maps.cf \
  "SELECT 'lmtp:inet:dovecot:24' FROM core_maildomain WHERE is_active = true AND name='%d' LIMIT 1"

postconf -e 'transport_maps=pgsql:/etc/postfix/pgsql-transport-maps.cf'
postconf -e 'relay_domains=$virtual_mailbox_domains'
postconf -e 'virtual_transport=lmtp:inet:dovecot:24'

postfix reload 2>/dev/null || true
echo "[jirmail-postfix] transport_maps: virtual domain -> LMTP, diğerleri -> smtp"
