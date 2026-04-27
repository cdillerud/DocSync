# P0.1 Starter — Mutating Route Inventory (auto-generated)

Total mutating endpoints: **407**

Total GET endpoints: **473**

## Per-router mutating count

| Router | Count |
|---|---|
| `inventory_ledger.py` | 42 |
| `posting_patterns.py` | 27 |
| `admin.py` | 22 |
| `gpi_integration.py` | 21 |
| `bakeoff.py` | 18 |
| `document_intelligence.py` | 17 |
| `documents.py` | 16 |
| `pilot.py` | 16 |
| `inside_sales_pilot.py` | 14 |
| `sharepoint_routing.py` | 14 |
| `ap_review.py` | 12 |
| `readiness.py` | 11 |
| `sales_dashboard.py` | 9 |
| `intake_learning.py` | 8 |
| `inventory_xls.py` | 8 |
| `learning_core.py` | 8 |
| `vendor_reprocess.py` | 8 |
| `ap_advisory.py` | 7 |
| `bc_sandbox.py` | 7 |
| `freight_routing.py` | 7 |
| `settings.py` | 7 |
| `spiro.py` | 7 |
| `stable_vendor.py` | 7 |
| `aliases.py` | 6 |
| `auto_clear.py` | 5 |
| `auto_clear_reprocess.py` | 5 |
| `automation_rules.py` | 5 |
| `knowledge_seed.py` | 5 |
| `mailbox_sources.py` | 5 |
| `vendor_extraction_profiles.py` | 5 |
| `dev_tools.py` | 4 |
| `alerts.py` | 3 |
| `automation_intelligence.py` | 3 |
| `file_import.py` | 3 |
| `reprocess_comparison.py` | 3 |
| `ar_release.py` | 2 |
| `auth.py` | 2 |
| `auto_approve.py` | 2 |
| `cache.py` | 2 |
| `consigned_item_registry.py` | 2 |
| `cp_item_registry.py` | 2 |
| `dedup.py` | 2 |
| `email_polling.py` | 2 |
| `file_integrity.py` | 2 |
| `migration_routes.py` | 2 |
| `sales_pipeline_demo.py` | 2 |
| `sharepoint.py` | 2 |
| `square9.py` | 2 |
| `vendor_intelligence.py` | 2 |
| `vendor_profile_rebuild.py` | 2 |
| `workflow_fix.py` | 2 |
| `admin_eod.py` | 1 |
| `ap_validation.py` | 1 |
| `explain.py` | 1 |
| `feedback_health.py` | 1 |
| `inventory_items.py` | 1 |
| `layout_fingerprints.py` | 1 |
| `metrics.py` | 1 |
| `po_resolution.py` | 1 |
| `vendors.py` | 1 |
| `workflows.py` | 1 |

## Full mutating route list

| Router | Method | Path | Function |
|---|---|---|---|
| `admin.py` | POST | `/backfill-ap-mailbox` | `backfill_ap_mailbox` |
| `admin.py` | POST | `/backfill-sales-mailbox` | `backfill_sales_mailbox` |
| `admin.py` | POST | `/migrate-sales-to-unified` | `migrate_sales_documents_to_unified` |
| `admin.py` | POST | `/square9-cutover` | `execute_square9_cutover` |
| `admin.py` | POST | `/recompute-derived-states` | `recompute_derived_states` |
| `admin.py` | POST | `/sh-invoice/{doc_id}/assign-processor` | `assign_sh_processor` |
| `admin.py` | POST | `/sales-learning/backfill-bc-orders` | `backfill_sales_learning` |
| `admin.py` | POST | `/sales-learning/detect-posted-drafts` | `detect_posted_so_drafts` |
| `admin.py` | POST | `/sales-learning/evaluate-readiness` | `evaluate_readiness` |
| `admin.py` | POST | `/sales-learning/calibrate-confidence` | `calibrate_confidence_batch` |
| `admin.py` | POST | `/sales-learning/calibrate-document/{document_id}` | `calibrate_single_document` |
| `admin.py` | POST | `/sales-learning/generate-learning-suggestions` | `gen_learning_suggestions` |
| `admin.py` | POST | `/sales-learning/learning-suggestions/{suggestion_id}/approve` | `approve_learning_suggestion` |
| `admin.py` | POST | `/sales-learning/learning-suggestions/{suggestion_id}/reject` | `reject_learning_suggestion` |
| `admin.py` | POST | `/sales-learning/learning-suggestions/{suggestion_id}/apply` | `apply_learning_suggestion` |
| `admin.py` | POST | `/unknown-doc-reclaim/run` | `unknown_doc_reclaim_run` |
| `admin.py` | POST | `/unknown-doc-reclaim/post-process` | `unknown_doc_reclaim_post_process` |
| `admin.py` | POST | `/filename-heuristics/apply` | `filename_heuristics_apply` |
| `admin.py` | POST | `/duplicate-docs/resolve` | `duplicate_docs_resolve` |
| `admin.py` | POST | `/filename-heuristics/auto-apply` | `filename_heuristics_auto_apply` |
| `admin.py` | POST | `/filename-heuristics/custom-rules/{rule_id}/toggle` | `filename_heuristics_custom_rule_toggle` |
| `admin.py` | POST | `/sales-order-graph/feedback` | `sales_order_graph_feedback` |
| `admin_eod.py` | POST | `/run` | `run_eod` |
| `alerts.py` | POST | `/evaluate` | `trigger_alert_evaluation` |
| `alerts.py` | POST | `/{pattern_key}/dismiss` | `dismiss_alert` |
| `alerts.py` | POST | `/{pattern_key}/resolve` | `resolve_alert` |
| `aliases.py` | POST | `/vendors` | `create_vendor_alias` |
| `aliases.py` | DELETE | `/vendors/{alias_id}` | `delete_vendor_alias` |
| `aliases.py` | POST | `/vendors/dismiss-unmatched` | `dismiss_unmatched_vendor` |
| `aliases.py` | DELETE | `/vendors/by-alias/{alias}` | `delete_vendor_alias_by_name` |
| `aliases.py` | POST | `/vendors/accept-suggestion` | `accept_vendor_suggestion` |
| `aliases.py` | POST | `/vendors/batch-resolve` | `batch_resolve_vendor_aliases` |
| `ap_advisory.py` | POST | `/review/{document_id}` | `review_ap_document` |
| `ap_advisory.py` | POST | `/feedback/{document_id}` | `submit_ap_feedback` |
| `ap_advisory.py` | POST | `/calibrate/{document_id}` | `calibrate_ap_document` |
| `ap_advisory.py` | POST | `/generate-suggestions` | `generate_ap_suggestions` |
| `ap_advisory.py` | POST | `/suggestions/{suggestion_id}/approve` | `approve_ap_suggestion_endpoint` |
| `ap_advisory.py` | POST | `/suggestions/{suggestion_id}/reject` | `reject_ap_suggestion_endpoint` |
| `ap_advisory.py` | POST | `/suggestions/{suggestion_id}/apply` | `apply_ap_suggestion_endpoint` |
| `ap_review.py` | PUT | `/documents/{doc_id}` | `save_ap_review` |
| `ap_review.py` | POST | `/documents/{doc_id}/mark-ready` | `mark_ready_for_post` |
| `ap_review.py` | POST | `/documents/{doc_id}/override-po` | `override_po_check` |
| `ap_review.py` | POST | `/documents/{doc_id}/set-vendor` | `ap_review_set_vendor` |
| `ap_review.py` | POST | `/documents/{doc_id}/update-fields` | `ap_review_update_fields` |
| `ap_review.py` | POST | `/documents/{doc_id}/override-bc-validation` | `ap_review_override_bc_validation` |
| `ap_review.py` | POST | `/documents/{doc_id}/start-approval` | `ap_review_start_approval` |
| `ap_review.py` | POST | `/documents/{doc_id}/approve` | `ap_review_approve` |
| `ap_review.py` | POST | `/documents/{doc_id}/reject` | `ap_review_reject` |
| `ap_review.py` | POST | `/documents/{doc_id}/post-to-bc` | `post_document_to_bc` |
| `ap_review.py` | POST | `/documents/{doc_id}/extract-invoice-data` | `extract_invoice_data_endpoint` |
| `ap_review.py` | POST | `/vendor-profile/{vendor_no}/overrides` | `set_vendor_profile_overrides` |
| `ap_validation.py` | POST | `/validate/{doc_id}` | `validate_document_ap` |
| `ar_release.py` | POST | `/evaluate/{document_id}` | `evaluate_document` |
| `ar_release.py` | POST | `/override/{document_id}` | `override_document` |
| `auth.py` | POST | `/login` | `login` |
| `auth.py` | POST | `/logout` | `logout` |
| `auto_approve.py` | POST | `/dry-run` | `dry_run_auto_approve` |
| `auto_approve.py` | POST | `/run` | `run_auto_approve` |
| `auto_clear.py` | PUT | `/config/threshold/{doc_type}` | `update_auto_clear_threshold` |
| `auto_clear.py` | POST | `/evaluate/{doc_id}` | `evaluate_document_auto_clear` |
| `auto_clear.py` | POST | `/apply/{doc_id}` | `apply_auto_clear` |
| `auto_clear.py` | POST | `/route/{doc_id}` | `route_single_document` |
| `auto_clear.py` | POST | `/route-batch` | `route_batch_documents` |
| `auto_clear_reprocess.py` | POST | `/dry-run` | `dry_run` |
| `auto_clear_reprocess.py` | POST | `/run` | `run_reprocess` |
| `auto_clear_reprocess.py` | POST | `/force-clear-remaining` | `force_clear_remaining` |
| `auto_clear_reprocess.py` | POST | `/clear-junk/dry-run` | `dry_run_clear_junk` |
| `auto_clear_reprocess.py` | POST | `/clear-junk/run` | `run_clear_junk` |
| `automation_intelligence.py` | POST | `/automation/batch-evaluate` | `batch_evaluate` |
| `automation_intelligence.py` | POST | `/documents/{doc_id}/review-assist` | `review_assist` |
| `automation_intelligence.py` | POST | `/documents/{doc_id}/accept-suggestion` | `accept_suggestion` |
| `automation_rules.py` | POST | `` | `create_automation_rule` |
| `automation_rules.py` | PUT | `/{rule_id}` | `update_automation_rule` |
| `automation_rules.py` | DELETE | `/{rule_id}` | `delete_automation_rule` |
| `automation_rules.py` | POST | `/{rule_id}/toggle` | `toggle_automation_rule` |
| `automation_rules.py` | POST | `/evaluate/{doc_id}` | `evaluate_rules_for_document` |
| `bakeoff.py` | POST | `/runs` | `create_run` |
| `bakeoff.py` | PUT | `/runs/{run_id}` | `update_run` |
| `bakeoff.py` | POST | `/runs/{run_id}/complete` | `complete_run` |
| `bakeoff.py` | POST | `/runs/{run_id}/archive` | `archive_run` |
| `bakeoff.py` | DELETE | `/runs/{run_id}` | `delete_run` |
| `bakeoff.py` | POST | `/runs/{run_id}/documents` | `add_document` |
| `bakeoff.py` | POST | `/runs/{run_id}/documents/import` | `bulk_import_documents` |
| `bakeoff.py` | PUT | `/runs/{run_id}/documents/{doc_uid}` | `update_document_scoring` |
| `bakeoff.py` | DELETE | `/runs/{run_id}/documents/{doc_uid}` | `delete_document` |
| `bakeoff.py` | POST | `/runs/{run_id}/auto-populate` | `auto_populate_gpi` |
| `bakeoff.py` | POST | `/runs/{run_id}/reroute-folders` | `reroute_folders` |
| `bakeoff.py` | POST | `/runs/reroute-all` | `reroute_all_runs` |
| `bakeoff.py` | POST | `/runs/force-fix-mismatches` | `force_fix_mismatches` |
| `bakeoff.py` | POST | `/runs/fix-truth-and-output` | `fix_truth_and_output` |
| `bakeoff.py` | DELETE | `/routing-feedback/{routing_key}` | `delete_routing_feedback` |
| `bakeoff.py` | POST | `/routing-feedback/learn-from-benchmark` | `learn_from_benchmark` |
| `bakeoff.py` | POST | `/runs/enrich-and-reroute` | `enrich_location_codes_and_reroute` |
| `bakeoff.py` | POST | `/runs/{run_id}/scan-sharepoint` | `scan_sharepoint_folders` |
| `bc_sandbox.py` | POST | `/bc-sandbox/validate/vendor` | `bc_sandbox_validate_vendor` |
| `bc_sandbox.py` | POST | `/bc-sandbox/validate/invoice` | `bc_sandbox_validate_invoice` |
| `bc_sandbox.py` | POST | `/bc-sandbox/validate/ap-invoice` | `bc_sandbox_validate_ap_invoice` |
| `bc_sandbox.py` | POST | `/bc-sandbox/validate/sales-invoice` | `bc_sandbox_validate_sales_invoice` |
| `bc_sandbox.py` | POST | `/bc-sandbox/validate/purchase-order` | `bc_sandbox_validate_purchase_order` |
| `bc_sandbox.py` | POST | `/bc/sales-orders/create` | `create_bc_sales_order` |
| `bc_sandbox.py` | POST | `/bc-sandbox/document/{doc_id}/validate` | `bc_sandbox_validate_document` |
| `cache.py` | POST | `/bc/write-guard/check` | `check_bc_write_permission` |
| `cache.py` | POST | `/cache/sync` | `trigger_cache_sync` |
| `consigned_item_registry.py` | POST | `` | `upsert_item` |
| `consigned_item_registry.py` | POST | `/{item_no}/transition` | `transition_item` |
| `cp_item_registry.py` | POST | `` | `upsert_cp_item_endpoint` |
| `cp_item_registry.py` | POST | `/{item_no}/retire` | `retire_cp_item_endpoint` |
| `dedup.py` | POST | `/dry-run` | `dry_run` |
| `dedup.py` | POST | `/run` | `run_dedup` |
| `dev_tools.py` | POST | `/compare-extraction` | `compare_extraction` |
| `dev_tools.py` | POST | `/test-vendor-ranking` | `test_vendor_ranking` |
| `dev_tools.py` | POST | `/test-template-injection` | `test_template_injection` |
| `dev_tools.py` | POST | `/test-so-readiness` | `test_so_readiness` |
| `document_intelligence.py` | POST | `/process/{doc_id}` | `api_process_document` |
| `document_intelligence.py` | POST | `/detect-bundles` | `api_detect_bundles` |
| `document_intelligence.py` | PATCH | `/bundles/{bundle_id}` | `api_update_bundle` |
| `document_intelligence.py` | POST | `/validate-lifecycle/{entity_type}/{entity_id}` | `api_validate_lifecycle` |
| `document_intelligence.py` | POST | `/policies` | `api_create_policy` |
| `document_intelligence.py` | PATCH | `/policies/{policy_id}` | `api_update_policy` |
| `document_intelligence.py` | DELETE | `/policies/{policy_id}` | `api_delete_policy` |
| `document_intelligence.py` | POST | `/evaluate-decision/{doc_id}` | `api_evaluate_decision` |
| `document_intelligence.py` | POST | `/execute-decision/{decision_id}` | `api_execute_decision` |
| `document_intelligence.py` | PATCH | `/{doc_id}` | `api_correct_intelligence` |
| `document_intelligence.py` | POST | `/auto-draft/{doc_id}` | `api_create_auto_draft` |
| `document_intelligence.py` | POST | `/resolve-entities/{doc_id}` | `api_resolve_entities` |
| `document_intelligence.py` | PATCH | `/resolution/{resolution_id}` | `api_correct_resolution` |
| `document_intelligence.py` | POST | `/match-transactions/{doc_id}` | `api_match_transactions` |
| `document_intelligence.py` | POST | `/auto-link/{doc_id}` | `api_auto_link` |
| `document_intelligence.py` | PATCH | `/transaction-matches/{match_id}` | `api_confirm_match` |
| `document_intelligence.py` | POST | `/pipeline/{doc_id}` | `run_document_pipeline` |
| `documents.py` | POST | `/classification/bootstrap-from-history` | `bootstrap_classification_from_history` |
| `documents.py` | POST | `/{doc_id}/refresh-state` | `refresh_document_state` |
| `documents.py` | PUT | `/{doc_id}` | `update_document` |
| `documents.py` | DELETE | `/{doc_id}` | `delete_document` |
| `documents.py` | POST | `/{doc_id}/upload-file` | `upload_replacement_file` |
| `documents.py` | POST | `/{doc_id}/auto-split` | `auto_split_document` |
| `documents.py` | POST | `/{doc_id}/split` | `split_document` |
| `documents.py` | POST | `/{doc_id}/split-batch` | `split_batch_po` |
| `documents.py` | POST | `/{doc_id}/reprocess-batch` | `reprocess_batch` |
| `documents.py` | POST | `/{doc_id}/delete-pages` | `delete_pages` |
| `documents.py` | POST | `/{doc_id}/reset-retries` | `reset_document_retries` |
| `documents.py` | POST | `/{doc_id}/file-and-clear` | `file_and_clear_document` |
| `documents.py` | POST | `/bulk-file-and-clear` | `bulk_file_and_clear` |
| `documents.py` | POST | `/bulk-approve-and-file` | `bulk_approve_and_file` |
| `documents.py` | POST | `/sweep-reclassify-bols` | `sweep_reclassify_bols` |
| `documents.py` | POST | `/bulk-classify` | `bulk_classify_documents` |
| `email_polling.py` | POST | `/email-polling/trigger` | `trigger_email_poll` |
| `email_polling.py` | POST | `/graph/webhook` | `graph_webhook` |
| `explain.py` | POST | `/{document_id}/sales-order-review-feedback` | `submit_so_review_feedback` |
| `feedback_health.py` | POST | `/replay` | `replay_feedback` |
| `file_import.py` | POST | `/parse` | `parse_sales_file` |
| `file_import.py` | POST | `/import-orders` | `import_sales_orders_from_file` |
| `file_import.py` | POST | `/import-inventory` | `import_inventory_from_file` |
| `file_integrity.py` | POST | `/dry-run` | `dry_run` |
| `file_integrity.py` | POST | `/scan` | `scan_and_flag` |
| `freight_routing.py` | POST | `/update-gl-account` | `update_gl_account_number` |
| `freight_routing.py` | POST | `/accounts` | `create_freight_gl_account` |
| `freight_routing.py` | PUT | `/accounts/{account_id}` | `update_freight_gl_account` |
| `freight_routing.py` | DELETE | `/accounts/{account_id}` | `delete_freight_gl_account` |
| `freight_routing.py` | POST | `/classify/{doc_id}` | `classify_freight_gl` |
| `freight_routing.py` | POST | `/override/{doc_id}` | `override_freight_gl` |
| `freight_routing.py` | POST | `/batch-classify` | `batch_classify_freight` |
| `gpi_integration.py` | POST | `/sales-orders` | `gpi_create_sales_order` |
| `gpi_integration.py` | POST | `/sales-orders/preflight/{doc_id}` | `sales_order_preflight` |
| `gpi_integration.py` | POST | `/sales-orders/from-document/{doc_id}` | `create_sales_order_from_document` |
| `gpi_integration.py` | POST | `/ds-purchase-orders/auto-create/{doc_id}` | `ds_po_auto_create` |
| `gpi_integration.py` | POST | `/purchase-invoices` | `gpi_create_purchase_invoice` |
| `gpi_integration.py` | POST | `/purchase-invoices/preflight/{doc_id}` | `purchase_invoice_preflight` |
| `gpi_integration.py` | POST | `/purchase-invoices/retry-lines/{doc_id}` | `retry_purchase_invoice_lines` |
| `gpi_integration.py` | POST | `/purchase-invoices/from-document/{doc_id}` | `create_purchase_invoice_from_document` |
| `gpi_integration.py` | POST | `/customers` | `gpi_create_customer` |
| `gpi_integration.py` | POST | `/vendors` | `gpi_create_vendor` |
| `gpi_integration.py` | POST | `/item-mappings` | `create_mapping_endpoint` |
| `gpi_integration.py` | PUT | `/item-mappings/{mapping_id}` | `update_mapping_endpoint` |
| `gpi_integration.py` | DELETE | `/item-mappings/{mapping_id}` | `delete_mapping_endpoint` |
| `gpi_integration.py` | POST | `/catalog/sync` | `trigger_catalog_sync` |
| `gpi_integration.py` | POST | `/catalog/suggest-items` | `suggest_items_for_line` |
| `gpi_integration.py` | POST | `/document-links/{bc_entity}/{bc_document_no}/upload` | `upload_document_to_bc_record` |
| `gpi_integration.py` | DELETE | `/document-links/{bc_entity}/{bc_document_no}/{doc_id_or_sp_item}` | `delete_document_link` |
| `gpi_integration.py` | POST | `/document-links/migrate-from-zetadocs` | `migrate_zetadocs_links` |
| `gpi_integration.py` | POST | `/sales-orders/cost-only-from-document/{doc_id}` | `create_cost_only_so_from_document` |
| `gpi_integration.py` | POST | `/order-patterns/learn/{customer_no}` | `learn_order_patterns` |
| `gpi_integration.py` | POST | `/order-patterns/suggest` | `suggest_order_lines` |
| `inside_sales_pilot.py` | POST | `/poll-now` | `trigger_pilot_poll` |
| `inside_sales_pilot.py` | POST | `/smart-reclassify` | `smart_reclassify` |
| `inside_sales_pilot.py` | POST | `/re-extract-all` | `re_extract_all_pilot_docs` |
| `inside_sales_pilot.py` | POST | `/validate/{doc_id}` | `validate_single_document` |
| `inside_sales_pilot.py` | POST | `/validate-all` | `validate_all_documents` |
| `inside_sales_pilot.py` | POST | `/readiness-review/{doc_id}` | `run_readiness_review` |
| `inside_sales_pilot.py` | POST | `/readiness-review-all` | `run_readiness_review_all` |
| `inside_sales_pilot.py` | POST | `/build-customer-aliases` | `build_customer_aliases` |
| `inside_sales_pilot.py` | POST | `/customer-aliases/manual` | `add_manual_customer_alias` |
| `inside_sales_pilot.py` | POST | `/validate-sales-corpus` | `validate_sales_corpus_batch` |
| `inside_sales_pilot.py` | POST | `/spiro-match/{doc_id}` | `spiro_match_single` |
| `inside_sales_pilot.py` | POST | `/spiro-match-all` | `spiro_match_all` |
| `inside_sales_pilot.py` | POST | `/so-rules-evaluate/{doc_id}` | `evaluate_single_so` |
| `inside_sales_pilot.py` | POST | `/so-rules-evaluate-all` | `evaluate_all_sos` |
| `intake_learning.py` | POST | `/learning/run/{doc_id}` | `run_learning_for_document` |
| `intake_learning.py` | POST | `/learning/run-xls/{staging_id}` | `run_learning_for_xls` |
| `intake_learning.py` | POST | `/learning/backfill` | `backfill_learning` |
| `intake_learning.py` | POST | `/learning/refresh-active` | `refresh_active` |
| `intake_learning.py` | POST | `/insights/feedback` | `post_feedback` |
| `intake_learning.py` | POST | `/learning/hygiene` | `trigger_hygiene` |
| `intake_learning.py` | POST | `/insights/promote-inherited` | `promote_inherited` |
| `intake_learning.py` | POST | `/learning/rebuild-fingerprints` | `rebuild_fingerprints` |
| `inventory_items.py` | POST | `/settings` | `api_upsert_settings` |
| `inventory_ledger.py` | POST | `/customers` | `api_create_customer` |
| `inventory_ledger.py` | PUT | `/customers/{customer_id}` | `api_update_customer` |
| `inventory_ledger.py` | POST | `/customers/{customer_id}/movements` | `api_create_movement` |
| `inventory_ledger.py` | POST | `/movements` | `api_manual_movement` |
| `inventory_ledger.py` | POST | `/import` | `api_import_csv` |
| `inventory_ledger.py` | POST | `/generate-po-draft` | `api_generate_po_draft` |
| `inventory_ledger.py` | PATCH | `/po-drafts/{draft_id}/status` | `api_update_po_draft_status` |
| `inventory_ledger.py` | PATCH | `/po-drafts/{draft_id}/vendor` | `api_update_po_draft_vendor` |
| `inventory_ledger.py` | PATCH | `/po-drafts/{draft_id}/bc-response` | `api_update_bc_response` |
| `inventory_ledger.py` | POST | `/po-drafts/{draft_id}/submission-log` | `api_create_submission_log` |
| `inventory_ledger.py` | POST | `/po-drafts/{draft_id}/bc-receipt` | `api_bc_receipt_capture` |
| `inventory_ledger.py` | POST | `/po-drafts/{draft_id}/create-incoming-supply` | `api_po_draft_create_incoming_supply` |
| `inventory_ledger.py` | POST | `/customers/{customer_id}/incoming` | `api_create_incoming` |
| `inventory_ledger.py` | PUT | `/customers/{customer_id}/incoming/{supply_id}` | `api_update_incoming` |
| `inventory_ledger.py` | POST | `/customers/{customer_id}/seed` | `api_seed_opening_balances` |
| `inventory_ledger.py` | POST | `/release` | `api_release_commitments` |
| `inventory_ledger.py` | POST | `/reconcile-sales-order` | `api_reconcile_sales_order` |
| `inventory_ledger.py` | POST | `/sync-bc-shipments` | `api_sync_bc_shipments` |
| `inventory_ledger.py` | PATCH | `/sales-orders/{sales_order_id}/order-type` | `api_set_order_type` |
| `inventory_ledger.py` | POST | `/sales-orders/{sales_order_id}/generate-drop-ship-po-draft` | `api_generate_drop_ship_po_draft` |
| `inventory_ledger.py` | POST | `/sales-orders/{sales_order_id}/drop-ship-vendor-shipment` | `api_drop_ship_vendor_shipment` |
| `inventory_ledger.py` | POST | `/sales-orders/{sales_order_id}/bc-shipment` | `api_bc_shipment_capture` |
| `inventory_ledger.py` | POST | `/sales-orders/{sales_order_id}/bc-invoice` | `api_bc_invoice_capture` |
| `inventory_ledger.py` | POST | `/document-links` | `api_create_document_link` |
| `inventory_ledger.py` | DELETE | `/document-links/{document_link_id}` | `api_delete_document_link` |
| `inventory_ledger.py` | POST | `/approvals/request` | `api_request_approval` |
| `inventory_ledger.py` | PATCH | `/approvals/{approval_id}` | `api_decide_approval` |
| `inventory_ledger.py` | POST | `/escalations` | `api_create_escalation` |
| `inventory_ledger.py` | PATCH | `/escalations/{escalation_id}` | `api_update_escalation` |
| `inventory_ledger.py` | POST | `/assignments` | `api_create_assignment` |
| `inventory_ledger.py` | PATCH | `/assignments/{assignment_id}` | `api_update_assignment` |
| `inventory_ledger.py` | POST | `/activities` | `api_create_activity` |
| `inventory_ledger.py` | POST | `/saved-views` | `api_create_saved_view` |
| `inventory_ledger.py` | PATCH | `/saved-views/{saved_view_id}` | `api_update_saved_view` |
| `inventory_ledger.py` | DELETE | `/saved-views/{saved_view_id}` | `api_delete_saved_view` |
| `inventory_ledger.py` | POST | `/operations-queue/bulk-action` | `api_bulk_action` |
| `inventory_ledger.py` | POST | `/templates` | `api_create_template` |
| `inventory_ledger.py` | PATCH | `/templates/{template_id}` | `api_update_template` |
| `inventory_ledger.py` | DELETE | `/templates/{template_id}` | `api_delete_template` |
| `inventory_ledger.py` | POST | `/templates/{template_id}/apply` | `api_apply_template` |
| `inventory_ledger.py` | POST | `/from-shortage` | `api_create_from_shortage` |
| `inventory_ledger.py` | POST | `/{supply_id}/status` | `api_transition_status` |
| `inventory_xls.py` | POST | `/ingest` | `ingest_xls` |
| `inventory_xls.py` | POST | `/ingest-pilot-doc/{doc_id}` | `ingest_from_pilot_doc` |
| `inventory_xls.py` | POST | `/staging/{staging_id}/update` | `api_update_staging` |
| `inventory_xls.py` | POST | `/staging/{staging_id}/re-normalize` | `api_renormalize_staging` |
| `inventory_xls.py` | POST | `/staging/{staging_id}/approve` | `api_approve_staging` |
| `inventory_xls.py` | POST | `/staging/{staging_id}/reject` | `api_reject_staging` |
| `inventory_xls.py` | POST | `/staging/re-suggest-customers` | `api_resuggest_customers` |
| `inventory_xls.py` | POST | `/backfill-pilot-docs` | `backfill_pilot_docs` |
| `knowledge_seed.py` | POST | `/run-all` | `run_full_seed` |
| `knowledge_seed.py` | POST | `/vendor-aliases` | `seed_aliases` |
| `knowledge_seed.py` | POST | `/sender-domains` | `seed_domains` |
| `knowledge_seed.py` | POST | `/vendor-profiles` | `seed_profiles` |
| `knowledge_seed.py` | POST | `/close-all-gaps` | `close_all_gaps` |
| `layout_fingerprints.py` | POST | `/backfill` | `backfill_layout_fingerprints` |
| `learning_core.py` | POST | `/drift/scan` | `drift_scan` |
| `learning_core.py` | POST | `/drift/alerts/{alert_id}/acknowledge` | `drift_ack` |
| `learning_core.py` | POST | `/drift/alerts/{alert_id}/resolve` | `drift_resolve` |
| `learning_core.py` | POST | `/fingerprints/rebuild` | `fingerprints_rebuild` |
| `learning_core.py` | POST | `/hygiene/run` | `hygiene_run` |
| `learning_core.py` | POST | `/feedback` | `unified_feedback` |
| `learning_core.py` | POST | `/digest/rebuild` | `digest_rebuild` |
| `learning_core.py` | POST | `/drift-watchlist/send-now` | `drift_watchlist_send_now` |
| `mailbox_sources.py` | POST | `` | `create_mailbox_source` |
| `mailbox_sources.py` | PUT | `/{mailbox_id}` | `update_mailbox_source` |
| `mailbox_sources.py` | DELETE | `/{mailbox_id}` | `delete_mailbox_source` |
| `mailbox_sources.py` | POST | `/{mailbox_id}/test-connection` | `test_mailbox_connection` |
| `mailbox_sources.py` | POST | `/{mailbox_id}/poll-now` | `poll_mailbox_now` |
| `metrics.py` | POST | `/settings/shadow-mode` | `update_shadow_mode_settings` |
| `migration_routes.py` | POST | `/run` | `run_migration_job` |
| `migration_routes.py` | POST | `/generate-sample` | `generate_sample_migration_file` |
| `pilot.py` | POST | `/send-daily-summary` | `trigger_daily_pilot_summary` |
| `pilot.py` | POST | `/settings/mailbox-sources` | `create_mailbox_source` |
| `pilot.py` | PUT | `/settings/mailbox-sources/{mailbox_id}` | `update_mailbox_source` |
| `pilot.py` | DELETE | `/settings/mailbox-sources/{mailbox_id}` | `delete_mailbox_source` |
| `pilot.py` | POST | `/settings/mailbox-sources/{mailbox_id}/test-connection` | `test_mailbox_connection` |
| `pilot.py` | POST | `/settings/mailbox-sources/{mailbox_id}/poll-now` | `poll_mailbox_now` |
| `pilot.py` | POST | `/aliases/vendors` | `create_vendor_alias` |
| `pilot.py` | DELETE | `/aliases/vendors/{alias_id}` | `delete_vendor_alias` |
| `pilot.py` | POST | `/simulation/document/{doc_id}/run` | `run_simulation_for_document` |
| `pilot.py` | POST | `/simulation/ap-invoice/{doc_id}` | `simulate_ap_invoice_export` |
| `pilot.py` | POST | `/simulation/sales-invoice/{doc_id}` | `simulate_sales_invoice_export_endpoint` |
| `pilot.py` | POST | `/simulation/po-linkage/{doc_id}` | `simulate_po_linkage_endpoint` |
| `pilot.py` | POST | `/simulation/attachment/{doc_id}` | `simulate_attachment_endpoint` |
| `pilot.py` | POST | `/simulation/batch` | `run_batch_simulation` |
| `pilot.py` | POST | `/reingest/start` | `start_batch_reingest` |
| `pilot.py` | POST | `/reingest/stop` | `stop_reingest` |
| `po_resolution.py` | POST | `/batch-resolve` | `batch_resolve_po` |
| `posting_patterns.py` | POST | `/review-queue/{doc_id}/approve` | `approve_draft` |
| `posting_patterns.py` | POST | `/review-queue/auto-approve` | `auto_approve_drafts` |
| `posting_patterns.py` | POST | `/review-queue/{doc_id}/correct` | `correct_draft` |
| `posting_patterns.py` | POST | `/review-queue/{doc_id}/sync-from-bc` | `sync_draft_from_bc_endpoint` |
| `posting_patterns.py` | POST | `/review-queue/sync-all` | `sync_all_drafts` |
| `posting_patterns.py` | POST | `/learning/run-all` | `run_all_learning_engines_endpoint` |
| `posting_patterns.py` | POST | `/learning/detect-posted` | `detect_posted_drafts_endpoint` |
| `posting_patterns.py` | POST | `/learning/cross-vendor` | `cross_vendor_learning_endpoint` |
| `posting_patterns.py` | POST | `/learning/auto-promote` | `auto_promote_confidence_endpoint` |
| `posting_patterns.py` | POST | `/analyze/{vendor_no}` | `analyze_single_vendor` |
| `posting_patterns.py` | POST | `/analyze-top` | `analyze_top_vendors` |
| `posting_patterns.py` | PUT | `/settings` | `update_auto_post_settings` |
| `posting_patterns.py` | POST | `/draft-preview/{doc_id}` | `preview_draft_pi` |
| `posting_patterns.py` | POST | `/create-draft/{doc_id}` | `create_draft_from_template` |
| `posting_patterns.py` | POST | `/auto-draft-queue` | `run_auto_draft_queue` |
| `posting_patterns.py` | POST | `/bc-sync-item/{item_number}` | `sync_item_to_sandbox` |
| `posting_patterns.py` | POST | `/daily-trace/run` | `run_daily_traces` |
| `posting_patterns.py` | POST | `/learning-pulse/backfill` | `backfill_per_document_learning` |
| `posting_patterns.py` | POST | `/intelligence/recalibrate-confidence` | `recalibrate_confidence_bands` |
| `posting_patterns.py` | POST | `/deep-learning/find-similar/{doc_id}` | `find_similar_documents` |
| `posting_patterns.py` | POST | `/deep-learning/self-correction/run` | `run_self_correction` |
| `posting_patterns.py` | POST | `/deep-learning/vendor-maturity/compute-all` | `compute_all_maturity` |
| `posting_patterns.py` | POST | `/deep-learning/predict-readiness/{doc_id}` | `predict_document_readiness` |
| `posting_patterns.py` | POST | `/advanced-learning/backfill` | `backfill_advanced_learning` |
| `posting_patterns.py` | POST | `/duplicate-intelligence/batch-clear` | `batch_clear_safe_duplicates` |
| `posting_patterns.py` | POST | `/intelligence/backfill` | `run_intelligence_backfill` |
| `posting_patterns.py` | POST | `/system/run-full-cycle` | `run_full_cycle` |
| `readiness.py` | POST | `/evaluate/{doc_id}` | `evaluate_document_readiness` |
| `readiness.py` | POST | `/batch` | `batch_evaluate_readiness` |
| `readiness.py` | POST | `/reevaluate-all` | `reevaluate_all_readiness` |
| `readiness.py` | POST | `/fix-validation-gaps` | `fix_validation_gaps` |
| `readiness.py` | POST | `/sync-status` | `sync_readiness_to_status` |
| `readiness.py` | POST | `/retry-failed` | `retry_failed_extractions` |
| `readiness.py` | POST | `/retry-captured` | `retry_captured_docs` |
| `readiness.py` | POST | `/po-pending/park` | `park_po_pending_docs` |
| `readiness.py` | POST | `/po-pending/retry` | `retry_po_pending_docs` |
| `readiness.py` | POST | `/retry-ready-to-post` | `retry_ready_to_post` |
| `readiness.py` | POST | `/repair-downgraded-docs` | `repair_downgraded_docs` |
| `reprocess_comparison.py` | POST | `/run` | `start_comparison` |
| `reprocess_comparison.py` | POST | `/apply/{run_id}` | `apply_improvements` |
| `reprocess_comparison.py` | POST | `/run-full` | `start_full_reprocess` |
| `sales_dashboard.py` | DELETE | `/queue/clear` | `clear_sales_queue` |
| `sales_dashboard.py` | POST | `/queue/{doc_id}/approve` | `approve_document` |
| `sales_dashboard.py` | POST | `/queue/{doc_id}/flag` | `flag_document` |
| `sales_dashboard.py` | POST | `/queue/{doc_id}/assign` | `assign_document` |
| `sales_dashboard.py` | POST | `/review/{doc_id}` | `review_document` |
| `sales_dashboard.py` | POST | `/seed-review-data` | `seed_review_data` |
| `sales_dashboard.py` | POST | `/run-auto-assign` | `run_auto_assign` |
| `sales_dashboard.py` | POST | `/rep-overrides` | `create_rep_override` |
| `sales_dashboard.py` | DELETE | `/rep-overrides/{customer_no}` | `delete_rep_override` |
| `sales_pipeline_demo.py` | POST | `/run` | `run_pipeline_demo` |
| `sales_pipeline_demo.py` | POST | `/run-batch` | `run_batch_demo` |
| `settings.py` | PUT | `/config` | `update_settings_config` |
| `settings.py` | POST | `/test-connection` | `test_connection` |
| `settings.py` | POST | `/features/create-draft-header` | `toggle_draft_creation_feature` |
| `settings.py` | PUT | `/job-types/{job_type}` | `update_job_type` |
| `settings.py` | PUT | `/email-watcher` | `update_email_watcher_settings` |
| `settings.py` | POST | `/email-watcher/subscribe` | `subscribe_email_watcher` |
| `settings.py` | PUT | `/notification-config` | `update_notification_config_endpoint` |
| `sharepoint.py` | POST | `/initialize-folders` | `initialize_sharepoint_folders` |
| `sharepoint.py` | POST | `/test-routing` | `test_folder_routing` |
| `sharepoint_routing.py` | POST | `/folder-rules` | `create_folder_rule` |
| `sharepoint_routing.py` | PUT | `/folder-rules/{folder_key}` | `update_folder_rule` |
| `sharepoint_routing.py` | DELETE | `/folder-rules/{folder_key}` | `delete_folder_rule` |
| `sharepoint_routing.py` | POST | `/vendor-mappings` | `create_vendor_mapping` |
| `sharepoint_routing.py` | PUT | `/vendor-mappings/{vendor_pattern}` | `update_vendor_mapping` |
| `sharepoint_routing.py` | DELETE | `/vendor-mappings/{vendor_pattern}` | `delete_vendor_mapping` |
| `sharepoint_routing.py` | POST | `/processor-assignments` | `create_processor_assignment` |
| `sharepoint_routing.py` | DELETE | `/processor-assignments` | `delete_processor_assignment` |
| `sharepoint_routing.py` | POST | `/suggest-folder` | `suggest_folder` |
| `sharepoint_routing.py` | POST | `/document/{doc_id}/assign-folder` | `assign_folder_to_document` |
| `sharepoint_routing.py` | POST | `/document/{doc_id}/move-to-sharepoint` | `move_document_to_sharepoint` |
| `sharepoint_routing.py` | POST | `/batch-move` | `batch_move_to_sharepoint` |
| `sharepoint_routing.py` | POST | `/batch-suggest` | `batch_suggest_folders` |
| `sharepoint_routing.py` | POST | `/seed-defaults` | `seed_defaults` |
| `spiro.py` | POST | `/callback` | `oauth_callback` |
| `spiro.py` | POST | `/sync` | `trigger_sync` |
| `spiro.py` | POST | `/sync/contacts` | `sync_contacts` |
| `spiro.py` | POST | `/sync/all` | `sync_all` |
| `spiro.py` | POST | `/context/test` | `test_spiro_context` |
| `spiro.py` | POST | `/match-vendor` | `spiro_match_vendor` |
| `spiro.py` | POST | `/is-freight-carrier` | `spiro_is_freight_carrier` |
| `square9.py` | POST | `/archive-stage-data` | `archive_stage_data` |
| `square9.py` | POST | `/restore-stage-data` | `restore_stage_data` |
| `stable_vendor.py` | PUT | `/config` | `update_stable_vendor_config` |
| `stable_vendor.py` | POST | `/evaluate-document/{doc_id}` | `evaluate_document_routing` |
| `stable_vendor.py` | POST | `/reevaluate-all` | `reevaluate_all_vendors` |
| `stable_vendor.py` | POST | `/vendors/{vendor_no}/override` | `apply_vendor_override` |
| `stable_vendor.py` | POST | `/vendors/{vendor_no}/clear-override` | `clear_vendor_override` |
| `stable_vendor.py` | POST | `/apply-suggested-thresholds` | `apply_suggested_thresholds` |
| `stable_vendor.py` | POST | `/reset-config` | `reset_stable_vendor_config` |
| `vendor_extraction_profiles.py` | POST | `/seed-top-vendors` | `seed_top_vendors` |
| `vendor_extraction_profiles.py` | POST | `/{vendor_id}/generate` | `generate_vendor_profile` |
| `vendor_extraction_profiles.py` | POST | `/generate-all` | `generate_all_profiles` |
| `vendor_extraction_profiles.py` | POST | `/{vendor_id}/toggle` | `toggle_vendor_profile` |
| `vendor_extraction_profiles.py` | POST | `/{vendor_id}/reset` | `reset_vendor_profile` |
| `vendor_intelligence.py` | POST | `/rebuild` | `rebuild_vendor_profiles` |
| `vendor_intelligence.py` | PATCH | `/profiles/{vendor_no}/bypass` | `set_vendor_processing_bypass` |
| `vendor_profile_rebuild.py` | POST | `/rebuild/dry-run` | `rebuild_dry_run` |
| `vendor_profile_rebuild.py` | POST | `/rebuild/run` | `rebuild_run` |
| `vendor_reprocess.py` | POST | `/run` | `run_reprocess` |
| `vendor_reprocess.py` | POST | `/run-all-unresolved` | `run_reprocess_all_unresolved` |
| `vendor_reprocess.py` | POST | `/dry-run` | `dry_run_reprocess` |
| `vendor_reprocess.py` | POST | `/learn-from-history` | `learn_sender_mappings_from_history` |
| `vendor_reprocess.py` | POST | `/sender-mappings/clear` | `clear_sender_mappings` |
| `vendor_reprocess.py` | POST | `/auto-map-domains` | `auto_map_unresolved_domains` |
| `vendor_reprocess.py` | POST | `/teach-domain` | `teach_domain_vendor` |
| `vendor_reprocess.py` | POST | `/resolve-by-sender` | `resolve_unresolved_by_sender` |
| `vendors.py` | POST | `/match` | `unified_vendor_match` |
| `workflow_fix.py` | POST | `/dry-run` | `dry_run` |
| `workflow_fix.py` | POST | `/run` | `run_fix` |
| `workflows.py` | POST | `/{wf_id}/retry` | `retry_workflow` |
