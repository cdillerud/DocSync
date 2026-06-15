#!/usr/bin/env bash
set -Eeuo pipefail

# Deploys the isolated BC/GPI Hub sandbox from the Sprint 1 branch and then
# switches the backend container to the preview-only server_sprint1 entry point.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${GPI_SANDBOX_DIR:-/opt/gpi-hub-bc-sandbox}"
PROJECT_NAME="${GPI_SANDBOX_PROJECT_NAME:-gpi-hub-bc-sandbox}"
COMPOSE_FILE="docker-compose.bc-sandbox.yml"
COMPOSE_PATH="${APP_DIR}/${COMPOSE_FILE}"
ENV_PATH="${APP_DIR}/backend/.env"
BACKEND_PORT="${GPI_SANDBOX_BACKEND_PORT:-8010}"

export GPI_SANDBOX_BRANCH="${GPI_SANDBOX_BRANCH:-feature/sprint1-order-confirmation-preflight}"

"${SCRIPT_DIR}/deploy_bc_sandbox.sh" "$@"

if [[ ! -f "$COMPOSE_PATH" ]]; then
  echo "[ERROR] Expected compose file was not created: ${COMPOSE_PATH}" >&2
  exit 1
fi

if [[ ! -f "$ENV_PATH" ]]; then
  echo "[ERROR] Expected sandbox environment file was not created: ${ENV_PATH}" >&2
  exit 1
fi

if ! grep -q '^BC_DOCUMENT_EVENTS_API_KEY=' "$ENV_PATH"; then
  if command -v openssl >/dev/null 2>&1; then
    API_KEY="$(openssl rand -hex 32)"
  else
    API_KEY="$(python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"
  fi

  {
    echo ""
    echo "# Sprint 1 Business Central preflight API authentication"
    echo "BC_DOCUMENT_EVENTS_API_KEY=${API_KEY}"
    echo "BC_DOCUMENT_EVENTS_REQUIRE_API_KEY=true"
  } >> "$ENV_PATH"
  chmod 600 "$ENV_PATH"
  echo "[INFO] Added a new Sprint 1 API key to ${ENV_PATH}."
else
  API_KEY="$(grep '^BC_DOCUMENT_EVENTS_API_KEY=' "$ENV_PATH" | tail -n 1 | cut -d= -f2-)"
  echo "[INFO] Reusing the existing Sprint 1 API key from ${ENV_PATH}."
fi

python3 - "$COMPOSE_PATH" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
command = '    command: ["uvicorn", "server_sprint1:app", "--host", "0.0.0.0", "--port", "8001"]\n'

if 'server_sprint1:app' not in text:
    needle = '      dockerfile: Dockerfile\n'
    if needle not in text:
        raise SystemExit('Could not find the backend Dockerfile line in the generated compose file')
    text = text.replace(needle, needle + command, 1)
    path.write_text(text)
PY

cd "$APP_DIR"

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
elif sudo docker compose version >/dev/null 2>&1; then
  COMPOSE=(sudo docker compose)
else
  echo "[ERROR] Docker Compose is not available." >&2
  exit 1
fi

"${COMPOSE[@]}" -p "$PROJECT_NAME" -f "$COMPOSE_PATH" up -d --build backend

for attempt in $(seq 1 45); do
  if curl -fsS "http://127.0.0.1:${BACKEND_PORT}/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo ""
echo "Sprint 1 backend status:"
curl -fsS \
  -H "X-GPI-Hub-Api-Key: ${API_KEY}" \
  "http://127.0.0.1:${BACKEND_PORT}/api/document-delivery/v1/status" \
  | python3 -m json.tool

echo ""
echo "Business Central setup values:"
echo "  Hub Base URL: use the approved public HTTPS tunnel URL for port ${BACKEND_PORT}"
echo "  API Key: ${API_KEY}"
echo "  Integration Enabled: false until Test Connection succeeds, then true"
echo ""
echo "The key was also saved in ${ENV_PATH}."
