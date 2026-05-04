# Square9 Fast-Track — Running Status

- Generated: 2026-05-01 (UTC)
- Mode: continuous-execution; updated as work lands.
- Target: end of week 2026-05-08, Square9 turn-off with no
  user-visible regression.

## Done — code changes shipped to /app

| ID | Item | Evidence |
|---|---|---|
| **G1** | `SearchPage.js` is the canonical retrieval surface. Default load shows recent docs (browse mode via `/api/documents`). Text search uses `/api/documents/search`. Filters: free-text, doc_type, status, vendor, customer, date range, BC #. Doc-type and status options are dynamic (with live counts) from `filter_options`. URL deep-linkable. Click-through to `DocumentDetailPage` and SharePoint. All `data-testid` set. | `frontend/src/pages/SearchPage.js`, route `/search` in `App.js`, "Search" nav link in `Layout.js`. ESLint clean. |
| **G1.chips** | Square9-style drawer presets as one-click chips: AP Invoices, Purchase Orders, Sales, Warehouse / Shipping, Unclassified, Needs Review, Exceptions. Toggling re-runs the query. | Same file, `QUICK_FILTERS` constant + chip row above filter card. |
| **G1.smoke** | Backend `GET /api/documents/search?q=invoice` and `GET /api/documents?limit=2&queue_view=false&include_cleared=true` both return well-shaped JSON on the live preview env (151 docs, types A/P/S/W/Other all present, `filter_options.types` populated with counts). | curl validation. Preview pod auth gate prevents Playwright snapshot of the rendered page; lint clean. Operator's prod VM build will render. |
| Audit Δ | `tier1_batch_runner.py` not touched. `vendor_mismatch_sweep.py` not touched. `folder_routing_service.py` not touched. AP path fully preserved. Cutover toggle (`POST /api/square9/archive-stage-data`) confirmed wired. | grep + view confirmed. |

## In flight — operator-side (config / answers)

| ID | Item | What's needed |
|---|---|---|
| **G2** | Sales mailbox polling. Root cause CONFIRMED via codebase: `SALES_EMAIL_POLLING_ENABLED` and `SALES_EMAIL_POLLING_USER` default to `false` / `''` in `backend/server.py:198–199`; worker short-circuits at `email_polling_service.py:583`. Wiring fully built. | Operator sets the two env vars in `backend/.env` on prod VM and restarts backend. Bare-line block: `/app/memory/SQUARE9_FAST_TRACK_OPERATOR_BLOCK_001.md` Step 3–4. |
| **C1** | Square9 historical archive reach. | Operator one-line answer (Step 5 in operator block). |
| **C2** | Warehouse / shipping mailbox path. | Codebase: warehouse/shipping flow through `hub-ap-intake@` and route via `folder_routing_service.py`. Likely **ALREADY-COVERED**. Operator confirms (Step 6). |
| **C5** | Scanner / MFP inflow. | Operator one-line answer (Step 8). |

## Remaining (engineering — pending operator data)

| ID | Item | Conditional plan |
|---|---|---|
| Search→Square9 archive deep-link | If C1 reveals unmirrored Square9 archive with active retrieval need | Add a "Search Square9 archive" button on the empty-results state of SearchPage that opens the Square9 native search with the same query. Trivially small. **Not built yet — gated on C1 answer.** |
| C3 nav surface | If `DocTypeDashboardPage` is not reachable but operator wants by-doc-type page | The new SearchPage chips already cover this; no extra page needed. **Confirmed: no work.** |
| C4 split UX | If last-30d split events > 0 | `SplitPreviewPanel.js` already wired in `DocumentDetailPage`. Likely **ALREADY-COVERED**. **Confirmed: no work pending evidence.** |

## Hard blockers

None.

## Today's concrete progress (2026-05-01)

- `SearchPage.js` v1 → v2 with dual-endpoint mode (search + browse), live filter options, and 7 quick-filter chips. ESLint clean.
- `App.js` route + `Layout.js` nav link added.
- Operator block written: `/app/memory/SQUARE9_FAST_TRACK_OPERATOR_BLOCK_001.md`.
- Audit / plan / running-status docs in sync.

## Can Square9 be turned off yet?

**Not yet.** Code-side gaps are closed. Open items:

1. **G2** (sales mailbox env vars) — must land on prod VM before cutover; otherwise sales users will notice. Config-only fix.
2. **C1, C5** answers — needed to confirm no surprise dependency (active scanner / unmirrored archive). If both are clean, no further code is required.
3. Operator must rebuild and deploy the latest hub commit so SearchPage is live.

Once those three items resolve clean, this status flips to ready and `SQUARE9_READY_FOR_CUTOVER.md` becomes the active artifact.
