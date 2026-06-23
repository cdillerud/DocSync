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
  "frontend/src/components/AppLayout.js"
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
import sys

root = Path(sys.argv[1])

routes_init = root / "backend/routes/__init__.py"
text = routes_init.read_text(encoding="utf-8")
registration = (
    "\n# Register sales-order review endpoints on the existing sales router.\n"
    "from . import sales_order_review as _sales_order_review  # noqa: F401\n"
)
if "sales_order_review as _sales_order_review" not in text:
    marker = "from .dashboard import router as dashboard_router, set_db as set_dashboard_db\n"
    if marker not in text:
        raise SystemExit(f"Could not find route insertion marker in {routes_init}")
    text = text.replace(marker, marker + registration, 1)
    routes_init.write_text(text, encoding="utf-8")

app = root / "frontend/src/App.js"
text = app.read_text(encoding="utf-8")

if 'import AppLayout from "@/components/AppLayout";' not in text:
    old_import = 'import Layout from "@/components/Layout";'
    if old_import not in text:
        raise SystemExit(f"Could not find Layout import in {app}")
    text = text.replace(
        old_import,
        'import AppLayout from "@/components/AppLayout";',
        1,
    )

if 'import SalesOrderReviewPage from "@/pages/SalesOrderReviewPage";' not in text:
    marker = 'import SharePointMigrationPage from "@/pages/SharePointMigrationPage";\n'
    if marker not in text:
        raise SystemExit(f"Could not find page import marker in {app}")
    text = text.replace(
        marker,
        marker + 'import SalesOrderReviewPage from "@/pages/SalesOrderReviewPage";\n',
        1,
    )

text = text.replace(
    '<ProtectedRoute><Layout /></ProtectedRoute>',
    '<ProtectedRoute><AppLayout /></ProtectedRoute>',
)

if 'path="sales/order-review"' not in text:
    marker = '        <Route path="email-parser" element={<EmailParserPage />} />\n'
    if marker not in text:
        raise SystemExit(f"Could not find route insertion marker in {app}")
    text = text.replace(
        marker,
        marker + '        <Route path="sales/order-review" element={<SalesOrderReviewPage />} />\n',
        1,
    )

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

cd "${TARGET_ROOT}"

echo "Compiling the deployed sales-order backend modules..."
docker compose run --rm --no-deps backend \
  python -m py_compile \
    services/sales_order_preflight.py \
    services/sales_order_runtime.py \
    services/sales_order_bc_lookup.py \
    services/sales_order_bc_writer.py \
    services/sales_order_review_service.py \
    routes/sales_order_review.py

echo "Building existing GPI Hub backend and frontend..."
docker compose build backend frontend

echo "Restarting only the existing backend and frontend containers..."
docker compose up -d --no-deps backend frontend

echo "Waiting for the existing frontend..."
for attempt in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8080/api/sales/order-intake/status >/dev/null; then
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
