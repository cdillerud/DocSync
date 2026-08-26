from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

from bc_client import BusinessCentralClient, BusinessCentralSettings


COMMERCIAL_GUARDRAILS_GROUP = "commercialGuardrails"


def _client() -> BusinessCentralClient:
    return BusinessCentralClient(
        BusinessCentralSettings.from_environment()
    )


def _decimal(value: Any) -> Decimal:
    try:
        if value in (None, ""):
            return Decimal("0")
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _margin_percent(sales: Decimal, cost: Decimal) -> Decimal | None:
    if sales == 0:
        return None
    return ((sales - cost) / sales) * Decimal("100")


def calculate_line_margin(row: dict[str, Any]) -> dict[str, Any]:
    quantity = _decimal(row.get("quantity"))
    unit_cost = _decimal(row.get("unitCostLCY"))
    sales = _decimal(row.get("lineAmount"))
    estimated_cost = quantity * unit_cost
    margin = _margin_percent(sales, estimated_cost)

    return {
        **row,
        "deterministicCostAmount": float(estimated_cost),
        "deterministicGrossProfit": float(sales - estimated_cost),
        "deterministicMarginPercent": (
            float(margin.quantize(Decimal("0.01")))
            if margin is not None
            else None
        ),
        "marginBasis": (
            "Posted Sales Invoice Line Amount less "
            "Quantity x Unit Cost (LCY)"
        ),
    }


def posted_margin_candidates(
    posting_date: date,
    *,
    hard_floor_percent: float = 20.0,
    top: int = 1000,
) -> dict[str, Any]:
    top = min(max(top, 1), 5000)
    filter_text = f"postingDate eq {posting_date.isoformat()}"
    encoded_filter = quote(filter_text, safe="()$=,' ")
    payload = _client().get_api_json(
        COMMERCIAL_GUARDRAILS_GROUP,
        (
            "historicalSalesLines?"
            f"$filter={encoded_filter}"
            f"&$orderby=invoiceNo,lineNo&$top={top}"
        ),
    )

    rows = payload.get("value", [])
    if not isinstance(rows, list):
        rows = []

    evaluated = [
        calculate_line_margin(row)
        for row in rows
        if isinstance(row, dict)
        and str(row.get("itemNo") or "").strip()
    ]

    threshold = Decimal(str(hard_floor_percent))
    candidates = [
        row
        for row in evaluated
        if row["deterministicMarginPercent"] is not None
        and Decimal(str(row["deterministicMarginPercent"])) < threshold
    ]

    invoice_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        invoice_groups[str(row.get("invoiceNo") or "")].append(row)

    return {
        "postingDate": posting_date.isoformat(),
        "hardFloorPercent": hard_floor_percent,
        "evaluatedLineCount": len(evaluated),
        "candidateLineCount": len(candidates),
        "candidateInvoiceCount": len(invoice_groups),
        "candidateInvoices": [
            {
                "invoiceNo": invoice_no,
                "customerNo": lines[0].get("customerNo") if lines else None,
                "customerName": lines[0].get("customerName") if lines else None,
                "salespersonCode": lines[0].get("salespersonCode") if lines else None,
                "candidateLineCount": len(lines),
                "lowestMarginPercent": min(
                    line["deterministicMarginPercent"]
                    for line in lines
                    if line["deterministicMarginPercent"] is not None
                ),
                "lines": lines,
            }
            for invoice_no, lines in invoice_groups.items()
            if invoice_no
        ],
    }


def historical_margin_context(
    customer_no: str,
    item_no: str,
    *,
    top: int = 250,
) -> dict[str, Any]:
    customer = customer_no.replace("'", "''")
    item = item_no.replace("'", "''")
    filter_text = (
        f"customerNo eq '{customer}' and itemNo eq '{item}'"
    )
    encoded_filter = quote(filter_text, safe="()$=,' ")
    payload = _client().get_api_json(
        COMMERCIAL_GUARDRAILS_GROUP,
        (
            "historicalSalesLines?"
            f"$filter={encoded_filter}"
            f"&$orderby=postingDate desc&$top={min(max(top, 1), 1000)}"
        ),
    )
    rows = payload.get("value", [])
    if not isinstance(rows, list):
        rows = []

    evaluated = [
        calculate_line_margin(row)
        for row in rows
        if isinstance(row, dict)
    ]
    margins = [
        Decimal(str(row["deterministicMarginPercent"]))
        for row in evaluated
        if row["deterministicMarginPercent"] is not None
    ]

    average = (
        sum(margins) / Decimal(len(margins))
        if margins
        else None
    )

    total_sales = sum(
        (_decimal(row.get("lineAmount")) for row in evaluated),
        Decimal("0"),
    )
    total_cost = sum(
        (
            _decimal(row.get("deterministicCostAmount"))
            for row in evaluated
        ),
        Decimal("0"),
    )
    weighted_margin = _margin_percent(total_sales, total_cost)

    return {
        "customerNo": customer_no,
        "itemNo": item_no,
        "lineCount": len(evaluated),
        "averageMarginPercent": (
            float(average.quantize(Decimal("0.01")))
            if average is not None
            else None
        ),
        "weightedMarginPct": (
            float(weighted_margin.quantize(Decimal("0.01")))
            if weighted_margin is not None
            else None
        ),
        "totalSalesAmount": float(total_sales),
        "totalDeterministicCostAmount": float(total_cost),
        "minimumMarginPercent": float(min(margins)) if margins else None,
        "maximumMarginPercent": float(max(margins)) if margins else None,
        "rows": evaluated,
    }


def build_margin_context(
    *,
    customer_no: str,
    item_no: str,
    current_unit_price: float,
    current_unit_cost: float,
    current_quantity: float,
    top: int = 250,
) -> dict[str, Any]:
    quantity = _decimal(current_quantity)
    unit_price = _decimal(current_unit_price)
    unit_cost = _decimal(current_unit_cost)
    current_sales = quantity * unit_price
    current_cost = quantity * unit_cost
    current_margin = _margin_percent(current_sales, current_cost)

    historical = historical_margin_context(
        customer_no,
        item_no,
        top=top,
    )

    return {
        "customerNo": customer_no,
        "itemNo": item_no,
        "current": {
            "quantity": float(quantity),
            "unitPrice": float(unit_price),
            "unitCost": float(unit_cost),
            "salesAmount": float(current_sales),
            "costAmount": float(current_cost),
            "grossProfit": float(current_sales - current_cost),
            "marginPct": (
                float(current_margin.quantize(Decimal("0.01")))
                if current_margin is not None
                else None
            ),
            "marginBasis": (
                "Current Unit Price x Quantity less "
                "Current Unit Cost x Quantity"
            ),
        },
        "historical": historical,
    }
