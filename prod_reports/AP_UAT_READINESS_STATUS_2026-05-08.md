# AP UAT Readiness — Internal Status Summary

> **INTERNAL — IT / Engineering only.**
> Accounting has not been engaged. Do not send this to AP.
> **Date:** 2026-05-08

---

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
