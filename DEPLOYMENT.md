# GPI Document Hub - Deployment Guide

## Quick Start

### 1. Copy to VM
```bash
scp -r ./gpi-hub azureuser@4.204.41.190:/opt/gpi-hub
```

### 2. SSH to VM
```bash
ssh azureuser@4.204.41.190
cd /opt/gpi-hub
```

### 3. Configure Environment
```bash
cp backend/.env.example backend/.env
nano backend/.env  # Fill in your values
```

### 4. Deploy
```bash
chmod +x deploy.sh
./deploy.sh
```

### 5. Access
Open http://4.204.41.190 in your browser.

---

## Configuration

### Required Environment Variables

| Variable | Description |
|----------|-------------|
| `TENANT_ID` | Azure AD tenant ID |
| `BC_CLIENT_ID` | Business Central app client ID |
| `BC_CLIENT_SECRET` | Business Central app secret |
| `GRAPH_CLIENT_ID` | Graph API app client ID |
| `GRAPH_CLIENT_SECRET` | Graph API app secret |
| `SHAREPOINT_SITE_HOSTNAME` | e.g., `yourcompany.sharepoint.com` |
| `SHAREPOINT_SITE_PATH` | e.g., `/sites/DocumentHub` |
| `JWT_SECRET` | Strong random secret for auth |
| `EMERGENT_LLM_KEY` | Emergent LLM key for AI classification |

### Optional Feature Flags

| Variable | Default | Description |
|----------|---------|-------------|
| `DEMO_MODE` | `false` | Enable demo mode (mock APIs) |
| `ENABLE_CREATE_DRAFT_HEADER` | `false` | Enable BC draft creation |
| `EMAIL_POLLING_ENABLED` | `false` | Enable email polling |
| `EMAIL_POLLING_USER` | | AP inbox email address |
| `CATALOG_FORWARD_ENABLED` | `false` | Send supplier pricing documents to the Commercial AI catalog inbox (see below) |
| `CATALOG_FORWARD_URL` | | Catalog inbox submit URL |
| `CATALOG_FORWARD_KEY` | | Catalog inbox intake key (secret) |
| `CATALOG_FORWARD_DRY_RUN` | `false` | Decide and log only; send nothing |

### Catalog Forward (supplier pricing to the Packaging Catalog)

When it is on, the Hub sends supplier pricing documents it has just received
by email to the Commercial AI catalog inbox. The inbox reads them and, a few
minutes later, emails the catalog reviewers the usual review (changes,
proposed new products, flagged price moves). It is **off by default**.

**What gets sent:** supplier price lists, supplier quotes, price-increase and
surcharge letters, RFQ responses, and stock / availability / open-inventory
lists (.xlsx, .xlsm, .csv, .pdf, .msg, .eml), recognised from the file name or
email subject, from a supplier (sender outside gamerpackaging.com, or a
supplier read from the document when a Gamer person forwards it). All such
attachments of one email go in one submit.

**What is never sent:** AP invoices, statements, remittances, credit memos,
purchase orders and customer orders (and anything else the classifier gave a
transactional type), Gamer's own quotes to customers (Spiro `QUO-####`
numbers or Gamer letterhead), page-split copies (`*_doc1.pdf`), files over
15 MB, and anything already sent once.

**Turn it on** by adding these lines to `backend/.env` on the Hub VM (the
backend container reads that file) and restarting the backend. The URL and
the key come from the Commercial AI web app (`GPI_CATALOG_INTAKE_KEY` app
setting). Start with a dry run for a few days:

```bash
CATALOG_FORWARD_ENABLED=true
CATALOG_FORWARD_DRY_RUN=true
CATALOG_FORWARD_URL=https://gpi-commercial-ai-v62-uat-4e0833.azurewebsites.net/api/v70/catalog/intake/submit
CATALOG_FORWARD_KEY=<intake key>
```

```bash
sudo docker compose up -d backend
```

Check what it decided at `GET /api/admin/catalog-forward/status` (admin
login; shows recent decisions with reasons, never the key) or in the backend
log (`[CatalogForward]` lines). When the decisions look right, set
`CATALOG_FORWARD_DRY_RUN=false` and restart the backend again. To turn it
off, set `CATALOG_FORWARD_ENABLED=false` (or remove the lines) and restart.

Each document's outcome is kept on its record in `hub_documents`
(`catalog_forward`, and `catalog_forwarded_utc` once the inbox accepted it)
and in the `catalog_forward_log` collection. A failed send is recorded as
`failed` and is not retried automatically. Code: `backend/services/catalog_forward.py`.

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
# Check backend logs
sudo docker compose logs backend

# Check if container is running
sudo docker compose ps

# Restart backend
sudo docker compose restart backend
```

### MongoDB Connection Issues
```bash
# Check MongoDB status
sudo docker exec -it gpi-mongodb mongosh --eval "db.adminCommand('ping')"

# Restart MongoDB
sudo docker compose restart mongodb
```

### Frontend Not Loading
```bash
# Check nginx logs
sudo docker compose logs frontend

# Verify build
sudo docker compose exec frontend ls -la /usr/share/nginx/html
```

---

## Security Notes

1. **Firewall**: Only port 80 is exposed externally
2. **MongoDB**: Only accessible within Docker network
3. **Backend**: Only accessible via nginx proxy
4. **Secrets**: Never commit `.env` to git

---

## Architecture

```
Internet → :80 (nginx) → Frontend (React)
                      → /api/* → Backend (FastAPI) → MongoDB
```

All services run in isolated Docker containers on a private network.



---

## Square9 Decommission Procedure

### Overview

GPI Hub replaces Square9 as the authoritative document management system.
After cutover, all document intake, classification, filing, and approval
happens exclusively in GPI Hub. Square9 stage data is preserved as
historical metadata on `hub_documents.square9_stage`.

### Pre-Cutover Checklist

1. **Verify Hub readiness**
   ```
   GET /api/square9/migration-status
   ```
   Confirm `cutover_readiness: "ready"` and review `unique_stages` for any
   documents still in active Square9 processing.

2. **Validate mailbox sources** — ensure all AP and Sales mailboxes are
   configured in GPI Hub (`/api/mailbox-sources`).

3. **Test email polling** — trigger a manual poll:
   ```
   POST /api/email-polling/trigger
   ```

### Execute Cutover

```
POST /api/admin/square9-cutover
```

This endpoint:
- Sets `square9_active=false` in `hub_config`
- Records the cutover timestamp
- Logs a system activity record
- Is idempotent (safe to call multiple times)

The dashboard will show a green banner confirming decommission.

### Redirect Email Mailboxes from Square9 to GPI Hub

| Mailbox | Purpose | GPI Hub Config |
|---------|---------|----------------|
| `ap@gamerpackaging.com` | AP invoices, freight bills | mailbox source `category: "AP"` |
| `sales@gamerpackaging.com` | Sales orders, confirmations | mailbox source `category: "Sales"` |
| `logistics@gamerpackaging.com` | Shipping docs, BOLs, PODs | mailbox source `category: "Logistics"` |
| `warehouse@gamerpackaging.com` | Warehouse receipts, storage | mailbox source `category: "Warehouse"` |

**Steps per mailbox:**
1. Disable Square9 inbox rule in Exchange Admin
2. Add GPI Hub mailbox source via `/api/mailbox-sources`
3. Configure Graph API credentials (`EMAIL_CLIENT_ID`, `EMAIL_CLIENT_SECRET`, `EMAIL_TENANT_ID`)
4. Set `EMAIL_POLLING_ENABLED=true` and restart backend
5. Verify via `GET /api/email-polling/status`

### Rollback

Re-enable Square9: set `square9_active=true` in `hub_config`, re-enable inbox rules.
