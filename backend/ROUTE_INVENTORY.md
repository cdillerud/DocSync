# Route Inventory Map — server.py Extraction

**Goal:** Extract all 85 routes from the monolithic `server.py` into domain-specific routers.
**Strategy:** Thin wrappers — import handler functions from `server.py`, re-register on new routers.
**Priority order:** new routers load before legacy router in `main.py`, so they take precedence.

---

## Domain 1: Auth (`routers/auth_routes.py`) — 2 routes

| # | Method | Path | Function | server.py Line | Status |
|---|--------|------|----------|----------------|--------|
| 1 | POST | /auth/login | `login` | 273 | EXTRACTED |
| 2 | GET | /auth/me | `get_me` | 280 | EXTRACTED |

---

## Domain 2: Documents (`routers/documents_routes.py`) — 28 routes

### CRUD & Metadata
| # | Method | Path | Function | server.py Line | Status |
|---|--------|------|----------|----------------|--------|
| 3 | POST | /documents/upload | `upload_document` | 1115 | EXTRACTED |
| 4 | GET | /documents | `list_documents` | 1201 | EXTRACTED |
| 5 | GET | /documents/{doc_id} | `get_document` | 1248 | EXTRACTED |
| 6 | GET | /documents/{doc_id}/events | `get_document_events` | 1283 | EXTRACTED |
| 7 | GET | /documents/{doc_id}/timeline | `get_document_timeline` | 1310 | EXTRACTED |
| 8 | GET | /documents/{doc_id}/derived-state | `get_document_derived_state` | 1331 | EXTRACTED |
| 9 | POST | /documents/{doc_id}/refresh-state | `refresh_document_state` | 1359 | EXTRACTED |
| 10 | GET | /documents/{doc_id}/matching-debug | `get_matching_debug` | 1608 | EXTRACTED |
| 11 | POST | /documents/{doc_id}/matching-debug/rerun | `rerun_matching_with_diagnostics` | 1688 | EXTRACTED |
| 12 | PUT | /documents/{doc_id} | `update_document` | 1770 | EXTRACTED |
| 13 | DELETE | /documents/{doc_id} | `delete_document` | 1780 | EXTRACTED |
| 14 | GET | /documents/{doc_id}/file | `get_document_file` | 1794 | EXTRACTED |
| 15 | GET | /documents/{doc_id}/square9-status | `get_square9_status` | 1827 | EXTRACTED |
| 16 | POST | /documents/{doc_id}/retry | `retry_document` | 1842 | EXTRACTED |
| 17 | POST | /documents/{doc_id}/reset-retries | `reset_document_retries` | 1919 | EXTRACTED |
| 18 | POST | /documents/{doc_id}/resubmit | `resubmit_document` | 1942 | EXTRACTED |
| 19 | POST | /documents/{doc_id}/link | `link_document` | 1978 | EXTRACTED |

### BC Reference Resolution (under /documents/)
| # | Method | Path | Function | server.py Line | Status |
|---|--------|------|----------|----------------|--------|
| 20 | POST | /documents/{doc_id}/resolve-reference | `resolve_document_reference` | 1416 | EXTRACTED |
| 21 | POST | /documents/{doc_id}/resolve-intelligence | `resolve_document_intelligence` | 1475 | EXTRACTED |
| 22 | GET | /documents/{doc_id}/reference-intelligence | `get_document_reference_intelligence` | 1520 | EXTRACTED |
| 23 | POST | /documents/{doc_id}/auto-resolve | `trigger_auto_resolve` | 1545 | EXTRACTED |

### Document Processing
| # | Method | Path | Function | server.py Line | Status |
|---|--------|------|----------|----------------|--------|
| 24 | POST | /documents/intake | `intake_document` | 5587 | EXTRACTED |
| 25 | POST | /documents/{doc_id}/classify | `classify_document` | 6022 | EXTRACTED |
| 26 | POST | /documents/{doc_id}/resolve | `resolve_and_link_document` | 6087 | EXTRACTED |
| 27 | POST | /documents/{doc_id}/reprocess | `reprocess_document` | 6210 | EXTRACTED |
| 28 | POST | /documents/batch-revalidate | `batch_revalidate_documents` | 6396 | EXTRACTED |
| 29 | POST | /documents/{doc_id}/preview-post | `preview_post_to_bc` | 6527 | EXTRACTED |

---

## Domain 3: Workflows (`routers/workflows_routes.py`) — 28 routes

### Legacy Workflow CRUD
| # | Method | Path | Function | server.py Line | Status |
|---|--------|------|----------|----------------|--------|
| 30 | GET | /workflows | `list_workflows` | 2073 | EXTRACTED |
| 31 | GET | /workflows/{wf_id} | `get_workflow` | 2082 | EXTRACTED |
| 32 | POST | /workflows/{wf_id}/retry | `retry_workflow` | 2089 | EXTRACTED |

### AP Invoice Queues
| # | Method | Path | Function | server.py Line | Status |
|---|--------|------|----------|----------------|--------|
| 33 | GET | /workflows/ap_invoice/status-counts | `get_ap_workflow_status_counts` | 7631 | EXTRACTED |
| 34 | GET | /workflows/ap_invoice/vendor-pending | `get_vendor_pending_queue` | 7656 | EXTRACTED |
| 35 | GET | /workflows/ap_invoice/bc-validation-pending | `get_bc_validation_pending_queue` | 7695 | EXTRACTED |
| 36 | GET | /workflows/ap_invoice/bc-validation-failed | `get_bc_validation_failed_queue` | 7728 | EXTRACTED |
| 37 | GET | /workflows/ap_invoice/data-correction-pending | `get_data_correction_pending_queue` | 7758 | EXTRACTED |
| 38 | GET | /workflows/ap_invoice/ready-for-approval | `get_ready_for_approval_queue` | 7781 | EXTRACTED |
| 39 | GET | /workflows/ap_invoice/metrics | `get_ap_workflow_metrics` | 8933 | EXTRACTED |

### AP Invoice Mutations
| # | Method | Path | Function | server.py Line | Status |
|---|--------|------|----------|----------------|--------|
| 40 | POST | /workflows/ap_invoice/{doc_id}/set-vendor | `set_vendor_for_document` | 7985 | EXTRACTED |
| 41 | POST | /workflows/ap_invoice/{doc_id}/update-fields | `update_document_fields` | 8066 | EXTRACTED |
| 42 | POST | /workflows/ap_invoice/{doc_id}/override-bc-validation | `override_bc_validation` | 8156 | EXTRACTED |
| 43 | POST | /workflows/ap_invoice/{doc_id}/start-approval | `start_approval` | 8218 | EXTRACTED |
| 44 | POST | /workflows/ap_invoice/{doc_id}/approve | `approve_document` | 8268 | EXTRACTED |
| 45 | POST | /workflows/ap_invoice/{doc_id}/reject | `reject_document` | 8324 | EXTRACTED |

### Generic Workflow Queues
| # | Method | Path | Function | server.py Line | Status |
|---|--------|------|----------|----------------|--------|
| 46 | GET | /workflows/generic/queue | `get_workflow_queue` | 7816 | EXTRACTED |
| 47 | GET | /workflows/generic/status-counts-by-type | `get_status_counts_by_doc_type` | 7866 | EXTRACTED |
| 48 | GET | /workflows/generic/metrics-by-type | `get_workflow_metrics_by_doc_type` | 7904 | EXTRACTED |

### Generic Workflow Mutations
| # | Method | Path | Function | server.py Line | Status |
|---|--------|------|----------|----------------|--------|
| 49 | POST | /workflows/{doc_id}/mark-ready-for-review | `mark_ready_for_review` | 8385 | EXTRACTED |
| 50 | POST | /workflows/{doc_id}/mark-reviewed | `mark_reviewed` | 8436 | EXTRACTED |
| 51 | POST | /workflows/{doc_id}/start-approval | `start_approval_generic` | 8487 | EXTRACTED |
| 52 | POST | /workflows/{doc_id}/approve | `approve_generic` | 8545 | EXTRACTED |
| 53 | POST | /workflows/{doc_id}/reject | `reject_generic` | 8603 | EXTRACTED |
| 54 | POST | /workflows/{doc_id}/complete-triage | `complete_triage` | 8661 | EXTRACTED |
| 55 | POST | /workflows/{doc_id}/link-credit-to-invoice | `link_credit_to_invoice` | 8718 | EXTRACTED |
| 56 | POST | /workflows/{doc_id}/tag-quality | `tag_quality_doc` | 8783 | EXTRACTED |
| 57 | POST | /workflows/{doc_id}/export | `export_document` | 8847 | EXTRACTED |

---

## Domain 4: BC Integration (`routers/bc_routes.py`) — 3 routes

| # | Method | Path | Function | server.py Line | Status |
|---|--------|------|----------|----------------|--------|
| 58 | POST | /bc/resolve-reference | `resolve_bc_reference` | 1385 | EXTRACTED |
| 59 | GET | /bc/companies | `list_bc_companies` | 2431 | EXTRACTED |
| 60 | GET | /bc/sales-orders | `list_bc_sales_orders` | 2436 | EXTRACTED |

---

## Domain 5: Mailbox Settings (`routers/mailbox_routes.py`) — 8 routes

| # | Method | Path | Function | server.py Line | Status |
|---|--------|------|----------|----------------|--------|
| 61 | GET | /settings/mailbox-sources | `list_mailbox_sources` | 8989 | EXTRACTED |
| 62 | GET | /settings/mailbox-sources/polling-status | `get_mailbox_polling_status` | 8995 | EXTRACTED |
| 63 | GET | /settings/mailbox-sources/{mailbox_id} | `get_mailbox_source` | 9029 | EXTRACTED |
| 64 | POST | /settings/mailbox-sources | `create_mailbox_source` | 9037 | EXTRACTED |
| 65 | PUT | /settings/mailbox-sources/{mailbox_id} | `update_mailbox_source` | 9062 | EXTRACTED |
| 66 | DELETE | /settings/mailbox-sources/{mailbox_id} | `delete_mailbox_source` | 9084 | EXTRACTED |
| 67 | POST | /settings/mailbox-sources/{mailbox_id}/test-connection | `test_mailbox_connection` | 9097 | EXTRACTED |
| 68 | POST | /settings/mailbox-sources/{mailbox_id}/poll-now | `poll_mailbox_now` | 9135 | EXTRACTED |

---

## Domain 6: Vendor Aliases (`routers/aliases_routes.py`) — 4 routes

| # | Method | Path | Function | server.py Line | Status |
|---|--------|------|----------|----------------|--------|
| 69 | GET | /aliases/vendors | `get_vendor_aliases` | 9316 | EXTRACTED |
| 70 | POST | /aliases/vendors | `create_vendor_alias` | 9322 | EXTRACTED |
| 71 | DELETE | /aliases/vendors/{alias_id} | `delete_vendor_alias` | 9364 | EXTRACTED |
| 72 | GET | /aliases/vendors/suggest | `suggest_alias_creation` | 9372 | EXTRACTED |

---

## Domain 7: Spiro Integration (`routers/spiro_routes.py`) — 4 routes

| # | Method | Path | Function | server.py Line | Status |
|---|--------|------|----------|----------------|--------|
| 73 | POST | /spiro/match-vendor | `spiro_match_vendor` | 2377 | EXTRACTED |
| 74 | GET | /spiro/search-companies | `spiro_search_companies` | 2387 | EXTRACTED |
| 75 | GET | /spiro/freight-carriers | `spiro_get_freight_carriers` | 2401 | EXTRACTED |
| 76 | POST | /spiro/is-freight-carrier | `spiro_is_freight_carrier` | 2414 | EXTRACTED |

---

## Domain 8: File Import (`routers/file_import_routes.py`) — 6 routes

| # | Method | Path | Function | server.py Line | Status |
|---|--------|------|----------|----------------|--------|
| 77 | POST | /sales/file-import/parse | `parse_sales_file` | 9672 | EXTRACTED |
| 78 | POST | /sales/file-import/import-orders | `import_sales_orders_from_file` | 9708 | EXTRACTED |
| 79 | POST | /sales/file-import/import-inventory | `import_inventory_from_file` | 9765 | EXTRACTED |
| 80 | GET | /sales/file-import/excel-sheets | `get_excel_sheets` | 9822 | EXTRACTED |
| 81 | GET | /sales/file-import/column-mappings | `get_column_mappings` | 9834 | EXTRACTED |
| 82 | GET | /sales/file-import/history | `get_import_history` | 9851 | EXTRACTED |

---

## Already-Extracted (in existing routers/ — these are dead code in server.py)

| # | Method | Path | Function | server.py Line | Existing Router |
|---|--------|------|----------|----------------|-----------------|
| 83 | GET | /automation-rules | `list_automation_rules` | 1574 | routers/automation_rules.py |
| 84 | POST | /automation-rules | `create_automation_rule` | 1584 | routers/automation_rules.py |
| 85 | GET | /vendor-extraction-profiles | `get_all_extraction_profiles` | 1749 | routers/vendor_extraction_profiles.py |

---

## Summary

| Domain | Router File | Routes | Status |
|--------|-------------|--------|--------|
| Auth | routers/auth_routes.py | 2 | EXTRACTED |
| Documents | routers/documents_routes.py | 28 | EXTRACTED |
| Workflows | routers/workflows_routes.py | 28 | EXTRACTED |
| BC Integration | routers/bc_routes.py | 3 | EXTRACTED |
| Mailbox Settings | routers/mailbox_routes.py | 8 | EXTRACTED |
| Vendor Aliases | routers/aliases_routes.py | 4 | EXTRACTED |
| Spiro Integration | routers/spiro_routes.py | 4 | EXTRACTED |
| File Import | routers/file_import_routes.py | 6 | EXTRACTED |
| **Already Extracted** | various | 3 | N/A |
| **TOTAL** | | **85** | |

---

*Created: Feb 2026 — Part of server.py modular refactor (P0)*
