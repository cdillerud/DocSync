# INTERNAL — AP Review Metadata Validation

**Audience:** GPI Hub IT / Engineering. **Not for Accounting.**
**Status:** Internal validation note only. Accounting has not been engaged.
**Posture:** Read-only investigation; no code changes, no Mongo writes,
no AP-facing communication.

---

## 1. Current finding

The existing GPI Hub AP Review panel can update every metadata field
the document-body reconciliation probe scores against. **No new UI or
API needs to be built before AP testing begins.**

This was discovered while investigating two `content_match_invoice_only_below_threshold`
rows from the rerun probe. Their bodies matched a Hub doc on invoice
number but the Hub-side metadata was thin enough that score stayed at
0.55 (below the 0.85 confidence gate). The question — "can the
existing UI fix this?" — is answered: **yes**.

---

## 2. Existing route

```
Browser:   /documents/{doc_id}
Component: frontend/src/components/APReviewPanel.js
           (rendered by frontend/src/pages/DocumentDetailPage.js:1137,
            gated on document_type === 'AP_Invoice' OR
            suggested_job_type === 'AP_Invoice')
API:       PUT /api/ap-review/documents/{doc_id}
Handler:   backend/routers/ap_review.py:157  (save_ap_review)
Wrapper:   frontend/src/lib/api.js:308       (saveAPReview)
```

The handler has **no workflow_status gate** — it `find_one({"id": doc_id})`
and `$set`s, regardless of current workflow state. (Different from the
sibling `POST /update-fields` endpoint, which IS status-gated. The UI
uses the unrestricted `PUT` path.)

---

## 3. Fields verified writable + matcher mapping

| AP Review form field | DB field(s) written | Matcher field consumed |
| --- | --- | --- |
| Vendor (BC vendor lookup → `vendor_id`) | `vendor_canonical`, `vendor_id` | `vendor_canonical` ✓ |
| Vendor display name | `vendor_name_resolved`, `vendor_raw` | (haystack only) |
| Invoice Number | `invoice_number_clean` + `extracted_fields.invoice_number` | both ✓ |
| Invoice Date | top-level `invoice_date` + `extracted_fields.invoice_date` | both ✓ |
| Total Amount | `amount_float` + `extracted_fields.amount` | `amount_float` ✓ |
| PO Number | `po_number_clean` + `extracted_fields.po_number` | `po_number_clean` ✓ |
| Notes | `ap_review_notes` | n/a (audit trail) |
| Tax Amount | `tax_amount` | n/a |
| Document Type | `document_type`, `suggested_job_type`, + `classification_override` audit subdoc | n/a |

**Audit trail** (auto-emitted by `save_ap_review` via
`services.feedback_loop_service.record_feedback`):

- `vendor_correction` — before/after on `vendor_id` change.
- `amount_correction` — before/after on `total_amount` change.
- `po_correction` — before/after on `po_number` change.
- `field_edit` — before/after on `invoice_number` change.
- `approval` — every save records an `ap_review` source signal.
- `updated_utc` is stamped on every save.

---

## 4. Internal validation examples

These rows surfaced from the 2026-02 rerun probe (`PROBE_EXIT_CODE=0`,
both bodies fetched HTTP 200, both invoice numbers agreed with the
named Hub doc, both stuck at score 0.55). They are listed here as
**fixture cases for the IT/Eng validation lane only** — not as a work
queue handed to Accounting.

### Example A — Hawkemedia
- Hub doc id: `674926c1-d4da-42aa-897b-59cd4867c15f`
- Square9 file: `Hawkemedia_BILL-2026-04-84480_05012026.pdf`
- Body-level invoice extracted: `BILL-2026-04-84480`
- Probe `hub_missing_fields`: `amount_float`, `vendor_canonical`, `po_number_clean`
- Projected score after metadata fill (invoice + amount + invoice_date + vendor):
  `0.55 + 0.20 + 0.10 + 0.05 = 0.90` → above the 0.85 gate → would
  promote to `content_match_found`.

### Example B — XPO Logistics
- Hub doc id: `34a351ba-c1e2-4cd2-aac8-c6fa535fa352`
- Square9 file: `110749_XPO_104-570966_04132026_detention was requested to be removed.pdf`
- Body-level invoice extracted: `104-570966`
- Probe `hub_missing_fields`: `invoice_date`
- Projected score after `invoice_date` fill:
  `0.55 + 0.20 + 0.10 = 0.85` → at the gate → would promote to
  `content_match_found`.

---

## 5. Important note (read this before circulating)

- These two rows are **internal validation examples** only.
- **Accounting has not been engaged.** No AP user has been asked to
  edit or review either record.
- **Do not** route this memo, the rerun CSV
  (`prod_reports/AP_METADATA_CLEANUP_RERUN_ROWS.csv`), or the rerun
  probe outputs to Accounting. Do not draft AP-facing instructions
  off of them. Do not frame this work as user testing.
- The right way to use these examples internally is: an IT/Eng
  contributor with appropriate access opens the Hub AP Review panel,
  applies a metadata correction, and re-runs the probe to confirm the
  bucket flips. Until that internal pass is done, the lane stays
  closed at the engineering boundary.

---

## 6. Future AP testing implication (forward-looking, not a current ask)

When the AP UAT package is eventually assembled, the following are
already built and don't need to be added to that package's engineering
scope:

- A working AP Review panel that can correct vendor / invoice number /
  invoice date / amount / PO / notes on any AP_Invoice document.
- A working save endpoint (`PUT /api/ap-review/documents/{doc_id}`)
  that writes every matcher-relevant field and emits a structured
  audit trail.
- A reconciliation rerun command that AP-side cleanups can be measured
  against without rerunning the full 100-row sweep.

What the AP UAT package will need (when it is built — not now):

- Remedial step-by-step instructions tailored to the AP Review panel
  (screenshots, click-paths, "what to look at first").
- A short list of validation rows AP can practice on (curated from the
  current `content_match_invoice_only_below_threshold` cohort, after
  IT/Eng has dry-run them internally).
- A clear "stop here, escalate to IT" boundary for cases where the
  AP Review panel can't render (e.g. doc currently classified as
  non-AP_Invoice; the panel is gated on `document_type === 'AP_Invoice'`).

None of the above is in scope today. Captured here so the AP UAT lane
inherits the right starting context whenever it opens.

---

## 7. Post-edit internal verification command

After an internal contributor has corrected the metadata on either of
the example Hub docs through the AP Review panel, the reconciliation
probe rerun command is:

```bash
docker compose exec -T backend python -m scripts.document_body_reconciliation_probe \
    --triage-csv prod_reports/uncertain_square9_deep_triage.csv \
    --rerun-rows-csv prod_reports/AP_METADATA_CLEANUP_RERUN_ROWS.csv \
    --diag-sample 2 \
    --no-cache \
    --out-csv prod_reports/document_body_reconciliation_ap_cleanup_rerun.csv \
    --json    prod_reports/document_body_reconciliation_ap_cleanup_rerun.json \
    --md      prod_reports/document_body_reconciliation_ap_cleanup_rerun.md
```

Expected internal-validation outcome:

- `PROBE_EXIT_CODE=0`.
- Each row that received a metadata fill flips from
  `content_match_invoice_only_below_threshold` →
  `content_match_found`.
- Rows that were not touched stay where they were.

---

## 8. Scope fence (this memo enforces)

- ✗ No code changes proposed.
- ✗ No Mongo writes.
- ✗ No matcher / classifier / routing / Square9 / cutover changes.
- ✗ No DocuSign, HTTPS, or parked-AP work.
- ✗ No AP-user-facing instructions, emails, or handoff packs.
- ✓ Captures the validation-path-exists finding for future planning.
- ✓ Names two fixture rows the IT/Eng lane can dry-run against without
  needing Accounting.
