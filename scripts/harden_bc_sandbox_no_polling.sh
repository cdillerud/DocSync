#!/usr/bin/env bash
set -Eeuo pipefail

###############################################################################
# Harden BC sandbox environment so no email mailbox polling runs.
#
# This is safe to run repeatedly from /opt/gpi-hub-bc-sandbox.
###############################################################################

APP_DIR="${GPI_SANDBOX_DIR:-/opt/gpi-hub-bc-sandbox}"
PROJECT_NAME="${GPI_SANDBOX_PROJECT_NAME:-gpi-hub-bc-sandbox}"
COMPOSE_FILE="${GPI_SANDBOX_COMPOSE_FILE:-docker-compose.bc-sandbox.yml}"
ENV_FILE="${APP_DIR}/backend/.env"

log() {
  printf '\n[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

fail() {
  printf '\n[ERROR] %s\n' "$*" >&2
  exit 1
}

docker_compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  elif command -v sudo >/dev/null 2>&1 && sudo docker compose version >/dev/null 2>&1; then
    sudo docker compose "$@"
  else
    fail "Neither docker compose nor docker-compose is available."
  fi
}

set_env_key() {
  local key="$1"
  local value="$2"
  local file="$3"

  touch "$file"

  if grep -q "^${key}=" "$file"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$file"
  else
    printf '%s=%s\n' "$key" "$value" >> "$file"
  fi
}

get_env_key() {
  local key="$1"
  local file="$2"
  grep -E "^${key}=" "$file" 2>/dev/null | tail -n 1 | cut -d= -f2- || true
}

generate_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  elif command -v python3 >/dev/null 2>&1; then
    python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
  else
    printf 'change-me-%s-%s' "$(date +%s)" "$RANDOM"
  fi
}

ensure_bc_events_api_key() {
  local existing_key
  existing_key="$(get_env_key "BC_DOCUMENT_EVENTS_API_KEY" "$ENV_FILE")"

  if [[ -z "$existing_key" ]]; then
    existing_key="$(generate_secret)"
    set_env_key "BC_DOCUMENT_EVENTS_API_KEY" "$existing_key" "$ENV_FILE"
    log "Generated BC_DOCUMENT_EVENTS_API_KEY for sandbox."
  else
    log "Preserving existing BC_DOCUMENT_EVENTS_API_KEY."
  fi

  set_env_key "BC_DOCUMENT_EVENTS_REQUIRE_API_KEY" "true" "$ENV_FILE"
}

main() {
  [[ -d "$APP_DIR" ]] || fail "Sandbox directory not found: ${APP_DIR}"
  cd "$APP_DIR"

  [[ -f "$COMPOSE_FILE" ]] || fail "Compose file not found: ${APP_DIR}/${COMPOSE_FILE}"

  log "Stopping sandbox containers before applying no-polling hardening."
  docker_compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" down --remove-orphans || true

  log "Forcing all mailbox polling flags off in ${ENV_FILE}."
  set_env_key "EMAIL_POLLING_ENABLED" "false" "$ENV_FILE"
  set_env_key "SALES_EMAIL_POLLING_ENABLED" "false" "$ENV_FILE"
  set_env_key "DYNAMIC_MAILBOX_POLLING_ENABLED" "false" "$ENV_FILE"
  set_env_key "ENABLE_CREATE_DRAFT_HEADER" "false" "$ENV_FILE"
  set_env_key "BC_BLOCK_PRODUCTION_WRITES" "true" "$ENV_FILE"
  set_env_key "PILOT_MODE_ENABLED" "false" "$ENV_FILE"

  # Clear mailbox users so even accidental true flags cannot poll real mailboxes.
  set_env_key "EMAIL_POLLING_USER" "" "$ENV_FILE"
  set_env_key "SALES_EMAIL_POLLING_USER" "" "$ENV_FILE"

  ensure_bc_events_api_key

  # Leave Graph credentials intact for later deliberate testing, but keep polling users blank.
  # If a test requires email access later, restore the user intentionally and only in sandbox.

  log "Current sandbox safety-related environment values:"
  grep -E '^(EMAIL_POLLING_ENABLED|EMAIL_POLLING_USER|SALES_EMAIL_POLLING_ENABLED|SALES_EMAIL_POLLING_USER|DYNAMIC_MAILBOX_POLLING_ENABLED|ENABLE_CREATE_DRAFT_HEADER|BC_BLOCK_PRODUCTION_WRITES|PILOT_MODE_ENABLED|BC_DOCUMENT_EVENTS_REQUIRE_API_KEY)=' "$ENV_FILE" || true
  if grep -q '^BC_DOCUMENT_EVENTS_API_KEY=' "$ENV_FILE"; then
    log "BC_DOCUMENT_EVENTS_API_KEY is configured."
  fi

  log "Restarting sandbox containers."
  docker_compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up -d --build

  log "Sandbox status:"
  docker_compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" ps

  log "Done. Watch backend logs and confirm no SalesPoll or DynamicMailboxWorker polling occurs."
  cat <<EOF

Log command:
  cd ${APP_DIR}
  docker compose -p ${PROJECT_NAME} -f ${COMPOSE_FILE} logs -f backend

Expected:
  - /api/health checks are OK
  - No new [SalesPoll:*] mailbox polling attempts
  - No Graph /mailFolders/Inbox/messages requests
  - /api/bc-document-events/status shows api_key_required=true and api_key_configured=true
EOF
}

main "$@"
