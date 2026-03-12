# GPI Hub Integration - Publishing Guide

## Prerequisites

1. **VS Code** with the [AL Language extension](https://marketplace.visualstudio.com/items?itemName=ms-dynamics-smb.al) installed
2. **BC Sandbox environment** accessible via `https://businesscentral.dynamics.com`
3. **Azure AD app registration** with:
   - `API.ReadWrite.All` permission for BC
   - `D365 AUTOMATION` permission set assigned in BC

## Step 1: Open the Project

```bash
# From your local machine, open the bc-extension folder
code /path/to/bc-extension
```

## Step 2: Configure launch.json

Edit `.vscode/launch.json` to match your BC environment:
- `environmentName`: Your sandbox name (e.g., "Sandbox_11_3_2025")
- `authentication`: Use "AAD" for Azure AD authentication

## Step 3: Download Symbols

1. Press `Ctrl+Shift+P` (or `Cmd+Shift+P` on Mac)
2. Type and select: `AL: Download Symbols`
3. Enter your BC credentials when prompted
4. Wait for symbols to download (may take 1-2 minutes)

## Step 4: Build and Package

1. Press `Ctrl+Shift+P`
2. Type and select: `AL: Package`
3. This creates `GPI Hub Integration_1.0.0.0.app` in the project root

## Step 5: Publish to Sandbox

### Option A: From VS Code (recommended for development)
1. Press `F5` to publish with debugging
2. Or press `Ctrl+F5` to publish without debugging
3. BC will open in your browser with the extension installed

### Option B: Manual Upload
1. In BC, go to **Extension Management**
2. Click **Manage** > **Upload Extension**
3. Select the `.app` file
4. Click **Deploy**
5. Wait for deployment to complete (check status in Extension Management)

## Step 6: Assign Permissions

1. In BC, go to **Users**
2. Select the integration user (the Azure AD app)
3. Go to **User Permission Sets**
4. Add: `GPI HUB INTEGRATION` (Permission Set ID: 50100)

## Step 7: Verify Installation

### Check Factbox
1. Open a **Purchase Invoice** in BC
2. Look for the "GPI Documents" factbox on the right side
3. Open a **Sales Order** — the factbox should also appear

### Check API Endpoints
Test the custom API is available:

```bash
# List companies
curl -X GET \
  "https://api.businesscentral.dynamics.com/v2.0/{tenantId}/{environment}/api/gpi/integration/v1.0/companies" \
  -H "Authorization: Bearer {token}"

# Test sales order creation
curl -X POST \
  "https://api.businesscentral.dynamics.com/v2.0/{tenantId}/{environment}/api/gpi/integration/v1.0/companies({companyId})/salesOrderRequests" \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "idempotencyKey": "TEST_001",
    "sourceSystem": "GPI_HUB",
    "sourceDocumentId": "test-doc-001",
    "transactionId": "TXN_test001",
    "customerNo": "C00100",
    "externalDocumentNo": "TEST-PO-001",
    "orderDate": "2026-03-12"
  }'

# Check integration logs
curl -X GET \
  "https://api.businesscentral.dynamics.com/v2.0/{tenantId}/{environment}/api/gpi/integration/v1.0/companies({companyId})/integrationLogs?\$top=10&\$orderby=entryNo desc" \
  -H "Authorization: Bearer {token}"
```

## Step 8: Configure GPI Hub Backend

After the extension is published, the GPI Hub backend will automatically connect through:
- `GET /api/gpi-integration/status` — verifies configuration
- `POST /api/gpi-integration/sales-orders` — creates sales orders via the new API
- etc.

No additional backend configuration is needed — the same BC credentials already in `.env` are used.

## Troubleshooting

### "Extension not found" in Extension Management
- Ensure the `.app` file was built with matching symbols for your BC version
- Check that `app.json` `platform` and `application` versions match your BC version

### "Permission denied" on API calls
- Verify the "GPI Hub Integration" permission set is assigned to the integration user
- Check the Azure AD app has `API.ReadWrite.All` consent granted

### "Object ID out of range"
- All objects use IDs 50100-50199, which is the standard ISV range
- If another extension already uses these IDs, contact your BC administrator

### Idempotency Issues
- Each request needs a unique `idempotencyKey`
- The key is scoped per record type (Sales Order, Purchase Invoice, etc.)
- Reusing a key for the same record type returns the previously created record
