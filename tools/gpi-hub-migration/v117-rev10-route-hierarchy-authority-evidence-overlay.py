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

    old_neighborhood = '''def _route_balanced_neighborhood(
    ranked: Sequence[Dict[str, Any]],
    *,
    limit: int,
) -> List[Dict[str, Any]]:
    """Bound a relevance-ranked TRAIN neighborhood without route crowd-out.

    The first pass keeps the highest-ranked example for each distinct observed
    route. The second pass fills any remaining slots in the original relevance
    order. This changes prompt evidence composition only; it does not create or
    relax routing authority.
    """
    bounded_limit = max(1, int(limit))
    if len(ranked) <= bounded_limit:
        return [dict(row) for row in ranked]

    selected_indexes: List[int] = []
    selected_index_set = set()
    seen_routes = set()

    for index, row in enumerate(ranked):
        route = normalize_route_path(row.get("route_path") or row.get("final_human_route"))
        if not route or route in seen_routes:
            continue
        selected_indexes.append(index)
        selected_index_set.add(index)
        seen_routes.add(route)
        if len(selected_indexes) >= bounded_limit:
            break

    if len(selected_indexes) < bounded_limit:
        for index in range(len(ranked)):
            if index in selected_index_set:
                continue
            selected_indexes.append(index)
            selected_index_set.add(index)
            if len(selected_indexes) >= bounded_limit:
                break

    return [dict(ranked[index]) for index in selected_indexes]
'''
    new_neighborhood = '''def _route_balanced_neighborhood(
    ranked: Sequence[Dict[str, Any]],
    *,
    limit: int,
    max_per_route: int = 3,
) -> List[Dict[str, Any]]:
    """Build a relevance-first HUMAN TRAIN neighborhood with bounded route density.

    The prior implementation forced one example per distinct route before any
    route could contribute a second example. That made repeated exact-route
    evidence look artificially sparse in nearest_human_route_observations and
    route_hierarchy_nearest. Preserve relevance order instead, while capping any
    single route so one common workflow cannot crowd out nearby alternatives.
    This changes prompt evidence composition only; it does not create or relax
    routing authority.
    """
    bounded_limit = max(1, int(limit))
    route_cap = max(1, int(max_per_route))
    if not ranked:
        return []

    selected: List[Dict[str, Any]] = []
    route_counts: Counter[str] = Counter()
    deferred: List[Dict[str, Any]] = []

    for source in ranked:
        row = dict(source)
        route = normalize_route_path(row.get("route_path") or row.get("final_human_route"))
        if route and route_counts[route] >= route_cap:
            deferred.append(row)
            continue
        selected.append(row)
        if route:
            route_counts[route] += 1
        if len(selected) >= bounded_limit:
            return selected

    # If TRAIN has fewer distinct usable routes than the requested context size,
    # fill the remaining prompt-only context from the original relevance order.
    # The cap is a diversity preference, not a reason to discard available HUMAN
    # evidence when there is otherwise unused context capacity.
    for row in deferred:
        selected.append(row)
        if len(selected) >= bounded_limit:
            break
    return selected
'''
    raw = replace_once(
        raw,
        old_neighborhood,
        new_neighborhood,
        "REV11 density-aware TRAIN neighborhood",
    )

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
    require(
        "relevance-first HUMAN TRAIN neighborhood with bounded route density" in raw,
        "REV11 density-aware TRAIN neighborhood missing",
    )
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

    require(
        "same_vendor_document_type_route_support" in raw,
        "REV10 same-vendor route-support deficits missing",
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
