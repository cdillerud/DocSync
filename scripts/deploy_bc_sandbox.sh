#!/usr/bin/env bash
set -Eeuo pipefail

###############################################################################
# GPI Hub BC Document Delivery Sandbox Deployment
#
# Purpose:
#   Creates a side-by-side sandbox deployment of GPI Hub on the VM without
#   touching the existing /opt/gpi-hub AP smoke-test stack.
#
# Default sandbox:
#   Directory: /opt/gpi-hub-bc-sandbox
#   Branch:    feature/bc-document-delivery-gpihub
#   Project:   gpi-hub-bc-sandbox
#   Frontend:  http://<vm-ip>:3010
#   Backend:   http://127.0.0.1:8010/api
#   Database:  gpi_hub_bc_sandbox
#
# Safety defaults:
#   EMAIL_POLLING_ENABLED=false
#   ENABLE_CREATE_DRAFT_HEADER=false
#   BC_BLOCK_PRODUCTION_WRITES=true
#   DEMO_MODE=true unless overridden
###############################################################################

APP_NAME="gpi-hub-bc-sandbox"
PROJECT_NAME="${GPI_SANDBOX_PROJECT_NAME:-gpi-hub-bc-sandbox}"
REPO_URL="${GPI_SANDBOX_REPO_URL:-https://github.com/cdillerud/DocSync.git}"
BRANCH="${GPI_SANDBOX_BRANCH:-feature/bc-document-delivery-gpihub}"
APP_DIR="${GPI_SANDBOX_DIR:-/opt/gpi-hub-bc-sandbox}"
PROD_ENV_SOURCE="${GPI_PROD_ENV_SOURCE:-/opt/gpi-hub/backend/.env}"
FRONTEND_PORT="${GPI_SANDBOX_FRONTEND_PORT:-3010}"
BACKEND_PORT="${GPI_SANDBOX_BACKEND_PORT:-8010}"
DB_NAME="${GPI_SANDBOX_DB_NAME:-gpi_hub_bc_sandbox}"
DEMO_MODE_VALUE="${GPI_SANDBOX_DEMO_MODE:-true}"
RESET_DB="${GPI_SANDBOX_RESET_DB:-false}"
PUBLIC_URL="${GPI_SANDBOX_PUBLIC_URL:-}"
COMPOSE_FILE="docker-compose.bc-sandbox.yml"
COMPOSE_PATH="${APP_DIR}/${COMPOSE_FILE}"
ENV_PATH="${APP_DIR}/backend/.env"

log() {
  printf '\n[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

warn() {
  printf '\n[WARNING] %s\n' "$*" >&2
}

fail() {
  printf '\n[ERROR] %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

sudo_prefix() {
  if [[ "$(id -u)" -eq 0 ]]; then
    printf ''
  elif command -v sudo >/dev/null 2>&1; then
    printf 'sudo'
  else
    printf ''
  fi
}

SUDO="$(sudo_prefix)"

run_as_root_if_needed() {
  if [[ -n "$SUDO" ]]; then
    sudo "$@"
  else
    "$@"
  fi
}

init_docker_prefix() {
  if docker ps >/dev/null 2>&1; then
    printf ''
  elif [[ -n "$SUDO" ]]; then
    printf 'sudo'
  else
    printf ''
  fi
}

DOCKER_SUDO=""

docker_compose() {
  if [[ -n "$DOCKER_SUDO" ]]; then
    if docker compose version >/dev/null 2>&1; then
      sudo docker compose "$@"
    elif command -v docker-compose >/dev/null 2>&1; then
      sudo docker-compose "$@"
    else
      fail "Neither 'docker compose' nor 'docker-compose' is available."
    fi
  else
    if docker compose version >/dev/null 2>&1; then
      docker compose "$@"
    elif command -v docker-compose >/dev/null 2>&1; then
      docker-compose "$@"
    else
      fail "Neither 'docker compose' nor 'docker-compose' is available."
    fi
  fi
}

get_azure_public_ip() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsS \
      -H "Metadata:true" \
      --connect-timeout 1 \
      --max-time 2 \
      "http://169.254.169.254/metadata/instance/network/interface/0/ipv4/ipAddress/0/publicIpAddress?api-version=2021-02-01&format=text" \
      2>/dev/null || true
  fi
}

get_first_local_ip() {
  hostname -I 2>/dev/null | awk '{print $1}' || true
}

resolve_public_url() {
  if [[ -n "$PUBLIC_URL" ]]; then
    printf '%s' "$PUBLIC_URL"
    return
  fi

  local ip
  ip="$(get_azure_public_ip)"

  if [[ -z "$ip" ]]; then
    ip="$(get_first_local_ip)"
  fi

  if [[ -z "$ip" ]]; then
    ip="localhost"
  fi

  printf 'http://%s:%s' "$ip" "$FRONTEND_PORT"
}

sanitize_env_from_prod() {
  local source_file="$1"
  local target_file="$2"

  if [[ -f "$source_file" ]]; then
    log "Copying existing environment values from ${source_file}, with sandbox overrides."
    grep -Ev '^(MONGO_URL|DB_NAME|EMAIL_POLLING_ENABLED|ENABLE_CREATE_DRAFT_HEADER|DEMO_MODE|BC_BLOCK_PRODUCTION_WRITES|PILOT_MODE_ENABLED|REACT_APP_BACKEND_URL|ENVIRONMENT|SANDBOX_BRANCH)=' "$source_file" > "$target_file" || true
  else
    log "No production .env found at ${source_file}. Creating a minimal sandbox .env."
    cat > "$target_file" <<'EOF'
# Minimal sandbox environment.
# Add real Graph, SharePoint, BC, and LLM credentials only when needed.
EOF
  fi
}

ensure_jwt_secret() {
  local target_file="$1"

  if grep -q '^JWT_SECRET=' "$target_file" 2>/dev/null; then
    return
  fi

  local secret=""
  if command -v openssl >/dev/null 2>&1; then
    secret="$(openssl rand -hex 32)"
  elif command -v python3 >/dev/null 2>&1; then
    secret="$(python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"
  else
    secret="CHANGE_ME_SANDBOX_JWT_SECRET_$(date +%s)_$RANDOM"
  fi

  {
    echo ""
    echo "JWT_SECRET=${secret}"
  } >> "$target_file"
}

write_sandbox_env() {
  mkdir -p "${APP_DIR}/backend"
  sanitize_env_from_prod "$PROD_ENV_SOURCE" "$ENV_PATH"
  ensure_jwt_secret "$ENV_PATH"

  cat >> "$ENV_PATH" <<EOF

# -----------------------------------------------------------------------------
# BC document delivery sandbox safety overrides
# -----------------------------------------------------------------------------
MONGO_URL=mongodb://mongodb:27017
DB_NAME=${DB_NAME}
EMAIL_POLLING_ENABLED=false
ENABLE_CREATE_DRAFT_HEADER=false
BC_BLOCK_PRODUCTION_WRITES=true
DEMO_MODE=${DEMO_MODE_VALUE}
PILOT_MODE_ENABLED=false
ENVIRONMENT=bc-document-delivery-sandbox
SANDBOX_BRANCH=${BRANCH}
EOF

  chmod 600 "$ENV_PATH"
  log "Sandbox .env written to ${ENV_PATH}."
}

write_compose_file() {
  local resolved_public_url="$1"

  cat > "$COMPOSE_PATH" <<EOF
version: '3.8'

services:
  mongodb:
    image: mongo:6.0
    container_name: ${APP_NAME}-mongodb
    restart: unless-stopped
    volumes:
      - bc_sandbox_mongodb_data:/data/db
    networks:
      - gpi-bc-sandbox-network
    healthcheck:
      test: echo 'db.runCommand("ping").ok' | mongosh localhost:27017/test --quiet
      interval: 30s
      timeout: 10s
      retries: 5

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: ${APP_NAME}-backend
    restart: unless-stopped
    depends_on:
      mongodb:
        condition: service_healthy
    env_file:
      - ./backend/.env
    environment:
      - MONGO_URL=mongodb://mongodb:27017
      - DB_NAME=${DB_NAME}
      - EMAIL_POLLING_ENABLED=false
      - ENABLE_CREATE_DRAFT_HEADER=false
      - BC_BLOCK_PRODUCTION_WRITES=true
      - DEMO_MODE=${DEMO_MODE_VALUE}
      - ENVIRONMENT=bc-document-delivery-sandbox
    volumes:
      - bc_sandbox_uploads_data:/app/uploads
    ports:
      - "127.0.0.1:${BACKEND_PORT}:8001"
    networks:
      - gpi-bc-sandbox-network

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
      args:
        - REACT_APP_BACKEND_URL=${resolved_public_url}
    container_name: ${APP_NAME}-frontend
    restart: unless-stopped
    depends_on:
      - backend
    ports:
      - "${FRONTEND_PORT}:3000"
    networks:
      - gpi-bc-sandbox-network

volumes:
  bc_sandbox_mongodb_data:
    driver: local
  bc_sandbox_uploads_data:
    driver: local

networks:
  gpi-bc-sandbox-network:
    driver: bridge
EOF

  log "Sandbox compose file written to ${COMPOSE_PATH}."
}

clone_or_update_repo() {
  log "Preparing sandbox directory: ${APP_DIR}"
  run_as_root_if_needed mkdir -p "$APP_DIR"
  run_as_root_if_needed chown -R "$(id -u):$(id -g)" "$APP_DIR"

  if [[ ! -d "${APP_DIR}/.git" ]]; then
    if [[ -n "$(find "$APP_DIR" -mindepth 1 -maxdepth 1 2>/dev/null | head -n 1)" ]]; then
      fail "${APP_DIR} is not empty and is not a git repository. Move it aside or set GPI_SANDBOX_DIR to a different path."
    fi

    log "Cloning ${REPO_URL} branch ${BRANCH}."
    git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
  else
    log "Updating existing sandbox repository."
    cd "$APP_DIR"

    if [[ -n "$(git status --porcelain)" ]]; then
      fail "Sandbox repo has uncommitted changes. Commit, stash, or remove them before rerunning this script."
    fi

    git fetch origin "$BRANCH"
    git checkout "$BRANCH"
    git pull --ff-only origin "$BRANCH"
  fi
}

wait_for_url() {
  local name="$1"
  local url="$2"
  local max_attempts="${3:-30}"
  local attempt=1

  while [[ "$attempt" -le "$max_attempts" ]]; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      log "${name} is responding at ${url}."
      return 0
    fi

    sleep 2
    attempt=$((attempt + 1))
  done

  warn "${name} did not respond at ${url} within the expected window. Check logs with the commands printed below."
  return 1
}

print_status() {
  local resolved_public_url="$1"

  log "Sandbox deployment status"
  docker_compose -p "$PROJECT_NAME" -f "$COMPOSE_PATH" ps || true

  cat <<EOF

Sandbox URLs:
  Frontend: ${resolved_public_url}
  Backend health from VM: http://127.0.0.1:${BACKEND_PORT}/api/health

Useful commands:
  cd ${APP_DIR}
  docker compose -p ${PROJECT_NAME} -f ${COMPOSE_FILE} ps
  docker compose -p ${PROJECT_NAME} -f ${COMPOSE_FILE} logs -f backend
  docker compose -p ${PROJECT_NAME} -f ${COMPOSE_FILE} logs -f frontend
  docker compose -p ${PROJECT_NAME} -f ${COMPOSE_FILE} down

To reset the sandbox database on the next run:
  GPI_SANDBOX_RESET_DB=true ${APP_DIR}/scripts/deploy_bc_sandbox.sh

To force a specific browser URL during frontend build:
  GPI_SANDBOX_PUBLIC_URL=http://YOUR_VM_PUBLIC_IP:${FRONTEND_PORT} ${APP_DIR}/scripts/deploy_bc_sandbox.sh

Safety flags currently forced:
  EMAIL_POLLING_ENABLED=false
  ENABLE_CREATE_DRAFT_HEADER=false
  BC_BLOCK_PRODUCTION_WRITES=true
  DEMO_MODE=${DEMO_MODE_VALUE}
  DB_NAME=${DB_NAME}
EOF
}

main() {
  require_command git
  require_command docker
  require_command curl

  DOCKER_SUDO="$(init_docker_prefix)"

  clone_or_update_repo
  cd "$APP_DIR"

  local resolved_public_url
  resolved_public_url="$(resolve_public_url)"
  log "Using frontend public URL: ${resolved_public_url}"

  write_sandbox_env
  write_compose_file "$resolved_public_url"

  log "Stopping any existing sandbox containers for project ${PROJECT_NAME}."
  if [[ "$RESET_DB" == "true" ]]; then
    warn "GPI_SANDBOX_RESET_DB=true set. Sandbox containers and volumes will be removed."
    docker_compose -p "$PROJECT_NAME" -f "$COMPOSE_PATH" down -v --remove-orphans || true
  else
    docker_compose -p "$PROJECT_NAME" -f "$COMPOSE_PATH" down --remove-orphans || true
  fi

  log "Building and starting sandbox stack."
  docker_compose -p "$PROJECT_NAME" -f "$COMPOSE_PATH" up -d --build

  wait_for_url "Backend" "http://127.0.0.1:${BACKEND_PORT}/api/health" 45 || true
  wait_for_url "Frontend" "http://127.0.0.1:${FRONTEND_PORT}" 45 || true

  print_status "$resolved_public_url"
}

main "$@"
