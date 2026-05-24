#!/bin/sh
# Virtual domainler → Dovecot LMTP; diğer tüm alan adları → varsayılan internet SMTP.
set -e

. /docker-init.d/_jirmail-common.sh

DB_HOST="${DB_HOST:-postgres}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-${POSTGRES_DB:-jir_mail_prod}}"
DB_USER="${DB_USER:-postgres}"
export DB_HOST DB_PORT DB_NAME DB_USER DB_PASS

_strip_legacy_pgsql_port_lines

_write_pgsql_cf /etc/postfix/pgsql-transport-maps.cf \
  "SELECT 'lmtp:inet:dovecot:24' FROM core_maildomain d INNER JOIN core_mailaccount a ON a.domain_id = d.id AND a.is_active = true WHERE d.is_active = true AND d.name='%d' LIMIT 1"

postconf -e 'transport_maps=pgsql:/etc/postfix/pgsql-transport-maps.cf'
postconf -e 'relay_domains='
postconf -e 'virtual_transport=lmtp:inet:dovecot:24'

_postfix_reload_if_running
echo "[jirmail-postfix] transport_maps: hesaplı domain -> LMTP, tüm dış alıcılar -> internet SMTP"
