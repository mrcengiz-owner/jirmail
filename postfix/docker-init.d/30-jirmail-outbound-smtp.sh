#!/bin/sh
# Gönderim: yalnızca virtual domainler Dovecot LMTP; dış adresler (Gmail vb.) internet SMTP.
set -e

# boky/postfix varsayılanları bazen tüm postayı LMTP'ye yönlendirir — düzelt.
postconf -e 'default_transport=smtp'
postconf -e 'relay_transport=smtp'
RELAYHOST="${SMTP_RELAYHOST:-}"
if [ -n "$RELAYHOST" ]; then
  postconf -e "relayhost=${RELAYHOST}"
  echo "[jirmail-postfix] relayhost=${RELAYHOST}"
else
  postconf -e 'relayhost='
fi
postconf -e 'smtp_dns_support_level=dnssec'
postconf -e 'smtp_host_lookup=dns'

# Yerel teslimat: virtual_mailbox_domains + virtual_transport (10-jirmail-inbound.sh)
# $myhostname posta kutusu olarak kullanılmasın (CC@mail.jircode.com hatası önlenir)
postconf -e 'mydestination=localhost'
postconf -e 'local_transport=error:local mail delivery is disabled'

# İnternet çıkışı (port 25 MX) — konteyner ağından
postconf -e 'smtp_bind_address='
postconf -e 'smtp_bind_address6='

postfix reload 2>/dev/null || true
if [ -z "$RELAYHOST" ]; then
  echo "[jirmail-postfix] outbound: virtual domain -> LMTP, dış adresler -> internet SMTP (port 25)"
  echo "[jirmail-postfix] ipucu: port 25 kapalıysa SMTP_RELAYHOST=[relay]:587 ayarlayın"
else
  echo "[jirmail-postfix] outbound: dış posta relayhost üzerinden"
fi
