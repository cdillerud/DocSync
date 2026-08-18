from __future__ import annotations

from datetime import date, datetime
from typing import Mapping, Sequence

from .bc_adapter import BusinessCentralClient
from .proposal_special_pricing import ProposalPricingRule


RULE_API_SELECT = (
    "id,entryNo,enabled,customerNo,itemNo,ruleType,lockedSellPrice,"
    "effectiveFrom,effectiveTo,approver,notes"
)


def _bool(value: object, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def _float_or_none(value: object) -> float | None:
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    number = float(text.replace("$", "").replace(",", ""))
    return number if number != 0 else None


def _date_or_none(value: object) -> date | None:
    text = str(value if value is not None else "").strip()
    if not text or text.startswith("0001-01-01") or text.startswith("1753-01-01"):
        return None
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError as exc:
        raise ValueError(f"Unsupported BC guardrail effective date: {text!r}") from exc


def _rule_type(value: object) -> str:
    if isinstance(value, (int, float)):
        if int(value) == 0:
            return "SPECIAL_PRICING"
        if int(value) == 1:
            return "FIXED_PRICE"

    text = str(value if value is not None else "").strip()
    if text in {"0", "1"}:
        return "SPECIAL_PRICING" if text == "0" else "FIXED_PRICE"

    normalized = text.upper().replace("-", "_").replace(" ", "_")
    if normalized in {"SPECIAL_PRICING", "FIXED_PRICE"}:
        return normalized
    raise ValueError(f"Unsupported BC pricing rule type: {text!r}")


def pricing_rules_from_bc_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[ProposalPricingRule]:
    rules: list[ProposalPricingRule] = []
    for row in rows:
        if not _bool(row.get("enabled"), default=True):
            continue

        rules.append(
            ProposalPricingRule(
                customer_no=str(row.get("customerNo") or "*").strip() or "*",
                item_no=str(row.get("itemNo") or "*").strip() or "*",
                rule_type=_rule_type(row.get("ruleType")),
                locked_sell_price=_float_or_none(row.get("lockedSellPrice")),
                effective_from=_date_or_none(row.get("effectiveFrom")),
                effective_to=_date_or_none(row.get("effectiveTo")),
                approver=str(row.get("approver") or "").strip(),
                notes=str(row.get("notes") or "").strip(),
            )
        )
    return rules


def fetch_bc_pricing_rule_rows(client: BusinessCentralClient) -> list[dict]:
    """Read enabled pricing guardrails from the custom BC API.

    This uses the same GET-only BusinessCentralClient as the historical-sales POC.
    The API page itself has Insert/Modify/Delete disabled.
    """
    company_id = client.resolve_company_id()
    url = (
        f"{client.environment_root}/api/gpi/commercialGuardrails/v1.0/"
        f"companies({company_id})/pricingGuardrails"
    )
    return client._get_all(url, {"$select": RULE_API_SELECT})


def fetch_bc_pricing_rules(client: BusinessCentralClient) -> list[ProposalPricingRule]:
    return pricing_rules_from_bc_rows(fetch_bc_pricing_rule_rows(client))
