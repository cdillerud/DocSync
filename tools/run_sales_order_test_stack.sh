#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.sales-order-test.yml"
PROJECT_NAME="gpi-sales-order-test"
BACKEND_CONTAINER="gpi-sales-order-test-backend"
FRONTEND_CONTAINER="gpi-sales-order-test-frontend"

cd "${ROOT_DIR}"

wait_for_healthy() {
  local container="$1"
  local label="$2"

  echo "Waiting for the isolated ${label} health check..."
  for attempt in $(seq 1 90); do
    status="$(
      docker inspect \
        --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
        "${container}" 2>/dev/null || true
    )"

    if [[ "${status}" == "healthy" ]]; then
      return 0
    fi

    if [[ "${status}" == "unhealthy" ]]; then
      echo "${label} became unhealthy. Recent logs:" >&2
      docker logs --tail 200 "${container}" >&2 || true
      return 1
    fi

    if [[ "${attempt}" == "90" ]]; then
      echo "${label} did not become healthy. Recent logs:" >&2
      docker logs --tail 200 "${container}" >&2 || true
      return 1
    fi

    sleep 2
  done
}

echo "Validating isolated Compose configuration..."
docker compose \
  -p "${PROJECT_NAME}" \
  -f "${COMPOSE_FILE}" \
  config >/dev/null

echo "Building and starting isolated MongoDB, backend, and frontend..."
docker compose \
  -p "${PROJECT_NAME}" \
  -f "${COMPOSE_FILE}" \
  up -d --build

wait_for_healthy "${BACKEND_CONTAINER}" "backend"
wait_for_healthy "${FRONTEND_CONTAINER}" "frontend"

echo "Seeding deterministic sales-order test documents..."
docker compose \
  -p "${PROJECT_NAME}" \
  -f "${COMPOSE_FILE}" \
  exec -T backend \
  python scripts/seed_sales_order_test_data.py

echo "Running isolated API smoke tests..."
docker compose \
  -p "${PROJECT_NAME}" \
  -f "${COMPOSE_FILE}" \
  exec -T backend \
  python scripts/smoke_sales_order_review.py \
    --base-url http://localhost:8001

echo "Verifying the browser route is served..."
docker compose \
  -p "${PROJECT_NAME}" \
  -f "${COMPOSE_FILE}" \
  exec -T frontend \
  wget -q --spider http://localhost:3000/sales/order-review

echo
echo "Sales-order test stack is healthy and remains in shadow mode."
echo "Review UI: http://127.0.0.1:18080/sales/order-review"
echo "Backend: http://127.0.0.1:18001"
echo "MongoDB: mongodb://127.0.0.1:27028/gpi_sales_order_test"
echo
echo "Stop without deleting test data:"
echo "  docker compose -p ${PROJECT_NAME} -f ${COMPOSE_FILE} down"
echo
echo "Stop and delete isolated test data:"
echo "  docker compose -p ${PROJECT_NAME} -f ${COMPOSE_FILE} down -v"
