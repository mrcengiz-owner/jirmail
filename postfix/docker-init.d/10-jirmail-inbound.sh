#!/bin/sh
# Gelen posta (MX): dış göndericiler (Gmail vb.) kabul + Postgres'ten canlı adres listesi
set -e

DOMAIN="${MAIL_DOMAIN:-mail.local}"
export DB_HOST DB_PORT DB_NAME DB_USER DB_PASS MAIL_DOMAIN

echo "[jirmail-postfix] Inbound MX (domain=${DOMAIN})"

# boky/postfix: gönderen domain kısıtı — Gmail "Sender address rejected" verir
postconf -e 'smtpd_sender_restrictions=permit'
postconf -e 'smtpd_client_restrictions=permit'
postconf -e 'smtpd_helo_restrictions=permit'
postconf -e 'smtpd_tls_security_level=may'
postconf -e 'smtpd_tls_auth_only=no'
postconf -e 'smtpd_recipient_restrictions=permit_mynetworks,permit_sasl_authenticated,reject_unauth_destination'
postconf -e 'smtpd_relay_restrictions=permit_mynetworks,permit_sasl_authenticated,reject_unauth_destination'

# Eski boky gönderen tabloları devre dışı
rm -f /etc/postfix/allowed_senders /etc/postfix/allowed_senders.db 2>/dev/null || true

# Postgres → sanal posta kutuları (hesap eklenince otomatik; postmap gerekmez)
TPL="${JIR_POSTFIX_TEMPLATES:-/usr/share/jir-mail/postfix-templates}"
envsubst '$DB_HOST $DB_PORT $DB_NAME $DB_USER $DB_PASS' \
  <"$TPL/pgsql-virtual-mailboxes.cf.tpl" >/etc/postfix/pgsql-virtual-mailboxes.cf
envsubst '$DB_HOST $DB_PORT $DB_NAME $DB_USER $DB_PASS' \
  <"$TPL/pgsql-virtual-domains.cf.tpl" >/etc/postfix/pgsql-virtual-domains.cf
chmod 600 /etc/postfix/pgsql-virtual-*.cf

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

postfix reload 2>/dev/null || true
echo "[jirmail-postfix] pgsql virtual maps aktif"
