#!/bin/sh
set -e
TPL_DIR="${JIR_DOVECOT_TEMPLATES:-/usr/share/jir-mail/dovecot-templates}"

for v in DB_HOST DB_PORT DB_NAME DB_USER DB_PASS MAIL_DOMAIN; do
  eval "test -n \"\$$v\"" || { echo "dovecot: eksik ortam: $v" >&2; exit 1; }
done
export DB_HOST DB_PORT DB_NAME DB_USER DB_PASS MAIL_DOMAIN
umask 077

if [ ! -f "$TPL_DIR/dovecot-sql.conf.ext.tpl" ]; then
  echo "dovecot: şablon bulunamadı: $TPL_DIR" >&2
  ls -la "$TPL_DIR" 2>/dev/null || ls -la /usr/share/jir-mail/ 2>/dev/null || true
  exit 1
fi

mkdir -p /etc/dovecot/ssl
envsubst '$DB_HOST $DB_PORT $DB_NAME $DB_USER $DB_PASS' \
  < "$TPL_DIR/dovecot-sql.conf.ext.tpl" > /etc/dovecot/dovecot-sql.conf.ext
sed -i 's/^driver = postgres/driver = pgsql/' /etc/dovecot/dovecot-sql.conf.ext
sed -i 's/^default_pass_scheme = bcrypt/default_pass_scheme = BLF-CRYPT/' /etc/dovecot/dovecot-sql.conf.ext
grep -q '^driver = pgsql' /etc/dovecot/dovecot-sql.conf.ext || {
  echo 'dovecot: SQL driver pgsql olmalı (şablon/entrypoint güncel değil)' >&2
  head -3 /etc/dovecot/dovecot-sql.conf.ext >&2
  exit 1
}
chmod 600 /etc/dovecot/dovecot-sql.conf.ext
envsubst '$MAIL_DOMAIN' \
  < "$TPL_DIR/dovecot.conf.tpl" > /etc/dovecot/dovecot.conf

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
