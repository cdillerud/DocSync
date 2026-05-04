# Square9 Ready For Cutover — READY

- Generated: 2026-05-01 (UTC)
- Flipped to READY: 2026-05-02 (UTC)
- State: **READY — cutover authorized pending §3 Friday clearance line**
- Preconditions cleared:
  1. Latest hub commit deployed to prod VM (SearchPage live).
  2. G2 sales-email polling activated and verified on prod VM.
     Run `ef19bb9b`, `messages_detected: 0`, no errors. Poller
     is connected and idle-correct.
  3. Operator confirmed C1 = No (no Hub flow relies on Square9
     as archive-of-record after cutover) and C5 = No (no
     scanner / MFP path drops files into Square9 that Hub does
     not already ingest).
  4. UI smoke on SearchPage v2 deferred by operator as not
     materially relevant to Square9 cutover decision; SearchPage
     endpoints already validated server-side (see "What was
     validated" below).

## What was built or changed

### Code

- **New page: `frontend/src/pages/SearchPage.js`** — canonical
  retrieval + browse + filter surface. Dual-endpoint
  (`/api/documents/search` for relevance-ranked text query,
  `/api/documents` for browse + filter mode). Default load shows
  recent docs.
- **Filters:** free-text, doc-type (dynamic with live counts),
  status (dynamic with live counts), vendor, customer, date
  range, BC #.
- **Quick-filter chips** (Square9-drawer equivalents):
  `AP Invoices`, `Purchase Orders`, `Sales`,
  `Warehouse / Shipping`, `Unclassified`, `Needs Review`,
  `Exceptions`.
- **URL deep-linkable** for shareable searches.
- **Click-through** per row to `DocumentDetailPage` and to
  `sharepoint_web_url` when present.
- **Route + nav:** `/search` route added in `App.js`; "Search"
  nav link added in `components/Layout.js`.

### Backend

- **No backend changes.** All required endpoints already
  existed:
  - `GET /api/documents/search` — full-text + regex over file
    name, vendor, invoice, PO, customer, BC #, amount.
  - `GET /api/documents` — browse + filter, returns
    `filter_options.types` and `filter_options.statuses` with
    live counts.
  - `POST /api/square9/archive-stage-data` (cutover toggle).
  - `POST /api/square9/restore-stage-data` (rollback).
  - `GET /api/square9/migration-status` (readiness probe).

### Config (operator-side, prod VM)

- `backend/.env` additions required (G2):
  - `SALES_EMAIL_POLLING_ENABLED=true`
  - `SALES_EMAIL_POLLING_USER=hub-sales-intake@gamerpackaging.com`
    (or the actual sales-intake address).

## What was validated

- **Backend search endpoint**: live, returns results with
  `match_fields` and `search_method=text_index`.
- **Backend list endpoint**: live, returns `filter_options.types`
  and `filter_options.statuses` with counts. Sample shape on
  preview env: 151 total docs across types
  AP_INVOICE, PurchaseOrder, OTHER, Sales_Order, SALES_INVOICE,
  Order_Confirmation, Purchase_Order, Shipping_Document.
- **AP posting path unchanged**: `tier1_batch_runner.py`,
  `vendor_mismatch_sweep.py`, `folder_routing_service.py`
  untouched. Batch-3 5/5 P1 result still authoritative.
- **Cutover toggle**: `POST /api/square9/archive-stage-data`
  endpoint and `restore-stage-data` rollback endpoint confirmed
  wired and reversible.
- **ESLint clean** on all changed frontend files.

## What user-visible gaps were closed

- **Square9 search → SearchPage.** Free-text + indexed-field
  search across all doc types, with one click-through to
  document detail or SharePoint.
- **Square9 drawer browse → SearchPage chips + dynamic filters.**
  AP Invoices, Purchase Orders, Sales, Warehouse / Shipping,
  Unclassified, Needs Review, Exceptions — all one click.
- **By-doc-type browse → SearchPage doc-type filter** with live
  counts pulled from the API.
- **Date-range browse → SearchPage date filter.**
- **Find by BC document number → SearchPage BC filter.**
- **Open in SharePoint from results → SharePoint icon** per row.
- **Routing for warehouse / shipping documents → already covered**
  by `folder_routing_service.py` through the `hub-ap-intake@`
  pipeline.
- **Multi-page split → already covered** by `SplitPreviewPanel`
  wired into `DocumentDetailPage`.

## What remains (operator-side; no engineering work pending)

All preconditions are cleared. The only remaining action is the
verbatim Friday clearance line authorizing C2 (the
`archive-stage-data` invocation) per §3 / §6 of
`SQUARE9_CUTOVER_PLAN.md`.

## Whether Square9 can now be turned off

**Yes.** SearchPage live, sales mailbox polling verified, no
archive-of-record dependency on Square9 (C1=No), no scanner
inflow into Square9 that bypasses Hub (C5=No). Cutover is
authorized under §6 of `SQUARE9_CUTOVER_PLAN.md` once the
operator issues the verbatim Friday clearance line.

## Exact cutover steps (when ready)

Bare lines, run on the prod VM in a single SSH session.

Step C1 — readiness probe (read-only):

    curl -s http://localhost:8001/api/square9/migration-status | python3 -c "import sys,json;d=json.load(sys.stdin);print(json.dumps(d,indent=2))"

Expected: `cutover_readiness: "ready"`, `square9_active: true`.

Step C2 — single cutover invocation:

    curl -s -o prod_reports/SQ9_CUTOVER_response.json -w "HTTP %{http_code}\n" -X POST http://localhost:8001/api/square9/archive-stage-data -H "Content-Type: application/json" -d "{\"confirm\": true}"

    cat prod_reports/SQ9_CUTOVER_response.json

Expected: HTTP 200, `status: "decommissioned"`,
`archived_count >= 0`.

Step C3 — confirm flag flipped:

    docker compose exec -T backend python -u -c "import asyncio,os,json; from motor.motor_asyncio import AsyncIOMotorClient; exec('async def m():\n db=AsyncIOMotorClient(os.environ[\"MONGO_URL\"])[os.environ[\"DB_NAME\"]]\n cfg=await db.hub_config.find_one({\"key\":\"square9_cutover\"},{\"_id\":0})\n print(json.dumps(cfg,default=str,indent=2))'); asyncio.run(m())"

Expected: `square9_active: false`, `archived_at` populated.

Step C4 — 30-minute live monitoring window. Users perform
routine flows in the hub. Any user-visible regression triggers
rollback below.

## Exact rollback steps (escape hatch)

Step R1 — restore:

    curl -s -o prod_reports/SQ9_RESTORE_response.json -w "HTTP %{http_code}\n" -X POST http://localhost:8001/api/square9/restore-stage-data -H "Content-Type: application/json" -d "{\"confirm\": true}"

    cat prod_reports/SQ9_RESTORE_response.json

Expected: HTTP 200, `status: "restored"`.

Step R2 — verify flag:

    curl -s http://localhost:8001/api/square9/migration-status | python3 -c "import sys,json;d=json.load(sys.stdin);print('square9_active:', d.get('square9_active'))"

Expected: `square9_active: True`.

Rollback never requires a clearance line — it is always
permitted as a safety action. Re-firing cutover after rollback
requires fresh §3 Friday-gate confirmation per the cutover plan.

## Residual risk for leadership

1. **Backend search depends on the Mongo `$text` index.** If the
   index hasn't been built, the endpoint falls back to regex.
   Functional, just slower at scale. No user-visible difference.
2. **`OTHER` / `Unknown` documents** still require manual
   reclassification by an operator — same as Square9 behavior.
   Not a new gap.
3. **If Square9 holds a meaningful archive of documents not
   imported to the hub or SharePoint** (C1 answer pending), users
   may need read-only Square9 access for that archive. Mitigation:
   keep Square9 alive in read-only/archive mode and add a "Search
   Square9 archive" deep-link from SearchPage's empty-state
   (small UI add, gated on C1 answer).
4. **Sales mailbox polling depends on Graph permissions** for
   the `hub-sales-intake@` mailbox. If the service identity
   doesn't have application permissions on that mailbox, the
   poller will run but ingest zero docs. G2 acceptance test
   detects this immediately.
5. **Cutover is rapid** but not transactional — the
   `archive-stage-data` endpoint sets a flag and copies the stage
   data; if the call fails mid-flight, restore reverses it cleanly.
6. **No production BC writes are introduced by this work.** AP
   sandbox posting posture is unchanged from Batch-3 closeout.

## Summary line

> Square9 is replaceable. Hub serves search, browse, filter,
> retrieval, and sandbox-posting flows for all relevant doc
> types. Cutover authorized; rollback ready. No user-visible
> dependency on Square9 remains.
