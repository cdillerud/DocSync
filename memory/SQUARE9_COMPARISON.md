# Square9 Workflow Comparison

## Overview

This document compares the original Square9 workflow logic with our GPI Document Hub implementation.

---

## AP Invoice Workflow Comparison

### Square9 AP Workflow States & Our Implementation

| Square9 Stage | Square9 Action | GPI Hub Status | GPI Hub Implementation | Match |
|---------------|----------------|----------------|------------------------|-------|
| **Import from Email** | Document enters via email | `captured` | Email polling via Graph API → `hub_documents` | ✅ |
| **CTS Direct Connect** | Alternative import | `captured` | Manual upload, CSV import | ✅ |
| **Classification** | Document categorized | `classified` | AI classification (Gemini 3 Flash) | ✅ |
| **Unclassified** | Classification failed | `captured` + retry | Re-classification with AI fallback | ✅ |
| **Set Counter to 0** | Initialize retry counter | N/A (no counter) | Not implemented - uses workflow_history instead | ⚠️ |
| **PO Number Is Empty** | Check for PO | `extracted` + validation | `validation_results.checks[po_exists]` | ✅ |
| **Set WF Status "Missing PO"** | Flag missing PO | `data_correction_pending` | `workflow_status` = data_correction_pending | ✅ |
| **Vendor ID Is Empty** | Check for Vendor | `vendor_pending` | `workflow_status` = vendor_pending | ✅ |
| **Location Code Check** | Validate location | N/A | Not implemented - BC validates directly | ⚠️ |
| **Error Recovery** | Handle errors | `failed` + retry | Manual re-process button | ✅ |
| **Counter < 4** | Retry limit check | N/A | No automatic retry limit | ⚠️ |
| **Delete Document** | Remove failed doc | Manual delete | DELETE /api/documents/{id} | ✅ |
| **Office 365 Connect** | Send to O365 | `exported` | SharePoint upload via Graph API | ✅ |

### Key Differences - AP Workflow

1. **Retry Counter**: Square9 has a counter (0-4) for retry attempts. We track history but don't auto-delete after N failures.
2. **Location Code Validation**: Square9 validates location codes (SC, MSC). We rely on BC lookup instead.
3. **Easy Lookup**: Square9 has "Easy Lookup" for initial matching. We use vendor alias system + BC API lookup.
4. **International Flag**: Square9 has "International12h" checks. Not implemented in GPI Hub.

---

## Warehouse Workflow Comparison

### Square9 Warehouse Workflow States & Our Implementation

| Square9 Stage | Square9 Action | GPI Hub Status | GPI Hub Implementation | Match |
|---------------|----------------|----------------|------------------------|-------|
| **Import from Email** | Document enters | `captured` | Same as AP | ✅ |
| **Set Counter to 0** | Initialize | N/A | Not implemented | ⚠️ |
| **Classification** | Categorize doc | `classified` | AI classifies as SHIPMENT, RECEIPT, etc. | ✅ |
| **PO Number Is Empty** | Check PO | `validation_pending` | PO validation check | ✅ |
| **Set WF Status "Missing PO"** | Flag missing | `data_correction_pending` | Sets workflow_status | ✅ |
| **Invoice Number Is Empty** | Check invoice | `extracted` | Extraction validation | ✅ |
| **Set WF Status "Missing Invoice"** | Flag missing | `data_correction_pending` | Sets workflow_status | ✅ |
| **Document Date Is Empty** | Check date | `extracted` | Date extraction validation | ✅ |
| **Set WF Status "Missing Location"** | Flag missing | N/A | Not directly mapped | ⚠️ |
| **Valid Document (✓)** | All checks pass | `ready_for_approval` | BC validation passed | ✅ |
| **Counter < 4 → Delete** | Auto-delete | N/A | Manual delete only | ⚠️ |
| **Error Recovery** | Handle errors | `failed` | Manual re-process | ✅ |
| **Send to SharePoint** | Archive | `exported` | SharePoint upload | ✅ |

---

## Workflow State Mapping

### Our Workflow States vs Square9 Concepts

| GPI Hub Status | Square9 Equivalent | Description |
|----------------|-------------------|-------------|
| `captured` | Initial import | Document received |
| `classified` | Classified | Document type identified |
| `extracted` | Fields validated | Data extraction complete |
| `vendor_pending` | "Missing Vendor ID" | Vendor not matched |
| `bc_validation_pending` | Pre-validation | Awaiting BC lookup |
| `bc_validation_failed` | Validation failed | BC check failed |
| `data_correction_pending` | Missing PO/Invoice/Date | Missing required fields |
| `ready_for_approval` | Valid Document (✓) | All validations passed |
| `approved` | N/A (manual) | Manually approved |
| `exported` | Send to SharePoint/O365 | Document archived |
| `archived` | N/A | Final state |
| `failed` | Error Recovery | Processing error |

---

## What We've Implemented ✅

1. **Email Import** - Graph API polling from configured mailboxes
2. **Document Classification** - AI-powered with Gemini 3 Flash
3. **Field Extraction** - Vendor, Invoice Number, Amount, PO Number, Due Date
4. **Vendor Matching** - Multiple strategies: exact, normalized, alias, fuzzy
5. **BC Validation** - Live lookup against BC Sandbox (vendors, POs, invoices)
6. **Duplicate Detection** - Check for existing invoices in BC
7. **SharePoint Integration** - Document upload and sharing links
8. **Manual Override** - Vendor resolution, BC validation override
9. **Workflow History** - Full audit trail of status transitions

---

## What's Missing or Different ⚠️

### Not Implemented

1. **Retry Counter** - Square9 deletes after 4 failed attempts. We don't auto-delete.
2. **Location Code Validation** - Square9 validates SC/MSC. We don't check location codes.
3. **Page Range Deletion** - Square9 can delete specific pages. We process entire documents.
4. **International Flag** - Square9 has "International12h" logic. Not implemented.
5. **Easy Lookup** - Square9's initial quick lookup. We go directly to full validation.

### Implemented Differently

1. **Classification Retry** - Square9 uses counter. We use AI confidence thresholds.
2. **Vendor Resolution** - Square9 may have dropdown lists. We use alias mapping + BC search.
3. **Error Handling** - Square9 has "Error Recovery" node. We have manual re-process + troubleshooting.

---

## Recommendations

### High Priority

1. **Add Retry Counter** - Implement automatic retry limits with configurable threshold
2. **Location Code Support** - Add location validation if required for warehouse docs
3. **Auto-Cleanup** - Consider auto-archiving/deleting documents after N failed retries

### Medium Priority

1. **Page-Level Processing** - Support for multi-page documents with page-specific actions
2. **International Handling** - Add flag/logic for international invoices if needed

### Low Priority

1. **Easy Lookup Cache** - Pre-cache common vendor lookups for faster matching
2. **Counter UI** - Show retry count in document detail view

---

*Generated: February 24, 2026*
