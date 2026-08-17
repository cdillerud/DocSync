from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Mapping, Optional, Sequence
from urllib.parse import quote

import requests

from .engine import Transaction


BC_SCOPE = "https://api.businesscentral.dynamics.com/.default"
BC_API_HOST = "https://api.businesscentral.dynamics.com"


class BusinessCentralError(RuntimeError):
    """Raised when the read-only Business Central adapter cannot complete a request."""


@dataclass(frozen=True)
class BCConfig:
    environment: str
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    access_token: str = ""
    company_id: str = ""
    company_name: str = ""
    source: str = "custom"

    @classmethod
    def from_env(cls, source: Optional[str] = None) -> "BCConfig":
        return cls(
            environment=os.getenv("BC_ENVIRONMENT", "Sandbox_NoZetadocs_UAT").strip(),
            tenant_id=os.getenv("BC_TENANT_ID", "").strip(),
            client_id=os.getenv("BC_CLIENT_ID", "").strip(),
            client_secret=os.getenv("BC_CLIENT_SECRET", "").strip(),
            access_token=os.getenv("BC_ACCESS_TOKEN", "").strip(),
            company_id=os.getenv("BC_COMPANY_ID", "").strip(),
            company_name=os.getenv("BC_COMPANY_NAME", "").strip(),
            source=(source or os.getenv("BC_GUARDRAIL_SOURCE", "custom")).strip().lower(),
        )

    def validate(self) -> None:
        if not self.environment:
            raise BusinessCentralError("BC_ENVIRONMENT is required.")
        if not self.access_token and not (self.tenant_id and self.client_id and self.client_secret):
            raise BusinessCentralError(
                "Provide BC_ACCESS_TOKEN, or BC_TENANT_ID + BC_CLIENT_ID + BC_CLIENT_SECRET."
            )
        if self.source not in {"custom", "analytics"}:
            raise BusinessCentralError("BC source must be 'custom' or 'analytics'.")


def _parse_bc_date(value: str) -> datetime:
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    raise BusinessCentralError(f"Unsupported BC posting date: {value!r}")


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _odata_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _combine_filters(parts: Iterable[str]) -> str:
    usable = [part for part in parts if part]
    return " and ".join(f"({part})" for part in usable)


def build_sales_filter(
    start_date: str = "",
    end_date: str = "",
    item_nos: Sequence[str] = (),
    customer_nos: Sequence[str] = (),
) -> str:
    parts: List[str] = []
    if start_date:
        parts.append(f"postingDate ge {start_date}")
    if end_date:
        parts.append(f"postingDate le {end_date}")
    if item_nos:
        item_filter = " or ".join(f"itemNo eq {_odata_literal(value)}" for value in item_nos)
        parts.append(item_filter)
    if customer_nos:
        cust_filter = " or ".join(f"customerNo eq {_odata_literal(value)}" for value in customer_nos)
        parts.append(cust_filter)
    return _combine_filters(parts)


def build_analytics_filter(
    start_date: str = "",
    end_date: str = "",
    item_nos: Sequence[str] = (),
    customer_nos: Sequence[str] = (),
) -> str:
    parts: List[str] = []
    if start_date:
        parts.append(f"postingDate ge {start_date}")
    if end_date:
        parts.append(f"postingDate le {end_date}")
    if item_nos:
        item_filter = " or ".join(f"no eq {_odata_literal(value)}" for value in item_nos)
        parts.append(item_filter)
    if customer_nos:
        cust_filter = " or ".join(
            f"sellToCustomerNo eq {_odata_literal(value)}" for value in customer_nos
        )
        parts.append(cust_filter)
    return _combine_filters(parts)


class BusinessCentralClient:
    """GET-only Business Central data client. The only POST is the OAuth token exchange."""

    def __init__(
        self,
        config: BCConfig,
        session: Optional[requests.Session] = None,
        timeout_seconds: int = 60,
    ) -> None:
        self.config = config
        self.config.validate()
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds
        self._token = config.access_token

    @property
    def environment_root(self) -> str:
        env = quote(self.config.environment, safe="")
        if self.config.tenant_id:
            tenant = quote(self.config.tenant_id, safe="")
            return f"{BC_API_HOST}/v2.0/{tenant}/{env}"
        return f"{BC_API_HOST}/v2.0/{env}"

    def _get_token(self) -> str:
        if self._token:
            return self._token

        token_url = (
            f"https://login.microsoftonline.com/{quote(self.config.tenant_id, safe='')}"
            "/oauth2/v2.0/token"
        )
        response = self.session.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "scope": BC_SCOPE,
            },
            timeout=self.timeout_seconds,
        )
        if not response.ok:
            raise BusinessCentralError(
                f"Microsoft Entra token request failed ({response.status_code})."
            )

        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise BusinessCentralError("Microsoft Entra token response did not include access_token.")
        self._token = token
        return token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Accept": "application/json",
        }

    def _get_json(self, url: str, params: Optional[Mapping[str, str]] = None) -> dict:
        response = self.session.get(
            url,
            headers=self._headers(),
            params=dict(params or {}),
            timeout=self.timeout_seconds,
        )
        if not response.ok:
            body = (response.text or "").replace("\n", " ")[:500]
            raise BusinessCentralError(
                f"Business Central GET failed ({response.status_code}) for {url}: {body}"
            )
        return response.json()

    def _get_all(self, url: str, params: Optional[Mapping[str, str]] = None) -> List[dict]:
        rows: List[dict] = []
        next_url: Optional[str] = url
        next_params = dict(params or {})
        while next_url:
            payload = self._get_json(next_url, next_params)
            rows.extend(payload.get("value", []))
            next_url = payload.get("@odata.nextLink")
            next_params = {}
        return rows

    def resolve_company_id(self) -> str:
        if self.config.company_id:
            return self.config.company_id

        url = f"{self.environment_root}/api/v2.0/companies"
        companies = self._get_all(url)
        if not companies:
            raise BusinessCentralError("No Business Central companies were returned.")

        requested = self.config.company_name.casefold()
        if requested:
            matches = [
                company
                for company in companies
                if requested
                in {
                    str(company.get("name", "")).casefold(),
                    str(company.get("displayName", "")).casefold(),
                }
            ]
            if len(matches) == 1:
                return str(matches[0]["id"])
            if not matches:
                available = ", ".join(
                    str(c.get("displayName") or c.get("name") or c.get("id"))
                    for c in companies[:10]
                )
                raise BusinessCentralError(
                    f"BC_COMPANY_NAME {self.config.company_name!r} was not found. "
                    f"Available: {available}"
                )
            raise BusinessCentralError(
                f"BC_COMPANY_NAME {self.config.company_name!r} matched more than one company."
            )

        if len(companies) == 1:
            return str(companies[0]["id"])

        available = ", ".join(
            str(c.get("displayName") or c.get("name") or c.get("id")) for c in companies[:10]
        )
        raise BusinessCentralError(
            "More than one Business Central company is available. "
            f"Set BC_COMPANY_ID or BC_COMPANY_NAME. Available: {available}"
        )

    def fetch_custom_historical_sales_lines(
        self,
        start_date: str = "",
        end_date: str = "",
        item_nos: Sequence[str] = (),
        customer_nos: Sequence[str] = (),
    ) -> List[dict]:
        company_id = self.resolve_company_id()
        url = (
            f"{self.environment_root}/api/gpi/commercialGuardrails/v1.0/"
            f"companies({company_id})/historicalSalesLines"
        )
        params = {
            "$select": (
                "invoiceNo,lineNo,postingDate,orderNo,customerNo,customerName,"
                "salespersonCode,lineType,itemNo,description,quantity,quantityBase,"
                "unitOfMeasureCode,unitCostLCY,unitPrice,lineAmount"
            )
        }
        sales_filter = build_sales_filter(start_date, end_date, item_nos, customer_nos)
        if sales_filter:
            params["$filter"] = sales_filter
        return self._get_all(url, params)

    def fetch_analytics_sales_lines(
        self,
        start_date: str = "",
        end_date: str = "",
        item_nos: Sequence[str] = (),
        customer_nos: Sequence[str] = (),
    ) -> List[dict]:
        company_id = self.resolve_company_id()
        url = (
            f"{self.environment_root}/api/microsoft/analytics/v1.0/"
            f"companies({company_id})/salesInvoiceLines"
        )
        params = {
            "$select": (
                "postingDate,type,description,documentNo,lineNo,no,quantityBase,"
                "amount,unitCostLCY,sellToCustomerNo,salesInvoiceDocumentNo,salespersonCode"
            )
        }
        sales_filter = build_analytics_filter(start_date, end_date, item_nos, customer_nos)
        if sales_filter:
            params["$filter"] = sales_filter
        return self._get_all(url, params)

    def fetch_transactions(
        self,
        start_date: str = "",
        end_date: str = "",
        item_nos: Sequence[str] = (),
        customer_nos: Sequence[str] = (),
    ) -> List[Transaction]:
        if self.config.source == "custom":
            rows = self.fetch_custom_historical_sales_lines(
                start_date=start_date,
                end_date=end_date,
                item_nos=item_nos,
                customer_nos=customer_nos,
            )
            return transactions_from_custom_rows(rows)

        rows = self.fetch_analytics_sales_lines(
            start_date=start_date,
            end_date=end_date,
            item_nos=item_nos,
            customer_nos=customer_nos,
        )
        return transactions_from_analytics_rows(rows)


def transactions_from_custom_rows(rows: Sequence[Mapping[str, object]]) -> List[Transaction]:
    transactions: List[Transaction] = []
    for row in rows:
        line_type = str(row.get("lineType") or "").strip().casefold()
        if line_type and line_type != "item":
            continue

        quantity = _as_float(row.get("quantity"))
        item_no = str(row.get("itemNo") or "").strip()
        if not item_no or quantity == 0:
            continue

        line_amount = _as_float(row.get("lineAmount"))
        unit_sell_price = line_amount / quantity
        invoice_no = str(row.get("invoiceNo") or "").strip()
        line_no = str(row.get("lineNo") or "").strip()

        transactions.append(
            Transaction(
                transaction_id=f"{invoice_no}:{line_no}",
                order_no=str(row.get("orderNo") or invoice_no).strip(),
                transaction_date=_parse_bc_date(str(row.get("postingDate") or "")),
                customer_no=str(row.get("customerNo") or "").strip(),
                customer_name=str(row.get("customerName") or row.get("customerNo") or "").strip(),
                item_no=item_no,
                item_description=str(row.get("description") or "").strip(),
                quantity=quantity,
                uom=str(row.get("unitOfMeasureCode") or "").strip(),
                unit_cost=_as_float(row.get("unitCostLCY")),
                unit_sell_price=unit_sell_price,
                sales_rep=str(row.get("salespersonCode") or "").strip(),
                special_pricing=False,
            )
        )
    return transactions


def transactions_from_analytics_rows(rows: Sequence[Mapping[str, object]]) -> List[Transaction]:
    """
    Analytics API fallback.

    It exposes quantityBase and unitCostLCY but not the sales UOM. This path is useful
    for a fast POC only when the item is known to be transacted consistently in its
    base unit. Use the custom API query for authoritative UOM-aware margin analysis.
    """
    transactions: List[Transaction] = []
    for row in rows:
        line_type = str(row.get("type") or "").strip().casefold()
        if line_type and line_type != "item":
            continue

        quantity_base = _as_float(row.get("quantityBase"))
        item_no = str(row.get("no") or "").strip()
        if not item_no or quantity_base == 0:
            continue

        amount = _as_float(row.get("amount"))
        unit_sell_price = amount / quantity_base
        invoice_no = str(
            row.get("salesInvoiceDocumentNo") or row.get("documentNo") or ""
        ).strip()
        line_no = str(row.get("lineNo") or "").strip()
        customer_no = str(row.get("sellToCustomerNo") or "").strip()

        transactions.append(
            Transaction(
                transaction_id=f"{invoice_no}:{line_no}",
                order_no=invoice_no,
                transaction_date=_parse_bc_date(str(row.get("postingDate") or "")),
                customer_no=customer_no,
                customer_name=customer_no,
                item_no=item_no,
                item_description=str(row.get("description") or "").strip(),
                quantity=quantity_base,
                uom="BASE",
                unit_cost=_as_float(row.get("unitCostLCY")),
                unit_sell_price=unit_sell_price,
                sales_rep=str(row.get("salespersonCode") or "").strip(),
                special_pricing=False,
            )
        )
    return transactions


def write_transactions_csv(transactions: Sequence[Transaction], path: str | Path) -> None:
    fieldnames = [
        "transaction_id",
        "order_no",
        "transaction_date",
        "customer_no",
        "customer_name",
        "item_no",
        "item_description",
        "quantity",
        "uom",
        "unit_cost",
        "unit_sell_price",
        "sales_rep",
        "special_pricing",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for tx in transactions:
            writer.writerow(
                {
                    "transaction_id": tx.transaction_id,
                    "order_no": tx.order_no,
                    "transaction_date": tx.transaction_date.strftime("%Y-%m-%d"),
                    "customer_no": tx.customer_no,
                    "customer_name": tx.customer_name,
                    "item_no": tx.item_no,
                    "item_description": tx.item_description,
                    "quantity": tx.quantity,
                    "uom": tx.uom,
                    "unit_cost": tx.unit_cost,
                    "unit_sell_price": tx.unit_sell_price,
                    "sales_rep": tx.sales_rep,
                    "special_pricing": tx.special_pricing,
                }
            )
