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
###############################################################################

BASE_URL="${BC_EVENTS_BASE_URL:-http://127.0.0.1:8010/api}"
EXPECTED_EVENTS="${BC_EVENTS_EXPECTED_EVENTS:-4}"
EXPECTED_DOCS="${BC_EVENTS_EXPECTED_DOCS:-4}"

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

post_json() {
  local endpoint="$1"
  local file="$2"

  need_file "$file"
  log "POST ${endpoint} using ${file}"

  curl -fsS \
    -X POST "${BASE_URL}${endpoint}" \
    -H 'Content-Type: application/json' \
    -d "@${file}" \
    | python3 -m json.tool
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

main() {
  need_command curl
  need_command python3

  cd "$(dirname "$0")/.."

  log "BC Document Events Smoke Test"
  log "Base URL: ${BASE_URL}"

  log "Checking status endpoint."
  get_json "/bc-document-events/status"

  post_json "/bc-document-events/delivery-sent" "scripts/sample_bc_delivery_sent_event.json"
  post_json "/bc-document-events/delivery-failed" "scripts/sample_bc_delivery_failed_event.json"
  post_json "/bc-document-events/attachment-linked" "scripts/sample_bc_attachment_linked_event.json"
  post_json "/bc-document-events/attachment-sync-failed" "scripts/sample_bc_attachment_sync_failed_event.json"

  log "Checking idempotency by reposting delivery-sent sample."
  duplicate_response="$(curl -fsS \
    -X POST "${BASE_URL}/bc-document-events/delivery-sent" \
    -H 'Content-Type: application/json' \
    -d @scripts/sample_bc_delivery_sent_event.json)"

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
