# Square9 Fast-Track — Running Status

- Generated: 2026-05-01 (UTC)
- Mode: continuous-execution; updated as work lands.
- Target: end of week 2026-05-08, Square9 can be turned off
  with no user-visible regression.

## Done

| ID | Item | Evidence |
|---|---|---|
| G1 | `SearchPage.js` shipped (Square9 retrieval replacement). Filters: free-text, doc_type, vendor, customer, date range, BC #. Click-through to `DocumentDetailPage` and SharePoint. URL-deep-linkable (`/search?q=...&doc_type=...`). All `data-testid` set. | `frontend/src/pages/SearchPage.js`; route added in `App.js`; nav link "Search" added in `components/Layout.js`. ESLint clean. |
| G1.smoke | Backend endpoint live: `GET /api/documents/search?q=invoice` returns 3 results with `match_fields` + `search_method=text_index` on the preview env. | `curl` validation from agent. |
| Audit Δ | Confirmed `tier1_batch_runner.py` runner is unchanged (no AP regression risk from this work). Folder routing service already covers warehouse/shipping/international/dunnage/storage subfolders — no new build needed at intake. | `backend/services/folder_routing_service.py` unchanged. |
| Cutover toggle | Confirmed `POST /api/square9/archive-stage-data` endpoint live and reversible via `restore-stage-data`. Friday cutover is one authorized API call. | `backend/routers/square9.py` unchanged. |

## In flight

| ID | Item | Status |
|---|---|---|
| G2 | Sales mailbox polling enablement. Root cause is config: `SALES_EMAIL_POLLING_ENABLED='false'` and `SALES_EMAIL_POLLING_USER=''` are the defaults in `backend/server.py` (lines 198–199). Wiring is fully built. | Awaits operator-side prod-VM `.env` update (see §G2 operator block). No code change needed. |

## Remaining (planned)

| ID | Item | Plan |
|---|---|---|
| C1 | Square9 historical archive reach. | Operator answer needed: "approximately how many docs live ONLY in Square9 not on hub/SharePoint, and is anyone retrieving them this week?" If meaningful + active → BUILD a thin "Open in Square9 archive" deep-link from SearchPage; otherwise DEFER-NOT-USER-VISIBLE. |
| C2 | Warehouse / shipping mailbox path. | Codebase shows no separate warehouse/shipping mailbox; warehouse docs flow through `hub-ap-intake@` and route by `folder_routing_service.py`. Likely **ALREADY-COVERED**; await operator confirmation on whether warehouse/shipping users currently rely on a separate Square9 inbox. |
| C3 | Drawer/folder browse for non-AP. | `DocTypeDashboardPage.js` already filters by doc_type dynamically. Likely **ALREADY-COVERED**; UI walkthrough by operator on prod VM will confirm. |
| C4 | Manual page-range split UX. | `SplitPreviewPanel.js` already wired in `DocumentDetailPage.js`. Likely **ALREADY-COVERED**; operator confirms last-30d usage > 0 or = 0. |
| C5 | Scanner / MFP inflow. | Operator confirmation only. If active, halt cutover for that path; if not, DEFER. |

## Blocked

None as of this write.

## Next operator step (single block)

See `/app/memory/SQUARE9_FAST_TRACK_OPERATOR_BLOCK_001.md` for
the bare-line commands the operator runs to:

1. Verify SearchPage live on prod VM after rebuild.
2. Set the two G2 env vars in `backend/.env`, restart, prove
   ingest.
3. Run the C1/C2/C4/C5 evidence probes (read-only).

Single message paste-back from the operator → I synthesize
final disposition for each conditional gate and either ship
the next missing piece or declare cutover-ready.
