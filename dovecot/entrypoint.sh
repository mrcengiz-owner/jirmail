#!/bin/sh
set -e
for v in DB_HOST DB_PORT DB_NAME DB_USER DB_PASS MAIL_DOMAIN; do
  eval "test -n \"\$$v\"" || { echo "dovecot: eksik ortam: $v" >&2; exit 1; }
done
export DB_HOST DB_PORT DB_NAME DB_USER DB_PASS MAIL_DOMAIN
umask 077
envsubst '$DB_HOST $DB_PORT $DB_NAME $DB_USER $DB_PASS' \
  < /etc/dovecot/dovecot-sql.conf.ext.tpl > /etc/dovecot/dovecot-sql.conf.ext
chmod 600 /etc/dovecot/dovecot-sql.conf.ext
envsubst '$MAIL_DOMAIN' \
  < /etc/dovecot/dovecot.conf.tpl > /etc/dovecot/dovecot.conf
mkdir -p /etc/dovecot/ssl
CERT=/etc/dovecot/ssl/dovecot.crt
KEY=/etc/dovecot/ssl/dovecot.key
PKI_CERT=/etc/jir-mail/tls/server.crt
PKI_KEY=/etc/jir-mail/tls/server.key
if [ -s "$PKI_CERT" ] && [ -s "$PKI_KEY" ]; then
  cp "$PKI_CERT" "$CERT"
  cp "$PKI_KEY" "$KEY"
  chmod 600 "$KEY"
elif [ ! -s "$CERT" ]; then
  CN="${MAIL_DOMAIN:-mail.local}"
  openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
    -keyout "$KEY" -out "$CERT" -subj "/CN=$CN"
  chmod 600 "$KEY"
fi
exec "$@"
