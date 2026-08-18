from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping, Sequence

from .bc_adapter import BusinessCentralClient


ITEM_COST_CONTEXT_SELECT = (
    "itemNo,description,baseUnitOfMeasure,unitCost,blocked,vendorNo,vendorItemNo,"
    "uomCode,qtyPerUnitOfMeasure"
)


def _odata_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_item_cost_filter(item_nos: Sequence[str]) -> str:
    values = [value.strip() for value in item_nos if value and value.strip()]
    if not values:
        return ""
    return " or ".join(f"itemNo eq {_odata_literal(value)}" for value in values)


def _float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y"}


@dataclass(frozen=True)
class BCItemCostContext:
    item_no: str
    description: str
    base_uom: str
    base_unit_cost: float
    blocked: bool
    vendor_no: str
    vendor_item_no: str
    uom: str
    qty_per_uom: float

    @property
    def unit_cost_in_uom(self) -> float | None:
        if self.base_unit_cost < 0 or self.qty_per_uom <= 0:
            return None
        return self.base_unit_cost * self.qty_per_uom

    def to_dict(self) -> dict:
        data = asdict(self)
        data["unit_cost_in_uom"] = self.unit_cost_in_uom
        return data


def item_cost_contexts_from_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[BCItemCostContext]:
    contexts: list[BCItemCostContext] = []
    for row in rows:
        item_no = str(row.get("itemNo") or "").strip()
        if not item_no:
            continue

        base_uom = str(row.get("baseUnitOfMeasure") or "").strip().upper()
        uom = str(row.get("uomCode") or "").strip().upper()
        qty_per_uom = _float(row.get("qtyPerUnitOfMeasure"), 0.0)

        # Business Central requires the base item UOM row to have Qty. per Unit of Measure = 1.
        # If an API row omits that value but clearly represents the base UOM, retain a safe 1:1 context.
        if qty_per_uom <= 0 and uom and base_uom and uom == base_uom:
            qty_per_uom = 1.0

        contexts.append(
            BCItemCostContext(
                item_no=item_no,
                description=str(row.get("description") or "").strip(),
                base_uom=base_uom,
                base_unit_cost=_float(row.get("unitCost"), 0.0),
                blocked=_bool(row.get("blocked")),
                vendor_no=str(row.get("vendorNo") or "").strip(),
                vendor_item_no=str(row.get("vendorItemNo") or "").strip(),
                uom=uom,
                qty_per_uom=qty_per_uom,
            )
        )
    return contexts


def fetch_bc_item_cost_context_rows(
    client: BusinessCentralClient,
    item_nos: Sequence[str] = (),
) -> list[dict]:
    """Read current Item Unit Cost plus Item UOM conversion context from the POC API."""
    company_id = client.resolve_company_id()
    url = (
        f"{client.environment_root}/api/gpi/commercialGuardrails/v1.0/"
        f"companies({company_id})/itemCostContexts"
    )
    params = {"$select": ITEM_COST_CONTEXT_SELECT}
    item_filter = build_item_cost_filter(item_nos)
    if item_filter:
        params["$filter"] = item_filter
    return client._get_all(url, params)


def fetch_bc_item_cost_contexts(
    client: BusinessCentralClient,
    item_nos: Sequence[str] = (),
) -> list[BCItemCostContext]:
    return item_cost_contexts_from_rows(fetch_bc_item_cost_context_rows(client, item_nos))
