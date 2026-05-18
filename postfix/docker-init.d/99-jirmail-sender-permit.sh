#!/bin/sh
# Submission (587): yalnızca kimliği doğrulanmış gönderim — global permit yok (inbound spoof açmaz)
set -e

if postconf -Mf submission/inet >/dev/null 2>&1; then
  postconf -P submission/inet/smtpd_sender_restrictions \
    "permit_mynetworks,permit_sasl_authenticated,reject" \
    2>/dev/null || true
  echo "[jirmail-postfix] submission/inet sender: SASL/mynetworks"
else
  echo "[jirmail-postfix] submission/inet yok — SASL gönderim master.cf kontrol edin"
fi
