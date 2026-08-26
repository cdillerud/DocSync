from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

from bc_client import BusinessCentralClient, BusinessCentralSettings


COMMERCIAL_AGENTS_GROUP = "commercialAgents"

ATTRIBUTE_WEIGHTS: dict[str, Decimal] = {
    "material": Decimal("18"),
    "style": Decimal("18"),
    "capacity": Decimal("18"),
    "capacityUom": Decimal("6"),
    "finish": Decimal("10"),
    "finishType": Decimal("5"),
    "color": Decimal("7"),
    "packoutType": Decimal("6"),
    "vendorNo": Decimal("5"),
    "gramWeight": Decimal("7"),
}


def _client() -> BusinessCentralClient:
    return BusinessCentralClient(
        BusinessCentralSettings.from_environment()
    )


def _literal(value: str) -> str:
    return value.replace("'", "''")


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _exact(a: Any, b: Any) -> Decimal:
    left = _normalize(a)
    right = _normalize(b)
    if not left or not right:
        return Decimal("0")
    return Decimal("1") if left == right else Decimal("0")


def _relative_numeric(a: Any, b: Any) -> Decimal:
    left = _decimal(a)
    right = _decimal(b)
    if left is None or right is None:
        return Decimal("0")
    if left == right:
        return Decimal("1")

    denominator = max(abs(left), abs(right))
    if denominator == 0:
        return Decimal("1")

    similarity = Decimal("1") - (abs(left - right) / denominator)
    return max(Decimal("0"), similarity)


def get_product_by_item(item_no: str) -> dict[str, Any] | None:
    item_no = item_no.strip()
    filter_text = f"bcItemNo eq '{_literal(item_no)}' and blocked eq false"
    encoded = quote(filter_text, safe="()$=,' ")
    payload = _client().get_api_json(
        COMMERCIAL_AGENTS_GROUP,
        f"commercialProducts?$filter={encoded}&$top=2",
    )
    rows = payload.get("value", [])
    if not isinstance(rows, list) or not rows:
        return None
    rows = [row for row in rows if isinstance(row, dict)]
    if len(rows) != 1:
        return None
    return rows[0]


def list_products(*, top: int = 1000) -> list[dict[str, Any]]:
    top = min(max(top, 1), 1000)
    payload = _client().get_api_json(
        COMMERCIAL_AGENTS_GROUP,
        f"commercialProducts?$filter=blocked eq false&$top={top}",
    )
    rows = payload.get("value", [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def compare_products(
    reference: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    component_scores: dict[str, float] = {}
    weighted_score = Decimal("0")
    available_weight = Decimal("0")

    for attribute, weight in ATTRIBUTE_WEIGHTS.items():
        if attribute in {"capacity", "gramWeight"}:
            component = _relative_numeric(
                reference.get(attribute),
                candidate.get(attribute),
            )
        else:
            component = _exact(
                reference.get(attribute),
                candidate.get(attribute),
            )

        if reference.get(attribute) not in (None, "") and candidate.get(attribute) not in (None, ""):
            available_weight += weight
            weighted_score += component * weight

        component_scores[attribute] = float(
            (component * Decimal("100")).quantize(Decimal("0.01"))
        )

    score = Decimal("0")
    if available_weight > 0:
        score = weighted_score / available_weight * Decimal("100")

    differences = [
        attribute
        for attribute, value in component_scores.items()
        if value < 100
    ]

    return {
        "referenceProductNo": reference.get("productNo"),
        "referenceItemNo": reference.get("bcItemNo"),
        "candidateProductNo": candidate.get("productNo"),
        "candidateItemNo": candidate.get("bcItemNo"),
        "similarityScore": float(score.quantize(Decimal("0.01"))),
        "componentScores": component_scores,
        "differentAttributes": differences,
        "reference": reference,
        "candidate": candidate,
    }


def similar_items(
    reference_item_no: str,
    *,
    top_candidates: int = 20,
) -> dict[str, Any]:
    reference = get_product_by_item(reference_item_no)
    if reference is None:
        return {
            "referenceItemNo": reference_item_no.strip(),
            "catalogProductFound": False,
            "candidates": [],
        }

    comparisons = []
    for candidate in list_products():
        if candidate.get("id") == reference.get("id"):
            continue
        if not str(candidate.get("bcItemNo") or "").strip():
            continue
        comparisons.append(compare_products(reference, candidate))

    comparisons.sort(
        key=lambda row: row["similarityScore"],
        reverse=True,
    )

    return {
        "referenceItemNo": reference_item_no.strip(),
        "catalogProductFound": True,
        "referenceProduct": reference,
        "candidates": comparisons[: max(1, min(top_candidates, 100))],
    }
