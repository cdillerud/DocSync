# GPI Document Hub - Changelog

## March 10, 2026

### BC Reference Cache Layer (COMPLETED)
- **NEW:** `BCReferenceCacheService` — 277K+ records, 5 entity types, bulk/incremental sync, 10-min background refresh
- **Cache-First Resolver:** Checks cache first (<50ms), falls back to BC API
- **Endpoints:** `GET /api/cache/status`, `POST /api/cache/sync`, `GET /api/cache/search`
- **TESTS:** iteration_23.json (17 backend, 100% frontend)

### Auto-Resolution on Document Intake (COMPLETED)
- **NEW:** `AutoResolutionService` in `/app/backend/services/auto_resolution_service.py`
  - 5 async background workers, rate-limited, non-blocking
  - Document-type-aware: only AP Invoice, Freight, Shipping, BOL, Sales Order
  - Idempotent: version + SHA256 hash tracking (skips if data unchanged)
  - Retry: max 3 attempts with 30s/60s/120s exponential backoff
  - Cache-first, read-only (inherits BC write guard)
- **Endpoints:** `GET /api/auto-resolve/stats`, `POST /api/documents/{id}/auto-resolve`
- **Document Fields:** `reference_intelligence_status` (not_run/pending/completed/ambiguous/failed/retry_scheduled), `_version`, `_hash`, `_last_run`, `_outcome`, `_best_score`
- **Queue UI:** "Ref Intel" column in UnifiedQueuePage with status badges + score
- **Detail UI:** ReferenceIntelligencePanel shows pending/failed/retry indicators
- **Events:** `reference.resolve.queued/started/completed/failed/retry_scheduled/skipped`
- **TESTS:** iteration_24.json (11 backend, 100% frontend)

### Vendor Intelligence Engine (COMPLETED)
- **NEW:** `VendorIntelligenceService` in `/app/backend/services/vendor_intelligence_service.py`
  - `vendor_intelligence_profiles` collection — 16 vendors, 25 docs processed from historical rebuild
  - Behavioral metrics: PO/BOL/shipment frequencies, resolution/automation success rates
  - Stable vendor detection (50+ invoices, 90%+ automation)
  - Vendor-aware resolver hints (search order boost, domain priority, behavior scoring)
  - Async profile updates after auto-resolution (non-blocking)
- **Endpoints:** `GET /api/vendor-intelligence/stats`, `.../profiles`, `.../profiles/{id}`, `POST .../rebuild`, `GET .../resolver-hints/{name}`
- **Dashboard:** New `/vendor-intelligence` page — stats cards, sortable vendor table, search, detail side panel
- **Resolver Integration:** `score_bc_match` now accepts `vendor_hints` for behavior-based scoring boost (0.15 weight)
- **Events:** `vendor.profile.created/updated`, `vendor.stable.detected`
- **TESTS:** iteration_25.json (18 backend, 100% frontend)


### AI-Assisted Reference Intelligence Engine (COMPLETED)
- **NEW:** `ReferenceIntelligenceService` in `/app/backend/services/reference_intelligence_service.py`
  - Extracts multiple candidate references (PO, BOL, Order, Shipment, Load, PRO, Invoice) from documents
  - Reference normalization layer (strips prefixes, standardizes for BC lookup)
  - AI reference classification (predicts domain: purchase/sales/shipping and entity types)
  - Document-type-aware resolver strategy (AP Invoice → PO first; BOL → Sales Orders first)
  - BC match scoring: exact match (0.4), entity alignment (0.2), domain alignment (0.15), vendor alignment (0.15), confidence (0.1)
- **NEW:** API Endpoints:
  - `POST /api/documents/{id}/resolve-intelligence` - Full AI-assisted resolution
  - `GET /api/documents/{id}/reference-intelligence` - Get stored intelligence data
- **NEW:** Frontend `ReferenceIntelligencePanel` component with:
  - Match outcome banner (Exact Match / Likely Match / Ambiguous / No Match with score)
  - Best match details (BC doc no, entity type, vendor/customer, date, status)
  - Alternate matches list with scores
  - Extracted references list with label badges, domain classification, confidence
  - Collapsible "Resolver Debug" panel (strategy, BC queries, processing time, search order)
- **UPDATED:** Credentials fixed in `/app/backend/.env` (correct TENANT_ID, BC_CLIENT_ID, etc.)
- **EVENTS:** `reference.extraction.completed`, `reference.resolve.completed`, `reference.resolve.ambiguous` emitted
- **TESTS:** 13 backend tests + full frontend verification (100% pass rate)
- **Test Report:** `/app/test_reports/iteration_22.json`

## February 22, 2026

### Multi-Document Type Workflow Engine
- **NEW:** Full state machines for all 10 doc_types
  - SALES_INVOICE: Standard approval workflow
  - PURCHASE_ORDER: PO validation workflow (validation_pending, validation_failed)
  - SALES_CREDIT_MEMO/PURCHASE_CREDIT_MEMO: Invoice linkage workflow (linked_to_invoice)
  - STATEMENT/REMINDER/FINANCE_CHARGE_MEMO: Fast-path review workflows
  - QUALITY_DOC: Tagging and review workflow (tagged, review_in_progress)
  - OTHER: Triage workflow (triage_pending, triage_completed)
- **NEW:** 13 workflow events: ON_PO_VALIDATION_STARTED, ON_PO_VALID, ON_PO_INVALID, etc.
- **NEW:** 9 workflow statuses: VALIDATION_PENDING, VALIDATION_FAILED, LINKED_TO_INVOICE, etc.
- **NEW:** 9 generic mutation endpoints for workflow transitions
- **NEW:** Dashboard metric: active_queue_count per doc_type
- **TESTS:** 45 automated tests (23 unit + 22 API)

### Classification Dashboard Extension
- **NEW:** Classification method breakdown per doc_type
  - `classification_counts`: { deterministic, ai, other } for each document type
  - `ai_assisted_count`: Documents where AI successfully changed type from OTHER
  - `ai_suggested_but_rejected_count`: Documents where AI was invoked but result rejected
- **NEW:** Classification filter on dashboard API
  - Query param: `?classification=deterministic|ai|all`
  - `classification_totals` in response for summary stats
- **NEW:** CSV export includes classification columns
- **NEW:** Frontend "Classification" column with compact badges (Det/AI/Other)
- **NEW:** Frontend classification filter dropdown with counts
- **TESTS:** 22 new tests for classification dashboard (34 total backend tests)

### AI-Assisted Document Classification
- **NEW:** Deterministic-first classification pipeline
  - Priority order: Zetadocs set codes → Square9 workflows → Mailbox category → Legacy AI extraction → AI fallback
- **NEW:** AI fallback classifier using EMERGENT_LLM_KEY (GPT-5.2)
  - Only invoked when deterministic rules return OTHER
  - Confidence threshold of 0.8 for accepting AI classification
- **NEW:** AI classification audit trail (`ai_classification` field)
  - Records: proposed_doc_type, confidence, model_name, timestamp
  - Saved only when AI classifier is invoked
- **NEW:** Classification method tracking (`classification_method` field)
  - Examples: `legacy_ai:AP_Invoice`, `ai:gpt-5.2:0.91`, `zetadocs:ZD00015`, `default`
- **NEW:** AI classifier service at `/app/backend/services/ai_classifier.py`
- **TESTS:** 29 automated tests (16 unit + 13 integration)

### Document Type Dashboard
- Backend API: GET /api/dashboard/document-types
- CSV Export: GET /api/dashboard/document-types/export
- Frontend page at `/doc-types` with filters and metrics

### Multi-Document Type Classification
- 10 document types: AP_INVOICE, SALES_INVOICE, PURCHASE_ORDER, SALES_CREDIT_MEMO, PURCHASE_CREDIT_MEMO, STATEMENT, REMINDER, FINANCE_CHARGE_MEMO, QUALITY_DOC, OTHER
- Type-aware workflow engine with different state machines per doc_type
- Generic queue APIs for all doc_types

### AP Invoice Workflow Engine
- Pure state machine implementation
- 12 workflow statuses with full history tracking
- Queue and mutation APIs for exception handling
- Frontend workflow page with action dialogs

## February 21, 2026

### Email Ingestion Infrastructure
- Microsoft Graph API integration for email polling
- Dynamic mailbox source configuration via UI
- Attachment extraction and deduplication
- Read-only polling (doesn't change email status)

### Core Platform
- FastAPI backend with MongoDB
- React frontend with Shadcn/UI
- SharePoint integration for document storage
- JWT authentication (mock for POC)
