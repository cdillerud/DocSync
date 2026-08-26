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
            "rows": [],
        }

    first = rows[0]
    return {
        "itemNo": item_no,
        "found": True,
        "description": first.get("description"),
        "baseUnitOfMeasure": first.get("baseUnitOfMeasure"),
        "unitCost": first.get("unitCost"),
        "vendorNo": first.get("vendorNo"),
        "vendorItemNo": first.get("vendorItemNo"),
        "blocked": first.get("blocked"),
        "uoms": [
            {
                "code": row.get("uomCode"),
                "qtyPerUnitOfMeasure": row.get("qtyPerUnitOfMeasure"),
            }
            for row in rows
            if row.get("uomCode")
        ],
        "rows": rows,
    }


def cost_change_context(
    item_no: str,
    *,
    top: int = 500,
) -> dict[str, Any]:
    item_no = item_no.strip()
    top = min(max(top, 1), 1000)
    filter_text = f"itemNo eq '{_odata_literal(item_no)}'"
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

    customers: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "lineCount": 0,
            "quantityBase": Decimal("0"),
            "sales": Decimal("0"),
            "latestPostingDate": None,
            "salespersonCodes": set(),
        }
    )

    for row in rows:
        customer_no = str(row.get("customerNo") or "").strip()
        if not customer_no:
            continue

        customer = customers[customer_no]
        customer["lineCount"] += 1
        customer["quantityBase"] += _decimal(row.get("quantityBase"))
        customer["sales"] += _decimal(row.get("lineAmount"))

        posting_date = str(row.get("postingDate") or "").strip()
        if posting_date and (
            customer["latestPostingDate"] is None
            or posting_date > customer["latestPostingDate"]
        ):
            customer["latestPostingDate"] = posting_date

        salesperson_code = str(
            row.get("salespersonCode") or ""
        ).strip()
        if salesperson_code:
            customer["salespersonCodes"].add(salesperson_code)

    exposure = []
    for customer_no, values in customers.items():
        exposure.append(
            {
                "customerNo": customer_no,
                "lineCount": values["lineCount"],
                "quantityBase": float(values["quantityBase"]),
                "sales": float(values["sales"]),
                "latestPostingDate": values["latestPostingDate"],
                "salespersonCodes": sorted(values["salespersonCodes"]),
            }
        )

    exposure.sort(
        key=lambda row: (row["sales"], row["lineCount"]),
        reverse=True,
    )

    return {
        "item": item_cost_context(item_no),
        "historicalLineCount": len(rows),
        "customerCount": len(exposure),
        "customerExposure": exposure,
        "historicalRows": rows,
    }


def incorrect_item_context(
    customer_no: str,
    item_no: str,
    *,
    top: int = 500,
) -> dict[str, Any]:
    all_history = customer_item_history(
        customer_no,
        top=top,
    )
    candidate_history = customer_item_history(
        customer_no,
        item_no,
        top=top,
    )

    candidate_line_count = candidate_history["lineCount"]
    return {
        "customerNo": customer_no.strip(),
        "candidateItemNo": item_no.strip(),
        "candidatePurchasedBefore": candidate_line_count > 0,
        "candidateHistoricalLineCount": candidate_line_count,
        "candidateItem": item_cost_context(item_no),
        "customerHistorySummary": {
            key: value
            for key, value in all_history.items()
            if key != "rows"
        },
        "candidateHistorySummary": {
            key: value
            for key, value in candidate_history.items()
            if key != "rows"
        },
        "mostCommonItems": all_history["mostCommonItems"],
    }
