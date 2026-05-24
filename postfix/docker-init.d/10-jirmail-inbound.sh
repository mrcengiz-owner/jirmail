#!/bin/sh
# Gelen posta (MX): dış göndericiler (Gmail vb.) kabul + Postgres'ten canlı adres listesi
set -e

. /docker-init.d/_jirmail-common.sh

DOMAIN="${MAIL_DOMAIN:-mail.local}"
DB_HOST="${DB_HOST:-postgres}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-${POSTGRES_DB:-jir_mail_prod}}"
DB_USER="${DB_USER:-postgres}"
export DB_HOST DB_PORT DB_NAME DB_USER DB_PASS MAIL_DOMAIN

echo "[jirmail-postfix] Inbound MX (domain=${DOMAIN}, db=${DB_NAME})"

_strip_legacy_pgsql_port_lines

postconf -e 'smtpd_client_restrictions=permit'
postconf -e 'smtpd_helo_restrictions=permit'
postconf -e 'smtpd_tls_security_level=may'
postconf -e 'smtpd_tls_auth_only=no'
postconf -e 'smtpd_recipient_restrictions=permit_mynetworks,permit_sasl_authenticated,reject_unauth_destination'
postconf -e 'smtpd_relay_restrictions=permit_mynetworks,permit_sasl_authenticated,reject_unauth_destination'

rm -f /etc/postfix/allowed_senders /etc/postfix/allowed_senders.db 2>/dev/null || true

_write_pgsql_cf /etc/postfix/pgsql-virtual-mailboxes.cf \
  "SELECT CONCAT(a.email, ' ', d.name, '/', a.username, '/') AS mailbox FROM core_mailaccount a INNER JOIN core_maildomain d ON d.id = a.domain_id WHERE a.is_active = true AND d.is_active = true"

_write_pgsql_cf /etc/postfix/pgsql-virtual-domains.cf \
  "SELECT DISTINCT d.name FROM core_maildomain d INNER JOIN core_mailaccount a ON a.domain_id = d.id AND a.is_active = true WHERE d.is_active = true"

postconf -e "virtual_mailbox_domains=pgsql:/etc/postfix/pgsql-virtual-domains.cf"
postconf -e 'virtual_mailbox_maps=pgsql:/etc/postfix/pgsql-virtual-mailboxes.cf'
postconf -e 'virtual_mailbox_base=/var/mail/vhosts'
postconf -e 'virtual_uid_maps=static:5000'
postconf -e 'virtual_gid_maps=static:5000'
postconf -e 'virtual_transport=lmtp:inet:dovecot:24'
postconf -e 'virtual_minimum_uid=5000'

if postconf -Mf submission/inet >/dev/null 2>&1; then
  postconf -P submission/inet -e smtpd_tls_security_level=encrypt 2>/dev/null || true
fi

_postfix_reload_if_running
echo "[jirmail-postfix] pgsql virtual maps aktif (dbname=${DB_NAME})"
