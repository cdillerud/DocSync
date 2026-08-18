from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Mapping, Sequence

from .bc_adapter import BusinessCentralClient, BusinessCentralError


@dataclass(frozen=True)
class ItemCandidate:
    item_no: str
    description: str
    score: float
    reasons: tuple[str, ...]
    blocked: bool = False
    base_uom: str = ""


_MATERIALS = {
    "pet": ("pet",),
    "glass": ("glass", "flint"),
    "hdpe": ("hdpe",),
    "pp": ("pp",),
    "aluminum": ("aluminum", "aluminium"),
}

_FORMS = {
    "bottle": ("bottle",),
    "can": ("can",),
    "cap": ("cap", "closure"),
    "jar": ("jar",),
}

_FILL = {
    "hot fill": ("hot fill", "hotfill"),
    "cold fill": ("cold fill", "coldfill"),
}

_PACK = {
    "bag packed": ("bag packed", "bag pack"),
    "tray packed": ("tray packed", "tray pack"),
    "bulk": ("bulk",),
    "6pk": ("6pk", "6 pack", "6-pack"),
    "12pk": ("12pk", "12 pack", "12-pack"),
}

_COLOR = {
    "clear": ("clear",),
    "flint": ("flint",),
    "natural": ("natural",),
    "white": ("white",),
}


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _contains_any(text: str, variants: Iterable[str]) -> bool:
    return any(variant in text for variant in variants)


def _first_label(text: str, mapping: Mapping[str, Sequence[str]]) -> str:
    for label, variants in mapping.items():
        if _contains_any(text, variants):
            return label
    return ""


def _size_oz(text: str) -> str:
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:oz|ounce|ounces)\b", text)
    return match.group(1) if match else ""


def _finish(text: str) -> str:
    match = re.search(r"\b(\d{2,3})\s*[-/]\s*(\d{3,4})\b", text)
    return f"{match.group(1)}-{match.group(2)}" if match else ""


def _weight_g(text: str) -> str:
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*g\b", text)
    return match.group(1) if match else ""


def _ring_neck(text: str) -> bool:
    return bool(re.search(r"\bring\s*[- ]?\s*neck\b", text))


def _features(description: str) -> dict:
    text = _text(description)
    return {
        "size_oz": _size_oz(text),
        "finish": _finish(text),
        "material": _first_label(text, _MATERIALS),
        "form": _first_label(text, _FORMS),
        "fill": _first_label(text, _FILL),
        "pack": _first_label(text, _PACK),
        "color": _first_label(text, _COLOR),
        "weight_g": _weight_g(text),
        "ring_neck": _ring_neck(text),
    }


def score_related_item(proposed_description: str, candidate_description: str) -> tuple[float, tuple[str, ...]]:
    proposed = _features(proposed_description)
    candidate = _features(candidate_description)
    score = 0.0
    reasons: List[str] = []

    # These are identity-level packaging attributes. A contradiction should prevent
    # a candidate from being treated as a close commercial substitute.
    if proposed["size_oz"] and candidate["size_oz"]:
        if proposed["size_oz"] != candidate["size_oz"]:
            return 0.0, ("different ounce size",)
        score += 24
        reasons.append(f"{proposed['size_oz']}oz")

    if proposed["form"] and candidate["form"]:
        if proposed["form"] != candidate["form"]:
            return 0.0, ("different container form",)
        score += 18
        reasons.append(proposed["form"])

    if proposed["material"] and candidate["material"]:
        if proposed["material"] != candidate["material"]:
            return 0.0, ("different material",)
        score += 18
        reasons.append(proposed["material"].upper())

    if proposed["finish"] and candidate["finish"]:
        if proposed["finish"] == candidate["finish"]:
            score += 20
            reasons.append(proposed["finish"])
        else:
            score -= 8

    if proposed["ring_neck"] and candidate["ring_neck"]:
        score += 14
        reasons.append("ring neck")
    elif proposed["ring_neck"] != candidate["ring_neck"]:
        score -= 12

    if proposed["fill"] and candidate["fill"]:
        if proposed["fill"] == candidate["fill"]:
            score += 8
            reasons.append(proposed["fill"])
        else:
            # Hot-fill versus cold-fill is intentionally still considered related.
            # It is exactly the kind of similar-looking but commercially important
            # distinction the guardrail should surface.
            score += 3
            reasons.append(f"{candidate['fill']} vs {proposed['fill']}")

    if proposed["color"] and candidate["color"] and proposed["color"] == candidate["color"]:
        score += 4
        reasons.append(proposed["color"])

    if proposed["pack"] and candidate["pack"]:
        if proposed["pack"] == candidate["pack"]:
            score += 4
            reasons.append(proposed["pack"])
        else:
            score += 1
            reasons.append(f"{candidate['pack']} vs {proposed['pack']}")

    if proposed["weight_g"] and candidate["weight_g"]:
        if proposed["weight_g"] == candidate["weight_g"]:
            score += 4
            reasons.append(f"{proposed['weight_g']}g")
        else:
            score += 1
            reasons.append(f"{candidate['weight_g']}g vs {proposed['weight_g']}g")

    return max(0.0, score), tuple(reasons)


def rank_related_items(
    proposed_item_no: str,
    proposed_description: str,
    items: Sequence[Mapping[str, object]],
    min_score: float = 55.0,
    max_results: int = 12,
    include_blocked: bool = False,
) -> List[ItemCandidate]:
    ranked: List[ItemCandidate] = []

    for row in items:
        item_no = str(row.get("number") or "").strip()
        if not item_no or item_no == proposed_item_no:
            continue

        blocked = bool(row.get("blocked"))
        if blocked and not include_blocked:
            continue

        description = str(row.get("displayName") or "").strip()
        if not description:
            continue

        score, reasons = score_related_item(proposed_description, description)
        if score < min_score:
            continue

        ranked.append(
            ItemCandidate(
                item_no=item_no,
                description=description,
                score=score,
                reasons=reasons,
                blocked=blocked,
                base_uom=str(row.get("baseUnitOfMeasureCode") or "").strip(),
            )
        )

    ranked.sort(key=lambda item: (-item.score, item.item_no))
    return ranked[:max(1, max_results)]


def fetch_item_master(client: BusinessCentralClient) -> List[dict]:
    company_id = client.resolve_company_id()
    url = f"{client.environment_root}/api/v2.0/companies({company_id})/items"
    return client._get_all(
        url,
        {
            "$select": "number,displayName,baseUnitOfMeasureCode,unitCost,blocked",
        },
    )


def discover_related_items(
    client: BusinessCentralClient,
    proposed_item_no: str,
    min_score: float = 55.0,
    max_results: int = 12,
    include_blocked: bool = False,
) -> tuple[dict, List[ItemCandidate]]:
    items = fetch_item_master(client)
    proposed = next(
        (row for row in items if str(row.get("number") or "").strip() == proposed_item_no),
        None,
    )
    if proposed is None:
        raise BusinessCentralError(f"BC item {proposed_item_no!r} was not found in the item master.")

    description = str(proposed.get("displayName") or "").strip()
    candidates = rank_related_items(
        proposed_item_no=proposed_item_no,
        proposed_description=description,
        items=items,
        min_score=min_score,
        max_results=max_results,
        include_blocked=include_blocked,
    )
    return dict(proposed), candidates
