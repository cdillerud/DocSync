# GPI Hub Integration - Business Central Extension

## Overview

A comprehensive Business Central extension that provides:

1. **GPI Documents Factbox** — SharePoint document link viewer with **upload capability** on Purchase Invoices, Purchase Orders, Sales Orders, and Posted document pages. Full Zetadocs replacement.
2. **GPI Integration API** — Stable, idempotent REST API endpoints for creating Sales Orders, Purchase Invoices, Customers, and Vendors from GPI Document Hub
3. **Audit Logging** — Every integration transaction is logged with source system, idempotency key, and result

## Extension Objects

### Tables
| ID | Name | Purpose |
|----|------|---------|
| 50100 | GPI Document Link | Stores SharePoint document links for BC records |
| 50101 | GPI Integration Log | Audit log for all integration transactions |
| 50102 | GPI Sales Order Request | API buffer for sales order creation requests |
| 50103 | GPI Purch. Invoice Request | API buffer for purchase invoice creation requests |
| 50104 | GPI Customer Request | API buffer for customer creation requests |
| 50105 | GPI Vendor Request | API buffer for vendor creation requests |

### Table Extensions
| ID | Name | Extends |
|----|------|---------|
| 50100 | GPI Sales Header Ext | Sales Header (adds GPI metadata) |
| 50101 | GPI Purchase Header Ext | Purchase Header (adds GPI metadata) |
| 50102 | GPI Customer Ext | Customer (adds GPI metadata) |
| 50103 | GPI Vendor Ext | Vendor (adds GPI metadata) |

### Enums
| ID | Name | Values |
|----|------|--------|
| 50100 | GPI Doc Link Type | Purchase Invoice, Posted Purchase Invoice, Sales Invoice, Posted Sales Invoice, Sales Order, Posted Sales Order, **Purchase Order** |
| 50101 | GPI Doc Link Source | GPIHub, Manual, **BCDrop**, **ZetadocsLegacy** |
| 50100 | GPI Record Type | Sales Order, Purchase Invoice, Customer, Vendor, Company |
| 50101 | GPI Request Status | Pending, Created, Already Exists, Failed, Validation Error |

### Codeunits
| ID | Name | Purpose |
|----|------|---------|
| 50100 | GPI Integration Mgt | Core: idempotency checks, audit logging, validation helpers |
| 50101 | GPI Sales Order Mgt | Sales Order creation with validation and line management |
| 50102 | GPI Purchase Invoice Mgt | Purchase Invoice creation with vendor validation |
| 50103 | GPI Customer Mgt | Customer creation with address validation |
| 50104 | GPI Vendor Mgt | Vendor creation with address validation |
| **50105** | **GPI Document Link Mgt** | **Hub API client: refresh links, upload files, remove links, migrate Zetadocs** |

### API Pages (Custom REST API)
| ID | Name | Entity Set | Methods |
|----|------|-----------|---------|
| 50111 | GPI Companies API | companies | GET |
| 50112 | GPI Sales Orders API | salesOrderRequests | GET, POST |
| 50113 | GPI Purchase Invoices API | purchaseInvoiceRequests | GET, POST |
| 50114 | GPI Customers API | customerRequests | GET, POST |
| 50115 | GPI Vendors API | vendorRequests | GET, POST |
| 50116 | GPI Integration Log API | integrationLogs | GET |
| 50110 | GPI Document Link API | documentLinks | GET, POST, PATCH, DELETE |

### Pages (UI)
| ID | Name | Type |
|----|------|------|
| 50100 | GPI Document Link Factbox | **ListPart** (multi-doc view with Upload, Remove, Refresh actions) |
| 50101 | GPI Document Link List | List (admin view) |
| 50102 | GPI Document Link Card | Card (admin detail view) |

### Page Extensions
| ID | Name | Extends |
|----|------|---------|
| 50100 | GPI Purch Invoice Extension | Purchase Invoice (adds GPI Documents factbox) |
| 50101 | GPI Posted Purch Inv Extension | Posted Purchase Invoice |
| 50102 | GPI Sales Order Extension | Sales Order |
| 50103 | GPI Posted Sales Inv Extension | Posted Sales Invoice |
| **50104** | **GPI Purch Order Extension** | **Purchase Order** |

### Permission Set
| ID | Name | Description |
|----|------|-------------|
| 50100 | GPI Hub Integration | Full RIMD access to all GPI tables, execute on codeunits, RIM on standard BC tables |

## API Endpoints

**Base URL:** `https://api.businesscentral.dynamics.com/v2.0/{tenantId}/{environment}/api/gpi/integration/v1.0/companies({companyId})`

### List Companies (GET)
```
GET .../api/gpi/integration/v1.0/companies
```

### Create Sales Order (POST)
```
POST .../salesOrderRequests
{
  "idempotencyKey": "SO_DOC123_20260312",
  "sourceSystem": "GPI_HUB",
  "sourceDocumentId": "doc-uuid-123",
  "transactionId": "TXN_abc123",
  "customerNo": "C00100",
  "externalDocumentNo": "PO-2026-0042",
  "orderDate": "2026-03-12"
}
```

**Response:**
```json
{
  "idempotencyKey": "SO_DOC123_20260312",
  "resultSuccess": true,
  "resultRecordNo": "SO-103456",
  "resultSystemId": "guid...",
  "resultStatus": "created",
  "errorMessage": ""
}
```

### Create Purchase Invoice (POST)
```
POST .../purchaseInvoiceRequests
{
  "idempotencyKey": "PI_DOC456_20260312",
  "sourceSystem": "GPI_HUB",
  "sourceDocumentId": "doc-uuid-456",
  "transactionId": "TXN_def456",
  "vendorNo": "V00100",
  "vendorInvoiceNo": "INV-2026-789",
  "documentDate": "2026-03-12",
  "postingDate": "2026-03-12"
}
```

### Create Customer (POST)
```
POST .../customerRequests
{
  "idempotencyKey": "CUST_DOC789_20260312",
  "sourceSystem": "GPI_HUB",
  "sourceDocumentId": "doc-uuid-789",
  "name": "Acme Corp",
  "address": "123 Main St",
  "city": "Portland",
  "stateCode": "OR",
  "postalCode": "97201",
  "countryCode": "US"
}
```

### Create Vendor (POST)
```
POST .../vendorRequests
{
  "idempotencyKey": "VEND_DOC101_20260312",
  "sourceSystem": "GPI_HUB",
  "sourceDocumentId": "doc-uuid-101",
  "name": "Global Parts Inc",
  "address": "456 Oak Ave",
  "city": "Seattle",
  "stateCode": "WA",
  "postalCode": "98101",
  "countryCode": "US"
}
```

### Query Integration Logs (GET)
```
GET .../integrationLogs?$filter=recordType eq 'Sales Order'&$top=50&$orderby=entryNo desc
```

### Document Links API (existing)
```
POST .../api/gpi/documents/v1.0/companies({companyId})/documentLinks
{
  "documentType": "Purchase Invoice",
  "targetSystemId": "guid-of-purchase-invoice",
  "bcDocumentNo": "72520",
  "sharePointUrl": "https://tenant.sharepoint.com/sites/...",
  "source": "GPIHub"
}
```

## Idempotency

All create operations are idempotent:
- Caller supplies an `idempotencyKey` with each request
- If the same key + record type has already been processed successfully, the API returns the existing record's details with `resultStatus: "already_exists"`
- Duplicate attempts are logged in the Integration Log

## Installation

1. Open the `/app/bc-extension/` folder in VS Code with the AL Language extension
2. Configure `launch.json` to target your BC Sandbox environment
3. Download symbols: `Ctrl+Shift+P` > `AL: Download Symbols`
4. Package: `Ctrl+Shift+P` > `AL: Package` (creates `.app` file)
5. Publish: `F5` (Publish) or upload `.app` via Extension Management in BC
6. Assign the "GPI Hub Integration" permission set to the integration user

## GPI Hub Backend Integration

The Python backend provides a bridge layer:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/gpi-integration/status` | Check BC integration configuration |
| GET | `/api/gpi-integration/companies` | List BC companies |
| POST | `/api/gpi-integration/sales-orders` | Create sales order via BC custom API |
| POST | `/api/gpi-integration/purchase-invoices` | Create purchase invoice |
| POST | `/api/gpi-integration/customers` | Create customer |
| POST | `/api/gpi-integration/vendors` | Create vendor |
| GET | `/api/gpi-integration/logs` | Query integration audit logs |
| GET | `/api/gpi-integration/document-links/{entity}/{docNo}` | List all documents linked to a BC record |
| POST | `/api/gpi-integration/document-links/{entity}/{docNo}/upload` | Upload file to SharePoint + create BC link |
| DELETE | `/api/gpi-integration/document-links/{entity}/{docNo}/{docId}` | Soft-delete a document link |
| POST | `/api/gpi-integration/document-links/migrate-from-zetadocs` | Import legacy Zetadocs links |

## Version History

- **2.0.0.0** - Full Zetadocs replacement (current)
  - Factbox upgraded from CardPart → ListPart (shows multiple documents)
  - Upload action: files go through GPI Hub → SharePoint → BC link (round-trip)
  - Remove action: soft-delete link (SharePoint file preserved for audit)
  - Refresh action: syncs document list from GPI Hub API
  - New Purchase Order page extension (PageExt 50104)
  - New `GPI Document Link Mgt` codeunit (50105) — HTTP client for Hub API
  - Enum additions: `Purchase Order` type, `BCDrop` + `ZetadocsLegacy` sources
  - `File Name` field added to GPI Document Link table
  - All page extensions updated with `SetContext()` for vendor/customer context
  - Folder resolution: matches existing folder from hub first, falls back to routing rules
  - Zetadocs migration support via Hub API

- **1.0.0.0** - Initial release
  - GPI Document Link factbox and API
  - GPI Integration API (Sales Orders, Purchase Invoices, Customers, Vendors)
  - Integration Log audit table
  - Permission set
  - Idempotency protection on all create operations
