#!/bin/sh
# Kimlik doğrulamalı SMTP relay (SendGrid, Mailgun, ISP SMTP vb.)
set -e

. /docker-init.d/_jirmail-common.sh

RELAYHOST="${SMTP_RELAYHOST:-}"
USER="${SMTP_RELAY_USER:-}"
PASS="${SMTP_RELAY_PASSWORD:-}"

if [ -z "$RELAYHOST" ] && [ -n "${SMTP_RELAY_HOST:-}" ]; then
  _port="${SMTP_RELAY_PORT:-587}"
  RELAYHOST="[${SMTP_RELAY_HOST}]:${_port}"
fi

if [ -z "$RELAYHOST" ] || [ -z "$USER" ] || [ -z "$PASS" ]; then
  postconf -e 'smtp_sasl_auth_enable=no'
  postconf -e 'smtp_sasl_password_maps='
  postconf -e 'smtp_tls_security_level=may'
  echo "[jirmail-postfix] relay SASL: devre dışı (kimlik bilgisi yok)"
  exit 0
fi

# relayhost köşeli parantez içinde host — sasl_passwd anahtarı için normalize et
_key="$RELAYHOST"
case "$_key" in
  \[*\]:*) ;;
  *:*) _host="${_key%%:*}"; _port="${_key##*:}"; _key="[${_host}]:${_port}" ;;
esac

printf '%s\t%s:%s\n' "$_key" "$USER" "$PASS" > /etc/postfix/sasl_passwd
chmod 600 /etc/postfix/sasl_passwd
postmap /etc/postfix/sasl_passwd
chmod 600 /etc/postfix/sasl_passwd.db 2>/dev/null || true

postconf -e 'smtp_sasl_auth_enable=yes'
postconf -e 'smtp_sasl_password_maps=hash:/etc/postfix/sasl_passwd'
postconf -e 'smtp_sasl_security_options=noanonymous'
postconf -e 'smtp_tls_security_level=encrypt'
postconf -e "relayhost=${RELAYHOST}"

_postfix_reload_if_running
echo "[jirmail-postfix] relay SASL: ${_key} (kimlik doğrulama aktif)"
