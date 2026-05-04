# Square9 Cutover Gap Audit — PLAN-ONLY (NO CODE, NO DATA CHANGES)

- Author/agent: Emergent fork agent
- Generated: 2026-05-01 (UTC)
- Status: DRAFT — awaiting user signature.
- Document class: read-only gap audit, scoping artifact.
- Successor artifact: `SQUARE9_CUTOVER_PLAN.md` (drafted only
  after this audit is signed).
- Locked planning assumptions (from operator, this thread):
  1. End-user touchpoint priority order: (1) search historical
     documents → (2) route/classify new email arrivals →
     (3) drawer/folder browse → (4) multi-page split (only if
     actively used this week).
  2. Doc types in scope: AP + warehouse/shipping/receipts +
     sales-side + OTHER (to the extent user-visible).
  3. Historical archive: must be reachable from the hub for
     normal retrieval. Square9 may remain as a backend archive
     temporarily; users should not be forced back into Square9.
  4. Scanner / paper inflow: assume zero. Validate as a Day-1
     gate (see §6).
  5. Friday success bar: AP team + warehouse/shipping +
     sales/accounting can perform routine routing,
     classification, and retrieval through the hub without
     opening Square9.

## 0. Out-of-scope fence (NON-NEGOTIABLE)

This audit does not authorize:

- Any code change.
- Any data mutation (hub or Square9).
- Any cutover execution (the
  `POST /api/square9/archive-stage-data` endpoint is **not**
  invoked by this artifact).
- Any reopening of parked AP classes (CARGOMO FREIGHT-WH,
  CITICARGO mapping, header-only PI policy,
  `doc_prestamp_or_fallback → CREAT`, SMC, SC-YANDELL,
  Smurfit, GROUPWA-SEAQUIS).
- Any change to the Batch-3 fence posture
  (clearance consumed, exclude list pinned-as-reference).
- Any production BC writes.
- Any Phase 4C(b) DocuSign live-path work.
- Any HTTPS migration, capacity engineering, or
  `server.py` refactor.

This artifact is scoping only. It produces a per-function
classification (`ALREADY-COVERED` / `BUILD-THIS-WEEK` /
`DEFER-NOT-USER-VISIBLE`) and a Day-1 validation checklist.

## 1. Verified current hub state

The audit was grounded in the **current** codebase, not the
2026-02-24 `SQUARE9_COMPARISON.md` snapshot or the 2026-04-28
`FUNCTIONAL_CAPABILITY_AUDIT.md` snapshot. Read-only inspection
covered:

- Backend routers: `documents.py` (45+ endpoints),
  `square9.py` (5 endpoints including a working cutover
  toggle), `dashboard.py`, `sharepoint_routing.py`,
  `email_polling.py`, `mailbox_sources.py`, `file_import.py`,
  `migration_routes.py`.
- Backend services: `square9_workflow.py` (557 lines),
  `folder_routing_service.py` (713 lines covering credit memos,
  freight, warehouse, vendor subfolders, dunnage, storage,
  international), `document_routing_service.py`,
  `sharepoint_service.py`, `classification_pipeline.py`,
  `document_intelligence_service.py`, `email_polling_service.py`.
- Frontend pages: 53 pages including `DocumentsHubPage.js`,
  `UnifiedQueuePage.js`, `DocTypeDashboardPage.js`,
  `MyQueuePage.js`, `OperationsQueuePage.js`,
  `TriageQueuePage.js`, `ReviewQueuePage.js`,
  `SharePointRoutingPage.js`, `UploadPage.js`,
  `FileImportPage.js`. No dedicated `SearchPage.js` exists.
- Frontend components: `Square9WorkflowTracker.js` (288
  lines).

## 2. Headline finding — cutover infrastructure already exists

The hub already ships a working, signed-off cutover toggle:

- `GET /api/square9/migration-status` — read-only readiness
  probe (returns `total_documents`, `with_square9_stage`,
  `without_square9_stage`, `unique_stages`, `cutover_readiness`).
- `POST /api/square9/archive-stage-data` (requires
  `confirm: true`) — bulk-archives `square9_stage` →
  `square9_archived_stage`, sets
  `hub_config.square9_cutover.square9_active = false`,
  irreversible without restore.
- `POST /api/square9/restore-stage-data` — escape hatch.
- `Square9WorkflowTracker.js` — surfaces stage progress per
  doc.

**This means the “turn off Square9” action itself is a single
authorized API call.** The cutover plan's job is to ensure
nothing user-visible regresses when that call is made. The
work this week is gap closure on the user surfaces, not on the
cutover mechanism.

## 3. Per-function classification

For each Square9 user-visible function, status against the
five locked assumptions, with current hub evidence and a
disposition.

### Priority 1 — Search historical documents

| Sub-function | Hub state today | Disposition |
|---|---|---|
| Backend full-text + indexed search across docs | `GET /api/documents/search` exists; supports `$text`, regex fallback, amount detection; searches `file_name`, `vendor_canonical`, `invoice_number_clean`, `po_number_clean`, `extracted_fields.{vendor,invoice_number,po_number,customer}`, `bc_document_no`. Sort by `textScore` or `created_utc`. | **ALREADY-COVERED** (backend) |
| Filter list endpoint (queue-axis filtering) | `GET /api/documents` (router line 168) supports list filters per existing UX. | **ALREADY-COVERED** |
| Dedicated retrieval-oriented frontend page | No `SearchPage.js`. Existing pages are queue-oriented (`DocumentsHubPage`, `UnifiedQueuePage`, `MyQueuePage`, `TriageQueuePage`, `ReviewQueuePage`). | **BUILD-THIS-WEEK** — minimal wrapper UI over the existing search endpoint. No new backend work required. |
| Search across non-AP doc types (sales / warehouse / OTHER) | The search endpoint is doc-type-agnostic and queries `hub_documents` directly, which contains all classified docs. | **ALREADY-COVERED** (backend); UI gap is the same as above. |
| Search across the **historical Square9 archive** that is not in `hub_documents` | Unknown — depends on whether Square9 holds documents that were never imported into the hub. See §6.A. | **VALIDATE DAY-1** — disposition deferred until §6.A finishes. |

### Priority 2 — Route/classify new email arrivals

| Sub-function | Hub state today | Disposition |
|---|---|---|
| AP mailbox intake (`hub-ap-intake@gamerpackaging.com`) | Live; 163+ AP docs ingested via Graph API polling per FUNCTIONAL_CAPABILITY_AUDIT. | **ALREADY-COVERED** |
| AI classification | Live; ~84% hit rate per audit (`AP_INVOICE`, `SALES_INVOICE`, `OTHER`, etc.). | **ALREADY-COVERED** |
| Field extraction | Live; 605 vendor profiles, 968 aliases. | **ALREADY-COVERED** |
| Vendor matching + BC validation | Live; 278K BC reference records cached; verified by Batch-3 5/5 P1 result. | **ALREADY-COVERED** |
| SharePoint routing (folder selection, upload) | Live; `folder_routing_service.py` handles credit memos / freight / warehouse / vendor / international / dunnage / storage; 199 `Completed` docs archived. | **ALREADY-COVERED** |
| Sales mailbox intake (`hub-sales-intake@gamerpackaging.com`) | Mailbox configured in `mailbox_sources`; per FUNCTIONAL_CAPABILITY_AUDIT, **0 mail_intake_log rows from it**. Poller has never fetched a customer PO. | **BUILD-THIS-WEEK** — diagnose + enable. Without this, sales-side users will notice on Friday. |
| Warehouse / shipping / receipts mailbox intake | Unknown. Intake may flow through `hub-ap-intake@` and be classified as warehouse/shipping types, or there may be a separate mailbox not yet polling. | **VALIDATE DAY-1** — see §6.B. |
| Classification of `OTHER` to a useful destination | Per audit, ~16% of docs are `doc_type: None`. They land in the queue but have no automated routing. | **DEFER-NOT-USER-VISIBLE** for cutover — these stay in the unclassified queue exactly as they would have under Square9's "Unclassified" stage. Manual reclass is current behavior. |

### Priority 3 — Drawer/folder browse

| Sub-function | Hub state today | Disposition |
|---|---|---|
| Browse by doc_type | `DocTypeDashboardPage.js` exists. | **VALIDATE DAY-1** — confirm whether warehouse / shipping / sales-side / OTHER doc types are first-class browsable categories. See §6.C. |
| Browse by SharePoint folder | `SharePointRoutingPage.js` exists; `folder_routing_service.py` covers the structured folder taxonomy. | **VALIDATE DAY-1** — confirm whether end-users (not admins) browse via this UX, or only via SharePoint directly. |
| Drawer-style hierarchy (Square9-style drawer → folder → doc) | No 1:1 equivalent in current UX. Hub's axes are doc_type / status / vendor. | **BUILD-THIS-WEEK** only if §6.C reveals operators rely on Square9 drawer browse for non-AP retrieval. Otherwise the existing search page covers retrieval. |
| Vendor / customer drill-down | `VendorIntelligencePage.js`, `StableVendorsPage.js`, `SalesDashboardPage.js` exist. | **ALREADY-COVERED** for vendor side; **VALIDATE DAY-1** for customer side. |

### Priority 4 — Multi-page PDF split with per-page filing

| Sub-function | Hub state today | Disposition |
|---|---|---|
| Auto-split (heuristic) | `POST /api/documents/{id}/auto-split` wired. | **ALREADY-COVERED** |
| Manual split with operator-defined page ranges | `POST /api/documents/{id}/split` accepts `SplitRequest`. Endpoint wired. | **ALREADY-COVERED** (backend) |
| Operator UX for manual page-range split | Unknown. Per FUNCTIONAL_CAPABILITY_AUDIT, "no operator UX to manually split a 50-page batch by page-range." | **VALIDATE DAY-1** — see §6.D. If used this week, **BUILD-THIS-WEEK**; if not, **DEFER-NOT-USER-VISIBLE**. |
| Batch PO split | `POST /api/documents/{id}/split-batch` wired. | **ALREADY-COVERED** |
| Delete pages | `POST /api/documents/{id}/delete-pages` wired. | **ALREADY-COVERED** |
| Split status | `GET /api/documents/{id}/split-status` wired. | **ALREADY-COVERED** |

### Other Square9 functions (not user-visible priorities)

| Function | Hub state | Disposition |
|---|---|---|
| Retry counter (Square9 deletes after 4 failures) | `POST /api/documents/{id}/reset-retries` exists; no auto-delete. Manual delete works. | **DEFER-NOT-USER-VISIBLE** |
| Location code validation (SC/MSC) | Not implemented; BC validation handles location at post time. | **DEFER-NOT-USER-VISIBLE** |
| Easy Lookup (initial quick match) | Not implemented; vendor alias + BC search handles. | **DEFER-NOT-USER-VISIBLE** |
| `International12h` flag | Not implemented; `_detect_international_vendor` exists in folder routing for routing only. | **DEFER-NOT-USER-VISIBLE** |
| Custom indexing fields per doc type | Not implemented; extraction fields are doc-type-fixed. | **DEFER-NOT-USER-VISIBLE** |
| Square9 stage display per doc | `Square9WorkflowTracker.js` + `square9_stage` field + `GET /api/square9/stage-counts`. | **ALREADY-COVERED** (and the cutover endpoint archives this field cleanly). |

## 4. Summary by classification

### ALREADY-COVERED (no work needed for Friday)

- AP mailbox intake / classification / extraction / vendor matching / BC validation / SharePoint upload.
- Backend search endpoint + list endpoint.
- Splitting backend (auto / manual / batch / delete-pages / status).
- Vendor drill-down.
- Square9 stage tracking (will be archived cleanly at cutover).
- Cutover toggle infrastructure (archive + restore + readiness probe).

### BUILD-THIS-WEEK (concrete gap closure)

- **G1.** A retrieval-oriented frontend page (working title:
  `SearchPage.js`) wrapping the existing
  `GET /api/documents/search` endpoint with filters by
  `doc_type`, `vendor_canonical`, `customer`, `created_utc`
  date range, and free-text. Adds a SharePoint-link click-through
  on each result.
- **G2.** Sales mailbox polling diagnosis + enablement so that
  `hub-sales-intake@gamerpackaging.com` actually produces
  `mail_intake_log` rows. Absence of this is the single most
  likely reason sales-side users would notice on Friday.

### CONDITIONAL — VALIDATE DAY-1 BEFORE CLASSIFYING

- **C1.** Historical Square9 archive reachability (§6.A).
- **C2.** Warehouse / shipping mailbox path (§6.B).
- **C3.** Drawer/folder browse for non-AP types (§6.C).
- **C4.** Operator manual page-range split UX usage (§6.D).
- **C5.** Scanner / MFP inflow (assumption #4 to validate).

Each may flip to `BUILD-THIS-WEEK` or
`DEFER-NOT-USER-VISIBLE` after a short read-only check on
Day 1 of the cutover plan.

### DEFER-NOT-USER-VISIBLE (explicitly out of scope this week)

- Retry counter auto-delete behaviour.
- Location code validation.
- Easy Lookup pre-match.
- `International12h` flag explicit handling.
- Custom indexing fields per doc type.
- `OTHER` doc-type auto-routing automation.
- Any code change to `tier1_batch_runner.py` or AP scripts.

## 5. Risk assessment for Friday cutover

Under the locked assumptions, the residual user-visible risks
are:

| Risk | Mitigation in cutover plan |
|---|---|
| User opens hub to search and gets no results because the search UX is missing | Build G1 (SearchPage wrapper). Ship by Wed. |
| Sales user expects an inbound PO to appear; it doesn't because sales-mailbox poller is dead | Diagnose + enable G2. Ship by Wed. |
| Warehouse user expects a routed shipment doc and it didn't route | Validate C2 Day-1. If warehouse uses a separate mailbox not currently polled, treat as a G2-equivalent. |
| User goes to find a 2024 historical doc that exists only in Square9 | Validate C1 Day-1. If Square9 has a meaningful unmirrored archive, document the read-only fallback path through Square9 archive (Square9 stays alive as backend archive per assumption #3) and surface it from the hub UI as a clearly-labeled link. |
| Operator needs to split a multi-page batch; UI doesn't expose page-range split | Validate C4 Day-1. If active, ship a thin UI over existing endpoints. |
| Someone scans a paper doc into a Square9-attached MFP | Validate C5 Day-1. If unused → no work. If used → defer cutover for that one inflow path or coordinate scan-to-email. |
| Cutover toggle fired but a hub regression appears | `POST /api/square9/restore-stage-data` is the documented escape hatch. |

## 6. Day-1 validation checklist (read-only)

These checks are **read-only** and produce evidence artifacts
in `prod_reports/`. They are pre-conditions for advancing to
the cutover plan; nothing here changes data or code.

| # | Check | Read-only command shape (illustrative; final commands appear in the cutover plan) |
|---|---|---|
| §6.A | Square9 historical archive reach: how many docs exist in Square9 that are **not** mirrored to `hub_documents` or SharePoint? Are any user-visible? | Inspect Square9 export count vs `hub_documents` count by date range; cross-check against SharePoint folder population. |
| §6.B | Warehouse / shipping mailbox path: do warehouse and shipping docs flow through `hub-ap-intake@` (and get classified as warehouse types) or via a separate mailbox? | `db.mailbox_sources.find()`, `db.mail_intake_log` last-7d aggregation by mailbox + classified `doc_type`. |
| §6.C | Drawer/folder browse coverage: does `DocTypeDashboardPage` actually surface warehouse / shipping / sales / OTHER as first-class browse categories, or only AP? | UI visit (operator-side; no DB write). |
| §6.D | Manual page-range split usage: have operators used the split endpoints in the last 30 days? | `db.workflow_events.find({event_type: /split/i, ts: last 30d})` count. |
| §6.E | Scanner / MFP inflow: any active scan-to-folder or scan-to-email source today? | Operator confirmation; check `mail_intake_log` for any sender pattern matching scanner devices. |
| §6.F | Sales mailbox status (G2 root cause): why did `hub-sales-intake@` never poll? Credentials, scheduler, mailbox empty, or disabled? | `db.mailbox_sources.find({mailbox_address:/sales-intake/i})`, `db.mail_intake_log.count(...)`, backend log scan for sales-mailbox poller errors. |

The cutover plan will spell these out as concrete `docker
compose exec -T ...` commands; this audit only declares what
needs to be checked.

## 7. Proposed shape of `SQUARE9_CUTOVER_PLAN.md`

The successor artifact (drafted only after this audit signs)
will contain:

1. Day-by-day Mon–Fri schedule keyed to the locked assumptions.
2. Day-1 evidence capture (the §6 checks above).
3. G1 (SearchPage) implementation gate + acceptance criteria.
4. G2 (sales mailbox diagnosis + enablement) gate + acceptance.
5. Conditional gates for C1–C5 if Day-1 flips them to
   `BUILD-THIS-WEEK`.
6. A 24–48h **parallel shadow phase** during which Square9
   stays active and the hub serves all user surfaces; any
   discrepancy is a no-go for cutover.
7. A signed Friday cutover gate that authorizes the single
   `POST /api/square9/archive-stage-data` call, with a §6-style
   verbatim clearance line analogous to Batch-3.
8. Post-cutover monitoring window (Fri–Mon) with the
   `restore-stage-data` escape hatch documented.
9. Out-of-scope fence restated (parked AP classes, no script
   edits, no production BC writes).

The plan does **not** authorize cutover by being signed; the
cutover itself is a separate Friday clearance line.

## 8. What this audit deliberately does NOT do

- Does not propose code changes.
- Does not invoke the Square9 cutover toggle.
- Does not change any hub or Square9 data.
- Does not classify scanner inflow without Day-1 evidence.
- Does not pre-commit to a non-AP doc-type drawer UI without
  Day-1 evidence (§6.C).
- Does not re-open any parked AP class.
- Does not extend, modify, or replace the Batch-3 fence
  posture.
- Does not reactivate the consumed Batch-3 §6 clearance.
- Does not commit to a Friday cutover. That commitment is the
  cutover plan + its own Friday clearance line.

## 9. Sign request

- **"Sign as-is"** → I draft `SQUARE9_CUTOVER_PLAN.md` next,
  Day-1 evidence first, against the classifications above.
  Lane 2 / Lane 3 onboarding can proceed in parallel and may
  even contribute (accounting in Lane 2 is exactly the cohort
  to test "no user notices").
- **"Sign with amendments: [paste]"** → revise; re-sign.
- **"Reject"** → re-scope direction.

Standing by.
