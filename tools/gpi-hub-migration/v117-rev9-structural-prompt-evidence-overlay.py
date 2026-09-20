from __future__ import annotations

from pathlib import Path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def replace_once(raw: str, old: str, new: str, label: str) -> str:
    require(old in raw, f"{label} anchor missing")
    return raw.replace(old, new, 1)


def patch_relevant_learning(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")

    old = '''    core_limit = max(1, min(limit, int(round(limit * 0.75))))
    same_vendor_rows = [row for row in ranked if row.get("_learned_same_vendor")]
    same_vendor_core_target = min(core_limit, len(same_vendor_rows))
    for row in same_vendor_rows:
        add(row)
        if len(selected) >= same_vendor_core_target:
            break
    for row in ranked:
        add(row)
        if len(selected) >= core_limit:
            break

    # Add at most two strongest same-vendor route contrasts. This teaches the
'''
    new = '''    core_limit = max(1, min(limit, int(round(limit * 0.75))))
    same_vendor_rows = [row for row in ranked if row.get("_learned_same_vendor")]

    # REV9: keep same-vendor evidence primary, but reserve up to two core slots
    # for route-neutral structural matches (reference family or high-signal
    # documented-business facts). REV8 could fill all six core slots from one
    # vendor even when a different HUMAN TRAIN example matched the current W/WTR/
    # WA, freight-line, context-pair, workflow, or shipment-method structure.
    # This only changes prompt evidence composition; it never selects a route.
    structural_prefixes = (
        "context_pair:",
        "freight_line:",
        "order_family:",
        "workflow:",
        "shipment_method:",
        "location_code:",
    )

    def structural_prompt_match(row: Dict[str, Any]) -> bool:
        similarity = row.get("_learned_feature_similarity") or {}
        current_ref = str(similarity.get("current_reference_family") or "")
        example_ref = str(similarity.get("example_reference_family") or "")
        if (
            current_ref
            and current_ref != "descriptor_or_none"
            and current_ref == example_ref
        ):
            return True
        shared_business = set(
            similarity.get("shared_business_context_features") or []
        )
        return any(
            feature.startswith(prefix)
            for feature in shared_business
            for prefix in structural_prefixes
        )

    structural_rows = [
        row
        for row in ranked
        if structural_prompt_match(row) and not row.get("_learned_same_vendor")
    ]
    reserved_structural = min(
        2,
        len(structural_rows),
        max(0, core_limit - 1),
    )
    same_vendor_core_target = min(
        len(same_vendor_rows),
        max(1, core_limit - reserved_structural),
    )
    for row in same_vendor_rows:
        add(row)
        if len(selected) >= same_vendor_core_target:
            break

    for row in structural_rows:
        add(row)
        if len(selected) >= core_limit:
            break

    for row in ranked:
        add(row)
        if len(selected) >= core_limit:
            break

    # Add at most two strongest same-vendor route contrasts. This teaches the
'''
    raw = replace_once(raw, old, new, "REV9 structural prompt reservation")
    require("reserved_structural = min(" in raw and "len(structural_rows)" in raw,
            "REV9 structural reservation missing after patch")
    compile(raw, str(path), "exec")
    path.write_text(raw, encoding="utf-8", newline="\n")


def patch_train_context(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")

    old_import = '''from services.ap_routing_learned_features_service import (
    feature_similarity,
    reference_family,
    semantic_features,
)
'''
    new_import = '''from services.ap_routing_business_context_service import (
    authority_business_signature,
    business_context_features,
)
from services.ap_routing_learned_features_service import (
    feature_similarity,
    reference_family,
    semantic_features,
)
'''
    raw = replace_once(raw, old_import, new_import, "REV9 business-context imports")

    insert_anchor = '''def _dynamic_route_usage(
'''
    helper = '''def _business_feature_route_usage(
    document: Dict[str, Any],
    rows: Sequence[Dict[str, Any]],
    *,
    feature_limit: int = 8,
    route_limit: int = 8,
) -> List[Dict[str, Any]]:
    """Bound HUMAN TRAIN route observations for current route-neutral business facts."""
    current = set(business_context_features(document))
    if not current:
        return []

    ignored = {
        "location_class:documented_warehouse",
        "location_class:zero",
        "service:cost_only",
    }
    priority = (
        "context_pair:",
        "freight_line:",
        "order_family:",
        "workflow:",
        "shipment_method:",
        "service:",
        "location_code:",
        "reference_evidence:",
        "vendor_fact:",
    )

    signature = list(sorted(authority_business_signature(document)))
    ordered: List[str] = []
    for feature in signature:
        if feature not in ignored and feature not in ordered:
            ordered.append(feature)
    for prefix in priority:
        for feature in sorted(current):
            if (
                feature not in ignored
                and feature.startswith(prefix)
                and feature not in ordered
            ):
                ordered.append(feature)
    selected_features = ordered[: max(1, int(feature_limit))]

    output: List[Dict[str, Any]] = []
    for feature in selected_features:
        matching = [
            row
            for row in rows
            if feature in business_context_features(row)
        ]
        if not matching:
            continue
        route_counts = _bounded_route_counts(
            matching,
            limit=max(1, int(route_limit)),
        )
        output.append(
            {
                "feature": feature,
                "human_train_support_count": len(matching),
                "route_counts": route_counts,
            }
        )
    return output


'''
    require(insert_anchor in raw, "REV9 train-context helper insertion anchor missing")
    raw = raw.replace(insert_anchor, helper + insert_anchor, 1)

    old_vars = '''    current_ref = reference_family(document)
    current_semantics = semantic_features(document)

    same_vendor = [row for row in eligible if vendor and _row_vendor(row) == vendor]
'''
    new_vars = '''    current_ref = reference_family(document)
    current_semantics = semantic_features(document)
    current_business_features = business_context_features(document)

    same_vendor = [row for row in eligible if vendor and _row_vendor(row) == vendor]
'''
    raw = replace_once(raw, old_vars, new_vars, "REV9 current business features")

    old_return = '''        "current_reference_family": current_ref,
        "current_semantic_features": sorted(current_semantics),
        "same_vendor_example_count": len(same_vendor),
'''
    new_return = '''        "current_reference_family": current_ref,
        "current_semantic_features": sorted(current_semantics),
        "current_business_context_features": sorted(current_business_features),
        "business_feature_route_usage": _business_feature_route_usage(
            document,
            eligible,
            feature_limit=8,
            route_limit=8,
        ),
        "same_vendor_example_count": len(same_vendor),
'''
    raw = replace_once(raw, old_return, new_return, "REV9 context output")

    compile(raw, str(path), "exec")
    path.write_text(raw, encoding="utf-8", newline="\n")


def patch_ai_primary(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")

    old_import = '''from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional
'''
    new_import = '''from __future__ import annotations

import json
import logging
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional

from services.ap_routing_business_context_service import business_context_features
from services.ap_routing_learned_features_service import reference_family, semantic_features
'''
    raw = replace_once(raw, old_import, new_import, "REV9 prompt evidence imports")

    old_helper = '''def _prompt_learning_example(example: Dict[str, Any]) -> Dict[str, Any]:
    """Expose the bounded semantics that made a human example relevant."""
    row = dict(example)
    extracted = dict(example.get("extracted_fields") or {})
    excerpt = str(example.get("raw_text_excerpt") or example.get("raw_text") or "")[:1600]
    row["key_evidence"] = {
        "extracted_fields": extracted,
        "semantic_excerpt": excerpt,
    }
    return row
'''
    new_helper = '''def _redact_cross_vendor_semantic_excerpt(example: Dict[str, Any]) -> str:
    excerpt = str(
        example.get("raw_text_excerpt")
        or example.get("raw_text")
        or ""
    )[:1600]
    fields = example.get("extracted_fields") or {}
    bc = example.get("bc_context") or {}
    live = bc.get("live_bc_context") or {}

    exact_values = []
    for value in (
        fields.get("po_number"),
        fields.get("order_number"),
        fields.get("reference_number"),
        fields.get("invoice_number"),
        fields.get("vendor_invoice_number"),
        (example.get("key_evidence") or {}).get("po_number"),
        bc.get("po_number"),
        bc.get("bc_document_no"),
        bc.get("bc_order_number"),
        live.get("bc_document_no"),
        live.get("bc_order_number"),
    ):
        token = str(value or "").strip()
        if len(token) >= 3:
            exact_values.append(token)

    for token in sorted(set(exact_values), key=len, reverse=True):
        excerpt = re.sub(re.escape(token), "[REDACTED_REF]", excerpt, flags=re.IGNORECASE)
    return excerpt


def _prompt_learning_example(
    example: Dict[str, Any],
    current_document: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Expose bounded HUMAN TRAIN evidence without leaking foreign exact refs."""
    current_document = current_document or {}
    current_fields = current_document.get("extracted_fields") or {}
    current_vendor = normalize_vendor_name(
        current_document.get("vendor_name")
        or current_document.get("vendor_canonical")
        or current_fields.get("vendor")
        or current_fields.get("vendor_name")
        or ""
    )
    example_fields = example.get("extracted_fields") or {}
    example_vendor = normalize_vendor_name(
        example.get("vendor_name")
        or example.get("normalized_vendor")
        or example_fields.get("vendor")
        or example_fields.get("vendor_name")
        or ""
    )
    same_vendor = bool(
        current_vendor
        and example_vendor
        and current_vendor == example_vendor
    )

    if same_vendor:
        row = dict(example)
        extracted = dict(example_fields)
        excerpt = str(
            example.get("raw_text_excerpt")
            or example.get("raw_text")
            or ""
        )[:1600]
        row["key_evidence"] = {
            "extracted_fields": extracted,
            "semantic_excerpt": excerpt,
            "reference_family": reference_family(example),
            "business_context_features": sorted(business_context_features(example)),
        }
        row["cross_vendor_exact_reference_redacted"] = False
        return row

    # REV9: cross-vendor examples remain useful for route-neutral structure and
    # semantics, but their exact filenames/order/PO/invoice references are not
    # shown to the model. This directly aligns prompt evidence with the existing
    # safety rule that foreign-vendor exact references cannot earn authority.
    return {
        "route_path": example.get("route_path") or example.get("final_human_route"),
        "document_type": example.get("document_type")
        or example.get("suggested_job_type"),
        "vendor_name": example.get("vendor_name")
        or example.get("normalized_vendor"),
        "label_source": example.get("label_source") or example.get("source"),
        "human_train_evidence": True,
        "cross_vendor_exact_reference_redacted": True,
        "key_evidence": {
            "semantic_features": sorted(semantic_features(example)),
            "semantic_excerpt": _redact_cross_vendor_semantic_excerpt(example),
            "reference_family": reference_family(example),
            "business_context_features": sorted(business_context_features(example)),
            "exact_reference_fields": "redacted_cross_vendor",
        },
    }
'''
    raw = replace_once(raw, old_helper, new_helper, "REV9 cross-vendor prompt redaction")

    old_examples = '''    prompt_examples = [_prompt_learning_example(item) for item in examples[:8]]
'''
    new_examples = '''    prompt_examples = [
        _prompt_learning_example(item, current_document=document)
        for item in examples[:8]
    ]
'''
    raw = replace_once(raw, old_examples, new_examples, "REV9 prompt example current-document binding")

    old_rules = '''        "22. An exact business, order, shipment, or BC reference observed only in another vendor's TRAIN examples is not "
        "routing authority for the current vendor. Do not rely on a foreign-vendor exact-reference example to justify the "
        "route unless independent same-vendor HUMAN TRAIN evidence supports that route; otherwise lower confidence and "
        "report the ambiguity in unresolved.\\n\\n"
'''
    new_rules = '''        "22. An exact business, order, shipment, or BC reference observed only in another vendor's TRAIN examples is not "
        "routing authority for the current vendor. Do not rely on a foreign-vendor exact-reference example to justify the "
        "route unless independent same-vendor HUMAN TRAIN evidence supports that route; otherwise lower confidence and "
        "report the ambiguity in unresolved.\\n"
        "23. business_feature_route_usage is HUMAN TRAIN prompt evidence for route-neutral current facts such as W/WTR/WA "
        "order family, documented context pairs, FREIGHT-WH/FREIGHT-DS, shipment method, workflow, and location. Use the "
        "observed HUMAN route distribution for the CURRENT matching fact before generic words such as freight, invoice, "
        "storage, or a plain numeric reference. It is context, not automatic authority.\\n"
        "24. A cross-vendor prompt example with cross_vendor_exact_reference_redacted=true may teach structural or semantic "
        "workflow only. Its missing exact identifiers are intentional; never reconstruct or assume them.\\n"
        "25. WTR, WA, and W structural families must be compared against HUMAN TRAIN examples sharing that same structural "
        "family or documented-business fact before crossing between Warehouse and Dropship families. Generic freight text "
        "alone is not sufficient to cross those families.\\n"
        "26. Approval and processor leaves are ownership assignments. Use a named child only when same-vendor HUMAN TRAIN "
        "or strong route-specific HUMAN TRAIN evidence supports that exact owner/processor leaf; otherwise prefer the "
        "supported parent and lower confidence rather than transplanting a child from another vendor.\\n\\n"
'''
    raw = replace_once(raw, old_rules, new_rules, "REV9 prompt rules")

    compile(raw, str(path), "exec")
    path.write_text(raw, encoding="utf-8", newline="\n")


def apply(root: str) -> None:
    base = Path(root)
    relevant = base / "backend/services/ap_routing_relevant_learning_service.py"
    train_context = base / "backend/services/ap_routing_train_context_service.py"
    ai_primary = base / "backend/services/ap_routing_ai_primary_service.py"

    for required in (relevant, train_context, ai_primary):
        require(required.is_file(), f"missing REV9 patch target: {required}")

    patch_relevant_learning(relevant)
    patch_train_context(train_context)
    patch_ai_primary(ai_primary)

    print("V117_REV9_STRUCTURAL_PROMPT_RESERVATION=PASS")
    print("V117_REV9_BUSINESS_FEATURE_ROUTE_USAGE=PASS")
    print("V117_REV9_CROSS_VENDOR_EXACT_REFERENCE_REDACTION=PASS")
    print("V117_REV9_AUTHORITY_THRESHOLDS=UNCHANGED")
    print("V117_REV9_DETERMINISTIC_ROUTE_SUBSTITUTION=NONE")


if __name__ == "__main__":
    import sys

    require(len(sys.argv) == 2, "usage: overlay.py <candidate-root>")
    apply(sys.argv[1])
