#!/usr/bin/env bash
set -Eeuo pipefail

BASE_URL="${GPI_SPRINT1_BASE_URL:-http://127.0.0.1:8010}"
PAYLOAD_FILE="${GPI_SPRINT1_PAYLOAD_FILE:-scripts/sample_document_delivery_preflight.json}"
API_KEY="${BC_DOCUMENT_EVENTS_API_KEY:-}"

if [[ -z "$API_KEY" && -f backend/.env ]]; then
  API_KEY="$(grep '^BC_DOCUMENT_EVENTS_API_KEY=' backend/.env | tail -n 1 | cut -d= -f2-)"
fi

if [[ -z "$API_KEY" ]]; then
  echo "[ERROR] Set BC_DOCUMENT_EVENTS_API_KEY or run from the sandbox repository with backend/.env present." >&2
  exit 1
fi

if [[ ! -f "$PAYLOAD_FILE" ]]; then
  echo "[ERROR] Payload file not found: ${PAYLOAD_FILE}" >&2
  exit 1
fi

status_json="$(curl -fsS \
  -H "X-GPI-Hub-Api-Key: ${API_KEY}" \
  "${BASE_URL}/api/document-delivery/v1/status")"

preflight_json="$(curl -fsS \
  -X POST \
  -H "Content-Type: application/json" \
  -H "X-GPI-Hub-Api-Key: ${API_KEY}" \
  --data "@${PAYLOAD_FILE}" \
  "${BASE_URL}/api/document-delivery/v1/preflight")"

python3 - "$status_json" "$preflight_json" <<'PY'
import json
import sys

status = json.loads(sys.argv[1])
preflight = json.loads(sys.argv[2])
package = preflight.get("package") or {}

assert status.get("status") == "ready", status
assert status.get("delivery_enabled") is False, status
assert status.get("email_sending") is False, status
assert status.get("writes_to_bc") is False, status
assert status.get("writes_to_sharepoint") is False, status

assert preflight.get("success") is True, preflight
assert package.get("status") == "PREFLIGHT_READY", package
assert package.get("delivery_enabled") is False, package
assert package.get("document", {}).get("report_id") == 50020, package
assert package.get("email", {}).get("to"), package
assert package.get("email", {}).get("from"), package

print(json.dumps({
    "status": status,
    "preflight": {
        "duplicate": preflight.get("duplicate"),
        "package_id": package.get("package_id"),
        "correlation_id": package.get("correlation_id"),
        "preflight_status": package.get("status"),
        "routing_rule": package.get("routing", {}).get("routing_rule_applied"),
        "to": package.get("email", {}).get("to"),
        "cc": package.get("email", {}).get("cc"),
        "report_id": package.get("document", {}).get("report_id"),
        "file_name": package.get("document", {}).get("file_name"),
    },
}, indent=2))
PY
