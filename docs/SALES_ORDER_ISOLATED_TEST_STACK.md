# Sales Order Isolated Test Stack

This stack runs beside the production GPI Hub checkout and does not reuse its
containers, database, ports, network, volumes, or Business Central write flags.

## Safety defaults

- Review UI binds only to `127.0.0.1:18080`.
- Backend binds only to `127.0.0.1:18001`.
- MongoDB binds only to `127.0.0.1:27028`.
- Database: `gpi_sales_order_test`.
- `AUTO_CREATE_SALES_ORDER_ENABLED=false`.
- `SALES_ORDER_ALLOW_PO_PRICE_OVERRIDE=false`.
- Business Central runs in mock mode.
- AP and Sales mailbox polling are disabled.
- Graph and email client credentials are blanked in the container environment.
- Daily pilot email summaries are disabled.

## Start, seed, and test

From the feature worktree:

```bash
cd /opt/gpi-hub-sales-order
git pull --ff-only
bash tools/run_sales_order_test_stack.sh
```

The runner will:

1. Validate the Compose file.
2. Build and start isolated MongoDB, backend, and frontend containers.
3. Wait for backend and frontend health checks.
4. Seed nine deterministic customer-order scenarios.
5. Run API smoke tests.
6. Confirm that create-draft remains blocked in shadow mode.
7. Confirm that the browser review route is served.

## Open the review UI from your workstation

The UI is intentionally bound to the VM loopback interface. Create an SSH tunnel
from a local terminal or PowerShell window:

```bash
ssh -L 18080:127.0.0.1:18080 azureuser@VM_IP_OR_HOSTNAME
```

Leave that SSH session open, then browse to:

```text
http://localhost:18080/sales/order-review
```

Use the isolated test login:

```text
Username: admin
Password: admin
```

The browser uses the frontend container's `/api` proxy, so a separate backend
port tunnel is not required.

## Manual API inspection

```bash
curl -s http://127.0.0.1:18001/api/sales/order-intake/status | python -m json.tool

curl -s \
  'http://127.0.0.1:18001/api/sales/order-intake/review?limit=100&refresh_missing=true' \
  | python -m json.tool
```

## Logs

```bash
docker logs --tail 200 gpi-sales-order-test-frontend

docker logs --tail 200 gpi-sales-order-test-backend

docker logs --tail 200 gpi-sales-order-test-mongodb
```

## Stop the stack

Keep the isolated MongoDB data:

```bash
docker compose \
  -p gpi-sales-order-test \
  -f docker-compose.sales-order-test.yml \
  down
```

Delete the isolated volumes and all seeded test data:

```bash
docker compose \
  -p gpi-sales-order-test \
  -f docker-compose.sales-order-test.yml \
  down -v
```

Do not set `AUTO_CREATE_SALES_ORDER_ENABLED=true` in this stack until the
Business Central sandbox contract tests and reviewer workflow are complete.
