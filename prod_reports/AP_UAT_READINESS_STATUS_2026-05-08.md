# AP UAT Readiness — Internal Status Summary

> **INTERNAL — IT / Engineering only.**
> Accounting has not been engaged. Do not send this to AP.
> **Last updated:** 2026-05-10 (controlled-pilot baseline).
> **Original draft:** 2026-05-08.

---

## 2026-05-10 — Controlled pilot baseline (GREEN)

The Hub is ready for a **controlled AP pilot**. This is not cutover,
not Square9 replacement, not posting-to-BC testing. It is a guided
review with 1–2 AP testers under IT supervision.

### Production VM smoke run

The automated DOM smoke checker
(`backend/scripts/ap_smoke_walk_dom_check.py`) was run against the
P0+P1 set (16 documents) on the production VM at
`http://4.204.41.190:8080` with an authenticated Playwright session.

| Check | Result |
| --- | --- |
| Documents loaded under authenticated session | 16 / 16 |
| `doc_id_in_url` for every doc | 16 / 16 |
| Filename or title visible on page | 16 / 16 |
| Document Status card present | 16 / 16 |
| Document preview rendered | 16 / 16 |
| AP Review panel anchored above the PDF preview | 16 / 16 |
| All five AP fields visible (Vendor, Invoice #, Date, Amount, PO) | 16 / 16 |
| Raw JSON warnings leaked to UI | 0 / 16 |
| Raw snake_case blocker codes leaked to UI | 0 / 16 |
| Save / Mark Ready / Post / Re-process actions triggered | **none** |
| **Automated DOM smoke checker exit code** | **0 (pass)** |

Output artifacts on the VM:
- `/opt/gpi-hub/prod_reports/AP_SMOKE_WALK_DOM_CHECK_RESULTS.csv`
- `/opt/gpi-hub/prod_reports/AP_SMOKE_WALK_DOM_CHECK_SUMMARY.md`
- `/opt/gpi-hub/prod_reports/ap_smoke_walk_screens/*.png` (16 PNGs)

### Two real findings surfaced and fixed in this round

1. **`entity_resolution_blocking_items` raw leak.** Five documents
   were rendering items like `vendor_unmatched: 'MRP Solutions'` as
   raw `<Badge>` content in the AP-facing
   `DocumentIntelligencePanel.js`. Fix: new `humanizeBlockingItem()`
   helper that splits on `:`, runs the prefix through
   `labelForBlocker()`, and preserves any quoted value. Now renders
   as *"Vendor not matched to a Business Central record yet —
   'MRP Solutions'"*. Frontend rebuilt with
   `docker compose build --no-cache --pull frontend && docker compose
   up -d --force-recreate frontend`. Re-smoked → 0 leaks.
2. **DOM checker false-negative on `Document Status`.** Hub UI
   renders the card label as `DOCUMENT STATUS` (uppercase). The
   smoke checker's substring match was case-sensitive and failed on
   every doc. Fixed in `ap_smoke_walk_dom_check.py` to use
   `body_text.lower()`. Re-smoked → all 16 pass.

### One small cosmetic fix in the same session

3. **`po_not_found` blocker code now mapped to plain English** —
   previously fell through to the title-case fallback ("Po Not
   Found"). Added to `BLOCKER_LABELS` in `frontend/src/lib/blockerLabels.js`
   as "PO extracted but not found in Business Central".

### Strict scope held

- No backend auth bypass.
- No Mongo writes.
- No Save / Mark Ready / Post / Re-process actions.
- No matcher / classifier / routing / Square9 / DocuSign / HTTPS /
  parked-AP changes.
- No production cutover.
- Smoke validation is read-only end-to-end.

### What this unlocks (and what it does NOT)

✅ Controlled pilot with 1–2 AP testers, IT-supervised, read-and-edit
   only, on the assigned smoke-set documents.
❌ Open AP-floor rollout.
❌ Square9 retirement.
❌ Hub-to-BC posting from AP hands.
❌ Treating Hub as system of record.

### Next gates before the pilot

- AP supervisor sign-off on the test plan and kickoff doc.
- Pilot testers identified and IT on-call assigned.
- Pre-send checklist (test plan §17, kickoff "Pre-send checklist"
  section) all green.

---

## 2026-05-08 — Original status (preserved for context)

## Where we are

Three frontend AP-readiness fixes shipped to production and verified on the
two P0 documents (Hawkemedia, XPO). The Hub is now usable enough for an
internal IT/Alani smoke walk. Accounting is still not involved.

## What changed in production this round

| # | Fix | File(s) | Status |
| --- | --- | --- | --- |
| 1 | AP Review panel renders **above the PDF preview** on AP_Invoice docs (was below the fold). Wrapped in `<div id="ap-review-panel">` for deep-linking. | `frontend/src/pages/DocumentDetailPage.js` | ✅ Live |
| 2 | Warnings render in **plain English** instead of `JSON.stringify` blobs on both the BC Validation card and the Document Status (Derived State) card. New `labelForWarning()` helper plus 7 mapped check_name codes. | `frontend/src/lib/blockerLabels.js`, `DocumentDetailPage.js` | ✅ Live |
| 3 | Blocking issues render in **plain English sentence case** — raw `vendor_match` / `po_validation` codes no longer leak. `labelForBlocker` short-circuits on whitespace so already-human strings aren't mangled. Dedupe by display text. | `frontend/src/lib/blockerLabels.js`, `DocumentDetailPage.js` | ✅ Live |

Bundle hash on production: `main.17bcddab.js` (was `main.b74d42e1.js`).
14 unit tests on `blockerLabels` — all green; lint clean on touched files.

## What the P0 docs now show

### Hawkemedia — `/documents/674926c1-d4da-42aa-897b-59cd4867c15f`

- AP Review panel visible directly under Auto-Ready Routing, above the PDF preview.
- Vendor / Invoice # / Invoice Date / Total Amount / PO Number fields all render; missing fields are visibly empty (vendor_canonical, amount, PO).
- Document Status → Blocking Issues reads sentence case throughout:
  - Vendor not matched
  - Vendor match failed
  - PO validation failed
  - Vendor 'Hawke Media, LLC' not resolved to BC vendor
  - Total amount missing
- No raw snake_case codes anywhere on the page.

### XPO — `/documents/34a351ba-c1e2-4cd2-aac8-c6fa535fa352`

- AP Review panel visible above the PDF preview. All five core fields populated except Invoice Date (the expected gap).
- BC Validation → Warnings reads as plain English:
  > "Could not determine if this freight invoice is inbound or outbound — the order reference does not match any Sales Order or Purchase Order. Order reference '110749' not found as Sales Order or Purchase Order - cannot determine freight direction"
- Document Status → Blocking Issues reads sentence case ("Missing invoice date", "Invoice date missing").
- No JSON blobs anywhere on the page.

## Posture

- **Read-only** for the body-reconciliation lane. No corrections were saved on either P0 doc. The smoke walk is observation-only.
- **No Mongo writes.** No matcher / classifier / routing / Square9 / cutover / DocuSign / HTTPS work in this round.
- **Accounting still not engaged.** No AP-facing communication has been sent. The internal validation memo, smoke-set CSV/MD, execution checklist, quick-start MD, and the AP UAT plan draft remain INTERNAL DRAFT.

## Next action

**Internal smoke walk by IT / Alani**, using the two P0 docs above and the existing artifacts (no new files needed):

- `prod_reports/AP_INTERNAL_SMOKE_TEST_QUICK_START.md` — 7-step, ~30-minute walk
- `prod_reports/AP_INTERNAL_SMOKE_TEST_DOCUMENT_SET.csv` — 18-row curated list (sort by `priority`, walk P0 → P1)
- `prod_reports/AP_INTERNAL_SMOKE_TEST_MINIMAL_FINDINGS.csv` — log one row per doc walked

The walk validates: document opens, preview loads, AP Review panel appears
above the preview, fields are visible, status text is understandable. No
saves. No emails to Accounting. Stop after the two P0s if anything is
visibly broken.

After the walk:
1. Eng triages findings within 24 hours.
2. Top High findings get a remediation owner + target date.
3. Update the AP UAT draft (`memory/GPI_HUB_AP_USER_ACCEPTANCE_TEST_PLAN_DRAFT.md` and companions) with anything the walk surfaced.
4. Backfill the three missing smoke-set categories (`non_invoice_attachment`, `ocr_required`, `sharepoint_permission_edge`).
5. **Only then** consider involving Accounting.

## Engineering hygiene backlog (parked, not started)

- **Document Intelligence empty-state endpoints — normalize 404 → 200 empty payload.**
  - Endpoints: `GET /api/document-intelligence/{doc_id}` and `GET /api/document-intelligence/decision/{doc_id}` raise 404 by design when no result has been generated yet. Frontend handles it via `try/catch` and renders the "No intelligence result yet" empty state correctly, but the browser's network layer logs the 404 to DevTools console regardless.
  - **Reason for parking:** UI behaves correctly. AP testers will not have DevTools open. Does **not** block AP UAT.
  - **Suggested fix when picked up:** change those two endpoints to return 200 with `{ "exists": false, "result": null }` (mirroring the pattern that `/resolution/{doc_id}` and `/transaction-matches/{doc_id}` already use in the same router). ~6 lines, two hunks in `backend/routers/document_intelligence.py` (lines 418–424 and 373–379).
  - **Pickup gate:** after AP UAT smoke testing completes.

## Other backlog (unchanged from prior summary)

- 🟡 P1: OCR pipeline (`pytesseract` / Azure OCR) for the 5 image PDFs in the `ocr_required` bucket.
- 🟡 P2: Investigate 11 missing `routing_status` docs.
- 🟡 P2: Investigate 26 stalled watermarks from `mail_poll_runs`.
- 🟡 P2: Backfill the three missing smoke-set categories (`non_invoice_attachment`, `ocr_required`, `sharepoint_permission_edge`).
- 🟡 P3: CARGOMO / CITICARGO mapping; DocuSign Phase 4; HTTPS migration.

---

_End of internal status summary._
