#!/usr/bin/env bash
set -Eeuo pipefail

###############################################################################
# Apply BC Document Events router wiring to the sandbox branch.
#
# This script is intentionally idempotent. It patches:
#   - backend/server.py      current running monolith
#   - backend/server_new.py  prepared refactor entry point
#
# It does not enable email polling or BC writes.
###############################################################################

APP_DIR="${GPI_SANDBOX_DIR:-/opt/gpi-hub-bc-sandbox}"
PROJECT_NAME="${GPI_SANDBOX_PROJECT_NAME:-gpi-hub-bc-sandbox}"
COMPOSE_FILE="${GPI_SANDBOX_COMPOSE_FILE:-docker-compose.bc-sandbox.yml}"
BRANCH="${GPI_SANDBOX_BRANCH:-feature/bc-document-delivery-gpihub}"

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

patch_server_py() {
  local file="backend/server.py"
  [[ -f "$file" ]] || fail "Missing ${file}"

  log "Patching ${file}."

  if ! grep -q 'from routes.bc_document_events import router as bc_document_events_router' "$file"; then
    python3 - <<'PY'
from pathlib import Path
p = Path('backend/server.py')
s = p.read_text()
needle = '# ==================== SPIRO INTEGRATION ====================\nfrom routes.spiro import spiro_router, set_spiro_routes_db\nfrom services.spiro.spiro_sync import set_spiro_db\n'
insert = needle + '\n# ==================== BC DOCUMENT EVENTS ====================\nfrom routes.bc_document_events import router as bc_document_events_router, set_db as set_bc_document_events_db\n'
if needle not in s:
    raise SystemExit('Could not find Spiro import block in backend/server.py')
s = s.replace(needle, insert, 1)
p.write_text(s)
PY
  else
    log "${file}: BC document events import already present."
  fi

  if ! grep -q 'app.include_router(bc_document_events_router, prefix="/api")' "$file"; then
    python3 - <<'PY'
from pathlib import Path
p = Path('backend/server.py')
s = p.read_text()
needle = 'app.include_router(spiro_router)\n'
insert = needle + '# BC Document Events Module\napp.include_router(bc_document_events_router, prefix="/api")\n'
if needle not in s:
    raise SystemExit('Could not find router include block in backend/server.py')
s = s.replace(needle, insert, 1)
p.write_text(s)
PY
  else
    log "${file}: router include already present."
  fi

  if ! grep -q 'set_bc_document_events_db(db)' "$file"; then
    python3 - <<'PY'
from pathlib import Path
p = Path('backend/server.py')
s = p.read_text()
needle = '    set_spiro_db(db)\n    set_spiro_routes_db(db)\n'
insert = needle + '    # BC Document Events: Initialize database\n    set_bc_document_events_db(db)\n'
if needle not in s:
    raise SystemExit('Could not find startup dependency block in backend/server.py')
s = s.replace(needle, insert, 1)
p.write_text(s)
PY
  else
    log "${file}: db dependency already present."
  fi

  if ! grep -q 'bc_document_events.create_index("event_id"' "$file"; then
    python3 - <<'PY'
from pathlib import Path
p = Path('backend/server.py')
s = p.read_text()
needle = '    # AP Review indexes\n    await db.hub_documents.create_index("review_status")\n    await db.hub_documents.create_index("bc_posting_status")\n    await db.hub_documents.create_index("vendor_id")\n'
insert = needle + '    # BC Document Events indexes\n    await db.hub_documents.create_index("bc_document_event_key")\n    await db.hub_documents.create_index("bc_source.record_type")\n    await db.hub_documents.create_index("bc_source.record_no")\n    await db.hub_documents.create_index("last_bc_event_utc")\n    await db.bc_document_events.create_index("event_id", unique=True)\n    await db.bc_document_events.create_index("hub_document_id")\n    await db.bc_document_events.create_index("bc_document_event_key")\n    await db.bc_document_events.create_index("bc_source.record_type")\n    await db.bc_document_events.create_index("bc_source.record_no")\n    await db.bc_document_events.create_index("received_utc")\n'
if needle not in s:
    raise SystemExit('Could not find AP Review index block in backend/server.py')
s = s.replace(needle, insert, 1)
p.write_text(s)
PY
  else
    log "${file}: BC document event indexes already present."
  fi
}

patch_server_new_py() {
  local file="backend/server_new.py"
  [[ -f "$file" ]] || fail "Missing ${file}"

  log "Patching ${file}."

  if ! grep -q 'bc_document_events' "$file"; then
    python3 - <<'PY'
from pathlib import Path
p = Path('backend/server_new.py')
s = p.read_text()
s = s.replace('from routes import documents, ingestion, workflows, dashboard, config', 'from routes import documents, ingestion, workflows, dashboard, config, bc_document_events', 1)
s = s.replace('    config.set_db(db)\n', '    config.set_db(db)\n    bc_document_events.set_db(db)\n', 1)
s = s.replace('    await db.hub_documents.create_index("created_utc")\n', '    await db.hub_documents.create_index("created_utc")\n    await db.hub_documents.create_index("bc_document_event_key")\n    await db.hub_documents.create_index("bc_source.record_type")\n    await db.hub_documents.create_index("bc_source.record_no")\n    await db.hub_documents.create_index("last_bc_event_utc")\n', 1)
s = s.replace('    # Mailboxes\n', '    # BC Document Events\n    await db.bc_document_events.create_index("event_id", unique=True)\n    await db.bc_document_events.create_index("hub_document_id")\n    await db.bc_document_events.create_index("bc_document_event_key")\n    await db.bc_document_events.create_index("bc_source.record_type")\n    await db.bc_document_events.create_index("bc_source.record_no")\n    await db.bc_document_events.create_index("received_utc")\n\n    # Mailboxes\n', 1)
s = s.replace('api_router.include_router(config.router)\n', 'api_router.include_router(config.router)\napi_router.include_router(bc_document_events.router)\n', 1)
p.write_text(s)
PY
  else
    log "${file}: BC document events wiring already present."
  fi
}

verify_python_imports() {
  log "Verifying Python syntax/importability."
  python3 -m py_compile backend/routes/bc_document_events.py
  python3 -m py_compile backend/server.py
  python3 -m py_compile backend/server_new.py
}

restart_sandbox() {
  log "Rebuilding and restarting sandbox backend."
  docker_compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" build --no-cache backend
  docker_compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up -d backend frontend
}

smoke_test() {
  log "Waiting for backend health."
  for i in $(seq 1 45); do
    if curl -fsS http://127.0.0.1:8010/api/health >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done

  log "Testing BC document events status endpoint."
  curl -fsS http://127.0.0.1:8010/api/bc-document-events/status | python3 -m json.tool
}

main() {
  [[ -d "$APP_DIR" ]] || fail "Sandbox directory not found: ${APP_DIR}"
  cd "$APP_DIR"

  log "Fetching latest ${BRANCH}."
  git fetch origin "$BRANCH"
  git checkout "$BRANCH"
  git pull --ff-only origin "$BRANCH"

  patch_server_py
  patch_server_new_py
  verify_python_imports
  restart_sandbox
  smoke_test

  cat <<EOF

Done.

Status endpoint:
  http://localhost:3010/api/bc-document-events/status

VM-local backend status:
  curl http://127.0.0.1:8010/api/bc-document-events/status

Example delivery event test:
  curl -X POST http://127.0.0.1:8010/api/bc-document-events/delivery-sent \\
    -H 'Content-Type: application/json' \\
    -d @scripts/sample_bc_delivery_sent_event.json
EOF
}

main "$@"
