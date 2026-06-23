#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="${SOURCE_ROOT:-/opt/gpi-hub-sales-order}"
TARGET_ROOT="${TARGET_ROOT:-/opt/gpi-hub}"
APPLY="${1:-}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_ROOT="${TARGET_ROOT}/backups/sales-order-shadow-${TIMESTAMP}"

if [[ ! -d "${SOURCE_ROOT}" ]]; then
  echo "Source worktree not found: ${SOURCE_ROOT}" >&2
  exit 1
fi

if [[ ! -d "${TARGET_ROOT}" ]]; then
  echo "Existing GPI Hub worktree not found: ${TARGET_ROOT}" >&2
  exit 1
fi

FILES_TO_COPY=(
  "backend/services/sales_order_preflight.py"
  "backend/services/sales_order_runtime.py"
  "backend/services/sales_order_bc_lookup.py"
  "backend/services/sales_order_bc_writer.py"
  "backend/services/sales_order_review_service.py"
  "backend/routes/sales_order_review.py"
  "frontend/src/pages/SalesOrderReviewPage.js"
)

PATCH_TARGETS=(
  "backend/routes/__init__.py"
  "frontend/src/App.js"
  "backend/.env"
)

echo "Existing stack target: ${TARGET_ROOT}"
echo "Source feature worktree: ${SOURCE_ROOT}"
echo "Existing database remains: gpi_document_hub"
echo "Existing user-facing frontend remains on port 8080"
echo "Existing application layout remains unchanged"
echo "Business Central writes will remain disabled"
echo

if [[ "${APPLY}" != "--apply" ]]; then
  echo "DRY RUN ONLY"
  echo
  echo "Files copied from the feature worktree:"
  printf '  %s\n' "${FILES_TO_COPY[@]}"
  echo
  echo "Files patched in place with backups:"
  printf '  %s\n' "${PATCH_TARGETS[@]}"
  echo
  echo "Run with --apply to deploy:"
  echo "  bash ${SOURCE_ROOT}/tools/deploy_sales_order_shadow_to_existing.sh --apply"
  exit 0
fi

if ! docker inspect gpi-mongodb >/dev/null 2>&1; then
  echo "gpi-mongodb does not exist" >&2
  exit 1
fi

if [[ "$(docker inspect gpi-mongodb --format '{{.State.Running}}')" != "true" ]]; then
  echo "gpi-mongodb is not running" >&2
  exit 1
fi

if ! docker exec gpi-mongodb mongosh --quiet --eval 'quit(db.adminCommand({ping:1}).ok === 1 ? 0 : 1)' >/dev/null; then
  echo "gpi-mongodb did not answer a ping" >&2
  exit 1
fi

mkdir -p "${BACKUP_ROOT}"

backup_file() {
  local relative="$1"
  local source="${TARGET_ROOT}/${relative}"
  if [[ -f "${source}" ]]; then
    mkdir -p "${BACKUP_ROOT}/$(dirname "${relative}")"
    cp -a "${source}" "${BACKUP_ROOT}/${relative}"
  fi
}

for relative in "${FILES_TO_COPY[@]}" "${PATCH_TARGETS[@]}"; do
  backup_file "${relative}"
done

for relative in "${FILES_TO_COPY[@]}"; do
  source_file="${SOURCE_ROOT}/${relative}"
  target_file="${TARGET_ROOT}/${relative}"
  if [[ ! -f "${source_file}" ]]; then
    echo "Required source file missing: ${source_file}" >&2
    exit 1
  fi
  mkdir -p "$(dirname "${target_file}")"
  cp -a "${source_file}" "${target_file}"
done

python3 - "${TARGET_ROOT}" <<'PY'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])

# Register the backend endpoints by import side effect. Appending is intentional:
# production routes/__init__.py may contain local imports or formatting that do not
# match the repository version exactly.
routes_init = root / "backend/routes/__init__.py"
text = routes_init.read_text(encoding="utf-8")
if "sales_order_review as _sales_order_review" not in text:
    if text and not text.endswith("\n"):
        text += "\n"
    text += (
        "\n# Register sales-order review endpoints on the existing sales router.\n"
        "from . import sales_order_review as _sales_order_review  # noqa: F401\n"
    )
    routes_init.write_text(text, encoding="utf-8")

# Preserve the existing Layout and navigation. Only import the page and add its
# child route under the already protected application shell.
app = root / "frontend/src/App.js"
text = app.read_text(encoding="utf-8")

page_import = 'import SalesOrderReviewPage from "@/pages/SalesOrderReviewPage";'
if page_import not in text:
    function_match = re.search(r"^function\s+", text, flags=re.MULTILINE)
    if not function_match:
        raise SystemExit(f"Could not locate the first function in {app}")
    import_region = text[:function_match.start()]
    last_import = list(re.finditer(r"^import\b[^\n]*;\s*$", import_region, flags=re.MULTILINE))
    if not last_import:
        raise SystemExit(f"Could not locate imports in {app}")
    insert_at = last_import[-1].end()
    text = text[:insert_at] + "\n" + page_import + text[insert_at:]

if re.search(r'path\s*=\s*["\']sales/order-review["\']', text) is None:
    route_line = '        <Route path="sales/order-review" element={<SalesOrderReviewPage />} />\n'
    markers = [
        r'(?m)^(\s*<Route\s+path=["\']settings["\'][^\n]*/>\s*)$',
        r'(?m)^(\s*<Route\s+path=["\']email-parser["\'][^\n]*/>\s*)$',
        r'(?m)^(\s*<Route\s+path=["\']queue["\'][^\n]*/>\s*)$',
    ]
    inserted = False
    for pattern in markers:
        match = re.search(pattern, text)
        if match:
            text = text[:match.start()] + route_line + text[match.start():]
            inserted = True
            break
    if not inserted:
        # Fall back to inserting before the first closing Route after the protected
        # parent route. This keeps the route inside the authenticated application.
        protected = re.search(r'<Route\b[^>]*element=\{<ProtectedRoute>', text)
        if not protected:
            raise SystemExit(f"Could not locate the protected parent route in {app}")
        closing = text.find("</Route>", protected.end())
        if closing < 0:
            raise SystemExit(f"Could not locate the protected route closing tag in {app}")
        text = text[:closing] + route_line + text[closing:]

if page_import not in text or 'sales/order-review' not in text:
    raise SystemExit(f"Sales-order page was not registered in {app}")

app.write_text(text, encoding="utf-8")
PY

ENV_FILE="${TARGET_ROOT}/backend/.env"
touch "${ENV_FILE}"

set_env_false() {
  local key="$1"
  if grep -q "^${key}=" "${ENV_FILE}"; then
    sed -i "s/^${key}=.*/${key}=false/" "${ENV_FILE}"
  else
    printf '\n%s=false\n' "${key}" >> "${ENV_FILE}"
  fi
}

set_env_false "AUTO_CREATE_SALES_ORDER_ENABLED"
set_env_false "SALES_ORDER_ALLOW_PO_PRICE_OVERRIDE"

echo "Compiling the deployed sales-order backend modules..."
python3 -m py_compile \
  "${TARGET_ROOT}/backend/services/sales_order_preflight.py" \
  "${TARGET_ROOT}/backend/services/sales_order_runtime.py" \
  "${TARGET_ROOT}/backend/services/sales_order_bc_lookup.py" \
  "${TARGET_ROOT}/backend/services/sales_order_bc_writer.py" \
  "${TARGET_ROOT}/backend/services/sales_order_review_service.py" \
  "${TARGET_ROOT}/backend/routes/sales_order_review.py"

cd "${TARGET_ROOT}"

echo "Building existing GPI Hub backend and frontend..."
docker compose build backend frontend

echo "Restarting only the existing backend and frontend containers..."
docker compose up -d --no-deps backend frontend

echo "Waiting for the existing application..."
for attempt in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8080/api/health >/dev/null 2>&1 && \
     curl -fsS http://127.0.0.1:8080/api/sales/order-intake/status >/dev/null 2>&1; then
    break
  fi
  if [[ "${attempt}" == "60" ]]; then
    echo "Existing app did not become ready. Recent logs:" >&2
    docker logs --tail 200 gpi-backend >&2 || true
    docker logs --tail 200 gpi-frontend >&2 || true
    exit 1
  fi
  sleep 2
done

echo
echo "Shadow review deployment completed."
echo "Backup directory: ${BACKUP_ROOT}"
echo "Review page: http://4.204.41.190:8080/sales/order-review"
echo "Database: gpi_document_hub"
echo "AUTO_CREATE_SALES_ORDER_ENABLED=false"
