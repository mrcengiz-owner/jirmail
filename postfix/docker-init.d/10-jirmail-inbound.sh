#!/bin/sh
# Gelen posta (port 25): Gmail ve diğer MTA'lar → virtual mailbox → Dovecot LMTP
set -e

DOMAIN="${MAIL_DOMAIN:-mail.local}"
DB_HOST="${DB_HOST:-postgres}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-jir_mail_prod}"
DB_USER="${DB_USER:-postgres}"
DB_PASS="${DB_PASS:-}"

echo "[jirmail-postfix] Inbound MX yapılandırması (domain=${DOMAIN})"

# boky/postfix varsayılanı: yalnızca izinli gönderen domain — Gmail reddedilir
postconf -e 'smtpd_client_restrictions=permit'
postconf -e 'smtpd_helo_restrictions=permit'

# Port 25: STARTTLS isteğe bağlı (MX); submission 587 ayrı tutulur
postconf -e 'smtpd_tls_security_level=may'
postconf -e 'smtpd_tls_auth_only=no'

postconf -e "virtual_mailbox_domains=${DOMAIN}"
postconf -e 'virtual_mailbox_base=/var/mail/vhosts'
postconf -e 'virtual_uid_maps=static:5000'
postconf -e 'virtual_gid_maps=static:5000'
postconf -e 'virtual_transport=lmtp:inet:dovecot:24'
postconf -e 'virtual_mailbox_maps=hash:/etc/postfix/virtual_mailboxes'

postconf -e 'smtpd_recipient_restrictions=permit_mynetworks,permit_sasl_authenticated,reject_unauth_destination'
postconf -e 'smtpd_relay_restrictions=permit_mynetworks,permit_sasl_authenticated,defer_unauth_destination'

# Submission (587): panel iç ağından gönderim
if postconf -Mf submission/inet >/dev/null 2>&1; then
  postconf -P submission/inet -e smtpd_tls_security_level=encrypt 2>/dev/null || true
fi

MAP=/etc/postfix/virtual_mailboxes
: >"$MAP"

if command -v psql >/dev/null 2>&1 && [ -n "$DB_PASS" ]; then
  export PGPASSWORD="$DB_PASS"
  psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -A -F '|' -c \
    "SELECT a.email, d.name, a.username
     FROM core_mailaccount a
     INNER JOIN core_maildomain d ON d.id = a.domain_id
     WHERE a.is_active = true AND d.is_active = true" \
    | while IFS='|' read -r email dname uname; do
      email=$(echo "$email" | tr -d '[:space:]')
      dname=$(echo "$dname" | tr -d '[:space:]')
      uname=$(echo "$uname" | tr -d '[:space:]')
      [ -z "$email" ] && continue
      [ -z "$dname" ] && dname="$DOMAIN"
      [ -z "$uname" ] && uname="${email%%@*}"
      echo "$email ${dname}/${uname}/" >>"$MAP"
    done
  unset PGPASSWORD
else
  echo "[jirmail-postfix] UYARI: psql/DB yok — virtual_mailboxes boş kalabilir" >&2
fi

if [ ! -s "$MAP" ]; then
  echo "postmaster@${DOMAIN} ${DOMAIN}/postmaster/" >>"$MAP"
fi

postmap "$MAP"
echo "[jirmail-postfix] virtual_mailboxes: $(wc -l <"$MAP") kayıt"
