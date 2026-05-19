#!/usr/bin/env bash
set -Eeuo pipefail

###############################################################################
# BC Document Events Smoke Test
#
# Validates the sandbox API surface for Business Central document delivery and
# attachment events.
#
# Safe behavior expected:
#   - API status endpoint responds.
#   - Four sample event types can be posted.
#   - Duplicate delivery-sent event is idempotent.
#   - Event/document counts match.
#   - No orphan events remain.
#   - writes_to_bc remains false.
#   - mailbox_polling remains false.
#   - write endpoints require X-GPI-Hub-Api-Key when configured.
###############################################################################

BASE_URL="${BC_EVENTS_BASE_URL:-http://127.0.0.1:8010/api}"
EXPECTED_EVENTS="${BC_EVENTS_EXPECTED_EVENTS:-4}"
EXPECTED_DOCS="${BC_EVENTS_EXPECTED_DOCS:-4}"
ENV_FILE="${BC_EVENTS_ENV_FILE:-backend/.env}"
API_KEY="${BC_DOCUMENT_EVENTS_API_KEY:-}"
HEALTH_TIMEOUT_SECONDS="${BC_EVENTS_HEALTH_TIMEOUT_SECONDS:-90}"

log() {
  printf '\n[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

fail() {
  printf '\n[FAIL] %s\n' "$*" >&2
  exit 1
}

need_file() {
  [[ -f "$1" ]] || fail "Missing required file: $1"
}

need_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

load_api_key() {
  if [[ -n "$API_KEY" ]]; then
    return
  fi

  if [[ -f "$ENV_FILE" ]]; then
    API_KEY="$(grep -E '^BC_DOCUMENT_EVENTS_API_KEY=' "$ENV_FILE" | tail -n 1 | cut -d= -f2- || true)"
  fi
}

wait_for_endpoint() {
  local endpoint="$1"
  local label="$2"
  local start_time
  local now
  local elapsed
  local response

  start_time="$(date +%s)"
  log "Waiting for ${label} at ${BASE_URL}${endpoint}."

  while true; do
    if response="$(curl -fsS --connect-timeout 2 --max-time 5 "${BASE_URL}${endpoint}" 2>/tmp/bc-events-wait-error.txt)"; then
      log "${label} is responding."
      return 0
    fi

    now="$(date +%s)"
    elapsed=$((now - start_time))
    if [[ "$elapsed" -ge "$HEALTH_TIMEOUT_SECONDS" ]]; then
      cat /tmp/bc-events-wait-error.txt >&2 || true
      fail "Timed out waiting for ${label} after ${HEALTH_TIMEOUT_SECONDS} seconds"
    fi

    sleep 2
  done
}

post_json() {
  local endpoint="$1"
  local file="$2"

  need_file "$file"
  log "POST ${endpoint} using ${file}"

  if [[ -n "$API_KEY" ]]; then
    curl -fsS \
      -X POST "${BASE_URL}${endpoint}" \
      -H "X-GPI-Hub-Api-Key: ${API_KEY}" \
      -H 'Content-Type: application/json' \
      -d "@${file}" \
      | python3 -m json.tool
  else
    curl -fsS \
      -X POST "${BASE_URL}${endpoint}" \
      -H 'Content-Type: application/json' \
      -d "@${file}" \
      | python3 -m json.tool
  fi
}

get_json() {
  local endpoint="$1"
  curl -fsS "${BASE_URL}${endpoint}" | python3 -m json.tool
}

json_value() {
  local json="$1"
  local expr="$2"

  python3 - <<PY
import json
obj = json.loads('''${json}''')
value = obj
for part in '${expr}'.split('.'):
    value = value[part]
print(value)
PY
}

assert_json_equals() {
  local json="$1"
  local expr="$2"
  local expected="$3"
  local actual

  actual="$(json_value "$json" "$expr")"

  if [[ "$actual" != "$expected" ]]; then
    fail "Expected ${expr}=${expected}, got ${actual}"
  fi

  log "OK: ${expr}=${expected}"
}

assert_protected_when_key_configured() {
  local status_json="$1"
  local api_key_configured
  local api_key_required
  local http_code

  api_key_configured="$(json_value "$status_json" "api_key_configured")"
  api_key_required="$(json_value "$status_json" "api_key_required")"

  if [[ "$api_key_configured" != "True" || "$api_key_required" != "True" ]]; then
    log "API key is not configured/required. Skipping unauthenticated rejection check."
    return
  fi

  log "Checking that unauthenticated write request is rejected."
  http_code="$(curl -sS -o /tmp/bc-events-unauth-response.json -w '%{http_code}' \
    -X POST "${BASE_URL}/bc-document-events/delivery-sent" \
    -H 'Content-Type: application/json' \
    -d @scripts/sample_bc_delivery_sent_event.json)"

  if [[ "$http_code" != "401" ]]; then
    cat /tmp/bc-events-unauth-response.json || true
    fail "Expected unauthenticated write to return 401, got ${http_code}"
  fi

  log "OK: unauthenticated write returned 401"
}

main() {
  need_command curl
  need_command python3

  cd "$(dirname "$0")/.."
  load_api_key

  log "BC Document Events Smoke Test"
  log "Base URL: ${BASE_URL}"
  if [[ -n "$API_KEY" ]]; then
    log "API key loaded from environment/.env."
  else
    log "No API key loaded. Write tests will run without X-GPI-Hub-Api-Key."
  fi

  wait_for_endpoint "/health" "backend health"
  wait_for_endpoint "/bc-document-events/status" "BC document events status endpoint"

  log "Checking status endpoint."
  status_before="$(curl -fsS "${BASE_URL}/bc-document-events/status")"
  echo "$status_before" | python3 -m json.tool
  assert_protected_when_key_configured "$status_before"

  post_json "/bc-document-events/delivery-sent" "scripts/sample_bc_delivery_sent_event.json"
  post_json "/bc-document-events/delivery-failed" "scripts/sample_bc_delivery_failed_event.json"
  post_json "/bc-document-events/attachment-linked" "scripts/sample_bc_attachment_linked_event.json"
  post_json "/bc-document-events/attachment-sync-failed" "scripts/sample_bc_attachment_sync_failed_event.json"

  log "Checking idempotency by reposting delivery-sent sample."
  if [[ -n "$API_KEY" ]]; then
    duplicate_response="$(curl -fsS \
      -X POST "${BASE_URL}/bc-document-events/delivery-sent" \
      -H "X-GPI-Hub-Api-Key: ${API_KEY}" \
      -H 'Content-Type: application/json' \
      -d @scripts/sample_bc_delivery_sent_event.json)"
  else
    duplicate_response="$(curl -fsS \
      -X POST "${BASE_URL}/bc-document-events/delivery-sent" \
      -H 'Content-Type: application/json' \
      -d @scripts/sample_bc_delivery_sent_event.json)"
  fi

  echo "$duplicate_response" | python3 -m json.tool
  assert_json_equals "$duplicate_response" "duplicate" "True"
  assert_json_equals "$duplicate_response" "orphaned_document" "False"

  log "Checking final status."
  status_json="$(curl -fsS "${BASE_URL}/bc-document-events/status")"
  echo "$status_json" | python3 -m json.tool

  assert_json_equals "$status_json" "status" "ready"
  assert_json_equals "$status_json" "events_recorded" "$EXPECTED_EVENTS"
  assert_json_equals "$status_json" "bc_event_documents" "$EXPECTED_DOCS"
  assert_json_equals "$status_json" "orphan_events" "0"
  assert_json_equals "$status_json" "writes_to_bc" "False"
  assert_json_equals "$status_json" "mailbox_polling" "False"

  log "Checking sample record lookup."
  get_json "/bc-document-events/records/Posted%20Sales%20Invoice/SAMPLE-INV-001"

  log "BC Document Events smoke test passed."
}

main "$@"
