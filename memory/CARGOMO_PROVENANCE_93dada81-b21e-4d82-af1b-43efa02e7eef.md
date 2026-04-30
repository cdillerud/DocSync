# Vendor-Canonical Provenance — `93dada81-b21e-4d82-af1b-43efa02e7eef`

- Generated: `2026-04-28T23:57:45.369070+00:00`
- Mode: **read-only**, no Mongo writes, no BC calls.

## §A · Doc snapshot

| field | value |
|---|---|
| `id` | `'93dada81-b21e-4d82-af1b-43efa02e7eef'` |
| `document_type` | `'AP_Invoice'` |
| `doc_type` | `'AP_INVOICE'` |
| `status` | `'ReadyForPost'` |
| `workflow_status` | `'ready_for_post'` |
| `extracted_vendor` | `'ANCHOR GLASS CONTAINER CORP'` |
| `vendor_canonical` | `'ANCH'` |
| `vendor_no` | `None` |
| `bc_purchase_invoice` | `None` |
| `source` | `'manual_auto_split'` |
| `source_email` | `None` |
| `source_path` | `None` |
| `capture_channel` | `'SHADOW_PILOT_UPLOAD'` |
| `created_utc` | `'2026-04-01T19:25:46.042384+00:00'` |
| `intake_at` | `None` |
| `updated_utc` | `'2026-04-28T14:48:34.890337+00:00'` |

**`bc_record_info`:**

```json
{}
```

**All top-level keys on this doc:**

`ai_confidence`, `amount_float`, `amount_raw`, `ap_validation_result`, `auto_clear_decision`, `auto_clear_details`, `auto_clear_reason`, `auto_cleared`, `auto_post_attempted`, `auto_post_error`, `auto_post_success`, `automation_confidence`, `automation_decision`, `automation_rule_applied`, `automation_rule_applied_at`, `automation_rule_name`, `automation_state`, `batch_group_num`, `batch_page_num`, `batch_pages`, `batch_parent_id`, `batch_source_filename`, `batch_split_mode`, `batch_total_pages`, `bc_company_id`, `bc_document_no`, `bc_posting_status`, `bc_record_id`, `bc_record_type`, `bc_vendor_number`, `canonical_fields`, `capture_channel`, `category`, `classification_method`, `confidence_penalty_applied`, `content_type`, `created_utc`, `customer_candidates`, `decision_explanation`, `derived_automation_state`, `derived_state_updated_utc`, `derived_workflow_state`, `doc_type`, `document_type`, `draft_candidate`, `due_date_iso`, `due_date_raw`, `duplicate_of_document_id`, `effective_confidence`, `email_id`, `email_received_utc`, `email_sender`, `email_subject`, `escalation_tracked`, `extracted_fields`, `file_content_b64`, `file_name`, `file_size`, `force_cleanup_at`, `force_cleanup_rule`, `freight_gl_classification`, `gap_closer_last_run`, `id`, `intake_insights`, `invoice_date`, `invoice_date_raw`, `invoice_number_clean`, `invoice_number_raw`, `last_error`, `line_items`, `mailbox_category`, `manual_override`, `manual_override_at`, `manual_override_by`, `manual_po_override`, `match_method`, `match_score`, `needs_review`, `normalized_fields`, `pilot_date`, `pilot_phase`, `po_candidates`, `po_number_clean`, `po_number_raw`, `po_resolution`, `possible_duplicate`, `readiness`, `ready_post_exhausted`, `ready_post_last_error`, `ready_post_retry_count`, `reference_candidates`, `reference_intelligence`, `reference_intelligence_best_score`, `reference_intelligence_hash`, `reference_intelligence_last_run`, `reference_intelligence_outcome`, `reference_intelligence_status`, `reference_intelligence_version`, `reference_match_outcome`, `reprocessed_utc`, `revalidated_from`, `revalidated_utc`, `review_priority`, `review_queue`, `routing_reasons`, `routing_score`, `routing_status`, `routing_timestamp`, `sha256_hash`, `sharepoint_drive_id`, `sharepoint_item_id`, `sharepoint_share_link_url`, `sharepoint_web_url`, `source`, `source_system`, `spiro_context`, `square9_stage`, `stable_vendor_routing`, `state_reason`, `status`, `status_synced_at`, `suggested_job_type`, `transaction_action`, `updated_utc`, `validation_errors`, `validation_last_run`, `validation_passed`, `validation_results`, `validation_state`, `validation_summary`, `validation_version`, `validation_warnings`, `vendor_candidates`, `vendor_canonical`, `vendor_match_method`, `vendor_normalized`, `vendor_raw`, `vendor_resolution`, `warnings`, `workflow_history`, `workflow_queue`, `workflow_state`, `workflow_status`, `workflow_status_updated_utc`

## §B · Doc-internal trail

- Searched the full doc for paths whose value contains the canonical code (`ANCH`), the canonical name (``), or the extracted vendor (`ANCHOR GLASS CONTAINER CORP`).

**paths referencing canonical code** — 25 hit(s)

- `extracted_fields.vendor = 'ANCHOR GLASS CONTAINER CORP'`
- `validation_results.normalized_fields.vendor = 'ANCHOR GLASS CONTAINER CORP'`
- `po_resolution.vendor_name = 'ANCHOR GLASS CONTAINER CORP'`
- `bc_vendor_number = 'ANCH'`
- `canonical_fields.vendor_raw = 'ANCHOR GLASS CONTAINER CORP'`
- `canonical_fields.vendor_normalized = 'anchor glass container corp'`
- `normalized_fields.vendor = 'ANCHOR GLASS CONTAINER CORP'`
- `spiro_context.matched_companies[0].name = 'Anchor Glass Container Corp'`
- `spiro_context.best_company_match.name = 'Anchor Glass Container Corp'`
- `validation_errors[0] = "Vendor not resolved: 'ANCHOR GLASS CONTAINER CORP' not found in BC"`
- `vendor_canonical = 'ANCH'`
- `vendor_normalized = 'anchor glass container corp'`
- `vendor_raw = 'ANCHOR GLASS CONTAINER CORP'`
- `vendor_resolution.raw = 'ANCHOR GLASS CONTAINER CORP'`
- `vendor_resolution.normalized = 'anchor glass container'`
- `vendor_resolution.matched_vendor_name = 'Anchor Glass - Shakopee Plant'`
- `vendor_resolution.matched_vendor_no = 'ANCH'`
- `decision_explanation.supporting_evidence[0] = 'Vendor resolved via alias_match → ANCH'`
- `reference_candidates[0].classification_reasoning = 'Invoice reference, document type: AP_Invoice; Vendor context: ANCHOR GLASS CONTAINER CORP'`
- `reference_intelligence.reference_candidates[0].classification_reasoning = 'Invoice reference, document type: AP_Invoice; Vendor context: ANCHOR GLASS CONTAINER CORP'`
- `reference_intelligence.matching_diagnostics.vendor_name = 'ANCHOR GLASS CONTAINER CORP'`
- `reference_intelligence.matching_diagnostics.candidates[0].reasoning = 'Invoice reference, document type: AP_Invoice; Vendor context: ANCHOR GLASS CONTAINER CORP'`
- `ap_validation_result.checks[0].details = "Vendor not resolved: 'ANCHOR GLASS CONTAINER CORP' not found in BC"`
- `ap_validation_result.blocking_issues[0] = "Vendor not resolved: 'ANCHOR GLASS CONTAINER CORP' not found in BC"`
- `stable_vendor_routing.checks[0].detail = "Vendor 'ANCHOR GLASS CONTAINER CORP' system=False effective=unstable"`

**paths referencing canonical name** — 0 hit(s)

**paths referencing extracted vendor** — 19 hit(s)

- `extracted_fields.vendor = 'ANCHOR GLASS CONTAINER CORP'`
- `validation_results.normalized_fields.vendor = 'ANCHOR GLASS CONTAINER CORP'`
- `po_resolution.vendor_name = 'ANCHOR GLASS CONTAINER CORP'`
- `canonical_fields.vendor_raw = 'ANCHOR GLASS CONTAINER CORP'`
- `canonical_fields.vendor_normalized = 'anchor glass container corp'`
- `normalized_fields.vendor = 'ANCHOR GLASS CONTAINER CORP'`
- `spiro_context.matched_companies[0].name = 'Anchor Glass Container Corp'`
- `spiro_context.best_company_match.name = 'Anchor Glass Container Corp'`
- `validation_errors[0] = "Vendor not resolved: 'ANCHOR GLASS CONTAINER CORP' not found in BC"`
- `vendor_normalized = 'anchor glass container corp'`
- `vendor_raw = 'ANCHOR GLASS CONTAINER CORP'`
- `vendor_resolution.raw = 'ANCHOR GLASS CONTAINER CORP'`
- `reference_candidates[0].classification_reasoning = 'Invoice reference, document type: AP_Invoice; Vendor context: ANCHOR GLASS CONTAINER CORP'`
- `reference_intelligence.reference_candidates[0].classification_reasoning = 'Invoice reference, document type: AP_Invoice; Vendor context: ANCHOR GLASS CONTAINER CORP'`
- `reference_intelligence.matching_diagnostics.vendor_name = 'ANCHOR GLASS CONTAINER CORP'`
- `reference_intelligence.matching_diagnostics.candidates[0].reasoning = 'Invoice reference, document type: AP_Invoice; Vendor context: ANCHOR GLASS CONTAINER CORP'`
- `ap_validation_result.checks[0].details = "Vendor not resolved: 'ANCHOR GLASS CONTAINER CORP' not found in BC"`
- `ap_validation_result.blocking_issues[0] = "Vendor not resolved: 'ANCHOR GLASS CONTAINER CORP' not found in BC"`
- `stable_vendor_routing.checks[0].detail = "Vendor 'ANCHOR GLASS CONTAINER CORP' system=False effective=unstable"`

**History-shaped embedded fields (full content):**

- `workflow_history`:

```json
[
  {
    "timestamp": "2026-04-01T19:25:46.042384+00:00",
    "from_status": null,
    "to_status": "captured",
    "event": "on_capture",
    "actor": "system",
    "reason": "Document captured from manual_auto_split",
    "metadata": {
      "source": "manual_auto_split",
      "sender": ""
    }
  }
]
```

## §C · `vendor_aliases`

- aliases pointing at canonical code: **39**
- aliases whose alias_string matches extracted name: **1**

**Aliases that map this extracted vendor name (showing first 5):**

```json
{
  "alias_id": "623873b3-daae-4fe8-a3b1-37749ecc182f",
  "alias_string": "Anchor Glass Container Corp",
  "alias": "ANCHOR GLASS CONTAINER CORP",
  "normalized_alias": "anchor glass container corp",
  "canonical_vendor_id": "ANCH",
  "vendor_no": "ANCH",
  "vendor_name": "Anchor Glass - Shakopee Plant",
  "source": "bc_cache_seed",
  "bc_doc_count": 1381,
  "learned_at": "2026-04-01T17:39:38.496479+00:00",
  "created_at": "2026-04-01T17:39:38.496479+00:00",
  "last_used_at": "2026-04-12T21:30:49.612878+00:00",
  "usage_count": 2
}
```

**Aliases pointing at `ANCH` (showing first 5):**

```json
{
  "alias_id": "6f1ff976-c569-4984-8966-5a1fe30d46de",
  "alias_string": "Anchor Glass - Shakopee Plant",
  "alias": "ANCHOR GLASS - SHAKOPEE PLANT",
  "normalized_alias": "anchor glass - shakopee plant",
  "canonical_vendor_id": "ANCH",
  "vendor_no": "ANCH",
  "vendor_name": "Anchor Glass - Shakopee Plant",
  "source": "bc_cache_seed",
  "bc_doc_count": 2069,
  "learned_at": "2026-04-01T17:39:38.496479+00:00",
  "created_at": "2026-04-01T17:39:38.496479+00:00"
}
```
```json
{
  "alias_id": "623873b3-daae-4fe8-a3b1-37749ecc182f",
  "alias_string": "Anchor Glass Container Corp",
  "alias": "ANCHOR GLASS CONTAINER CORP",
  "normalized_alias": "anchor glass container corp",
  "canonical_vendor_id": "ANCH",
  "vendor_no": "ANCH",
  "vendor_name": "Anchor Glass - Shakopee Plant",
  "source": "bc_cache_seed",
  "bc_doc_count": 1381,
  "learned_at": "2026-04-01T17:39:38.496479+00:00",
  "created_at": "2026-04-01T17:39:38.496479+00:00",
  "last_used_at": "2026-04-12T21:30:49.612878+00:00",
  "usage_count": 2
}
```
```json
{
  "alias_id": "34ba1e2d-80cf-4886-bd4d-7754376ddb65",
  "alias_string": "Anchor Glass - Henryetta Plant",
  "alias": "ANCHOR GLASS - HENRYETTA PLANT",
  "normalized_alias": "anchor glass - henryetta plant",
  "canonical_vendor_id": "ANCH",
  "vendor_no": "ANCH",
  "vendor_name": "Anchor Glass - Shakopee Plant",
  "source": "bc_cache_seed",
  "bc_doc_count": 1013,
  "learned_at": "2026-04-01T17:39:38.496479+00:00",
  "created_at": "2026-04-01T17:39:38.496479+00:00"
}
```
```json
{
  "alias_id": "c8bc16bc-986e-452f-a868-033e908d5f76",
  "alias_string": "Anchor Glass - B&B Packaging 123",
  "alias": "ANCHOR GLASS - B&B PACKAGING 123",
  "normalized_alias": "anchor glass - b&b packaging 123",
  "canonical_vendor_id": "ANCH",
  "vendor_no": "ANCH",
  "vendor_name": "Anchor Glass - Shakopee Plant",
  "source": "bc_cache_seed",
  "bc_doc_count": 482,
  "learned_at": "2026-04-01T17:39:38.496479+00:00",
  "created_at": "2026-04-01T17:39:38.496479+00:00"
}
```
```json
{
  "alias_id": "50582a7a-0a7e-4855-b531-bbfeb4b8ac2c",
  "alias_string": "Anchor Glass - Elmira Plant",
  "alias": "ANCHOR GLASS - ELMIRA PLANT",
  "normalized_alias": "anchor glass - elmira plant",
  "canonical_vendor_id": "ANCH",
  "vendor_no": "ANCH",
  "vendor_name": "Anchor Glass - Shakopee Plant",
  "source": "bc_cache_seed",
  "bc_doc_count": 230,
  "learned_at": "2026-04-01T17:39:38.496479+00:00",
  "created_at": "2026-04-01T17:39:38.496479+00:00"
}
```

## §D · `vendor_invoice_profiles`

```json
{
  "vendor_no": "ANCH",
  "vendor_name": "Anchor Glass - Re-Sort Solutions #111",
  "vendor_name_variants": [
    "Anchor Glass - Re-Sort Solutions #111",
    "Anchor Glass - Shakopee Plant",
    "Anchor Glass - Indiana Plant",
    "Anchor Glass - Hodges Tulsa 155",
    "Anchor Glass - Hodges Tulsa 198",
    "Anchor Glass - Tulsa",
    "Anchor Glass - Logistics Warehouse 137",
    "Anchor Glass - Resolve Packaging",
    "S&S Packaging - 131",
    "Anchor Glass - Logistics Warehouse #2 135",
    "Anchor Glass - Vista 107",
    "Anchor Glass - Miller Warehouse #2 104",
    "Anchor Glass -Allentown",
    "Anchor Glass - H&O Distribution 159",
    "Anchor Glass - H&O Distribution 124",
    "Anchor Glass - Lawrenceburg Plant",
    "Anchor Glass - Logistics Warehouse 135",
    "Anchor Glass - Glass & More 224",
    "Anchor Glass - Elmira",
    "Anchor Glass - B&B Packaging 123",
    "Anchor Glass - Vista 194",
    "Anchor Glass Container Corp",
    "Anchor Glass - Logistics Warehouse #135",
    "Anchor Glass - Hodges Okmulgee 127",
    "Anchor Glass - DIY Group Inc",
    "Anchor Glass - Glass & More",
    "Anchor Glass - Henryetta Plant",
    "Anchor Glass - Fort Smith",
    "Anchor Glass - Murphy Warehouse 163",
    "Anchor Glass - Logistics Warehouse 112",
    "Anchor Glass - Gateway Warehouse 102",
    "Universal Warehouse C/O Anchor Glass Container Corp",
    "Anchor Glass - Van Buren 135",
    "Anchor Glass - Warner Robins Plant",
    "Anchor Glass - Miller Tulsa 158",
    "H & O Distribution ",
    "Anchor Glass - Okmulgee",
    "Anchor Glass - Elmira Plant",
    "CPDS - 106"
  ],
  "source": "bc_cache_seed",
  "seeded_at": "2026-04-28T23:38:38.131396+00:00",
  "last_updated": "2026-04-28T23:38:38.131396+00:00",
  "bc_invoice_count": 6200
}
```

## §E · `bc_reference_cache`

_No bc_reference_cache record matches code `ANCH`._

## §F · `learning_events_v2`

_No learning_events_v2 rows reference this doc_id._

## §G · Other vendor / event / audit collections

**Collections scanned:**

`bc_cache_metadata`, `vendor_maturity_scores`, `classification_corrections`, `entity_resolutions`, `bc_item_mapping_history`, `vendor_matches`, `vendor_match_rejections`, `so_learning_apply_audit`, `sharepoint_vendor_mappings`, `feedback_events`, `intake_learning_events`, `ds_vendor_shipment_logs`, `vendor_extraction_successes`, `learning_events`, `ap_learning_suggestions`, `stable_vendor_config`, `customer_posting_profiles`, `sales_learning_jobs`, `vendor_type_patterns`, `self_correction_audits`, `workflow_events`, `learning_digests`, `hub_events`, `posting_learning_events`, `validation_gap_log`, `learning_metrics`, `customer_aliases`, `hub_bc_vendors`, `vendor_realtime_intelligence`, `reference_label_corrections`, `so_learning_suggestions`, `sender_vendor_map`, `vendor_extraction_profiles`, `intake_item_aliases`, `learning_drift_alerts`, `vendor_intelligence_profiles`, `stable_vendor_override_history`

### `vendor_maturity_scores`

(no doc-id link — matched on canonical code only)

```json
{
  "vendor_no": "ANCH",
  "composite_score": 96,
  "computed_at": "2026-04-28T23:43:07.284118+00:00",
  "dimensions": {
    "volume": {
      "score": 90,
      "weight": 0.15,
      "detail": "194 documents processed"
    },
    "accuracy": {
      "score": 97,
      "weight": 0.3,
      "detail": "189/194 successful"
    },
    "consistency": {
      "score": 100,
      "weight": 0.15,
      "detail": "0 corrections (0% rate)"
    },
    "recency": {
      "score": 80,
      "weight": 0.1,
      "detail": "Last activity: 2026-04-25"
    },
    "field_coverage": {
      "score": 100,
      "weight": 0.15,
      "detail": "5 reliable fields"
    },
    "error_rate": {
      "score": 100,
      "weight": 0.15,
      "detail": "0 failures (0% rate)"
    }
  },
  "has_posting_template": false,
  "maturity_level": "mastered",
  "template_confidence": "none",
  "total_documents": 194,
  "vendor_name": "ANCH"
}
```

### `classification_corrections`


```json
{
  "doc_id": "93dada81-b21e-4d82-af1b-43efa02e7eef",
  "vendor_id": "ANCH",
  "correction_type": "readiness_policy_held",
  "original_type": "True",
  "corrected_type": "False",
  "source": "readiness_self_correction",
  "confirmed_at": "2026-04-08T02:38:31.027877+00:00",
  "applied": true,
  "file_name": "multi-vendor-batch_doc2.pdf",
  "text_snippet": "ANCHOR GLASS CONTAINER CORP | AG-8842 | 2026-01-18 | 9500.00 | unknown",
  "vendor_canonical": "ANCH",
  "vendor_no": "ANCH"
}
```

### `vendor_extraction_successes`

(no doc-id link — matched on canonical code only)

```json
{
  "vendor_no": "ANCH",
  "confirmed_field_names": [
    "vendor",
    "invoice_number",
    "invoice_date",
    "amount",
    "freight_direction"
  ],
  "doc_type": "AP_Invoice",
  "last_success_at": "2026-04-25T18:46:03.146113+00:00",
  "last_successful_fields": [
    "vendor",
    "invoice_number",
    "invoice_date",
    "amount",
    "freight_direction"
  ],
  "success_count": 189
}
```

### `workflow_events`


```json
{
  "event_id": "d12dc39d-b629-47cd-be8e-f5aa8cc54b1a",
  "document_id": "93dada81-b21e-4d82-af1b-43efa02e7eef",
  "event_type": "document.received",
  "status": "completed",
  "source_service": "manual_auto_split",
  "correlation_id": "ce32acbc-d1d6-4d28-b1df-d0e18e1a1b9b",
  "timestamp": "2026-04-01T19:25:46.043168+00:00",
  "actor": null,
  "payload": {
    "source": "manual_auto_split",
    "file_name": "multi-vendor-batch_doc2.pdf",
    "content_type": "application/pdf",
    "file_size": 1318
  }
}
```
```json
{
  "event_id": "75619ae2-c6ae-4b2f-983b-155c3bc5b992",
  "document_id": "93dada81-b21e-4d82-af1b-43efa02e7eef",
  "event_type": "system.reprocessed",
  "timestamp": "2026-04-01T19:26:14.867316+00:00",
  "source_service": "ap_auto_post_service",
  "payload": {
    "trigger": "auto"
  }
}
```
```json
{
  "event_id": "bcac2cb1-f933-47de-8ef1-ae031940b818",
  "document_id": "93dada81-b21e-4d82-af1b-43efa02e7eef",
  "event_type": "automation.decision.completed",
  "timestamp": "2026-04-01T19:26:14.967316+00:00",
  "source_service": "ap_auto_post_service",
  "payload": {
    "decision": "NeedsReview",
    "auto_post": false,
    "reason": "BC post error: 502: BC API error: Client error '400 Bad Request' for url 'https://login.microsoftonline.com/doc-workflow-test/oauth2/v2.0/token'\nFor more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
    "source": "auto"
  }
}
```
```json
{
  "event_id": "cd7fc8c7-a944-499c-84a4-f378c4eff6e8",
  "document_id": "93dada81-b21e-4d82-af1b-43efa02e7eef",
  "event_type": "classification.completed",
  "status": "completed",
  "source_service": "ai_classifier",
  "correlation_id": "ce32acbc-d1d6-4d28-b1df-d0e18e1a1b9b",
  "timestamp": "2026-04-01T19:26:14.874241+00:00",
  "actor": null,
  "payload": {
    "doc_type": "AP_Invoice",
    "confidence": 0.98,
    "method": "ai",
    "model": "gemini-3-pro-preview"
  }
}
```
```json
{
  "event_id": "b08f4119-0fa7-45e9-a242-db99e266425a",
  "document_id": "93dada81-b21e-4d82-af1b-43efa02e7eef",
  "event_type": "vendor.match.failed",
  "status": "warning",
  "source_service": "unified_vendor_matcher",
  "correlation_id": "ce32acbc-d1d6-4d28-b1df-d0e18e1a1b9b",
  "timestamp": "2026-04-01T19:26:14.874682+00:00",
  "actor": null,
  "payload": {
    "vendor_raw": null,
    "reason": "No match found"
  }
}
```

### `vendor_realtime_intelligence`

(no doc-id link — matched on canonical code only)

```json
{
  "vendor_no": "ANCH",
  "by_type": {
    "AP_Invoice": {
      "total": 194,
      "success": 189
    }
  },
  "last_document_at": "2026-04-25T18:46:03.142558+00:00",
  "last_outcome": "auto_filed",
  "review_count": 5,
  "total_confidence_sum": 192.0600000000003,
  "total_documents": 194,
  "vendor_name": "ANCH",
  "auto_validation_rate": 0.9742,
  "avg_confidence": 0.99,
  "confidence_to_validation_gap": 0.0158,
  "correction_rate": 0.0,
  "rates_updated_at": "2026-04-25T18:46:03.143392+00:00",
  "gap_analysis": {
    "bc_connection": 5
  },
  "gap_last_seen": {
    "bc_connection": "2026-04-04T19:15:15.298301+00:00"
  },
  "success_count": 189
}
```

### `sender_vendor_map`

(no doc-id link — matched on canonical code only)

```json
{
  "sender_domain": "anchorglass.com",
  "vendor_canonical": "Anchor Glass - Shakopee Plant",
  "vendor_name": "Anchor Glass - Shakopee Plant",
  "vendor_no": "ANCH",
  "domain_confidence": 3,
  "source": "spiro_domain_seed",
  "created_at": "2026-04-01T17:40:06.656906+00:00",
  "updated_at": "2026-04-01T17:40:06.656906+00:00"
}
```

### `vendor_extraction_profiles`

(no doc-id link — matched on canonical code only)

```json
{
  "vendor_no": "ANCH",
  "amount_stats": {
    "count": 6176,
    "mean": 13037.24,
    "median": 12903.01,
    "stddev": 7381.74,
    "min": 50,
    "max": 499516.86,
    "p25": 11838.83,
    "p75": 14073.88
  },
  "confidence_adjustments": {
    "bc_data_rich": 0.02
  },
  "created_at": "2026-04-02T20:02:47.901237+00:00",
  "document_type_bias": "purchase_invoice",
  "enabled": true,
  "last_updated": "2026-04-02T20:02:47.901237+00:00",
  "learning_source": [
    "bc_cache_seed"
  ],
  "po_expected": true,
  "reference_label_bias": {},
  "reference_priority_order": [
    "purchase_order",
    "posted_purchase_invoice",
    "sales_order"
  ],
  "source_automation_rate": 0,
  "source_correction_count": 0,
  "source_invoice_count": 6200,
  "source_match_rate": 1.0,
  "vendor_name": "Anchor Glass - Okmulgee"
}
```

### `vendor_intelligence_profiles`

(no doc-id link — matched on canonical code only)

```json
{
  "vendor_no": "ANCH",
  "vendor_name": "ANCHOR GLASS CONTAINER CORP",
  "document_types_seen": [
    "AP_Invoice"
  ],
  "typical_reference_domain": "unknown",
  "reference_confidence_score": 0,
  "invoice_count": 1,
  "freight_invoice_count": 0,
  "shipping_document_count": 0,
  "po_reference_count": 0,
  "po_reference_frequency": 0.0,
  "shipment_reference_count": 0,
  "shipment_reference_frequency": 0.0,
  "bol_count": 0,
  "bol_presence_rate": 0.0,
  "invoice_reference_count": 1,
  "typical_bc_match_types": [],
  "bc_match_type_counts": {},
  "resolution_success_count": 0,
  "reference_resolution_success_rate": 0.0,
  "automation_success_count": 1,
  "automation_success_rate": 1.0,
  "validation_pass_count": 0,
  "validation_pass_rate": 0.0,
  "avg_match_score": 0,
  "match_outcome_counts": {
    "no_match": 1
  },
  "domain_counts": {
    "unknown": 1
  },
  "stable_vendor_flag": false,
  "first_document_seen": "2026-04-25T18:46:06.385481+00:00",
  "last_document_seen": "2026-04-25T18:46:06.385481+00:00",
  "created_at": "2026-04-25T18:46:06.385481+00:00",
  "updated_at": "2026-04-25T18:46:06.385481+00:00"
}
```

### `stable_vendor_override_history`

(no doc-id link — matched on canonical code only)

```json
{
  "vendor_no": "ANCH",
  "vendor_name": "ANCH",
  "action": "override_applied",
  "old_status": "unstable",
  "new_status": "watch",
  "override_status": "force_watch",
  "reason": "Testing override via pytest",
  "note": "Automated test - will be cleared",
  "actor": "pytest_admin",
  "timestamp": "2026-04-23T17:29:57.220342+00:00",
  "expires_at": null
}
```
```json
{
  "vendor_no": "ANCH",
  "vendor_name": "ANCH",
  "action": "override_applied",
  "old_status": "watch",
  "new_status": "unstable",
  "override_status": "force_unstable",
  "reason": "Test before clear",
  "note": "",
  "actor": "pytest",
  "timestamp": "2026-04-23T17:29:57.672887+00:00",
  "expires_at": null
}
```
```json
{
  "vendor_no": "ANCH",
  "vendor_name": "ANCH",
  "action": "override_cleared",
  "old_status": "unstable",
  "new_status": "unstable",
  "override_status": "none",
  "reason": "Clearing test override",
  "note": "",
  "actor": "pytest_admin",
  "timestamp": "2026-04-23T17:29:57.790985+00:00"
}
```
```json
{
  "vendor_no": "ANCH",
  "vendor_name": "ANCH",
  "action": "override_applied",
  "old_status": "unstable",
  "new_status": "stable",
  "override_status": "force_stable",
  "reason": "Test history",
  "note": "",
  "actor": "pytest_history_test",
  "timestamp": "2026-04-23T17:29:58.162147+00:00",
  "expires_at": null
}
```
```json
{
  "vendor_no": "ANCH",
  "vendor_name": "ANCH",
  "action": "override_cleared",
  "old_status": "stable",
  "new_status": "unstable",
  "override_status": "none",
  "reason": "Cleanup",
  "note": "",
  "actor": "pytest",
  "timestamp": "2026-04-23T17:29:58.373827+00:00"
}
```

## §H · Determination

**Best guess:** ALIAS — `vendor_aliases` row maps extracted name 'ANCHOR GLASS CONTAINER CORP' → vendor_no 'ANCH' (alias_id=contract-intel-9)

**Ranked hypotheses (highest evidence first):**

- ALIAS — `vendor_aliases` row maps extracted name 'ANCHOR GLASS CONTAINER CORP' → vendor_no 'ANCH' (alias_id=contract-intel-9)
- COLLECTION — `vendor_maturity_scores` carries history rows for this doc/code
- COLLECTION — `classification_corrections` carries history rows for this doc/code
- COLLECTION — `vendor_extraction_successes` carries history rows for this doc/code
- COLLECTION — `workflow_events` carries history rows for this doc/code
- COLLECTION — `vendor_realtime_intelligence` carries history rows for this doc/code
- COLLECTION — `sender_vendor_map` carries history rows for this doc/code
- COLLECTION — `vendor_extraction_profiles` carries history rows for this doc/code
- COLLECTION — `vendor_intelligence_profiles` carries history rows for this doc/code
- COLLECTION — `stable_vendor_override_history` carries history rows for this doc/code
