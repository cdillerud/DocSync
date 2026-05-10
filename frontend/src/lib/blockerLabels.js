/**
 * Human-readable labels for readiness blocker / warning codes.
 *
 * Scope: presentation-layer mapping only. Raw codes still live unchanged in
 * backend payloads (readiness.blocking_reasons, top_blocking_reasons,
 * validation_results.warnings, etc.).
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
  po_not_found: "PO extracted but not found in Business Central",
  po_validation: "PO validation failed",
  vendor_match: "Vendor match failed",
  vendor_unresolved: "Vendor unresolved",
  customer_unresolved: "Customer unresolved",
  missing_required_fields: "Missing required fields",
  classification_low_confidence: "Classification low confidence",
  extraction_failed: "Extraction failed",

  // Lane C Step 2.75 — warn-severity master-data gate
  master_data_incomplete: "Master data incomplete",

  // Warning-side codes (validation_results.warnings, derivedState.warnings)
  freight_direction_unknown:
    "Could not determine if this freight invoice is inbound or outbound — the order reference does not match any Sales Order or Purchase Order",
  vendor_unmatched: "Vendor not matched to a Business Central record yet",
  amount_missing: "Total amount is missing",
  invoice_date_missing: "Invoice date is missing",
  duplicate_suspect: "Possible duplicate of another invoice",
  extraction_low_confidence:
    "Some fields were extracted with low confidence — please double-check",
  bc_validation_failed:
    "Business Central validation failed — see details below",
};

export function labelForBlocker(code) {
  if (!code) return "";
  if (BLOCKER_LABELS[code]) return BLOCKER_LABELS[code];
  // If the input already contains whitespace, treat it as a
  // pre-formatted human sentence and return it unchanged. This
  // avoids the title-case fallback mangling sentences like
  // "Vendor 'X' not resolved to BC vendor" into "Vendor 'X' Not
  // Resolved To BC Vendor".
  if (/\s/.test(String(code))) return String(code);
  // Otherwise it's an unmapped snake_case code — title-case it so
  // AP testers never see a raw identifier.
  return String(code)
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Render any warning value into plain English. Accepts:
 *
 *   - null / undefined -> ""
 *   - string -> delegated to labelForBlocker (so "po_missing" becomes
 *     "PO missing" and unknown codes become Title Case rather than raw
 *     snake_case)
 *   - object with .message -> message (UI-friendly text from upstream)
 *   - object with .check_name -> mapped plain-English label, optionally
 *     followed by ".  <details>" when .details is present
 *   - object with only .details -> details
 *   - anything else -> "Warning"
 *
 * Never returns JSON.stringify output. The whole point of this helper is
 * that AP-facing surfaces should never display a stringified dict.
 */
export function labelForWarning(warn) {
  if (warn === null || warn === undefined) return "";
  if (typeof warn === "string") return labelForBlocker(warn);
  if (typeof warn !== "object") return "Warning";

  if (warn.message) return String(warn.message);

  if (warn.check_name) {
    const human = labelForBlocker(warn.check_name);
    if (warn.details) return `${human}. ${warn.details}`;
    return human;
  }

  if (warn.details) return String(warn.details);

  return "Warning";
}
