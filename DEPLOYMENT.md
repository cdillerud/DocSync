# GPI Document Hub - Deployment Guide

## Current Cutover Scope

The September 20 Square9 parity cutover is **AP and Warehouse only**. Sales and
Inside Sales remain paused and must not be enabled, redirected, or included in
cutover validation until a later explicitly approved phase.

Production Business Central writes remain blocked during parity/UAT work. Use
`Sandbox_NoZetadocs_UAT` for any write-capable Business Central validation.

## Quick Start

### 1. Copy to VM
```bash
scp -r ./gpi-hub <vm-user>@<vm-host>:/opt/gpi-hub
```

### 2. SSH to VM
```bash
ssh <vm-user>@<vm-host>
cd /opt/gpi-hub
```

### 3. Configure Environment

Create `backend/.env` from the approved runtime-secret source. Do not place real
credentials in `docker-compose.yml`, committed scripts, documentation, or Git.

Required secrets include the Business Central, Microsoft Graph, authentication,
and mailbox credentials used by the deployment. Rotate any credential that has
ever been committed to repository history before using the deployment for UAT
or Production.

### 4. Deploy
```bash
chmod +x deploy.sh
./deploy.sh
```

### 5. Establish the external HTTPS endpoint

The containers may communicate over HTTP on their private Docker network, but
**Business Central and browser users must consume an HTTPS endpoint** terminated
by an approved reverse proxy / load balancer with a valid certificate.

The Business Central **GPI Hub Setup** value must be the external API base and
must end in `/api`, for example:

```text
https://<approved-hub-hostname>/api
```

Do not configure Business Central with an IP-address HTTP URL. The extension is
intentionally fail-closed and rejects non-HTTPS Hub endpoints.

Before publishing/validating the BC extension, confirm:
- DNS resolves the approved Hub hostname.
- The TLS certificate is valid for that hostname.
- `https://<approved-hub-hostname>/api/...` reaches the FastAPI application.
- The reverse proxy preserves `/api/` routing to the backend.
- No Production Business Central write lane has been enabled.

---

## Configuration

### Required Environment Variables

| Variable | Description |
|----------|-------------|
| `TENANT_ID` | Azure AD tenant ID |
| `BC_CLIENT_ID` | Business Central app client ID |
| `BC_CLIENT_SECRET` | Business Central app secret; runtime secret only |
| `GRAPH_CLIENT_ID` | Graph API app client ID |
| `GRAPH_CLIENT_SECRET` | Graph API app secret; runtime secret only |
| `SHAREPOINT_SITE_HOSTNAME` | SharePoint hostname |
| `SHAREPOINT_SITE_PATH` | SharePoint site path |
| `JWT_SECRET` | Strong runtime-only authentication secret |
| `ADMIN_EMAIL` | Hub admin identity |
| `ADMIN_PASSWORD` | Runtime-only Hub admin credential |

### Parity Safety Variables

For UAT parity work, keep the following safety posture:

```text
BC_BLOCK_PRODUCTION_WRITES=true
BC_WRITE_ENVIRONMENT=Sandbox_NoZetadocs_UAT
BC_SALES_LINK_WRITE_ENABLED=false
```

The read environment may be Production where approved for read-only resolution,
but write operations must remain pinned to the sandbox until cutover approval.

### Optional Feature Flags

| Variable | Default | Description |
|----------|---------|-------------|
| `DEMO_MODE` | `false` | Enable demo mode (mock APIs) |
| `EMAIL_POLLING_ENABLED` | `false` | Enable email polling |
| `EMAIL_POLLING_USER` | | Static AP inbox address when that poller is used |

Do not enable Sales/Inside Sales intake or Sales BC-link writes during the AP /
Warehouse parity cutover.

---

## Operations

### View Logs
```bash
sudo docker compose logs -f
sudo docker compose logs -f backend  # Backend only
sudo docker compose logs -f frontend # Frontend only
```

### Restart Services
```bash
sudo docker compose restart
sudo docker compose restart backend  # Backend only
```

### Stop All Services
```bash
sudo docker compose down
```

### Rebuild After Code Changes
```bash
sudo docker compose up -d --build
```

### Check MongoDB
```bash
sudo docker exec -it gpi-mongodb mongosh gpi_document_hub
```

---

## Troubleshooting

### API Not Responding
```bash
sudo docker compose logs backend
sudo docker compose ps
sudo docker compose restart backend
```

For Business Central FactBox failures, test the **external HTTPS** `/api` URL,
not the backend container's private HTTP address.

### MongoDB Connection Issues
```bash
sudo docker exec -it gpi-mongodb mongosh --eval "db.adminCommand('ping')"
sudo docker compose restart mongodb
```

### Frontend Not Loading
```bash
sudo docker compose logs frontend
sudo docker compose exec frontend ls -la /usr/share/nginx/html
```

---

## Security Notes

1. **TLS**: the externally consumed Hub endpoint must use HTTPS with a valid certificate.
2. **MongoDB**: keep it accessible only within the private Docker network.
3. **Backend**: browser/BC traffic should enter through the approved HTTPS reverse proxy.
4. **Secrets**: never commit `.env`, passwords, JWT secrets, or client secrets to Git.
5. **Credential rotation**: any secret previously committed to Git history is considered exposed and must be rotated.
6. **Sales isolation**: Sales/Inside Sales remain disabled for this cutover.
7. **BC write isolation**: Production BC writes remain blocked during UAT.

---

## Architecture

```text
Internet / Business Central
          |
          v
HTTPS :443 (approved TLS reverse proxy / load balancer)
          |
          +--> Frontend (React/nginx)
          |
          +--> /api/* --> Backend (FastAPI) --> MongoDB
                                      |
                                      +--> Microsoft Graph / SharePoint
                                      +--> Business Central APIs
```

Container-internal HTTP is acceptable only behind the trusted TLS boundary.

---

## Square9 AP / Warehouse Cutover Procedure

### Overview

GPI Hub is being validated as the authoritative document-management replacement
for the **AP and Warehouse** Square9 flows. Square9 must not be decommissioned for
those flows until the parity evidence package is complete and accepted.

Sales and Inside Sales are explicitly out of scope for this cutover and remain
on their current process.

### Pre-Cutover Checklist

1. **Permanent CI is green on the exact release commit.**
   Include the Square9 parity, AP, Warehouse, SharePoint, split-provenance,
   deployment-security, UAT-harness, and visibility-evidence gates.

2. **Validate SharePoint schema.**
   Confirm the actual internal names/types for all required `GPI_*` fields and
   `ImportReady` in the UAT document library. Do not infer them from display names.

3. **Publish the BC extension to `Sandbox_NoZetadocs_UAT`.**
   Configure **GPI Hub Setup** with the approved external HTTPS `/api` URL.

4. **Prove exact AP and Warehouse FactBox visibility.**
   Run:
   ```powershell
   .\scripts\Collect-Square9-UAT-Visibility-Evidence.ps1 `
       -HubBaseUrl 'https://<approved-hub-hostname>/api' `
       -APDocumentNo '<known AP document>' `
       -APSystemId '<exact AP SystemId>' `
       -WarehouseDocumentNo '<known posted shipment>' `
       -WarehouseSystemId '<exact warehouse SystemId>'
   ```
   The collector is GET-only and fails unless entity, document number, SystemId,
   linked documents, and HTTPS SharePoint URLs all match.

5. **Validate mailbox sources.**
   Confirm the literal AP and Warehouse receiving mailbox identities are
   preserved in document provenance and in split-child observations.

6. **Run forced recovery tests.**
   Confirm metadata/link failures recover the same SharePoint item without a
   duplicate upload, and split-child retry does not disturb successful siblings.

7. **Reconcile source-to-final counts and exceptions.**
   Zero unexplained parity blockers are allowed at cutover.

### AP / Warehouse Mailbox Transition

Only transition the specific AP and Warehouse mailbox flows included in the
approved parity matrix. For each approved mailbox:
1. Record the exact pre-cutover Square9 routing configuration.
2. Enable the corresponding GPI Hub mailbox source.
3. Verify literal receiving-mailbox provenance on a test message.
4. Verify attachment extraction, classification, BC identity, SharePoint
   metadata, FactBox visibility, and audit state end-to-end.
5. Disable the equivalent Square9 intake only after the GPI Hub path is proven.
6. Keep a documented rollback path for the mailbox rule/source.

Do **not** redirect Sales or Inside Sales mailboxes as part of this cutover.

### Production Cutover

Production cutover is a separately authorized change. Do not infer approval from
successful UAT tests. Before any Production write or mailbox transition:
- obtain explicit cutover approval;
- record the release commit and evidence manifest hashes;
- confirm rollback steps;
- confirm current Production safeguards/settings;
- rotate any previously exposed credentials;
- verify the approved HTTPS Hub endpoint and SharePoint schema.

### Rollback

Rollback must restore the prior AP/Warehouse Square9 mailbox/routing path, stop
new GPI Hub intake for the affected lane, preserve all already-captured audit and
SharePoint evidence, and avoid destructive cleanup. Do not delete documents to
make reconciliation counts match.
