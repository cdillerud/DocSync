# GPI Document Hub - PRD

## Original Problem Statement
Build a "GPI Document Hub" test platform that replaces Zetadocs-style document linking in Microsoft Dynamics 365 Business Central by using SharePoint Online as the document repository and a middleware hub to orchestrate ingestion, metadata, approvals, and attachment linking back to BC.

## Current Status: PHASE 7 - OBSERVATION MODE (Read-Only BC)

**Shadow Mode Started:** February 18, 2026  
**Observation Window:** 14 days  
**BC Write Operations:** DISABLED (all integrations read-only)

---

## Phase 7 Implementation Summary

### 1. Normalized Fields on Document Model ✅

For `document_type = "AP_Invoice"`, the following fields are computed at ingestion and stored flat on the document:

| Field | Description |
|-------|-------------|
| `vendor_raw` | Original extracted vendor string |
| `vendor_normalized` | Lowercased, trimmed, multiple spaces collapsed |
| `invoice_number_raw` | Original invoice number |
| `invoice_number_clean` | Stripped of spaces/commas, uppercase |
| `amount_raw` | Original amount string |
| `amount_float` | Parsed numeric value as float |
| `due_date_raw` | Original date string |
| `due_date_iso` | Parsed ISO format (YYYY-MM-DD) |
| `po_number_raw` | Original PO string (if any) |
| `po_number_clean` | Normalized PO number for matching |

### 2. Required Field Completeness Check ✅

**Required Fields for AP Invoice Header Readiness:**
- `vendor_normalized`
- `invoice_number_clean`
- `amount_float`

**Computed Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `draft_candidate` | boolean | True when all 3 required fields present and valid |
| `validation_errors` | array | String codes: `missing_vendor`, `missing_invoice_number`, `missing_amount`, `low_classification_confidence`, `potential_duplicate_invoice` |
| `validation_warnings` | array | Non-blocking: `missing_po_number` |

### 3. Vendor Alias Support (Read-Only) ✅

**Collection:** `vendor_aliases`
```json
{
  "normalized": "tumalo creek transportation",
  "canonical_vendor_id": "TUMALO CREEK",
  "aliases": ["TUMALO CREEK Transportation", ...]
}
```

**Computed Fields on Document:**
| Field | Description |
|-------|-------------|
| `vendor_canonical` | Canonical vendor ID when found, else null |
| `vendor_match_method` | `"alias"`, `"exact_name"`, or `"none"` |

### 4. Duplicate Safety Check ✅

**Logic:** A document is a possible duplicate if another non-deleted doc exists with:
- Same `vendor_canonical` (if set) OR same `vendor_normalized`
- Same `invoice_number_clean`

**Computed Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `possible_duplicate` | boolean | True if duplicate detected |
| `duplicate_of_document_id` | string | ID of existing doc, or null |

### 5. Status Logic for AP Invoices (Phase 7) ✅

**Conservative Observation Mode:**
- All AP_Invoice documents → `status = "NeedsReview"`
- `draft_candidate` flag visible in API/UI for observation
- NO auto-advancement to BC-writing statuses
- NO draft creation regardless of readiness

### 6. Metrics Endpoint - Extraction Quality ✅

**Endpoint:** `GET /api/metrics/extraction-quality?days=N`

Returns:
```json
{
  "period_days": 7,
  "total_documents": 100,
  "extraction_rates": {
    "vendor": 87.0,
    "invoice_number": 83.0,
    "amount": 91.0,
    "po_number": 65.0,
    "due_date": 72.0
  },
  "readiness_metrics": {
    "ready_for_draft": {"count": 82, "rate": 82.0},
    "draft_candidates": {"count": 78, "rate": 78.0}
  },
  "completeness_summary": {
    "all_required_fields": 82,
    "missing_vendor": 13,
    "missing_invoice_number": 17,
    "missing_amount": 9
  },
  "vendor_variations": [...],
  "stable_vendors": [...]
}
```

### 7. Extraction Misses Drilldown ✅

**Endpoint:** `GET /api/metrics/extraction-misses?field=vendor|invoice_number|amount`

Returns array with:
- `document_id`
- `file_name`
- `document_type`
- `status`
- `vendor_raw`, `invoice_number_raw`, `amount_raw`, `due_date_raw`, `po_number_raw`
- `ai_confidence`
- `first_500_chars_text`

### 8. Stable Vendors Endpoint ✅

**Endpoint:** `GET /api/metrics/stable-vendors`

Criteria:
- `count >= 5`
- `completeness >= 85%`
- `alias variance <= 3`

### 9. Draft Candidates Endpoint ✅

**Endpoint:** `GET /api/metrics/draft-candidates`

Shows distribution of `draft_candidate` flags without enabling drafts.

---

## Non-Goals for Phase 7 (Explicitly Disabled)

- ❌ `CREATE_DRAFT_HEADER` - Disabled
- ❌ Auto-posting or draft creation in BC
- ❌ Automatic document deletion
- ❌ Freight workflow modifications
- ❌ Email polling behavior changes
- ❌ Match score threshold changes
- ❌ Vendor overrides
- ❌ AI prompt tuning

---

## API Endpoints Summary

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/metrics/extraction-quality` | GET | Extraction rates + draft readiness |
| `/api/metrics/extraction-misses` | GET | Drilldown on missing fields |
| `/api/metrics/stable-vendors` | GET | Vendors meeting stability criteria |
| `/api/metrics/draft-candidates` | GET | Draft candidate distribution |
| `/api/documents` | GET | Document list with new fields |

---

## Document Model (Phase 7 Fields)

```javascript
{
  // ... existing fields ...
  
  // Phase 7: Normalized fields (flat)
  "vendor_raw": "Tumalo Creek Transportation",
  "vendor_normalized": "tumalo creek transportation",
  "invoice_number_raw": "INV-2024-001",
  "invoice_number_clean": "INV2024001",
  "amount_raw": "$1,234.56",
  "amount_float": 1234.56,
  "due_date_raw": "March 15, 2024",
  "due_date_iso": "2024-03-15",
  "po_number_raw": "PO-123",
  "po_number_clean": "PO123",
  
  // Phase 7: Vendor alias results
  "vendor_canonical": "TUMALO CREEK",
  "vendor_match_method": "alias",
  
  // Phase 7: Duplicate detection
  "possible_duplicate": false,
  "duplicate_of_document_id": null,
  
  // Phase 7: Validation
  "validation_errors": [],
  "validation_warnings": ["missing_po_number"],
  "draft_candidate": true
}
```

---

## Next Steps

1. **Deploy to VM:** `git pull origin main && sudo docker compose build backend && sudo docker compose up -d`
2. **Re-process existing documents** to populate new fields (optional backfill)
3. **Monitor metrics** during 14-day observation window
4. **Phase 8 Planning:** When `draft_candidate` rate stabilizes ≥80%, plan controlled vendor enablement

---

## Testing Results
- Phase 7 endpoints: All functional
- Backend: Running with new validation logic
- Dashboard: Updated with AP Invoice Extraction Quality section
- BC writes: Confirmed DISABLED
- **Sales Module Phase 0**: All endpoints functional, seed data populated

---

## Sales Inventory & Orders Module (Phase 0)

**Status:** Implemented, BC Disconnected

### Data Collections (10 new)
- `sales_customers` - Customer master data
- `sales_items` - Item/SKU master
- `sales_customer_items` - Customer-specific SKU mappings
- `sales_warehouses` - Warehouse locations
- `sales_inventory_positions` - Inventory snapshots
- `sales_open_order_headers` - Open order headers
- `sales_open_order_lines` - Open order line items
- `sales_lost_business` - Lost business tracking
- `sales_pricing_tiers` - Customer item pricing
- `sales_order_draft_candidates` - Draft candidate pattern

### API Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/sales/customers` | GET | Customer list |
| `/api/sales/customers/{id}/dashboard` | GET | Dashboard data with summary, inventory, orders, alerts |
| `/api/sales/customers/{id}/open-orders` | GET | Open orders with line detail |
| `/api/sales/order-drafts` | GET | Draft candidates list |
| `/api/sales/order-drafts/{id}` | GET | Draft candidate detail |
| `/api/sales/warehouses` | GET | Warehouse list |
| `/api/sales/items` | GET | Item list |
| `/api/sales/seed-data` | POST | Initialize test data |

### UI: Sales Dashboard
- Customer selector dropdown
- Summary cards: On Hand, Available, Open Orders, On Water, On Order
- Inventory grid by item/warehouse with search
- Open orders grid with status badges
- Alerts panel: low stock, at-risk orders, lost business

### Seed Data Customers
- ET Browne
- HOW (House of Wines)
- Karlin
- Wing Nien

### Phase 0 Limitations
- ❌ No BC API calls
- ❌ bc_customer_no, bc_sales_order_no are null placeholders
- ❌ No Excel ingestion (manual seed data only)
- ❌ No draft creation to BC
