#!/usr/bin/env bash
set -Eeuo pipefail

###############################################################################
# Start Temporary HTTPS Tunnel for GPI Hub BC Sandbox
#
# Purpose:
#   Exposes the isolated BC sandbox stack through a temporary Cloudflare Quick
#   Tunnel so Business Central SaaS can reach the GPI Hub API.
#
# Local target:
#   http://127.0.0.1:3010
#
# Public result:
#   https://<random>.trycloudflare.com
#
# Safety checks:
#   - Confirms sandbox frontend is responding locally.
#   - Confirms backend health is responding locally.
#   - Confirms BC document event API key is configured and required.
#   - Does not expose the backend port directly.
#   - Does not change firewall/NSG rules.
###############################################################################

APP_DIR="${GPI_SANDBOX_DIR:-/opt/gpi-hub-bc-sandbox}"
PROJECT_NAME="${GPI_SANDBOX_PROJECT_NAME:-gpi-hub-bc-sandbox}"
COMPOSE_FILE="${GPI_SANDBOX_COMPOSE_FILE:-docker-compose.bc-sandbox.yml}"
TUNNEL_NAME="${GPI_SANDBOX_TUNNEL_NAME:-gpi-hub-bc-sandbox-cloudflared}"
LOCAL_FRONTEND_URL="${GPI_SANDBOX_LOCAL_FRONTEND_URL:-http://127.0.0.1:3010}"
LOCAL_BACKEND_HEALTH_URL="${GPI_SANDBOX_LOCAL_BACKEND_HEALTH_URL:-http://127.0.0.1:8010/api/health}"
LOCAL_BC_EVENTS_STATUS_URL="${GPI_SANDBOX_LOCAL_BC_EVENTS_STATUS_URL:-http://127.0.0.1:8010/api/bc-document-events/status}"
TUNNEL_IMAGE="${GPI_SANDBOX_TUNNEL_IMAGE:-cloudflare/cloudflared:latest}"
WAIT_SECONDS="${GPI_SANDBOX_TUNNEL_WAIT_SECONDS:-45}"

log() {
  printf '\n[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

fail() {
  printf '\n[ERROR] %s\n' "$*" >&2
  exit 1
}

docker_cmd() {
  if docker ps >/dev/null 2>&1; then
    docker "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo docker "$@"
  else
    fail "Docker is not available for the current user and sudo is not installed."
  fi
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

need_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

wait_for_url() {
  local url="$1"
  local label="$2"
  local max_seconds="$3"
  local start
  local now
  local elapsed

  start="$(date +%s)"
  log "Waiting for ${label}: ${url}"

  while true; do
    if curl -fsS --connect-timeout 2 --max-time 5 "$url" >/tmp/gpi-tunnel-url-check.txt 2>/tmp/gpi-tunnel-url-check.err; then
      log "${label} is responding."
      return 0
    fi

    now="$(date +%s)"
    elapsed=$((now - start))
    if [[ "$elapsed" -ge "$max_seconds" ]]; then
      cat /tmp/gpi-tunnel-url-check.err >&2 || true
      fail "Timed out waiting for ${label}."
    fi

    sleep 2
  done
}

extract_status_field() {
  local field="$1"
  python3 - <<PY
import json
from pathlib import Path
try:
    data = json.loads(Path('/tmp/gpi-tunnel-bc-events-status.json').read_text())
    print(data.get('${field}'))
except Exception:
    print('')
PY
}

verify_safety() {
  wait_for_url "$LOCAL_FRONTEND_URL" "sandbox frontend" 60
  wait_for_url "$LOCAL_BACKEND_HEALTH_URL" "sandbox backend health" 60
  wait_for_url "$LOCAL_BC_EVENTS_STATUS_URL" "BC document events status" 60

  curl -fsS "$LOCAL_BC_EVENTS_STATUS_URL" > /tmp/gpi-tunnel-bc-events-status.json

  local api_key_required
  local api_key_configured
  local writes_to_bc
  local mailbox_polling

  api_key_required="$(extract_status_field api_key_required)"
  api_key_configured="$(extract_status_field api_key_configured)"
  writes_to_bc="$(extract_status_field writes_to_bc)"
  mailbox_polling="$(extract_status_field mailbox_polling)"

  if [[ "$api_key_required" != "True" ]]; then
    cat /tmp/gpi-tunnel-bc-events-status.json | python3 -m json.tool || true
    fail "BC document events API key is not required. Run scripts/harden_bc_sandbox_no_polling.sh first."
  fi

  if [[ "$api_key_configured" != "True" ]]; then
    cat /tmp/gpi-tunnel-bc-events-status.json | python3 -m json.tool || true
    fail "BC document events API key is not configured. Run scripts/harden_bc_sandbox_no_polling.sh first."
  fi

  if [[ "$writes_to_bc" != "False" ]]; then
    cat /tmp/gpi-tunnel-bc-events-status.json | python3 -m json.tool || true
    fail "writes_to_bc is not false. Refusing to expose sandbox."
  fi

  if [[ "$mailbox_polling" != "False" ]]; then
    cat /tmp/gpi-tunnel-bc-events-status.json | python3 -m json.tool || true
    fail "mailbox_polling is not false. Refusing to expose sandbox."
  fi

  log "Safety status confirmed: API key required/configured, BC writes off, mailbox polling off."
}

stop_existing_tunnel() {
  if docker_cmd ps -a --format '{{.Names}}' | grep -qx "$TUNNEL_NAME"; then
    log "Stopping existing tunnel container: ${TUNNEL_NAME}"
    docker_cmd rm -f "$TUNNEL_NAME" >/dev/null 2>&1 || true
  fi
}

start_tunnel() {
  log "Pulling ${TUNNEL_IMAGE}."
  docker_cmd pull "$TUNNEL_IMAGE" >/dev/null

  log "Starting Cloudflare Quick Tunnel to ${LOCAL_FRONTEND_URL}."
  docker_cmd run -d \
    --name "$TUNNEL_NAME" \
    --restart unless-stopped \
    --network host \
    "$TUNNEL_IMAGE" \
    tunnel --url "$LOCAL_FRONTEND_URL" --no-autoupdate >/tmp/gpi-tunnel-container-id.txt
}

get_tunnel_url() {
  local start
  local now
  local elapsed
  local logs
  local url

  start="$(date +%s)"

  while true; do
    logs="$(docker_cmd logs "$TUNNEL_NAME" 2>&1 || true)"
    url="$(printf '%s\n' "$logs" | grep -Eo 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com' | tail -n 1 || true)"

    if [[ -n "$url" ]]; then
      printf '%s' "$url"
      return 0
    fi

    now="$(date +%s)"
    elapsed=$((now - start))
    if [[ "$elapsed" -ge "$WAIT_SECONDS" ]]; then
      printf '%s\n' "$logs" >&2
      fail "Timed out waiting for Cloudflare tunnel URL."
    fi

    sleep 2
  done
}

print_key_hint() {
  local env_file="${APP_DIR}/backend/.env"
  if [[ -f "$env_file" ]]; then
    log "BC setup API key command:"
    cat <<EOF
  grep '^BC_DOCUMENT_EVENTS_API_KEY=' ${env_file}
EOF
  fi
}

main() {
  need_command curl
  need_command python3

  [[ -d "$APP_DIR" ]] || fail "Sandbox directory not found: ${APP_DIR}"
  cd "$APP_DIR"

  [[ -f "$COMPOSE_FILE" ]] || fail "Compose file not found: ${APP_DIR}/${COMPOSE_FILE}"

  log "Current sandbox containers:"
  docker_compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" ps || true

  verify_safety
  stop_existing_tunnel
  start_tunnel

  tunnel_url="$(get_tunnel_url)"

  log "Temporary HTTPS tunnel is ready."
  cat <<EOF

GPI Hub BC Sandbox public URL:
  ${tunnel_url}

Business Central setup value:
  Hub Base URL = ${tunnel_url}

Business Central API key:
  Use the value from BC_DOCUMENT_EVENTS_API_KEY in backend/.env.

Test from VM:
  curl ${tunnel_url}/api/bc-document-events/status | python3 -m json.tool

Tunnel logs:
  docker logs -f ${TUNNEL_NAME}

Stop tunnel:
  docker rm -f ${TUNNEL_NAME}

EOF

  print_key_hint
}

main "$@"
