#!/usr/bin/env bash
# Dokploy "Custom Build / Deploy Command" için önerilen komut.
# Her deploy'da imajları yeniden derler ve TÜM konteynerleri yeniden oluşturur.
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE="${COMPOSE_FILE:-docker-compose.yml}"
PROJECT="${COMPOSE_PROJECT_NAME:-}"
ARGS=(-f "$COMPOSE" up -d --build --force-recreate --remove-orphans)
if [ -n "$PROJECT" ]; then
  ARGS=(-p "$PROJECT" "${ARGS[@]}")
fi
echo "==> docker compose ${ARGS[*]}"
docker compose "${ARGS[@]}"
