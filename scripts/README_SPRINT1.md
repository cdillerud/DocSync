# Sprint 1 Sandbox Runbook

Run these commands on the GPI Hub VM from a clone that contains this branch.

## Deploy or refresh the isolated sandbox

```bash
cd /opt/gpi-hub-bc-sandbox
bash scripts/deploy_sprint1_preflight.sh
```

The wrapper forces:

```text
feature/sprint1-order-confirmation-preflight
```

It preserves the existing isolated MongoDB volume unless `GPI_SANDBOX_RESET_DB=true` is supplied, disables mailbox polling and BC production writes, starts `server_sprint1:app`, creates a BC document-events API key when one is missing, and prints the values needed for Business Central setup.

## Test the Hub preflight API locally on the VM

```bash
cd /opt/gpi-hub-bc-sandbox
bash scripts/test_sprint1_preflight.sh
```

The smoke test verifies:

- The Sprint 1 status endpoint is ready.
- Email sending is disabled.
- BC and SharePoint writes are disabled.
- The sample Sales Order Confirmation package reaches `PREFLIGHT_READY`.
- Report 50020 and the expected PDF name are returned.

## Expose the sandbox to Business Central

Business Central SaaS cannot call the VM loopback URL. Start the existing approved HTTPS tunnel/proxy workflow for port 8010:

```bash
cd /opt/gpi-hub-bc-sandbox
bash scripts/start_bc_sandbox_https_tunnel.sh
```

Use the public HTTPS base URL printed by that script as the GPI Hub Base URL in Business Central.

## Business Central setup

Install extension version `0.2.0.0` in the BC sandbox, assign permission set `GPI DOC DELIVERY`, then open:

```text
GPI Document Delivery Setup
```

Enter:

- **GPI Hub Base URL:** public HTTPS tunnel URL, without a trailing slash
- **API Key:** value printed by `deploy_sprint1_preflight.sh`
- **Environment Name:** BC sandbox environment name
- **Company ID:** sandbox company ID or approved placeholder for the pilot
- **Company Name:** Gamer Packaging
- **Log Successful Events:** enabled
- **Integration Enabled:** disabled initially

Run **Test Connection**. After it succeeds, enable **Integration Enabled**.

## Business Central pilot test

1. Open a Sales Order with a sell-to customer and customer email.
2. Confirm the Salesperson Code is populated when OSR copy behavior is expected.
3. Select **Preview GPI Order Confirmation**.
4. Verify the preview page shows the expected From, To, CC, subject, body, report ID, and SharePoint path.
5. Select **Preview PDF** and compare report 50020 to the existing Zetadocs output.
6. Confirm no email was created or sent and no SharePoint file was written.
7. Review **GPI Document Delivery Log** in BC and the delivery package in GPI Hub.

## Useful diagnostics

```bash
cd /opt/gpi-hub-bc-sandbox

docker compose -p gpi-hub-bc-sandbox -f docker-compose.bc-sandbox.yml ps
docker compose -p gpi-hub-bc-sandbox -f docker-compose.bc-sandbox.yml logs -f backend
curl -fsS http://127.0.0.1:8010/api/health | python3 -m json.tool
```

The Sprint 1 action remains preview-only. Do not add automated sending until routing and report parity are signed off.
