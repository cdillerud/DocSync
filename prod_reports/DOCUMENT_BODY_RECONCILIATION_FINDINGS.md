# Document Body Reconciliation — Findings

**Audience:** AP team, IT, Engineering
**Source:** `prod_reports/document_body_reconciliation_probe_limit100_final.{csv,json,md}`
**Cohort:** First 100 rows of `uncertain_square9_deep_triage.csv` (`manual_review_required`).
**Posture:** Read-only diagnostic. No DB writes, no routing changes.

---

## 1. Executive Summary

Final 100-row distribution after body-level reconciliation:

| bucket | count | share |
|---|---:|---:|
| content_match_found | 0 | 0% |
| content_match_invoice_only_below_threshold | 2 | 2% |
| likely_same_invoice_different_attachment_granularity | 0 | 0% |
| square9_only_true_gap | 86 | 86% |
| ocr_required | 5 | 5% |
| non_invoice_attachment | 5 | 5% |
| insufficient_content_access | 2 | 2% |
| manual_review_still_required | 0 | 0% |

The matcher is no longer the bottleneck on this cohort.

---

## 2. What This Means

In plain language:

- **86 of 100 rows are real intake gaps.** Hub never received the document. Body extraction read these PDFs successfully, the matcher scanned all 7,605 Hub documents, and there was no candidate at all — not by invoice number, not by PO, not by amount, not by reference. These are upstream intake-pipeline gaps, not matcher misses.
- **5 of 100 rows are not invoices.** They are operational tracking spreadsheets (`.xls` / `.xlsx`) that ended up in the AP cohort by mistake. Excel/Word/OOXML/OLE files are now correctly flagged as `non_invoice_attachment` instead of being routed to OCR.
- **5 of 100 rows are scanned image PDFs** that have no embedded text. They need an OCR pass (separate P2 work).
- **2 of 100 rows are confirmed Hub matches** blocked only by thin Hub-side metadata. The body found the same invoice number that Hub already has, but Hub does not have enough surrounding metadata (amount, vendor, date) to clear the 0.85 confidence threshold.
- **2 of 100 rows are SharePoint permission issues.** Graph returns `http_403` on a specific subfolder. This is an IT/access-control matter, not a code matter.

---

## 3. AP Action Items — Hub Metadata Cleanup

These 2 documents already exist in Hub. Touching the listed fields will promote both rows from `content_match_invoice_only_below_threshold` to `content_match_found` on the next probe run.

| # | Square9 file | invoice number | hub_doc_id | fields to backfill |
|---:|---|---|---|---|
| 1 | `Hawkemedia_BILL-2026-04-84480_05012026.pdf` | `BILL-2026-04-84480` | `674926c1-d4d…` | `amount_float`, `vendor_canonical`, `po_number_clean` (if available on the source invoice) |
| 2 | `110749_XPO_104-570966_04132026_detention…pdf` | `104-570966` | `34a351ba-c1e…` | `invoice_date` |

**Owner:** AP team.
**Action:** open the two Hub records by `hub_doc_id`, populate the listed fields from the source invoice, save.

---

## 4. Cohort Cleanup Items — Non-Invoice Attachments

These 5 files are operational tracking spreadsheets, not invoices. They should be excluded from AP invoice reconciliation and reclassified as operational/tracking attachments at the intake layer.

| # | file | type |
|---:|---|---|
| 1 | `Buske Commers Inventory 260501.xls` | inventory tracking |
| 2 | `Buske Commers outbound handling 260501.xls` | outbound handling tracking |
| 3 | `Evergreen freight allocation.xlsx` | freight allocation tracking |
| 4 | `WTR Peppertree to Buske Fairfield Tracking.xlsx` | shipment tracking |
| 5 | `Freight Issues Tracking Sheet.xlsx` | freight issue log |

**Owner:** AP + Engineering (intake classifier).
**Action:** filter Excel/Word attachments out of the AP cohort upstream of Square9 reconciliation.

---

## 5. OCR Items — Image / Scanned PDFs

5 documents are PDFs with no embedded text (image-only or scanned). The fetcher reaches them, but `pypdf` cannot extract text. An OCR pipeline is needed to recover their identity signals.

**Owner:** Engineering (P2 backlog).
**Action:** none required this iteration. Pick up as a separate work item if AP wants these specific 5 rows resolved.

---

## 6. IT / Permission Items — SharePoint 403

2 rows returned `http_403` from Microsoft Graph when the fetcher attempted to download the file. Both live under the same subfolder:

`Accounts Payable/Temp Folder/Dropship Not International/Ball/`

Affected files:
- `113296_BallMetalBeverageContainer_6219909_05042026 Kelly - cost.pdf`
- `113296_RLCarriers_NO. 1860207661_050426.pdf`

**Owner:** IT.
**Action:** verify the Graph application principal (used by the body fetcher) has read access to the `Dropship Not International/Ball/` subfolder. The other folders in the same drive succeed with the same credentials, so the missing permission is scoped specifically to this subfolder.

---

## 7. Engineering Conclusion

Body reconciliation is functionally complete for this cohort.

- **Matcher correctness:** verified. Every row that has a real Hub counterpart was found. The 2 invoice-only rows prove the body+reference signal pipeline works end-to-end against real production data.
- **Body extraction quality:** clean. Garbage tokens (`OICE`, `DATE`, `LINE`, dates captured as invoices, words glued to invoice numbers) are gone after two regex hardening passes.
- **Hub coverage:** healthy. `invoice_number_clean`, `extracted_fields.invoice_number`, and `normalized_fields.invoice_number` are each populated for ~33–35% of the corpus. Reference-number scoring scans all of them.
- **Remaining misses are not matcher problems.** They split into operational lanes with clear owners (AP cleanup, intake reclassification, OCR work, IT permissions, intake-pipeline gap investigation).

---

## 8. Recommended Next Work

In priority order:

1. **AP** — complete the 2 Hub metadata backfills in §3. Smallest, fastest, most visible win.
2. **IT** — review the 2 SharePoint 403 paths in §6. One ACL fix unblocks both rows.
3. **AP + Engineering** — exclude or reclassify the 5 non-invoice attachments in §4 at the intake layer so they stop appearing in the AP cohort.
4. **Engineering (P2)** — OCR pipeline for the 5 image/scanned PDFs in §5. Optional; depends on whether AP wants these specific rows.
5. **Engineering** — return to parked backlog:
   - 11 missing `routing_status` docs
   - 26 stalled `mail_poll_runs` watermarks
   - CARGOMO FREIGHT-WH and CITICARGO classes
   - DocuSign Phase 4
   - HTTPS migration

---

*Generated read-only from the 100-row probe artifacts. No production data was modified to produce this memo.*
