#!/bin/sh
# Ortak Postfix init yardımcıları (source ile yüklenir)

_write_pgsql_cf() {
  _dest="$1"
  _query="$2"
  _hosts="${DB_HOST:-postgres}"
  if [ -n "${DB_PORT:-}" ] && [ "${DB_PORT}" != "5432" ]; then
    _hosts="${DB_HOST}:${DB_PORT}"
  fi
  {
    printf 'hosts = %s\n' "$_hosts"
    printf 'user = %s\n' "${DB_USER:-postgres}"
    printf 'password = %s\n' "${DB_PASS:-}"
    printf 'dbname = %s\n' "${DB_NAME:-jir_mail_prod}"
    printf 'query = %s\n' "$_query"
  } >"$_dest"
  chmod 600 "$_dest"
}

# Init script'leri genelde postfix start'tan önce çalışır — reload yalnızca master varken
_postfix_reload_if_running() {
  if postfix status >/dev/null 2>&1; then
    postfix reload 2>/dev/null || true
  else
    echo "[jirmail-postfix] postfix henüz çalışmıyor — reload atlandı (konteyner restart ile yüklenecek)"
  fi
}

_strip_legacy_pgsql_port_lines() {
  for _f in /etc/postfix/pgsql-*.cf; do
    [ -f "$_f" ] || continue
    if grep -q '^port = ' "$_f" 2>/dev/null; then
      sed -i '/^port = /d' "$_f"
      echo "[jirmail-postfix] eski port= satırı kaldırıldı: $_f"
    fi
  done
}

# core/mail_domains.py RESERVED_PUBLIC_DOMAINS ile senkron
_jir_sql_exclude_reserved_domains() {
  printf '%s' "AND d.name NOT IN ('aol.com', 'gmail.com', 'googlemail.com', 'gmx.com', 'gmx.net', 'hotmail.com', 'icloud.com', 'live.com', 'mac.com', 'mail.ru', 'me.com', 'msn.com', 'outlook.com', 'pm.me', 'proton.me', 'protonmail.com', 'tuta.io', 'tutanota.com', 'yahoo.com', 'yahoo.com.tr', 'yandex.com', 'yandex.com.tr', 'zoho.com')"
}
