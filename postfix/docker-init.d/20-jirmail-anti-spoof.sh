#!/bin/sh
# Gelen posta (port 25): dış sunucuların yerel domaini From olarak spoof etmesini engelle
set -e

DOMAIN="${MAIL_DOMAIN:-mail.local}"
DB_HOST="${DB_HOST:-postgres}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-${POSTGRES_DB:-jir_mail_prod}}"
DB_USER="${DB_USER:-postgres}"
export PGPASSWORD="${DB_PASS}"

REGEXP_FILE="/etc/postfix/reject_local_sender_spoof.regexp"
{
  echo "# Jîr-Mail — yerel domain spoof engeli (yalnızca port 25 / smtp)"
  echo "/^.*@${DOMAIN}\$/ REJECT 5.7.1 Bu adres yalnizca yetkili sunucudan gonderilebilir (spoof engellendi)"
  if command -v psql >/dev/null 2>&1 && [ -n "$DB_PASS" ]; then
    psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -A 2>/dev/null \
      -c "SELECT name FROM core_maildomain WHERE is_active = true" \
      | while IFS= read -r d; do
          d=$(echo "$d" | tr -d '[:space:]')
          [ -z "$d" ] && continue
          [ "$d" = "$DOMAIN" ] && continue
          esc=$(echo "$d" | sed 's/\./\\./g')
          echo "/^.*@${esc}\$/ REJECT 5.7.1 Bu adres yalnizca yetkili sunucudan gonderilebilir (spoof engellendi)"
        done || true
  fi
} >"$REGEXP_FILE"
chmod 644 "$REGEXP_FILE"

# Port 25 (smtp): dış bağlantıda yerel domain From → red
if postconf -Mf smtp/inet >/dev/null 2>&1; then
  postconf -P smtp/inet/smtpd_sender_restrictions \
    "permit_mynetworks,permit_sasl_authenticated,check_sender_access regexp:${REGEXP_FILE},permit" \
    2>/dev/null || true
fi

echo "[jirmail-postfix] Anti-spoof aktif (smtp/inet, domains=${DOMAIN}+DB)"
