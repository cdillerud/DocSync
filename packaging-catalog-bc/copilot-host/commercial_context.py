from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

from bc_client import BusinessCentralClient, BusinessCentralSettings


COMMERCIAL_GUARDRAILS_GROUP = "commercialGuardrails"


def _odata_literal(value: str) -> str:
    return value.replace("'", "''")


def _encode_filter(filter_text: str) -> str:
    return quote(filter_text, safe="()$=,' ")


def _decimal(value: Any) -> Decimal:
    try:
        if value in (None, ""):
            return Decimal("0")
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("value", [])
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _client() -> BusinessCentralClient:
    return BusinessCentralClient(
        BusinessCentralSettings.from_environment()
    )


def customer_item_history(
    customer_no: str,
    item_no: str | None = None,
    *,
    top: int = 250,
) -> dict[str, Any]:
    customer_no = customer_no.strip()
    item_no = item_no.strip() if item_no else None
    top = min(max(top, 1), 1000)

    filters = [
        f"customerNo eq '{_odata_literal(customer_no)}'"
    ]
    if item_no:
        filters.append(
            f"itemNo eq '{_odata_literal(item_no)}'"
        )

    filter_text = " and ".join(filters)
    query = (
        "historicalSalesLines?"
        f"$filter={_encode_filter(filter_text)}"
        f"&$top={top}"
    )

    rows = _rows(
        _client().get_api_json(
            COMMERCIAL_GUARDRAILS_GROUP,
            query,
        )
    )

    item_counts: Counter[str] = Counter()
    invoice_nos: set[str] = set()
    order_nos: set[str] = set()
    total_quantity = Decimal("0")
    total_sales = Decimal("0")
    posting_dates: list[str] = []

    for row in rows:
        row_item = str(row.get("itemNo") or "").strip()
        if row_item:
            item_counts[row_item] += 1

        invoice_no = str(row.get("invoiceNo") or "").strip()
        if invoice_no:
            invoice_nos.add(invoice_no)

        order_no = str(row.get("orderNo") or "").strip()
        if order_no:
            order_nos.add(order_no)

        total_quantity += _decimal(row.get("quantityBase"))
        total_sales += _decimal(row.get("lineAmount"))

        posting_date = str(row.get("postingDate") or "").strip()
        if posting_date:
            posting_dates.append(posting_date)

    most_common = [
        {"itemNo": key, "lineCount": count}
        for key, count in item_counts.most_common(25)
    ]

    return {
        "customerNo": customer_no,
        "itemNo": item_no,
        "lineCount": len(rows),
        "invoiceCount": len(invoice_nos),
        "orderCount": len(order_nos),
        "distinctItemCount": len(item_counts),
        "totalQuantityBase": float(total_quantity),
        "totalSales": float(total_sales),
        "mostCommonItems": most_common,
        "latestPostingDate": max(posting_dates) if posting_dates else None,
        "earliestPostingDate": min(posting_dates) if posting_dates else None,
        "rows": rows,
    }


def item_cost_context(item_no: str) -> dict[str, Any]:
    item_no = item_no.strip()
    filter_text = f"itemNo eq '{_odata_literal(item_no)}'"
    query = (
        "itemCostContexts?"
        f"$filter={_encode_filter(filter_text)}"
        "&$top=100"
    )

    rows = _rows(
        _client().get_api_json(
            COMMERCIAL_GUARDRAILS_GROUP,
            query,
        )
    )

    if not rows:
        return {
            "itemNo": item_no,
            "found": False,
        }

    current = rows[0]
    current["found"] = True
    return current


def packaging_product_context(item_no: str) -> dict[str, Any]:
    item_no = item_no.strip()
    filter_text = f"bcItemNo eq '{_odata_literal(item_no)}'"
    query = (
        "commercialProducts?"
        f"$filter={_encode_filter(filter_text)}"
        "&$top=25"
    )

    rows = _rows(
        _client().get_api_json(
            "commercialAgents",
            query,
        )
    )

    return {
        "itemNo": item_no,
        "matches": rows,
        "matchCount": len(rows),
    }


def customer_purchase_profile(
    customer_no: str,
    *,
    top: int = 500,
) -> dict[str, Any]:
    history = customer_item_history(
        customer_no,
        top=top,
    )
    return {
        "customerNo": customer_no,
        "lineCount": history["lineCount"],
        "invoiceCount": history["invoiceCount"],
        "orderCount": history["orderCount"],
        "distinctItemCount": history["distinctItemCount"],
        "latestPostingDate": history["latestPostingDate"],
        "earliestPostingDate": history["earliestPostingDate"],
        "mostCommonItems": history["mostCommonItems"],
    }


def commercial_context(
    customer_no: str,
    item_no: str,
) -> dict[str, Any]:
    return {
        "customerHistory": customer_item_history(
            customer_no,
            item_no,
        ),
        "customerProfile": customer_purchase_profile(
            customer_no,
        ),
        "itemCost": item_cost_context(item_no),
        "packagingProduct": packaging_product_context(item_no),
    }


def _similarity_fields(product: dict[str, Any]) -> dict[str, str]:
    return {
        "material": str(product.get("material") or "").strip().lower(),
        "style": str(product.get("style") or "").strip().lower(),
        "shape": str(product.get("shape") or "").strip().lower(),
        "capacity": str(product.get("capacity") or "").strip().lower(),
        "finish": str(product.get("finish") or "").strip().lower(),
        "color": str(product.get("color") or "").strip().lower(),
    }


def product_similarity(
    candidate: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any]:
    candidate_fields = _similarity_fields(candidate)
    reference_fields = _similarity_fields(reference)

    compared = 0
    matched = 0
    details: dict[str, dict[str, Any]] = {}

    for field, candidate_value in candidate_fields.items():
        reference_value = reference_fields[field]
        if not candidate_value or not reference_value:
            continue
        compared += 1
        is_match = candidate_value == reference_value
        if is_match:
            matched += 1
        details[field] = {
            "candidate": candidate_value,
            "reference": reference_value,
            "match": is_match,
        }

    score = 0.0 if compared == 0 else round((matched / compared) * 100, 2)
    return {
        "scorePct": score,
        "comparedFields": compared,
        "matchedFields": matched,
        "details": details,
    }


def customer_similarity_candidates(
    customer_no: str,
    item_no: str,
) -> dict[str, Any]:
    profile = customer_purchase_profile(customer_no, top=1000)
    candidate_product = packaging_product_context(item_no)
    candidate_matches = candidate_product["matches"]
    candidate = candidate_matches[0] if candidate_matches else {}

    scored: list[dict[str, Any]] = []
    for common in profile["mostCommonItems"]:
        historical_item = str(common.get("itemNo") or "").strip()
        if not historical_item or historical_item == item_no:
            continue
        reference_product = packaging_product_context(historical_item)
        reference_matches = reference_product["matches"]
        if not candidate or not reference_matches:
            continue
        similarity = product_similarity(candidate, reference_matches[0])
        scored.append(
            {
                "itemNo": historical_item,
                "historicalLineCount": common.get("lineCount", 0),
                **similarity,
            }
        )

    scored.sort(
        key=lambda row: (
            float(row.get("scorePct") or 0),
            int(row.get("historicalLineCount") or 0),
        ),
        reverse=True,
    )

    return {
        "customerNo": customer_no,
        "candidateItemNo": item_no,
        "customerProfile": profile,
        "candidateProduct": candidate,
        "similarItems": scored[:10],
    }


def incorrect_item_context(
    customer_no: str,
    item_no: str,
) -> dict[str, Any]:
    all_history = customer_item_history(
        customer_no,
        top=1000,
    )
    exact_history = customer_item_history(
        customer_no,
        item_no,
        top=250,
    )
    similarity = customer_similarity_candidates(
        customer_no,
        item_no,
    )

    prior_purchase_count = exact_history["lineCount"]
    historical_line_count = all_history["lineCount"]

    return {
        "customerNo": customer_no,
        "itemNo": item_no,
        "priorPurchaseLineCount": prior_purchase_count,
        "historicalLineCount": historical_line_count,
        "hasPriorPurchase": prior_purchase_count > 0,
        "latestPriorPurchaseDate": exact_history["latestPostingDate"],
        "customerProfile": {
            "invoiceCount": all_history["invoiceCount"],
            "orderCount": all_history["orderCount"],
            "distinctItemCount": all_history["distinctItemCount"],
            "latestPostingDate": all_history["latestPostingDate"],
            "mostCommonItems": all_history["mostCommonItems"],
        },
        "similarity": similarity,
    }


def historical_margin_context(
    customer_no: str,
    item_no: str,
) -> dict[str, Any]:
    history = customer_item_history(
        customer_no,
        item_no,
        top=500,
    )
    weighted_sales = Decimal("0")
    weighted_cost = Decimal("0")
    margin_points: list[Decimal] = []

    for row in history["rows"]:
        quantity = _decimal(row.get("quantityBase"))
        if quantity == 0:
            quantity = _decimal(row.get("quantity"))
        unit_price = _decimal(row.get("unitPrice"))
        unit_cost = _decimal(row.get("unitCostLCY"))
        sales = _decimal(row.get("lineAmount"))
        if sales == 0 and quantity != 0:
            sales = quantity * unit_price
        cost = quantity * unit_cost

        if sales != 0:
            weighted_sales += sales
            weighted_cost += cost
            margin_points.append(((sales - cost) / sales) * Decimal("100"))

    weighted_margin = None
    if weighted_sales != 0:
        weighted_margin = float(
            ((weighted_sales - weighted_cost) / weighted_sales) * Decimal("100")
        )

    average_margin = None
    if margin_points:
        average_margin = float(sum(margin_points) / Decimal(len(margin_points)))

    return {
        "customerNo": customer_no,
        "itemNo": item_no,
        "historicalLineCount": history["lineCount"],
        "historicalInvoiceCount": history["invoiceCount"],
        "latestPostingDate": history["latestPostingDate"],
        "weightedMarginPct": weighted_margin,
        "averageLineMarginPct": average_margin,
        "weightedSales": float(weighted_sales),
        "weightedCost": float(weighted_cost),
    }


def margin_context(
    customer_no: str,
    item_no: str,
    *,
    unit_price: float,
    unit_cost: float,
    quantity: float,
    line_amount: float | None = None,
) -> dict[str, Any]:
    unit_price_dec = _decimal(unit_price)
    unit_cost_dec = _decimal(unit_cost)
    quantity_dec = _decimal(quantity)
    line_sales = _decimal(line_amount)
    if line_sales == 0 and quantity_dec != 0:
        line_sales = quantity_dec * unit_price_dec
    line_cost = quantity_dec * unit_cost_dec

    current_margin = None
    if line_sales != 0:
        current_margin = float(
            ((line_sales - line_cost) / line_sales) * Decimal("100")
        )

    return {
        "customerNo": customer_no,
        "itemNo": item_no,
        "unitPrice": float(unit_price_dec),
        "unitCost": float(unit_cost_dec),
        "quantity": float(quantity_dec),
        "lineAmount": float(line_sales),
        "lineCost": float(line_cost),
        "currentMarginPct": current_margin,
        "historical": historical_margin_context(customer_no, item_no),
    }
