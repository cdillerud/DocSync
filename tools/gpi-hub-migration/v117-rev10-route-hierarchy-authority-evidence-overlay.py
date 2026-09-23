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
        "using transaction existence to refine the route.\\n"
        "31. Do not stop at a workflow parent merely because it is broader. When same-vendor or highly relevant HUMAN TRAIN "
        "shows a repeated exact child and the current document matches that workflow evidence, preserve the exact child. A parent "
        "is not safer when it erases a known GPI approval, processor, exception, or transaction-state assignment.\\n"
        "32. Distinguish sibling leaves by CURRENT evidence. For Freight Issues versus Sales Order not posted, or one named "
        "approver/processor versus another, generic words such as freight, issue, invoice, handling, or allocation are not enough. "
        "Use comparable HUMAN TRAIN evidence plus current BC/document facts for the exact sibling; otherwise lower confidence.\\n"
        "33. Literal workflow phrases matter. The exact phrase cost variance is discriminating workflow evidence; generic words "
        "such as cost, higher cost, price, variance-like commentary, or a filename note do not by themselves establish the Cost "
        "Variance workflow or switch a Dropship document into Warehouse.\\n"
        "34. DO NOT PAY requires current invalidation/stop-pay evidence or a highly comparable HUMAN TRAIN pattern. Phrases such "
        "as short paid, underpaid, balance difference, cost difference, credit, or payment history are not themselves stop-pay "
        "instructions. Do not turn a payable freight invoice into DO NOT PAY from those phrases alone.\\n"
        "35. Inventory, warehouse receipt, packing-list, BOL, photo, and transfer semantics describe document purpose, not the "
        "final Accounting queue by themselves. Preserve GPI ownership/workflow labels from relevant HUMAN TRAIN evidence; do not "
        "default these documents to Warehouse or Miscellaneous merely from their ordinary-English meaning.\\n"
        "36. Special top-level queues such as Meg to Process, Rhonda - Issues, and Miscellaneous are GPI workflow labels. Do not "
        "treat Miscellaneous as a semantic fallback for an unfamiliar document, and do not replace a supported special queue with "
        "Warehouse simply because the document concerns logistics or a receipt.\\n\\n"
'''
    raw = replace_once(raw, old, new, "REV10 hierarchy/topology prompt rules")

    review_anchor = '''async def propose_ap_route_ai_primary(
'''
    review_helpers = r'''def _route_hierarchy_parent_has_children(
    route: str,
    learning_context: Optional[Dict[str, Any]],
) -> bool:
    normalized = normalize_route_path(route)
    if not normalized or not learning_context:
        return False
    for key in (
        "route_hierarchy_same_vendor",
        "route_hierarchy_same_reference_family",
        "route_hierarchy_nearest",
    ):
        hierarchy = (learning_context or {}).get(key) or {}
        for row in hierarchy.get("parent_child_counts") or []:
            if normalize_route_path(row.get("parent_path")) != normalized:
                continue
            if int(row.get("child_count") or 0) > 0:
                return True
    return False


def _proposal_review_needed(
    prediction: RoutePrediction,
    learning_context: Optional[Dict[str, Any]],
) -> bool:
    """Bound a second AI review to uncertain or topology-sensitive proposals."""
    proposed = normalize_route_path(prediction.proposed_route)
    if not proposed:
        return True
    if prediction.unresolved:
        return True
    if float(prediction.confidence) < 0.90:
        return True
    return _route_hierarchy_parent_has_children(proposed, learning_context)


def _build_proposal_review_prompt(
    original_prompt: str,
    first_pass: RoutePrediction,
    learning_context: Optional[Dict[str, Any]],
) -> str:
    """Ask the same bounded model to independently review its first proposal.

    This is still AI-primary: the second pass receives only current evidence,
    TRAIN-only human context, and the first AI proposal. No held-out label,
    deterministic route recommendation, or authority decision is supplied.
    """
    first = first_pass.to_dict()
    return (
        original_prompt
        + "\n\nSECOND-PASS PROPOSAL REVIEW\n"
        + "Independently review the FIRST_PASS_AI_PROPOSAL against the current document, "
        + "Business Central facts, similar HUMAN TRAIN examples, and train_learning_context. "
        + "Do not preserve the first answer merely for consistency. The final proposed_route "
        + "must still be selected by the AI from the supplied routing_contract.\n"
        + "Review checks:\n"
        + "A. Re-check top-level workflow family before choosing a child. Document-purpose words "
        + "(inventory, receipt, BOL, photo, freight, cost, credit) are not folder selections.\n"
        + "B. If same-vendor or highly relevant HUMAN TRAIN repeatedly supports an exact child and "
        + "current evidence does not contradict that child, do not collapse it to the parent merely "
        + "because the child is more specific.\n"
        + "C. Distinguish sibling children using current facts plus exact-route HUMAN TRAIN support; "
        + "do not transplant a sibling from another vendor.\n"
        + "D. If a semantic hypothesis is ruled out (for example generic cost is not literal cost variance, "
        + "or short-paid language is not a stop-pay instruction), reconsider the remaining supported routes "
        + "instead of stopping at that rejected hypothesis.\n"
        + "E. Use unresolved only for a concrete missing or contradictory fact that prevents a supported "
        + "route selection. Low confidence or ordinary caution alone is not unresolved.\n"
        + "F. If the first pass produced no route, make a fresh bounded attempt from the TRAIN evidence "
        + "rather than repeating the abstention when a supported route exists.\n"
        + "Return JSON only in the exact routing-prediction shape required above.\n"
        + "FIRST_PASS_AI_PROPOSAL:\n"
        + json.dumps(first, ensure_ascii=False, default=str)
        + "\n"
    )


'''
    require(review_anchor in raw, "REV10 proposal-review insertion anchor missing")
    raw = raw.replace(review_anchor, review_helpers + review_anchor, 1)

    first_pass_old = '''    sender = llm_send or _default_llm_send
    try:
        raw = await sender(prompt, model)
        prediction = parse_route_prediction(raw, model=model)
    except Exception as exc:
        logger.exception("AI-primary AP routing model call failed")
        prediction = RoutePrediction(
            proposed_route="",
            confidence=0.0,
            evidence=[],
            reasoning_summary="routing model failure",
            bc_refs_used=[],
            unresolved=[f"model_error:{type(exc).__name__}"],
            matched_example_ids=[],
            model=model,
        )

    proposed = normalize_route_path(prediction.proposed_route)
'''
    first_pass_new = '''    sender = llm_send or _default_llm_send
    try:
        raw = await sender(prompt, model)
        prediction = parse_route_prediction(raw, model=model)
    except Exception as exc:
        logger.exception("AI-primary AP routing model call failed")
        prediction = RoutePrediction(
            proposed_route="",
            confidence=0.0,
            evidence=[],
            reasoning_summary="routing model failure",
            bc_refs_used=[],
            unresolved=[f"model_error:{type(exc).__name__}"],
            matched_example_ids=[],
            model=model,
        )

    first_pass_prediction = prediction
    proposal_review_used = False
    proposal_review_error = ""
    if _proposal_review_needed(first_pass_prediction, learning_context):
        proposal_review_used = True
        review_prompt = _build_proposal_review_prompt(
            prompt,
            first_pass_prediction,
            learning_context,
        )
        try:
            reviewed_raw = await sender(review_prompt, model)
            reviewed_prediction = parse_route_prediction(reviewed_raw, model=model)
            if normalize_route_path(reviewed_prediction.proposed_route):
                prediction = reviewed_prediction
            elif not normalize_route_path(first_pass_prediction.proposed_route):
                prediction = reviewed_prediction
        except Exception as exc:
            proposal_review_error = f"{type(exc).__name__}:{exc}"[:500]
            logger.warning(
                "AI-primary second-pass proposal review failed; preserving first pass: %s",
                proposal_review_error,
            )

    proposed = normalize_route_path(prediction.proposed_route)
'''
    raw = replace_once(
        raw,
        first_pass_old,
        first_pass_new,
        "REV10 bounded second-pass AI proposal review",
    )

    return_anchor = '''        "route_selected_by": "ai_model",
        "supervised_route_substitution": False,
'''
    return_new = '''        "route_selected_by": "ai_model",
        "supervised_route_substitution": False,
        "proposal_review_used": proposal_review_used,
        "proposal_review_error": proposal_review_error,
        "first_pass_prediction": first_pass_prediction.to_dict(),
'''
    raw = replace_once(
        raw,
        return_anchor,
        return_new,
        "REV10 proposal-review audit fields",
    )

    require("_proposal_review_needed" in raw, "REV10 proposal-review helper missing")
    require("SECOND-PASS PROPOSAL REVIEW" in raw, "REV10 second-pass prompt missing")
    require('"proposal_review_used": proposal_review_used' in raw, "REV10 proposal-review audit missing")

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

    def rev10_generic_deficit_allowed(rows: Sequence[Dict[str, Any]]) -> bool:
        # Preserve REV8's discriminating-semantic evidence contract. If a route
        # already exhibits one of those workflow semantics in HUMAN TRAIN, a
        # broader REV10 vendor/reference-family deficit must not admit generic
        # candidates that omit the semantic. Let the higher-specificity REV8
        # semantic deficit own expansion for that route slice.
        return not any(
            set(semantic_features(row)).intersection(_REV8_DISCRIMINATING_SEMANTICS)
            for row in rows
        )

    for (vendor, doc_type, route), rows in sorted(same_vendor_route_groups.items()):
        support = len(rows)
        minimum_support = 3
        if support >= minimum_support or not rev10_generic_deficit_allowed(rows):
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
        if support >= minimum_support or not rev10_generic_deficit_allowed(rows):
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
        if support >= minimum_support or not rev10_generic_deficit_allowed(rows):
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

    old_selector = '''def _round_robin_prefilter_labels(
    labels: Sequence[Dict[str, Any]],
    deficits: Sequence[Dict[str, Any]],
    *,
    excluded_source_item_ids: Set[str],
    already_selected_source_item_ids: Set[str],
    max_candidates: int,
) -> List[Dict[str, Any]]:
    target_routes = {str(row["route_path"]) for row in deficits}
    by_route: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    excluded = {str(value) for value in excluded_source_item_ids}
    already = {str(value) for value in already_selected_source_item_ids}
    for source in labels:
        row = dict(source)
        item_id = str(row.get("item_id") or "")
        route = normalize_route_path(row.get("route_path"))
        if not item_id or item_id in excluded or item_id in already or route not in target_routes:
            continue
        score = _candidate_prefilter_score(row, deficits)
        if score < 0:
            continue
        row["_business_context_prefilter_score"] = score
        by_route[route].append(row)
    for rows in by_route.values():
        rows.sort(
            key=lambda row: (
                int(row.get("_business_context_prefilter_score") or 0),
                str(row.get("modified_at") or ""),
                str(row.get("file_name") or ""),
                str(row.get("item_id") or ""),
            ),
            reverse=True,
        )
    selected: List[Dict[str, Any]] = []
    indices: Counter[str] = Counter()
    routes = sorted(by_route)
    while len(selected) < max(0, int(max_candidates)):
        progressed = False
        for route in routes:
            idx = indices[route]
            rows = by_route[route]
            if idx >= len(rows):
                continue
            selected.append(rows[idx])
            indices[route] += 1
            progressed = True
            if len(selected) >= max_candidates:
                break
        if not progressed:
            break
    return selected
'''
    new_selector = '''def _candidate_prefilter_affinity_for_deficit(
    label: Dict[str, Any],
    deficit: Dict[str, Any],
) -> Dict[str, bool]:
    pseudo = {"file_name": str(label.get("file_name") or "")}
    pseudo_signature = authority_business_signature(pseudo)
    pseudo_semantics = semantic_features(pseudo)
    pseudo_reference_family = reference_family(pseudo)
    lower = str(label.get("file_name") or "").lower()

    vendor = str(deficit.get("vendor") or "")
    vendor_terms = _vendor_filename_terms(vendor) if vendor else set()
    signature = set(deficit.get("business_signature") or [])
    required_semantics = set(deficit.get("required_semantics") or [])
    required_reference_family = str(deficit.get("required_reference_family") or "")

    return {
        "vendor_requested": bool(vendor_terms),
        "vendor_match": bool(vendor_terms and any(term in lower for term in vendor_terms)),
        "signature_requested": bool(signature),
        "signature_match": bool(signature and signature.issubset(pseudo_signature)),
        "semantics_requested": bool(required_semantics),
        "semantics_match": bool(required_semantics and required_semantics.issubset(pseudo_semantics)),
        "reference_requested": bool(required_reference_family),
        "reference_match": bool(
            required_reference_family
            and pseudo_reference_family == required_reference_family
        ),
    }


def _candidate_prefilter_score_for_deficit(
    label: Dict[str, Any],
    deficit: Dict[str, Any],
) -> int:
    route = normalize_route_path(label.get("route_path"))
    if not route or route != normalize_route_path(deficit.get("route_path")):
        return -1
    pseudo = {"file_name": str(label.get("file_name") or "")}
    pseudo_signature = authority_business_signature(pseudo)
    pseudo_semantics = semantic_features(pseudo)
    pseudo_reference_family = reference_family(pseudo)
    lower = str(label.get("file_name") or "").lower()

    local = 1
    vendor = str(deficit.get("vendor") or "")
    if vendor:
        terms = _vendor_filename_terms(vendor)
        if terms and any(term in lower for term in terms):
            local += 5
    signature = set(deficit.get("business_signature") or [])
    overlap = signature.intersection(pseudo_signature)
    local += min(8, 3 * len(overlap))
    required_semantics = set(deficit.get("required_semantics") or [])
    if required_semantics and required_semantics.issubset(pseudo_semantics):
        local += 8
    required_reference_family = str(deficit.get("required_reference_family") or "")
    if required_reference_family and pseudo_reference_family == required_reference_family:
        local += 8
    return local


def _round_robin_prefilter_labels(
    labels: Sequence[Dict[str, Any]],
    deficits: Sequence[Dict[str, Any]],
    *,
    excluded_source_item_ids: Set[str],
    already_selected_source_item_ids: Set[str],
    max_candidates: int,
) -> List[Dict[str, Any]]:
    """Allocate hydration candidates across TRAIN deficits, not merely routes.

    REV10 originally round-robined by route. With many vendor/reference-specific
    deficits under one route, the first few high-scoring files for that route
    could consume the entire hydration slice while other deficits on the same
    route received no candidate at all. This selector preserves the same
    TRAIN-only deficit contract and exact human route label, but gives each
    deficit a bounded opportunity to contribute candidates before taking a
    second candidate for already-covered deficits.
    """
    limit = max(0, int(max_candidates))
    if limit <= 0 or not deficits:
        return []

    excluded = {str(value) for value in excluded_source_item_ids}
    already = {str(value) for value in already_selected_source_item_ids}
    target_routes = {
        normalize_route_path(row.get("route_path"))
        for row in deficits
        if normalize_route_path(row.get("route_path"))
    }

    by_route: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for source in labels:
        row = dict(source)
        item_id = str(row.get("item_id") or "")
        route = normalize_route_path(row.get("route_path"))
        if (
            not item_id
            or item_id in excluded
            or item_id in already
            or route not in target_routes
        ):
            continue
        by_route[route].append(row)

    per_deficit_cap = max(
        2,
        min(
            12,
            int(math.ceil(limit / max(1, len(deficits)))) + 2,
        ),
    )
    buckets: List[List[Dict[str, Any]]] = []
    for deficit_index, deficit in enumerate(deficits):
        route = normalize_route_path(deficit.get("route_path"))
        ranked: List[Dict[str, Any]] = []
        for source in by_route.get(route, []):
            score = _candidate_prefilter_score_for_deficit(source, deficit)
            if score < 0:
                continue
            row = dict(source)
            row["_business_context_prefilter_score"] = score
            row["_business_context_prefilter_deficit_index"] = deficit_index
            row["_business_context_prefilter_deficit_kind"] = str(
                deficit.get("kind") or ""
            )
            ranked.append(row)
        # Prefer candidates whose filename already exhibits the deficit's
        # requested vendor/reference/semantic/signature affinity. Critically,
        # apply each preference only when at least one candidate actually
        # exhibits it; otherwise fall back to the broader same-route pool so a
        # sparse/opaque filename cannot starve the deficit completely.
        affinities = [
            (row, _candidate_prefilter_affinity_for_deficit(row, deficit))
            for row in ranked
        ]
        for requested_key, match_key in (
            ("vendor_requested", "vendor_match"),
            ("reference_requested", "reference_match"),
            ("semantics_requested", "semantics_match"),
            ("signature_requested", "signature_match"),
        ):
            if affinities and any(meta.get(requested_key) for _, meta in affinities):
                matched = [(row, meta) for row, meta in affinities if meta.get(match_key)]
                if matched:
                    affinities = matched
        ranked = [row for row, _ in affinities]
        ranked.sort(
            key=lambda row: (
                int(row.get("_business_context_prefilter_score") or 0),
                str(row.get("modified_at") or ""),
                str(row.get("file_name") or ""),
                str(row.get("item_id") or ""),
            ),
            reverse=True,
        )
        buckets.append(ranked[:per_deficit_cap])

    selected: List[Dict[str, Any]] = []
    selected_ids: Set[str] = set()
    indices = [0 for _ in buckets]
    while len(selected) < limit:
        progressed = False
        for bucket_index, rows in enumerate(buckets):
            while indices[bucket_index] < len(rows):
                row = rows[indices[bucket_index]]
                indices[bucket_index] += 1
                item_id = str(row.get("item_id") or "")
                if not item_id or item_id in selected_ids:
                    continue
                selected.append(row)
                selected_ids.add(item_id)
                progressed = True
                break
            if len(selected) >= limit:
                break
        if not progressed:
            break
    return selected
'''
    raw = replace_once(
        raw,
        old_selector,
        new_selector,
        "REV10 deficit-aware hydration prefilter",
    )

    old_candidate_limit = '''    candidate_limit = min(len(labels), max(0, int(max_additional)) * 4)
'''
    new_candidate_limit = '''    # REV11 evidence-discovery pass: hydrate a modestly broader, deficit-aware
    # candidate slice. This does not increase the number of TRAIN examples that
    # may be admitted (max_additional is unchanged); it only reduces false
    # negatives in pre-hydration discovery.
    candidate_limit = min(len(labels), max(0, int(max_additional)) * 6)
'''
    raw = replace_once(
        raw,
        old_candidate_limit,
        new_candidate_limit,
        "REV11 evidence-discovery candidate breadth",
    )

    require(
        "same_vendor_document_type_route_support" in raw,
        "REV10 same-vendor route-support deficits missing",
    )
    require(
        "_candidate_prefilter_affinity_for_deficit" in raw
        and "apply each preference only when at least one candidate actually" in raw,
        "REV11 deficit-affinity prefilter missing",
    )
    require(
        "rev10_generic_deficit_allowed" in raw
        and "_REV8_DISCRIMINATING_SEMANTICS" in raw,
        "REV10 generic evidence must defer to REV8 discriminating semantics",
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
