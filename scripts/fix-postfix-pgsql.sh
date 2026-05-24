#!/bin/sh
# Sunucuda: Postfix pgsql map dosyalarını düzelt (Dokploy redeploy öncesi acil onarım)
# Kullanım: docker exec jir_postfix sh -s < scripts/fix-postfix-pgsql.sh
set -e

. /docker-init.d/_jirmail-common.sh 2>/dev/null || true

DB_HOST="${DB_HOST:-postgres}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-${POSTGRES_DB:-jir_mail_prod}}"
DB_USER="${DB_USER:-postgres}"

if [ -z "$DB_PASS" ]; then
  echo "DB_PASS boş — konteyner ortam değişkenlerini kontrol edin" >&2
  exit 1
fi

export DB_HOST DB_PORT DB_NAME DB_USER DB_PASS

_excl="AND d.name NOT IN ('aol.com', 'gmail.com', 'googlemail.com', 'gmx.com', 'gmx.net', 'hotmail.com', 'icloud.com', 'live.com', 'mac.com', 'mail.ru', 'me.com', 'msn.com', 'outlook.com', 'pm.me', 'proton.me', 'protonmail.com', 'tuta.io', 'tutanota.com', 'yahoo.com', 'yahoo.com.tr', 'yandex.com', 'yandex.com.tr', 'zoho.com')"

_write() {
  dest="$1"
  query="$2"
  _hosts="$DB_HOST"
  if [ -n "${DB_PORT:-}" ] && [ "${DB_PORT}" != "5432" ]; then
    _hosts="${DB_HOST}:${DB_PORT}"
  fi
  {
    printf '# JIR_POSTFIX_MAPS_VERSION=3\n'
    printf 'hosts = %s\n' "$_hosts"
    printf 'user = %s\n' "$DB_USER"
    printf 'password = %s\n' "$DB_PASS"
    printf 'dbname = %s\n' "$DB_NAME"
    printf 'query = %s\n' "$query"
  } >"$dest"
  chmod 600 "$dest"
}

_gmail_routing_bad() {
  _vd=$(postmap -q gmail.com pgsql:/etc/postfix/pgsql-virtual-domains.cf 2>/dev/null || true)
  _tr=$(postmap -q gmail.com pgsql:/etc/postfix/pgsql-transport-maps.cf 2>/dev/null || true)
  if [ -n "$_vd" ]; then
    return 0
  fi
  echo "$_tr" | grep -qi lmtp && return 0
  return 1
}

_force_write_maps() {
  _write /etc/postfix/pgsql-virtual-mailboxes.cf \
    "SELECT CONCAT(a.email, ' ', d.name, '/', a.username, '/') AS mailbox FROM core_mailaccount a INNER JOIN core_maildomain d ON d.id = a.domain_id WHERE a.is_active = true AND d.is_active = true"
  _write /etc/postfix/pgsql-virtual-domains.cf \
    "SELECT 1 FROM core_maildomain d INNER JOIN core_mailaccount a ON a.domain_id = d.id AND a.is_active = true WHERE d.is_active = true $_excl AND d.name='%s' LIMIT 1"
  _write /etc/postfix/pgsql-transport-maps.cf \
    "SELECT 'lmtp:inet:dovecot:24' FROM core_maildomain d INNER JOIN core_mailaccount a ON a.domain_id = d.id AND a.is_active = true WHERE d.is_active = true $_excl AND d.name='%d' LIMIT 1"
  postconf -e 'virtual_mailbox_domains=pgsql:/etc/postfix/pgsql-virtual-domains.cf'
  postconf -e 'virtual_mailbox_maps=pgsql:/etc/postfix/pgsql-virtual-mailboxes.cf'
  postconf -e 'transport_maps=pgsql:/etc/postfix/pgsql-transport-maps.cf'
  postconf -e 'virtual_transport=lmtp:inet:dovecot:24'
  postconf -e 'default_transport=smtp'
  postconf -e 'relay_transport=smtp'
  postconf -e 'relay_domains='
  postfix reload
}

if [ -f /docker-init.d/10-jirmail-inbound.sh ] && [ -f /docker-init.d/31-jirmail-transport-maps.sh ]; then
  sh /docker-init.d/10-jirmail-inbound.sh
  sh /docker-init.d/31-jirmail-transport-maps.sh
  [ -f /docker-init.d/30-jirmail-outbound-smtp.sh ] && sh /docker-init.d/30-jirmail-outbound-smtp.sh || true
fi

if _gmail_routing_bad; then
  echo "[fix-postfix-pgsql] gmail.com hâlâ yerel — doğru SQL ile zorla yazılıyor"
  _force_write_maps
fi

if _gmail_routing_bad; then
  echo "HATA: gmail.com routing düzelmedi" >&2
  postmap -q gmail.com pgsql:/etc/postfix/pgsql-virtual-domains.cf 2>&1 || true
  postmap -q gmail.com pgsql:/etc/postfix/pgsql-transport-maps.cf 2>&1 || true
  exit 1
fi

echo "OK: pgsql maps yenilendi (dbname=$DB_NAME)"
postmap -q gmail.com pgsql:/etc/postfix/pgsql-virtual-domains.cf 2>/dev/null || true
postmap -q gmail.com pgsql:/etc/postfix/pgsql-transport-maps.cf 2>/dev/null || true
