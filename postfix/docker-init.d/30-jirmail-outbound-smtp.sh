#!/bin/sh
# Gönderim: yalnızca virtual domainler Dovecot LMTP; dış adresler internet SMTP veya relay.
set -e

. /docker-init.d/_jirmail-common.sh

_port25_ok() {
  timeout 5 bash -c 'exec 3<>/dev/tcp/gmail-smtp-in.l.google.com/25' 2>/dev/null
}

# boky/postfix varsayılanları bazen tüm postayı LMTP'ye yönlendirir — düzelt.
postconf -e 'default_transport=smtp'
postconf -e 'relay_transport=smtp'

RELAYHOST="${SMTP_RELAYHOST:-}"
if [ -z "$RELAYHOST" ] && [ -n "${SMTP_RELAY_HOST:-}" ]; then
  _port="${SMTP_RELAY_PORT:-587}"
  RELAYHOST="[${SMTP_RELAY_HOST}]:${_port}"
fi

# Port 25 kapalıysa ve relay tanımlıysa otomatik relay moduna geç
if [ -z "$RELAYHOST" ]; then
  if ! _port25_ok; then
    echo "[jirmail-postfix] port 25 kapalı — doğrudan MX teslimatı mümkün olmayabilir"
  fi
fi

if [ -n "$RELAYHOST" ]; then
  postconf -e "relayhost=${RELAYHOST}"
  echo "[jirmail-postfix] relayhost=${RELAYHOST}"
else
  postconf -e 'relayhost='
fi

postconf -e 'smtp_dns_support_level=dnssec'
postconf -e 'smtp_host_lookup=dns'

# Yerel teslimat: virtual_mailbox_domains + virtual_transport (10-jirmail-inbound.sh)
postconf -e 'mydestination=localhost'
postconf -e 'local_transport=error:local mail delivery is disabled'

# İnternet çıkışı (port 25 MX) — konteyner ağından
postconf -e 'smtp_bind_address='
postconf -e 'smtp_bind_address6='

# SASL relay (varsa)
if [ -f /docker-init.d/32-jirmail-relay-sasl.sh ]; then
  sh /docker-init.d/32-jirmail-relay-sasl.sh
fi

_postfix_reload_if_running
if [ -z "$RELAYHOST" ]; then
  echo "[jirmail-postfix] outbound: virtual domain -> LMTP, dış adresler -> internet SMTP (port 25)"
else
  echo "[jirmail-postfix] outbound: dış posta relayhost üzerinden"
fi
