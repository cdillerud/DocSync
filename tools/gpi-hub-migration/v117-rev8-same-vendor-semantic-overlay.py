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

    core_anchor = "    core_limit = max(1, min(limit, int(round(limit * 0.75))))\n"
    ranked_loop_anchor = "    for row in ranked:\n        add(row)\n        if len(selected) >= core_limit:\n            break\n"
    contrast_anchor = (
        "    # Add at most two strongest same-vendor route contrasts. This teaches the\n"
        "    # decision boundary without letting deliberately contradictory examples\n"
        "    # dominate the prompt.\n"
        "    same_vendor_rows = [row for row in ranked if row.get(\"_learned_same_vendor\")]\n"
        "    selected_routes = {normalize_route_path(row.get(\"route_path\")) for row in selected}\n"
    )

    require(core_anchor in raw, "same-vendor core-limit anchor missing")
    require(ranked_loop_anchor in raw, "same-vendor ranked-loop anchor missing")
    require(contrast_anchor in raw, "same-vendor contrast anchor missing")

    same_vendor_block = (
        core_anchor
        + "    same_vendor_rows = [row for row in ranked if row.get(\"_learned_same_vendor\")]\n"
        + "    same_vendor_core_target = min(core_limit, len(same_vendor_rows))\n"
        + "    for row in same_vendor_rows:\n"
        + "        add(row)\n"
        + "        if len(selected) >= same_vendor_core_target:\n"
        + "            break\n"
        + ranked_loop_anchor
    )
    raw = raw.replace(core_anchor + ranked_loop_anchor, same_vendor_block, 1)

    contrast_replacement = (
        "    # Add at most two strongest same-vendor route contrasts. This teaches the\n"
        "    # decision boundary without letting deliberately contradictory examples\n"
        "    # dominate the prompt.\n"
        "    selected_routes = {normalize_route_path(row.get(\"route_path\")) for row in selected}\n"
    )
    raw = raw.replace(contrast_anchor, contrast_replacement, 1)

    require(raw.count("same_vendor_core_target = min(core_limit, len(same_vendor_rows))") == 1,
            "same-vendor prompt core was not patched exactly once")
    require(raw.count('same_vendor_rows = [row for row in ranked if row.get("_learned_same_vendor")]') == 1,
            "same-vendor row set should exist exactly once after patch")

    compile(raw, str(path), "exec")
    path.write_text(raw, encoding="utf-8", newline="\n")


def patch_ai_prompt(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")
    old = '''        "20. A plain numeric BC/order reference is not a warehouse-versus-dropship discriminator. Determine that family "
        "from current document role, explicit structural references, and comparable human workflow evidence instead.\\n\\n"
'''
    new = '''        "20. A plain numeric BC/order reference is not a warehouse-versus-dropship discriminator. Determine that family "
        "from current document role, explicit structural references, and comparable human workflow evidence instead.\\n"
        "21. When same-vendor HUMAN TRAIN examples exist, treat them as the primary workflow evidence for the current vendor. "
        "Cross-vendor examples may teach route-neutral semantics and contrasts, but they must not override a different "
        "same-vendor workflow merely because they contain a visually similar reference or filename token.\\n"
        "22. An exact business, order, shipment, or BC reference observed only in another vendor's TRAIN examples is not "
        "routing authority for the current vendor. Do not rely on a foreign-vendor exact-reference example to justify the "
        "route unless independent same-vendor HUMAN TRAIN evidence supports that route; otherwise lower confidence and "
        "report the ambiguity in unresolved.\\n\\n"
'''
    raw = replace_once(raw, old, new, "REV8 prompt rules")
    compile(raw, str(path), "exec")
    path.write_text(raw, encoding="utf-8", newline="\n")


def patch_business_context_expansion(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")

    old_weights = '''_KIND_WEIGHT = {
    "same_vendor_document_type_business_context": 6,
    "cross_vendor_document_type_business_context": 4,
}
'''
    new_weights = '''_KIND_WEIGHT = {
    "discriminating_semantic_route_support": 8,
    "same_vendor_document_type_business_context": 6,
    "cross_vendor_document_type_business_context": 4,
}

# REV8 mirrors the existing learned-autonomy discriminating semantic set and
# minimum support without changing either authority threshold. Deficits are
# derived only from HUMAN TRAIN rows that already exhibit the semantic feature.
_REV8_DISCRIMINATING_SEMANTICS = frozenset(
    {
        "detention",
        "dunnage",
        "inventory",
        "reconciliation",
        "cost_variance",
        "quality_or_claim",
        "storage_accessorial",
    }
)
_REV8_MINIMUM_DISCRIMINATING_SEMANTIC_SUPPORT = 2
'''
    raw = replace_once(raw, old_weights, new_weights, "semantic deficit constants")

    old_insert = '''    unique: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for deficit in deficits:
'''
    new_insert = '''    # REV8: fill sparse route-matching semantic support using HUMAN TRAIN
    # evidence only. A deficit exists only for a semantic+route pair already
    # observed in TRAIN. Candidate admission still requires the candidate's
    # independent human Accounting placement to equal that exact route, so this
    # cannot infer a route from semantics and cannot use HOLDOUT identity/labels.
    for feature in sorted(_REV8_DISCRIMINATING_SEMANTICS):
        rows_by_route: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in eligible:
            if feature not in semantic_features(row):
                continue
            route = _route(row)
            if not route or route == DNP or route in manual_only:
                continue
            rows_by_route[route].append(row)
        for route, rows in sorted(rows_by_route.items()):
            support = len(rows)
            if support >= _REV8_MINIMUM_DISCRIMINATING_SEMANTIC_SUPPORT:
                continue
            deficits.append(
                {
                    "kind": "discriminating_semantic_route_support",
                    "route_path": route,
                    "vendor": "",
                    "document_type": "",
                    "business_signature": [],
                    "business_signal_families": [],
                    "required_semantics": [feature],
                    "support_count": support,
                    "contradiction_count": 0,
                    "matched_human_count": support,
                    "minimum_support": _REV8_MINIMUM_DISCRIMINATING_SEMANTIC_SUPPORT,
                    "minimum_purity": 1.0,
                    "additional_support_needed": (
                        _REV8_MINIMUM_DISCRIMINATING_SEMANTIC_SUPPORT - support
                    ),
                }
            )

    unique: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for deficit in deficits:
'''
    raw = replace_once(raw, old_insert, new_insert, "semantic deficit builder")

    old_key = '''            tuple(deficit["business_signature"]),
        )
'''
    new_key = '''            tuple(deficit["business_signature"]),
            tuple(deficit.get("required_semantics") or []),
        )
'''
    raw = replace_once(raw, old_key, new_key, "semantic deficit uniqueness")

    old_sort = '''            tuple(row["business_signature"]),
        )
'''
    new_sort = '''            tuple(row["business_signature"]),
            tuple(row.get("required_semantics") or []),
        )
'''
    raw = replace_once(raw, old_sort, new_sort, "semantic deficit sort")

    old_prefilter = '''    pseudo = {"file_name": str(label.get("file_name") or "")}
    pseudo_signature = authority_business_signature(pseudo)
    lower = str(label.get("file_name") or "").lower()
    score = 0
'''
    new_prefilter = '''    pseudo = {"file_name": str(label.get("file_name") or "")}
    pseudo_signature = authority_business_signature(pseudo)
    pseudo_semantics = semantic_features(pseudo)
    lower = str(label.get("file_name") or "").lower()
    score = 0
'''
    raw = replace_once(raw, old_prefilter, new_prefilter, "semantic candidate prefilter setup")

    old_local = '''        signature = set(deficit.get("business_signature") or [])
        overlap = signature.intersection(pseudo_signature)
        local += min(8, 3 * len(overlap))
        score = max(score, local)
'''
    new_local = '''        signature = set(deficit.get("business_signature") or [])
        overlap = signature.intersection(pseudo_signature)
        local += min(8, 3 * len(overlap))
        required_semantics = set(deficit.get("required_semantics") or [])
        if required_semantics and required_semantics.issubset(pseudo_semantics):
            local += 8
        score = max(score, local)
'''
    raw = replace_once(raw, old_local, new_local, "semantic candidate prefilter scoring")

    compile(raw, str(path), "exec")
    path.write_text(raw, encoding="utf-8", newline="\n")


def apply(root: str) -> None:
    base = Path(root)
    relevant = base / "backend/services/ap_routing_relevant_learning_service.py"
    ai_prompt = base / "backend/services/ap_routing_ai_primary_service.py"
    expansion = base / "backend/services/ap_routing_business_context_expansion_service.py"

    for required in (relevant, ai_prompt, expansion):
        require(required.is_file(), f"missing REV8 patch target: {required}")

    patch_relevant_learning(relevant)
    patch_ai_prompt(ai_prompt)
    patch_business_context_expansion(expansion)

    print("V117_REV8_SAME_VENDOR_PROMPT_ISOLATION=PASS")
    print("V117_REV8_FOREIGN_REFERENCE_PROMPT_GUARD=PASS")
    print("V117_REV8_TRAIN_SEMANTIC_DEFICIT_EXPANSION=PASS")
    print("V117_REV8_AUTHORITY_THRESHOLDS=UNCHANGED")
    print("V117_REV8_DETERMINISTIC_ROUTE_SUBSTITUTION=NONE")


if __name__ == "__main__":
    import sys

    require(len(sys.argv) == 2, "usage: overlay.py <candidate-root>")
    apply(sys.argv[1])
