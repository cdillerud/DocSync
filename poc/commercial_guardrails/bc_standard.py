from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, List, Mapping, Sequence

from .bc_adapter import BusinessCentralClient
from .proposal_guard import HistoricalLine, _parse_date


def _odata_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _combine(parts: Iterable[str]) -> str:
    usable = [part for part in parts if part]
    return " and ".join(f"({part})" for part in usable)


def build_standard_invoice_filter(
    start_date: str = "",
    end_date: str = "",
    customer_no: str = "",
) -> str:
    parts: List[str] = []
    if start_date:
        parts.append(f"postingDate ge {start_date}")
    if end_date:
        parts.append(f"postingDate le {end_date}")
    if customer_no:
        parts.append(f"customerNumber eq {_odata_literal(customer_no)}")
    return _combine(parts)


def historical_lines_from_standard_invoices(
    invoices: Sequence[Mapping[str, object]],
    item_nos: Sequence[str] = (),
) -> List[HistoricalLine]:
    allowed = {item.strip() for item in item_nos if item.strip()}
    history: List[HistoricalLine] = []

    for invoice in invoices:
        posting_date = _parse_date(str(invoice.get("postingDate") or ""))
        invoice_no = str(invoice.get("number") or "").strip()
        order_no = str(invoice.get("orderNumber") or "").strip()
        customer_no = str(invoice.get("customerNumber") or "").strip()
        customer_name = str(invoice.get("customerName") or customer_no).strip()

        raw_lines = invoice.get("salesInvoiceLines") or []
        if not isinstance(raw_lines, list):
            continue

        for line in raw_lines:
            if not isinstance(line, Mapping):
                continue
            if str(line.get("lineType") or "").strip().casefold() != "item":
                continue

            item_no = str(line.get("lineObjectNumber") or "").strip()
            if not item_no:
                continue
            if allowed and item_no not in allowed:
                continue

            quantity = float(line.get("quantity") or 0.0)
            unit_price = float(line.get("unitPrice") or 0.0)
            net_amount = float(line.get("amountExcludingTax") or 0.0)

            history.append(
                HistoricalLine(
                    posting_date=posting_date,
                    invoice_no=invoice_no,
                    order_no=order_no,
                    customer_no=customer_no,
                    customer_name=customer_name,
                    item_no=item_no,
                    description=str(line.get("description") or "").strip(),
                    uom=str(line.get("unitOfMeasureCode") or "").strip(),
                    quantity=quantity,
                    unit_price=unit_price,
                    net_amount=net_amount,
                )
            )
    return history


def fetch_standard_customer_family_history(
    client: BusinessCentralClient,
    customer_no: str,
    item_nos: Sequence[str],
    start_date: str = "",
    end_date: str = "",
) -> List[HistoricalLine]:
    company_id = client.resolve_company_id()
    url = f"{client.environment_root}/api/v2.0/companies({company_id})/salesInvoices"
    params = {
        "$select": "id,number,postingDate,customerNumber,customerName,orderNumber",
        "$expand": "salesInvoiceLines",
    }
    invoice_filter = build_standard_invoice_filter(start_date, end_date, customer_no)
    if invoice_filter:
        params["$filter"] = invoice_filter

    invoices = client._get_all(url, params)
    return historical_lines_from_standard_invoices(invoices, item_nos)


def write_family_history_csv(history: Sequence[HistoricalLine], path: str | Path) -> None:
    fieldnames = [
        "posting_date",
        "invoice_no",
        "order_no",
        "customer_no",
        "customer_name",
        "item_no",
        "description",
        "uom",
        "quantity",
        "unit_price",
        "net_amount",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for line in history:
            writer.writerow(
                {
                    "posting_date": line.posting_date.strftime("%Y-%m-%d"),
                    "invoice_no": line.invoice_no,
                    "order_no": line.order_no,
                    "customer_no": line.customer_no,
                    "customer_name": line.customer_name,
                    "item_no": line.item_no,
                    "description": line.description,
                    "uom": line.uom,
                    "quantity": line.quantity,
                    "unit_price": line.unit_price,
                    "net_amount": line.net_amount,
                }
            )
