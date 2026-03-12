# Route Inventory Map - server.py Extraction Progress

## Domain 1: Auth (2 routes) - TARGET: Remove duplicates (already in routes/auth.py)
| Line | Method | Path | Status |
|------|--------|------|--------|
| 273 | POST | /auth/login | PENDING |
| 280 | GET | /auth/me | PENDING |

## Domain 2: Aliases (4 routes + 1 helper) - TARGET: routers/aliases.py
| Line | Method | Path | Status |
|------|--------|------|--------|
| 9316 | GET | /aliases/vendors | PENDING |
| 9322 | POST | /aliases/vendors | PENDING |
| 9364 | DELETE | /aliases/vendors/{alias_id} | PENDING |
| 9372 | GET | /aliases/vendors/suggest | PENDING |
| 9407 | - | record_alias_usage() helper | PENDING |

## Domain 3: Mailbox Sources (8 routes + 1 helper) - TARGET: routers/mailbox_sources.py
| Line | Method | Path | Status |
|------|--------|------|--------|
| 8989 | GET | /settings/mailbox-sources | PENDING |
| 8995 | GET | /settings/mailbox-sources/polling-status | PENDING |
| 9029 | GET | /settings/mailbox-sources/{mailbox_id} | PENDING |
| 9037 | POST | /settings/mailbox-sources | PENDING |
| 9062 | PUT | /settings/mailbox-sources/{mailbox_id} | PENDING |
| 9084 | DELETE | /settings/mailbox-sources/{mailbox_id} | PENDING |
| 9097 | POST | /settings/mailbox-sources/{mailbox_id}/test-connection | PENDING |
| 9135 | POST | /settings/mailbox-sources/{mailbox_id}/poll-now | PENDING |
| 9158 | - | poll_mailbox_for_documents() helper (stays in server.py, used by worker) | STAYS |

## Domain 4: Sales File Import (6 routes) - TARGET: routers/file_import.py
| Line | Method | Path | Status |
|------|--------|------|--------|
| 9672 | POST | /sales/file-import/parse | PENDING |
| 9708 | POST | /sales/file-import/import-orders | PENDING |
| 9765 | POST | /sales/file-import/import-inventory | PENDING |
| 9822 | GET | /sales/file-import/excel-sheets | PENDING |
| 9834 | GET | /sales/file-import/column-mappings | PENDING |
| 9851 | GET | /sales/file-import/history | PENDING |

## Domain 5: BC Integration (2 routes) - TARGET: routers/bc_integration.py
| Line | Method | Path | Status |
|------|--------|------|--------|
| 2431 | GET | /bc/companies | PENDING |
| 2436 | GET | /bc/sales-orders | PENDING |

## Domain 6: Spiro (4 routes) - TARGET: Add to existing routes/spiro.py
| Line | Method | Path | Status |
|------|--------|------|--------|
| 2377 | POST | /spiro/match-vendor | PENDING |
| 2387 | GET | /spiro/search-companies | PENDING |
| 2401 | GET | /spiro/freight-carriers | PENDING |
| 2414 | POST | /spiro/is-freight-carrier | PENDING |

## Domain 7: Documents (~22 routes) - TARGET: routers/documents.py
| Line | Method | Path | Status |
|------|--------|------|--------|
| 1115 | POST | /documents/upload | PENDING |
| 1201 | GET | /documents | PENDING |
| 1248 | GET | /documents/{doc_id} | PENDING |
| 1283 | GET | /documents/{doc_id}/events | PENDING |
| 1310 | GET | /documents/{doc_id}/timeline | PENDING |
| 1331 | GET | /documents/{doc_id}/derived-state | PENDING |
| 1359 | POST | /documents/{doc_id}/refresh-state | PENDING |
| 1770 | PUT | /documents/{doc_id} | PENDING |
| 1780 | DELETE | /documents/{doc_id} | PENDING |
| 1794 | GET | /documents/{doc_id}/file | PENDING |
| 1827 | GET | /documents/{doc_id}/square9-status | PENDING |
| 1842 | POST | /documents/{doc_id}/retry | PENDING |
| 1919 | POST | /documents/{doc_id}/reset-retries | PENDING |
| 1942 | POST | /documents/{doc_id}/resubmit | PENDING |
| 1978 | POST | /documents/{doc_id}/link | PENDING |
| 5587 | POST | /documents/intake | PENDING |
| 6022 | POST | /documents/{doc_id}/classify | PENDING |
| 6087 | POST | /documents/{doc_id}/resolve | PENDING |
| 6210 | POST | /documents/{doc_id}/reprocess | PENDING |
| 6396 | POST | /documents/batch-revalidate | PENDING |
| 6527 | POST | /documents/{doc_id}/preview-post | PENDING |

## Domain 8: Workflows (~29 routes) - TARGET: routers/workflows.py
| Line | Method | Path | Status |
|------|--------|------|--------|
| 2073 | GET | /workflows | PENDING |
| 2082 | GET | /workflows/{wf_id} | PENDING |
| 2089 | POST | /workflows/{wf_id}/retry | PENDING |
| 7631 | GET | /workflows/ap_invoice/status-counts | PENDING |
| 7656 | GET | /workflows/ap_invoice/vendor-pending | PENDING |
| 7695 | GET | /workflows/ap_invoice/bc-validation-pending | PENDING |
| 7728 | GET | /workflows/ap_invoice/bc-validation-failed | PENDING |
| 7758 | GET | /workflows/ap_invoice/data-correction-pending | PENDING |
| 7781 | GET | /workflows/ap_invoice/ready-for-approval | PENDING |
| 7816 | GET | /workflows/generic/queue | PENDING |
| 7866 | GET | /workflows/generic/status-counts-by-type | PENDING |
| 7904 | GET | /workflows/generic/metrics-by-type | PENDING |
| 7985 | POST | /workflows/ap_invoice/{doc_id}/set-vendor | PENDING |
| 8066 | POST | /workflows/ap_invoice/{doc_id}/update-fields | PENDING |
| 8156 | POST | /workflows/ap_invoice/{doc_id}/override-bc-validation | PENDING |
| 8218 | POST | /workflows/ap_invoice/{doc_id}/start-approval | PENDING |
| 8268 | POST | /workflows/ap_invoice/{doc_id}/approve | PENDING |
| 8324 | POST | /workflows/ap_invoice/{doc_id}/reject | PENDING |
| 8385 | POST | /workflows/{doc_id}/mark-ready-for-review | PENDING |
| 8436 | POST | /workflows/{doc_id}/mark-reviewed | PENDING |
| 8487 | POST | /workflows/{doc_id}/start-approval | PENDING |
| 8545 | POST | /workflows/{doc_id}/approve | PENDING |
| 8603 | POST | /workflows/{doc_id}/reject | PENDING |
| 8661 | POST | /workflows/{doc_id}/complete-triage | PENDING |
| 8718 | POST | /workflows/{doc_id}/link-credit-to-invoice | PENDING |
| 8783 | POST | /workflows/{doc_id}/tag-quality | PENDING |
| 8847 | POST | /workflows/{doc_id}/export | PENDING |
| 8933 | GET | /workflows/ap_invoice/metrics | PENDING |

## Domain 9: Reference Intelligence (7 routes) - TARGET: routers/reference_intelligence.py
| Line | Method | Path | Status |
|------|--------|------|--------|
| 1385 | POST | /bc/resolve-reference | PENDING |
| 1416 | POST | /documents/{doc_id}/resolve-reference | PENDING |
| 1475 | POST | /documents/{doc_id}/resolve-intelligence | PENDING |
| 1520 | GET | /documents/{doc_id}/reference-intelligence | PENDING |
| 1545 | POST | /documents/{doc_id}/auto-resolve | PENDING |
| 1608 | GET | /documents/{doc_id}/matching-debug | PENDING |
| 1688 | POST | /documents/{doc_id}/matching-debug/rerun | PENDING |

## Remaining in server.py (not routes - shared infrastructure)
- Helper functions: get_graph_token, get_email_token, get_bc_token, upload_to_sharepoint, etc.
- AI classification pipeline functions
- Vendor matching functions  
- Document processing pipeline functions
- Config, models, constants
- Startup/shutdown lifecycle
- Background workers (email polling, etc.)

## Total Routes: 85 (across 9 domains)
