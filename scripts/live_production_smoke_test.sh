#!/usr/bin/env bash
set -Eeuo pipefail

BASE_URL="${1:-http://127.0.0.1:8005}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-30}"

pass=0
fail=0

test_endpoint() {
  local name="$1"
  local path="$2"
  local required_text="${3:-}"
  local body_file
  local status

  body_file="$(mktemp)"
  status="$(curl --silent --show-error \
    --connect-timeout 5 \
    --max-time "$TIMEOUT_SECONDS" \
    --output "$body_file" \
    --write-out '%{http_code}' \
    "$BASE_URL$path" || true)"

  if [[ "$status" != "200" ]]; then
    echo "FAIL  $name: HTTP ${status:-curl-error} ($path)"
    sed -n '1,12p' "$body_file" || true
    fail=$((fail + 1))
    rm -f "$body_file"
    return
  fi

  if [[ -n "$required_text" ]] && ! grep -Fq "$required_text" "$body_file"; then
    echo "FAIL  $name: HTTP 200 but response did not contain: $required_text"
    sed -n '1,12p' "$body_file" || true
    fail=$((fail + 1))
    rm -f "$body_file"
    return
  fi

  echo "PASS  $name: HTTP 200"
  pass=$((pass + 1))
  rm -f "$body_file"
}

echo "DocSync live production smoke test"
echo "Target: $BASE_URL"
echo

# Read-only checks only. This script does not create, update, post, migrate,
# delete, or otherwise mutate documents or Business Central records.
test_endpoint "API health" "/api/health"
test_endpoint "Migration compatibility routes" "/api/migration/supported-types" "supported_doc_types"
test_endpoint "Business Central companies" "/api/bc/companies" "Gamer Packaging"
test_endpoint "Inbox metrics" "/api/dashboard/inbox-metrics?scope=all"
test_endpoint "Inbox stats" "/api/dashboard/inbox-stats"
test_endpoint "Posting-pattern badge" "/api/posting-patterns/review-queue/badge-count"

echo
echo "Result: $pass passed, $fail failed"

if (( fail > 0 )); then
  echo "Smoke test failed. Review: docker logs gpi-backend --tail 200"
  exit 1
fi

echo "All live read-only checks passed."
