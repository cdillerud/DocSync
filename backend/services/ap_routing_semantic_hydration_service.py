"""Semantic-preserving hydration for V117 learned AP routing.

The legacy corpus hydrator extracted PDF text for BC/reference work but did not
persist that text into the supervised example. This adapter preserves a bounded
route-neutral semantic snapshot before the source file is deleted. It does not
inspect or select route labels; Accounting placement remains the only label.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from services import ap_routing_corpus_service as corpus
from services.ap_routing_learned_features_service import (
    SEMANTIC_FEATURE_SCHEMA,
    semantic_feature_snapshot,
)


def enrich_routing_example_with_semantics(
    example: Dict[str, Any],
    *,
    document: Dict[str, Any],
) -> Dict[str, Any]:
    """Attach route-neutral semantic evidence to a human-labeled example."""
    prepared = dict(example)
    snapshot = semantic_feature_snapshot(document)
    features = list(snapshot["features"])
    fields = dict(prepared.get("extracted_fields") or document.get("extracted_fields") or {})
    fields["_learned_feature_schema"] = SEMANTIC_FEATURE_SCHEMA
    fields["_learned_semantic_features"] = features

    prepared.update(
        {
            "raw_text_excerpt": str(document.get("raw_text") or document.get("raw_text_excerpt") or "")[:12000],
            "learned_feature_schema": SEMANTIC_FEATURE_SCHEMA,
            "learned_semantic_features": features,
            "learned_reference_family": snapshot["reference_family"],
            "extracted_fields": fields,
        }
    )
    return prepared


async def hydrate_accounting_label_with_semantics(
    label: Dict[str, Any],
    *,
    routing_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Hydrate one Accounting label and persist semantic substrate before cleanup."""
    file_name = str(label["file_name"])
    suffix = Path(file_name).suffix or ".bin"
    local_path = await corpus._download_graph_file(label["drive_id"], label["item_id"], suffix)
    try:
        primary = await corpus.classify_primary_document(local_path, file_name)
        primary_type = primary.get("suggested_job_type") or primary.get("document_type") or "Unknown_Document"
        primary_fields = dict(primary.get("extracted_fields") or {})
        bundle = await corpus.extract_supporting_references(
            local_path,
            file_name,
            primary_document_type=primary_type,
            primary_fields=primary_fields,
        )
        raw_text = corpus._extract_text_excerpt(local_path)
        document = {
            "id": f"accounting-temp:{label['item_id']}",
            "file_name": file_name,
            "document_type": primary_type,
            "suggested_job_type": primary_type,
            "confidence": primary.get("confidence"),
            "extracted_fields": primary_fields,
            "raw_text": raw_text,
        }
        bc_context = await corpus.resolve_ap_routing_context(document, bundle_refs=bundle)
        vendor_name = (
            primary_fields.get("vendor")
            or primary_fields.get("vendor_name")
            or bc_context.get("bc_vendor_name")
            or ((bc_context.get("live_bc_context") or {}).get("bc_vendor_name"))
            or ""
        )

        queue_route = corpus.normalize_route_path(label.get("route_path"))
        source_route = corpus.normalize_route_path(label.get("source_route_path") or queue_route)
        label_resolution = str(label.get("route_label_resolution") or "raw_accounting_placement")
        if (
            routing_contract
            and source_route
            and source_route != queue_route
            and not corpus._learning_exclusion_for_route(source_route, routing_contract)
            and corpus.route_is_allowed(source_route, routing_contract, bc_context)
        ):
            queue_route = source_route
            label_resolution = "verified_dynamic_route"

        example = {
            "label_source": corpus.LABEL_SOURCE_ACCOUNTING_TEMP,
            "source_item_id": label["item_id"],
            "source_drive_id": label["drive_id"],
            "source_web_url": label.get("web_url"),
            "source_route_path": source_route,
            "route_label_resolution": label_resolution,
            "file_name": file_name,
            "route_path": queue_route,
            "vendor_name": vendor_name,
            "document_type": primary_type,
            "classification_confidence": primary.get("confidence"),
            "extracted_fields": primary_fields,
            "bundle_references": bundle,
            "bc_context": bc_context,
            "key_evidence": {
                "invoice_number": primary_fields.get("invoice_number"),
                "po_number": bc_context.get("po_number"),
                "location_code": bc_context.get("location_code"),
                "supporting_references": bundle.get("references"),
            },
            "created_at": label.get("created_at"),
            "modified_at": label.get("modified_at"),
        }
        return corpus.prepare_routing_example(
            enrich_routing_example_with_semantics(example, document=document)
        )
    finally:
        try:
            os.remove(local_path)
        except OSError:
            pass
