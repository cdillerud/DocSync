/**
 * Human-readable labels for readiness blocker / warning codes.
 *
 * Scope: presentation-layer mapping only. Raw codes still live unchanged in
 * backend payloads (readiness.blocking_reasons, top_blocking_reasons, etc.).
 *
 * Wording aligns with the document-detail OwnershipEvidencePanel so reviewers
 * see the same business language in both surfaces.
 */

export const BLOCKER_LABELS = {
  // Customer-Owned Ware (Lane C Step 1 + follow-up)
  cow_item_on_po: "CP item on PO / Adj-journal",
  cow_so_uses_base_item: "CP item on Sales — bill base item",
  cow_so_wrong_customer: "CP item — wrong customer",

  // Vendor Consignment (Lane C Step 2)
  consigned_item_on_ap_invoice: "Consigned item on AP invoice",
  consigned_item_wrong_state_on_ap: "AP invoice on terminal consignment state",
  consigned_item_on_sales_doc: "Consigned item on Sales doc",
  consigned_item_post_lifecycle_on_so: "Consigned item on Sales after lifecycle closed",
  consigned_item_wrong_location_on_adj: "Consigned item — adj-journal location mismatch",

  // Pre-Lane-C readiness codes (common ones; others fall through)
  po_missing: "PO missing",
  vendor_unresolved: "Vendor unresolved",
  customer_unresolved: "Customer unresolved",
  missing_required_fields: "Missing required fields",
  classification_low_confidence: "Classification low confidence",
  extraction_failed: "Extraction failed",
};

export function labelForBlocker(code) {
  if (!code) return "";
  if (BLOCKER_LABELS[code]) return BLOCKER_LABELS[code];
  // Fallback: preserve existing snake→Title Case behavior for unmapped codes
  return String(code)
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
