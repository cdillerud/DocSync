#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.sales-order-test.yml"
PROJECT_NAME="gpi-sales-order-test"
BACKEND_CONTAINER="gpi-sales-order-test-backend"

cd "${ROOT_DIR}"

echo "Validating isolated Compose configuration..."
docker compose \
  -p "${PROJECT_NAME}" \
  -f "${COMPOSE_FILE}" \
  config >/dev/null

echo "Building and starting isolated MongoDB and backend..."
docker compose \
  -p "${PROJECT_NAME}" \
  -f "${COMPOSE_FILE}" \
  up -d --build

echo "Waiting for the isolated backend health check..."
for attempt in $(seq 1 60); do
  status="$(
    docker inspect \
      --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
      "${BACKEND_CONTAINER}" 2>/dev/null || true
  )"

  if [[ "${status}" == "healthy" ]]; then
    break
  fi

  if [[ "${status}" == "unhealthy" ]]; then
    echo "Backend became unhealthy. Recent logs:" >&2
    docker logs --tail 200 "${BACKEND_CONTAINER}" >&2 || true
    exit 1
  fi

  if [[ "${attempt}" == "60" ]]; then
    echo "Backend did not become healthy. Recent logs:" >&2
    docker logs --tail 200 "${BACKEND_CONTAINER}" >&2 || true
    exit 1
  fi

  sleep 2
done

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

echo
echo "Sales-order test stack is healthy and remains in shadow mode."
echo "Backend: http://127.0.0.1:18001"
echo "MongoDB: mongodb://127.0.0.1:27028/gpi_sales_order_test"
echo
echo "Stop without deleting test data:"
echo "  docker compose -p ${PROJECT_NAME} -f ${COMPOSE_FILE} down"
echo
echo "Stop and delete isolated test data:"
echo "  docker compose -p ${PROJECT_NAME} -f ${COMPOSE_FILE} down -v"
