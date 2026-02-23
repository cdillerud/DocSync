# GPI Document Hub - Architecture Refactor Plan

## Executive Summary

Simplify the over-engineered architecture into a clean, maintainable system with:
- **One document collection** (`hub_documents`)
- **One ingestion pipeline** (all sources → classify → route to workflow)
- **One unified queue UI** (filter by doc_type, status)
- **Modular backend** (separate route files instead of 12K line monolith)

---

## Current State Analysis

### Problems Identified

| Issue | Impact | Files Affected |
|-------|--------|----------------|
| 12,153 lines in server.py | Unmaintainable | server.py |
| 144 API routes in one file | Hard to navigate | server.py |
| Separate sales_module.py | Duplicate patterns | sales_module.py |
| 27 MongoDB collections | Data scattered | Multiple |
| Duplicate email polling | Confusing logic | server.py |
| 17 frontend pages | Too granular | /pages/*.js |
| Pilot/Simulation complexity | Premature optimization | Multiple services |

### Collections to KEEP (Core)
```
hub_documents        - ALL documents (unified)
hub_config           - System configuration
mailbox_sources      - Email polling config
vendor_aliases       - Vendor name matching
```

### Collections to MERGE into hub_documents
```
sales_documents      → hub_documents (as doc_type: SALES_*)
```

### Collections to REMOVE (Unused/Redundant)
```
hub_bc_vendors       - Not actively used
hub_job_types        - Hardcoded in workflow_engine
hub_workflow_runs    - Can be embedded in documents
mail_intake_log      - Merge with hub_documents.source_metadata
mail_poll_runs       - Keep minimal logging
sales_mail_*         - Duplicate of main polling
pilot_simulation_*   - Remove (simplify)
file_ingestion_log   - Embed in documents
```

### Sales Collections Decision
```
KEEP (master data):
- sales_customers
- sales_items  
- sales_warehouses

REMOVE (move to hub_documents):
- sales_documents
- sales_open_order_headers  → doc_type: SALES_ORDER in hub_documents
- sales_open_order_lines    → embedded in SALES_ORDER documents
- sales_inventory_positions → doc_type: INVENTORY_SNAPSHOT
- sales_customer_items      → embedded in customer master
- sales_order_draft_candidates → remove
- sales_lost_business       → remove
- sales_pricing_tiers       → remove for now
```

---

## Target Architecture

### Document Flow (Simplified)

```
┌─────────────────────────────────────────────────────────────────┐
│                        INGESTION LAYER                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Email (Graph API)  ──┐                                        │
│   Manual Upload      ──┼──► ingest_document() ──► hub_documents │
│   File Import (CSV)  ──┤         │                              │
│   Legacy Systems     ──┘         ▼                              │
│                          classify_document()                    │
│                                  │                              │
└──────────────────────────────────┼──────────────────────────────┘
                                   │
┌──────────────────────────────────┼──────────────────────────────┐
│                         WORKFLOW LAYER                          │
├──────────────────────────────────┼──────────────────────────────┤
│                                  ▼                              │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │              route_to_workflow(doc_type)                │   │
│   └─────────────────────────────────────────────────────────┘   │
│          │           │           │           │                  │
│          ▼           ▼           ▼           ▼                  │
│   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│   │ AP_INV   │ │ SALES_ORD│ │ PURCH_ORD│ │ OTHER    │          │
│   │ Workflow │ │ Workflow │ │ Workflow │ │ Workflow │          │
│   └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Simplified Document Schema

```python
# hub_documents (unified)
{
    "id": "doc_xxx",
    "doc_type": "AP_INVOICE|SALES_ORDER|PURCHASE_ORDER|...",
    "status": "received|classified|extracted|pending_review|approved|...",
    
    # Source info
    "source": "email|upload|file_import|zetadocs|square9",
    "source_metadata": {
        "email_id": "...",
        "mailbox": "...",
        "file_name": "...",
        "import_batch_id": "..."
    },
    
    # Classification result
    "classification": {
        "method": "deterministic|ai",
        "confidence": 0.95,
        "suggested_type": "AP_INVOICE",
        "extracted_fields": {}
    },
    
    # Workflow state
    "workflow_status": "captured|classified|extracted|...",
    "workflow_history": [...],
    
    # Document-specific data (varies by doc_type)
    "data": {
        # For AP_INVOICE:
        "vendor": "...",
        "invoice_number": "...",
        "amount": 0.00,
        
        # For SALES_ORDER:
        "customer_po": "...",
        "customer_id": "...",
        "lines": [...]
    },
    
    # Timestamps
    "created_utc": "...",
    "updated_utc": "..."
}
```

---

## Backend Refactor Plan

### Phase 1: Restructure Files (No Behavior Change)

**New file structure:**
```
/app/backend/
├── server.py              # App setup, middleware, startup only (~200 lines)
├── routes/
│   ├── __init__.py
│   ├── documents.py       # CRUD for hub_documents
│   ├── ingestion.py       # Intake from all sources
│   ├── workflows.py       # Workflow transitions
│   ├── config.py          # Settings, mailboxes
│   ├── dashboard.py       # Stats, metrics
│   └── admin.py           # Migration, backfill
├── services/
│   ├── ingestion_service.py    # Unified ingestion
│   ├── classification_service.py
│   ├── workflow_engine.py      # Keep (already good)
│   ├── email_service.py        # Keep
│   └── file_parser.py          # CSV/Excel parsing
├── models/
│   ├── document.py        # Pydantic models
│   └── workflow.py
└── tests/
```

### Phase 2: Consolidate Collections

1. Migrate `sales_documents` → `hub_documents`
2. Remove duplicate polling logic
3. Embed order lines in documents (not separate collection)

### Phase 3: Simplify Workflows

Keep only essential workflows:
- `AP_INVOICE` - Full approval workflow
- `SALES_ORDER` - Order processing
- `PURCHASE_ORDER` - PO validation
- `CREDIT_MEMO` - Credit processing
- `OTHER` - Manual triage

Remove over-engineered statuses.

---

## Frontend Refactor Plan

### Current Pages (17) → Target Pages (8)

| Keep | Remove/Merge |
|------|--------------|
| DashboardPage | APWorkflowsPage → merge into QueuePage |
| QueuePage (unified) | SalesWorkflowsPage → merge into QueuePage |
| DocumentDetailPage | OperationsWorkflowsPage → merge into QueuePage |
| UploadPage | WorkflowQueuesPage → remove (redundant) |
| SettingsPage | DocTypeDashboardPage → merge into Dashboard |
| LoginPage | PilotDashboardPage → remove |
| FileImportPage | SimulationDashboardPage → remove |
| AuditDashboardPage (optional) | SalesDashboardPage → remove |

### Unified Queue Design

```
┌─────────────────────────────────────────────────────────────────┐
│  Document Queue                                    [+ Upload]   │
├─────────────────────────────────────────────────────────────────┤
│  Filters: [All Types ▼] [All Status ▼] [Date Range] [Search]   │
├─────────────────────────────────────────────────────────────────┤
│  Quick Stats:  📄 156 Total  ⏳ 12 Pending  ✓ 140 Processed    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ INV-2024-001  │ AP Invoice  │ Pending Review │ 2h ago   │   │
│  │ PO-5523       │ Sales Order │ Classified     │ 3h ago   │   │
│  │ CM-1234       │ Credit Memo │ Approved       │ 1d ago   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Execution Order

### Step 1: Backend File Split (Low Risk)
- [ ] Create `/routes/` directory structure
- [ ] Extract document routes from server.py
- [ ] Extract workflow routes  
- [ ] Extract config routes
- [ ] Verify all tests pass
- [ ] server.py down to ~500 lines

### Step 2: Remove sales_module.py
- [ ] Migrate any needed logic to main routes
- [ ] Update imports
- [ ] Delete sales_module.py

### Step 3: Consolidate Frontend
- [ ] Merge workflow pages into QueuePage
- [ ] Add doc_type filter to QueuePage
- [ ] Remove redundant pages
- [ ] Update navigation

### Step 4: Database Cleanup
- [ ] Migrate sales_documents to hub_documents
- [ ] Remove unused collections
- [ ] Update indexes

### Step 5: Remove Pilot/Simulation Complexity
- [ ] Remove bc_simulation_service.py
- [ ] Remove simulation_metrics_service.py
- [ ] Remove PilotDashboardPage
- [ ] Remove SimulationDashboardPage
- [ ] Keep bc_sandbox_service.py (read-only BC validation is useful)

---

## Risk Mitigation

1. **Each step is independently testable** - we verify after each phase
2. **No data loss** - migrations copy, don't delete
3. **Rollback possible** - git history preserved
4. **Existing tests remain** - refactor routes, not logic

---

## Questions Before Proceeding

1. ✅ Full refactor - confirmed
2. ✅ Both frontend and backend - confirmed  
3. ✅ Integrate sales into unified hub - confirmed
4. ✅ Simplify pilot/simulation - confirmed

**Ready to execute?**
