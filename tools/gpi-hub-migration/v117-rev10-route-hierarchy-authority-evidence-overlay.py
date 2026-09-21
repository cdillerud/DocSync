from __future__ import annotations

from pathlib import Path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def replace_once(raw: str, old: str, new: str, label: str) -> str:
    require(old in raw, f"{label} anchor missing")
    return raw.replace(old, new, 1)


def patch_train_context(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")

    insert_anchor = '''def _dynamic_route_usage(
'''
    helper = '''def _route_parent(route: str) -> str:
    normalized = normalize_route_path(route)
    if not normalized or "/" not in normalized:
        return normalized
    return normalized.rsplit("/", 1)[0]


def _route_family(route: str) -> str:
    normalized = normalize_route_path(route)
    if not normalized:
        return ""
    return normalized.split("/", 1)[0]


def _route_hierarchy_usage(
    rows: Sequence[Dict[str, Any]],
    *,
    route_limit: int = 12,
    parent_limit: int = 8,
) -> Dict[str, Any]:
    """Summarize HUMAN TRAIN route depth without selecting a route."""
    exact = Counter(
        normalize_route_path(row.get("route_path") or row.get("final_human_route"))
        for row in rows
        if normalize_route_path(row.get("route_path") or row.get("final_human_route"))
    )
    family = Counter()
    for route, count in exact.items():
        family[_route_family(route)] += int(count)

    parents = []
    candidate_parents = set()
    for route in exact:
        candidate_parents.add(_route_parent(route))
    for parent in sorted(candidate_parents):
        if not parent:
            continue
        children = [
            (route, count)
            for route, count in exact.items()
            if route.startswith(parent + "/")
        ]
        if not children:
            continue
        children.sort(key=lambda item: (-int(item[1]), item[0]))
        parents.append(
            {
                "parent_path": parent,
                "parent_exact_count": int(exact.get(parent, 0)),
                "child_count": int(sum(int(count) for _, count in children)),
                "children": [
                    {"route_path": route, "count": int(count)}
                    for route, count in children[:6]
                ],
            }
        )
    parents.sort(
        key=lambda row: (
            -(int(row["parent_exact_count"]) + int(row["child_count"])),
            str(row["parent_path"]),
        )
    )

    return {
        "exact_route_counts": [
            {"route_path": route, "count": int(count)}
            for route, count in exact.most_common(max(1, int(route_limit)))
        ],
        "family_counts": [
            {"route_family": route_family, "count": int(count)}
            for route_family, count in family.most_common(max(1, int(route_limit)))
        ],
        "parent_child_counts": parents[: max(1, int(parent_limit))],
    }


'''
    require(insert_anchor in raw, "REV10 route hierarchy insertion anchor missing")
    raw = raw.replace(insert_anchor, helper + insert_anchor, 1)

    old_return = '''        "business_feature_route_usage": _business_feature_route_usage(
            document,
            eligible,
            feature_limit=8,
            route_limit=8,
        ),
        "same_vendor_example_count": len(same_vendor),
'''
    new_return = '''        "business_feature_route_usage": _business_feature_route_usage(
            document,
            eligible,
            feature_limit=8,
            route_limit=8,
        ),
        "route_hierarchy_same_vendor": _route_hierarchy_usage(
            same_vendor,
            route_limit=12,
            parent_limit=8,
        ),
        "route_hierarchy_same_reference_family": _route_hierarchy_usage(
            same_reference,
            route_limit=12,
            parent_limit=8,
        ),
        "route_hierarchy_nearest": _route_hierarchy_usage(
            nearest,
            route_limit=12,
            parent_limit=8,
        ),
        "same_vendor_example_count": len(same_vendor),
'''
    raw = replace_once(raw, old_return, new_return, "REV10 route hierarchy context output")

    require("route_hierarchy_same_vendor" in raw, "REV10 same-vendor route hierarchy missing")
    require("route_hierarchy_same_reference_family" in raw, "REV10 reference-family route hierarchy missing")
    compile(raw, str(path), "exec")
    path.write_text(raw, encoding="utf-8", newline="\n")


def patch_ai_primary(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")

    old = '''        "26. Approval and processor leaves are ownership assignments. Use a named child only when same-vendor HUMAN TRAIN "
        "or strong route-specific HUMAN TRAIN evidence supports that exact owner/processor leaf; otherwise prefer the "
        "supported parent and lower confidence rather than transplanting a child from another vendor.\\n\\n"
'''
    new = '''        "26. Approval and processor leaves are ownership assignments. Use a named child only when same-vendor HUMAN TRAIN "
        "or strong route-specific HUMAN TRAIN evidence supports that exact owner/processor leaf; otherwise prefer the "
        "supported parent and lower confidence rather than transplanting a child from another vendor.\\n"
        "27. Decide routing topology before workflow detail. First determine the supported top-level route family from current "
        "structural facts, route_hierarchy_* HUMAN TRAIN distributions, and business_feature_route_usage. Only after that may "
        "workflow semantics refine a child. Words such as cost variance, return, freight, inventory, quality, storage, or "
        "dunnage do not by themselves switch Warehouse, Dropship, Vendor Credit, S&H, or Miscellaneous families.\\n"
        "28. Treat route depth as evidence-sensitive. A child route is a more specific workflow state than its parent. If HUMAN "
        "TRAIN evidence supports the parent but the CURRENT document lacks direct support for the exact child, choose the "
        "supported parent rather than borrowing a sibling or child merely because it is nearby in the route tree.\\n"
        "29. Approval state, processor ownership, quality/credit state, and other leaf-level workflow states require current "
        "corroboration or strong exact-route HUMAN TRAIN support. Filename comments and historical notes can describe a past "
        "action; do not treat them as the current leaf state without corroboration.\\n"
        "30. A verified PO, purchase receipt, or BC transaction proves transaction context but does not alone decide Warehouse "
        "versus Dropship or parent-versus-child routing. Use current structural evidence plus HUMAN TRAIN topology before "
        "using transaction existence to refine the route.\\n\\n"
'''
    raw = replace_once(raw, old, new, "REV10 hierarchy/topology prompt rules")

    compile(raw, str(path), "exec")
    path.write_text(raw, encoding="utf-8", newline="\n")


def patch_business_context_expansion(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")

    old_import = '''from services.ap_routing_learned_features_service import semantic_features
'''
    new_import = '''from services.ap_routing_learned_features_service import reference_family, semantic_features
'''
    raw = replace_once(raw, old_import, new_import, "REV10 reference-family import")

    old_weights = '''_KIND_WEIGHT = {
    "discriminating_semantic_route_support": 8,
    "same_vendor_document_type_business_context": 6,
    "cross_vendor_document_type_business_context": 4,
}
'''
    new_weights = '''_KIND_WEIGHT = {
    "discriminating_semantic_route_support": 8,
    "same_vendor_document_type_route_support": 7,
    "same_vendor_document_type_reference_family_route_support": 7,
    "same_vendor_document_type_business_context": 6,
    "reference_family_route_support": 5,
    "cross_vendor_document_type_business_context": 4,
}
'''
    raw = replace_once(raw, old_weights, new_weights, "REV10 authority-evidence weights")

    insert_anchor = '''    unique: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for deficit in deficits:
'''
    block = '''    # REV10: fill sparse exact-route HUMAN TRAIN support without lowering
    # authority thresholds. These deficits never infer a route from vendor,
    # reference family, or document type: the route already comes from HUMAN
    # Accounting placement, and every admitted candidate must independently
    # carry that exact human route label.
    same_vendor_route_groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    same_vendor_reference_groups: Dict[
        Tuple[str, str, str, str], List[Dict[str, Any]]
    ] = defaultdict(list)
    reference_route_groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)

    for row in eligible:
        route = _route(row)
        if (
            not route
            or route == DNP
            or route in manual_only
            or _is_dynamic_child(route, contract)
        ):
            continue
        vendor = _vendor(row)
        doc_type = _doc_type(row)
        ref_family = reference_family(row)
        if vendor and doc_type:
            same_vendor_route_groups[(vendor, doc_type, route)].append(row)
        if (
            vendor
            and doc_type
            and ref_family
            and ref_family != "descriptor_or_none"
        ):
            same_vendor_reference_groups[
                (vendor, doc_type, ref_family, route)
            ].append(row)
        if doc_type and ref_family and ref_family != "descriptor_or_none":
            reference_route_groups[(doc_type, ref_family, route)].append(row)

    for (vendor, doc_type, route), rows in sorted(same_vendor_route_groups.items()):
        support = len(rows)
        minimum_support = 3
        if support >= minimum_support:
            continue
        deficits.append(
            {
                "kind": "same_vendor_document_type_route_support",
                "route_path": route,
                "vendor": vendor,
                "document_type": doc_type,
                "business_signature": [],
                "business_signal_families": [],
                "required_semantics": [],
                "required_reference_family": "",
                "support_count": support,
                "contradiction_count": 0,
                "matched_human_count": support,
                "minimum_support": minimum_support,
                "minimum_purity": 1.0,
                "additional_support_needed": minimum_support - support,
            }
        )

    for (vendor, doc_type, ref_family, route), rows in sorted(
        same_vendor_reference_groups.items()
    ):
        support = len(rows)
        minimum_support = 5
        if support >= minimum_support:
            continue
        deficits.append(
            {
                "kind": "same_vendor_document_type_reference_family_route_support",
                "route_path": route,
                "vendor": vendor,
                "document_type": doc_type,
                "business_signature": [],
                "business_signal_families": [],
                "required_semantics": [],
                "required_reference_family": ref_family,
                "support_count": support,
                "contradiction_count": 0,
                "matched_human_count": support,
                "minimum_support": minimum_support,
                "minimum_purity": 1.0,
                "additional_support_needed": minimum_support - support,
            }
        )

    for (doc_type, ref_family, route), rows in sorted(reference_route_groups.items()):
        support = len(rows)
        minimum_support = 5
        if support >= minimum_support:
            continue
        deficits.append(
            {
                "kind": "reference_family_route_support",
                "route_path": route,
                "vendor": "",
                "document_type": doc_type,
                "business_signature": [],
                "business_signal_families": [],
                "required_semantics": [],
                "required_reference_family": ref_family,
                "support_count": support,
                "contradiction_count": 0,
                "matched_human_count": support,
                "minimum_support": minimum_support,
                "minimum_purity": 1.0,
                "additional_support_needed": minimum_support - support,
            }
        )

    unique: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for deficit in deficits:
'''
    raw = replace_once(raw, insert_anchor, block, "REV10 authority-evidence deficit builder")

    old_match = '''    doc_type = str(deficit.get("document_type") or "")
    if doc_type and _doc_type(example) != doc_type:
        return False
    signature = set(deficit.get("business_signature") or [])
'''
    new_match = '''    doc_type = str(deficit.get("document_type") or "")
    if doc_type and _doc_type(example) != doc_type:
        return False
    required_reference_family = str(deficit.get("required_reference_family") or "")
    if required_reference_family and reference_family(example) != required_reference_family:
        return False
    signature = set(deficit.get("business_signature") or [])
'''
    raw = replace_once(raw, old_match, new_match, "REV10 reference-family candidate matching")

    old_key = '''            tuple(deficit.get("required_semantics") or []),
        )
'''
    new_key = '''            tuple(deficit.get("required_semantics") or []),
            str(deficit.get("required_reference_family") or ""),
        )
'''
    raw = replace_once(raw, old_key, new_key, "REV10 deficit uniqueness")

    old_sort = '''            tuple(row.get("required_semantics") or []),
        )
'''
    new_sort = '''            tuple(row.get("required_semantics") or []),
            str(row.get("required_reference_family") or ""),
        )
'''
    raw = replace_once(raw, old_sort, new_sort, "REV10 deficit sort")

    old_prefilter = '''    pseudo = {"file_name": str(label.get("file_name") or "")}
    pseudo_signature = authority_business_signature(pseudo)
    pseudo_semantics = semantic_features(pseudo)
    lower = str(label.get("file_name") or "").lower()
'''
    new_prefilter = '''    pseudo = {"file_name": str(label.get("file_name") or "")}
    pseudo_signature = authority_business_signature(pseudo)
    pseudo_semantics = semantic_features(pseudo)
    pseudo_reference_family = reference_family(pseudo)
    lower = str(label.get("file_name") or "").lower()
'''
    raw = replace_once(raw, old_prefilter, new_prefilter, "REV10 reference-family prefilter setup")

    old_score = '''        required_semantics = set(deficit.get("required_semantics") or [])
        if required_semantics and required_semantics.issubset(pseudo_semantics):
            local += 8
        score = max(score, local)
'''
    new_score = '''        required_semantics = set(deficit.get("required_semantics") or [])
        if required_semantics and required_semantics.issubset(pseudo_semantics):
            local += 8
        required_reference_family = str(deficit.get("required_reference_family") or "")
        if (
            required_reference_family
            and pseudo_reference_family == required_reference_family
        ):
            local += 8
        score = max(score, local)
'''
    raw = replace_once(raw, old_score, new_score, "REV10 reference-family prefilter scoring")

    require(
        "same_vendor_document_type_route_support" in raw,
        "REV10 same-vendor route-support deficits missing",
    )
    require(
        "reference_family_route_support" in raw,
        "REV10 reference-family route-support deficits missing",
    )
    compile(raw, str(path), "exec")
    path.write_text(raw, encoding="utf-8", newline="\n")


def apply(root: str) -> None:
    base = Path(root)
    train_context = base / "backend/services/ap_routing_train_context_service.py"
    ai_primary = base / "backend/services/ap_routing_ai_primary_service.py"
    expansion = base / "backend/services/ap_routing_business_context_expansion_service.py"

    for required in (train_context, ai_primary, expansion):
        require(required.is_file(), f"missing REV10 patch target: {required}")

    patch_train_context(train_context)
    patch_ai_primary(ai_primary)
    patch_business_context_expansion(expansion)

    print("V117_REV10_ROUTE_HIERARCHY_CONTEXT=PASS")
    print("V117_REV10_TOPOLOGY_FIRST_PROMPT=PASS")
    print("V117_REV10_ROUTE_DEPTH_DISCIPLINE=PASS")
    print("V117_REV10_AUTHORITY_EVIDENCE_EXPANSION=PASS")
    print("V117_REV10_AUTHORITY_THRESHOLDS=UNCHANGED")
    print("V117_REV10_DETERMINISTIC_ROUTE_SUBSTITUTION=NONE")


if __name__ == "__main__":
    import sys

    require(len(sys.argv) == 2, "usage: overlay.py <candidate-root>")
    apply(sys.argv[1])
