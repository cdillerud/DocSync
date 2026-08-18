from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

from .proposal_guard import Proposal, ProposalException


PROTECTED_RULE_TYPES = {"SPECIAL_PRICING", "FIXED_PRICE"}
PRICING_EXCEPTION_TYPES = {
    "SELL_BELOW_CUSTOMER_HISTORY",
    "SELL_ABOVE_CUSTOMER_HISTORY",
    "LOW_GP_ANOMALY",
    "MIN_GP_RULE",
    "MIN_SELL_RULE",
    "COST_UP_SELL_FLAT",
}


@dataclass(frozen=True)
class ProposalPricingRule:
    customer_no: str
    item_no: str
    rule_type: str
    locked_sell_price: float | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    approver: str = ""
    notes: str = ""

    @property
    def specificity(self) -> int:
        return int(self.customer_no != "*") + int(self.item_no != "*")

    def to_dict(self) -> dict:
        data = asdict(self)
        for key in ("effective_from", "effective_to"):
            value = data.get(key)
            if value is not None:
                data[key] = value.isoformat()
        return data


def _float_or_none(value: object) -> float | None:
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    text = text.replace("$", "").replace(",", "")
    return float(text)


def _date_or_none(value: object) -> date | None:
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unsupported effective date: {text!r}")


def parse_proposal_date(value: str | date | None) -> date:
    if isinstance(value, date):
        return value
    if not value:
        return date.today()
    parsed = _date_or_none(value)
    if parsed is None:
        return date.today()
    return parsed


def load_proposal_pricing_rules(path: str | Path | None) -> list[ProposalPricingRule]:
    if not path:
        return []

    rules: list[ProposalPricingRule] = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rule_type = str(row.get("rule_type") or "").strip().upper()
            if rule_type not in PROTECTED_RULE_TYPES:
                continue
            rules.append(
                ProposalPricingRule(
                    customer_no=str(row.get("customer_no") or "*").strip(),
                    item_no=str(row.get("item_no") or "*").strip(),
                    rule_type=rule_type,
                    locked_sell_price=_float_or_none(row.get("locked_sell_price")),
                    effective_from=_date_or_none(row.get("effective_from")),
                    effective_to=_date_or_none(row.get("effective_to")),
                    approver=str(row.get("approver") or "").strip(),
                    notes=str(row.get("notes") or "").strip(),
                )
            )
    return rules


def matching_proposal_pricing_rules(
    proposal: Proposal,
    rules: Sequence[ProposalPricingRule],
    as_of: str | date | None = None,
) -> list[ProposalPricingRule]:
    proposal_date = parse_proposal_date(as_of)
    matches: list[ProposalPricingRule] = []

    for rule in rules:
        if rule.customer_no not in {"*", proposal.customer_no}:
            continue
        if rule.item_no not in {"*", proposal.item_no}:
            continue
        if rule.effective_from and proposal_date < rule.effective_from:
            continue
        if rule.effective_to and proposal_date > rule.effective_to:
            continue
        matches.append(rule)

    return sorted(matches, key=lambda r: (-r.specificity, r.rule_type, r.customer_no, r.item_no))


def _review_action(rules: Sequence[ProposalPricingRule]) -> str:
    approvers = sorted({rule.approver for rule in rules if rule.approver})
    if approvers:
        return f"REVIEW SPECIAL PRICING RULE WITH {', '.join(approvers)}"
    return "REVIEW SPECIAL PRICING RULE"


def apply_special_pricing_firewall(
    proposal: Proposal,
    exceptions: Sequence[ProposalException],
    rules: Sequence[ProposalPricingRule],
    as_of: str | date | None = None,
) -> tuple[dict, list[ProposalException]]:
    proposal_date = parse_proposal_date(as_of)
    matched = matching_proposal_pricing_rules(proposal, rules, proposal_date)

    context = {
        "enabled": bool(rules),
        "protected": bool(matched),
        "as_of": proposal_date.isoformat(),
        "matched_rule_count": len(matched),
        "rule_types": sorted({rule.rule_type for rule in matched}),
        "approvers": sorted({rule.approver for rule in matched if rule.approver}),
        "notes": [rule.notes for rule in matched if rule.notes],
        "rules": [rule.to_dict() for rule in matched],
    }

    output = list(exceptions)
    if not matched:
        return context, output

    action = _review_action(matched)

    for exc in output:
        if exc.exception_type in PRICING_EXCEPTION_TYPES:
            exc.recommended_action = action
            exc.explanation += (
                " A protected special-pricing rule is active for this proposal, so the guardrail "
                "will not infer or recommend a replacement sell price from general history."
            )

    protection_note = "; ".join(context["notes"])
    protection = ProposalException(
        exception_type="SPECIAL_PRICING_PROTECTED",
        severity="INFO",
        actual=f"Proposed sell ${proposal.unit_price:.4f}/{proposal.uom or 'UOM'}",
        expected="Do not infer or recommend replacement pricing from general history",
        estimated_exposure=0.0,
        recommended_action=action,
        explanation=(
            "This customer/item is governed by an active special or fixed-pricing rule. Historical "
            "price and margin anomalies may still be surfaced as evidence, but pricing actions are "
            "redirected to the configured special-pricing approver."
            + (f" Rule notes: {protection_note}" if protection_note else "")
        ),
    )

    fixed_rules = [rule for rule in matched if rule.rule_type == "FIXED_PRICE" and rule.locked_sell_price is not None]
    if fixed_rules:
        highest_specificity = max(rule.specificity for rule in fixed_rules)
        fixed_rules = [rule for rule in fixed_rules if rule.specificity == highest_specificity]
        fixed_prices = sorted({round(float(rule.locked_sell_price), 8) for rule in fixed_rules})

        if len(fixed_prices) > 1:
            output.append(
                ProposalException(
                    exception_type="CONFLICTING_FIXED_PRICE_RULES",
                    severity="CRITICAL",
                    actual=f"{len(fixed_prices)} active fixed prices at equal specificity",
                    expected="Exactly one authoritative fixed price",
                    estimated_exposure=0.0,
                    recommended_action=action,
                    explanation=(
                        "Multiple equally specific active fixed-price rules disagree. Resolve the rule "
                        "configuration before relying on any automated pricing check."
                    ),
                )
            )
        else:
            locked = fixed_prices[0]
            if abs(proposal.unit_price - locked) > 0.0001:
                output.append(
                    ProposalException(
                        exception_type="FIXED_PRICE_MISMATCH",
                        severity="CRITICAL",
                        actual=f"Proposed ${proposal.unit_price:.4f}/{proposal.uom or 'UOM'}",
                        expected=f"Protected fixed price ${locked:.4f}/{proposal.uom or 'UOM'}",
                        estimated_exposure=abs(proposal.unit_price - locked) * proposal.quantity,
                        recommended_action=action,
                        explanation=(
                            "The proposed sell price differs from the active protected fixed-price rule. "
                            "Do not substitute a history-derived price. Verify the agreement and approver."
                        ),
                    )
                )

    return context, [protection, *output]
