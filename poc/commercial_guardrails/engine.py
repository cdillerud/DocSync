from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from statistics import median, pstdev
from typing import Dict, List, Optional, Sequence, Tuple


DEFAULT_THRESHOLDS = {
    "minimum_customer_history": 5,
    "minimum_item_history": 3,
    "low_gp_drop_points": 5.0,
    "high_gp_jump_points": 10.0,
    "minimum_gp_floor_pct": 10.0,
    "sell_price_below_median_pct": 7.5,
    "cost_increase_pct": 3.0,
    "unchanged_sell_tolerance_pct": 1.0,
}


@dataclass(frozen=True)
class Transaction:
    transaction_id: str
    order_no: str
    transaction_date: datetime
    customer_no: str
    customer_name: str
    item_no: str
    item_description: str
    quantity: float
    uom: str
    unit_cost: float
    unit_sell_price: float
    sales_rep: str = ""
    special_pricing: bool = False

    @property
    def revenue(self) -> float:
        return self.quantity * self.unit_sell_price

    @property
    def gp_dollars(self) -> float:
        return self.quantity * (self.unit_sell_price - self.unit_cost)

    @property
    def gp_pct(self) -> float:
        if self.unit_sell_price == 0:
            return -100.0
        return ((self.unit_sell_price - self.unit_cost) / self.unit_sell_price) * 100.0


@dataclass(frozen=True)
class GuardrailRule:
    customer_no: str
    item_no: str
    rule_type: str
    min_gp_pct: Optional[float] = None
    min_sell_price: Optional[float] = None
    locked_sell_price: Optional[float] = None
    approver: str = ""
    notes: str = ""


@dataclass
class ExceptionRecord:
    transaction_id: str
    order_no: str
    customer_no: str
    customer_name: str
    item_no: str
    item_description: str
    exception_type: str
    severity: str
    actual: str
    expected: str
    estimated_exposure: float
    special_pricing_protected: bool
    recommended_action: str
    explanation: str

    def to_dict(self) -> dict:
        data = asdict(self)
        data["estimated_exposure"] = round(self.estimated_exposure, 2)
        return data


def _parse_bool(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "x"}


def _parse_float(value: str | float | int | None, default: Optional[float] = 0.0) -> Optional[float]:
    text = str(value if value is not None else "").strip()
    if not text:
        return default
    text = text.replace("$", "").replace(",", "").replace("%", "")
    try:
        return float(text)
    except ValueError:
        return default


def _parse_date(value: str) -> datetime:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    raise ValueError(f"Unsupported transaction_date: {value!r}")


def load_transactions(path: str | Path) -> List[Transaction]:
    required = {
        "transaction_id", "order_no", "transaction_date", "customer_no",
        "customer_name", "item_no", "item_description", "quantity", "uom",
        "unit_cost", "unit_sell_price",
    }
    transactions: List[Transaction] = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Transactions CSV missing columns: {', '.join(sorted(missing))}")

        for row in reader:
            transactions.append(
                Transaction(
                    transaction_id=(row.get("transaction_id") or "").strip(),
                    order_no=(row.get("order_no") or "").strip(),
                    transaction_date=_parse_date(row["transaction_date"]),
                    customer_no=(row.get("customer_no") or "").strip(),
                    customer_name=(row.get("customer_name") or "").strip(),
                    item_no=(row.get("item_no") or "").strip(),
                    item_description=(row.get("item_description") or "").strip(),
                    quantity=_parse_float(row.get("quantity"), 0.0) or 0.0,
                    uom=(row.get("uom") or "").strip(),
                    unit_cost=_parse_float(row.get("unit_cost"), 0.0) or 0.0,
                    unit_sell_price=_parse_float(row.get("unit_sell_price"), 0.0) or 0.0,
                    sales_rep=(row.get("sales_rep") or "").strip(),
                    special_pricing=_parse_bool(row.get("special_pricing")),
                )
            )
    return transactions


def load_guardrails(path: str | Path | None) -> List[GuardrailRule]:
    if not path:
        return []

    rules: List[GuardrailRule] = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rules.append(
                GuardrailRule(
                    customer_no=(row.get("customer_no") or "*").strip(),
                    item_no=(row.get("item_no") or "*").strip(),
                    rule_type=(row.get("rule_type") or "").strip().upper(),
                    min_gp_pct=_parse_float(row.get("min_gp_pct"), None),
                    min_sell_price=_parse_float(row.get("min_sell_price"), None),
                    locked_sell_price=_parse_float(row.get("locked_sell_price"), None),
                    approver=(row.get("approver") or "").strip(),
                    notes=(row.get("notes") or "").strip(),
                )
            )
    return rules


def matching_rules(tx: Transaction, rules: Sequence[GuardrailRule]) -> List[GuardrailRule]:
    matches: List[Tuple[int, GuardrailRule]] = []
    for rule in rules:
        customer_match = rule.customer_no in {"*", tx.customer_no}
        item_match = rule.item_no in {"*", tx.item_no}
        if not (customer_match and item_match):
            continue
        specificity = int(rule.customer_no != "*") + int(rule.item_no != "*")
        matches.append((specificity, rule))
    matches.sort(key=lambda pair: pair[0], reverse=True)
    return [rule for _, rule in matches]


def _pct_change(new: float, old: float) -> Optional[float]:
    if old == 0:
        return None
    return ((new - old) / abs(old)) * 100.0


def _price_to_restore_gp(unit_cost: float, target_gp_pct: float) -> Optional[float]:
    if target_gp_pct >= 100:
        return None
    denominator = 1.0 - (target_gp_pct / 100.0)
    if denominator <= 0:
        return None
    return unit_cost / denominator


def _protected(tx: Transaction, rules: Sequence[GuardrailRule]) -> bool:
    return tx.special_pricing or any(r.rule_type in {"SPECIAL_PRICING", "FIXED_PRICE"} for r in rules)


def _action(protected: bool, default_action: str, rules: Sequence[GuardrailRule]) -> str:
    if not protected:
        return default_action
    approvers = sorted({r.approver for r in rules if r.approver})
    suffix = f" WITH {', '.join(approvers)}" if approvers else ""
    return f"REVIEW SPECIAL PRICING RULE{suffix}"


def analyze_transactions(
    transactions: Sequence[Transaction],
    rules: Sequence[GuardrailRule] = (),
    thresholds: Optional[Dict[str, float]] = None,
) -> List[ExceptionRecord]:
    cfg = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        cfg.update(thresholds)

    ordered = sorted(transactions, key=lambda t: (t.transaction_date, t.transaction_id))
    customer_history: Dict[str, List[Transaction]] = {}
    item_history: Dict[Tuple[str, str], List[Transaction]] = {}
    exceptions: List[ExceptionRecord] = []

    for tx in ordered:
        cust_hist = customer_history.get(tx.customer_no, [])
        item_hist = item_history.get((tx.customer_no, tx.item_no), [])
        matched = matching_rules(tx, rules)
        protected = _protected(tx, matched)

        if protected:
            notes = "; ".join(r.notes for r in matched if r.notes)
            exceptions.append(
                ExceptionRecord(
                    transaction_id=tx.transaction_id,
                    order_no=tx.order_no,
                    customer_no=tx.customer_no,
                    customer_name=tx.customer_name,
                    item_no=tx.item_no,
                    item_description=tx.item_description,
                    exception_type="SPECIAL_PRICING_PROTECTED",
                    severity="INFO",
                    actual=f"Sell ${tx.unit_sell_price:.4f}; GP {tx.gp_pct:.1f}%",
                    expected="Do not auto-recommend price changes",
                    estimated_exposure=0.0,
                    special_pricing_protected=True,
                    recommended_action=_action(True, "", matched),
                    explanation=(
                        "This customer/item is governed by a special or fixed-pricing rule. "
                        "The engine may identify margin exposure, but it will not recommend a price change."
                        + (f" Rule notes: {notes}" if notes else "")
                    ),
                )
            )

        for rule in matched:
            if rule.rule_type == "MIN_GP" and rule.min_gp_pct is not None and tx.gp_pct < rule.min_gp_pct:
                target_sell = _price_to_restore_gp(tx.unit_cost, rule.min_gp_pct)
                exposure = 0.0 if target_sell is None else max(0.0, (target_sell - tx.unit_sell_price) * tx.quantity)
                exceptions.append(
                    ExceptionRecord(
                        transaction_id=tx.transaction_id,
                        order_no=tx.order_no,
                        customer_no=tx.customer_no,
                        customer_name=tx.customer_name,
                        item_no=tx.item_no,
                        item_description=tx.item_description,
                        exception_type="MIN_GP_RULE",
                        severity="HIGH",
                        actual=f"{tx.gp_pct:.1f}% GP",
                        expected=f">= {rule.min_gp_pct:.1f}% GP",
                        estimated_exposure=exposure,
                        special_pricing_protected=protected,
                        recommended_action=_action(protected, "REVIEW MARGIN", matched),
                        explanation="GP is below the configured minimum for this customer/item.",
                    )
                )

            if rule.rule_type == "MIN_SELL" and rule.min_sell_price is not None and tx.unit_sell_price < rule.min_sell_price:
                exposure = max(0.0, (rule.min_sell_price - tx.unit_sell_price) * tx.quantity)
                exceptions.append(
                    ExceptionRecord(
                        transaction_id=tx.transaction_id,
                        order_no=tx.order_no,
                        customer_no=tx.customer_no,
                        customer_name=tx.customer_name,
                        item_no=tx.item_no,
                        item_description=tx.item_description,
                        exception_type="MIN_SELL_RULE",
                        severity="HIGH",
                        actual=f"${tx.unit_sell_price:.4f}",
                        expected=f">= ${rule.min_sell_price:.4f}",
                        estimated_exposure=exposure,
                        special_pricing_protected=protected,
                        recommended_action=_action(protected, "REVIEW SELL PRICE", matched),
                        explanation="Sell price is below the configured minimum.",
                    )
                )

            if rule.rule_type == "FIXED_PRICE" and rule.locked_sell_price is not None:
                if abs(tx.unit_sell_price - rule.locked_sell_price) > 0.0001:
                    exceptions.append(
                        ExceptionRecord(
                            transaction_id=tx.transaction_id,
                            order_no=tx.order_no,
                            customer_no=tx.customer_no,
                            customer_name=tx.customer_name,
                            item_no=tx.item_no,
                            item_description=tx.item_description,
                            exception_type="FIXED_PRICE_MISMATCH",
                            severity="CRITICAL",
                            actual=f"${tx.unit_sell_price:.4f}",
                            expected=f"${rule.locked_sell_price:.4f} fixed price",
                            estimated_exposure=abs(tx.unit_sell_price - rule.locked_sell_price) * tx.quantity,
                            special_pricing_protected=True,
                            recommended_action=_action(True, "", matched),
                            explanation="Transaction sell price differs from the protected fixed-price rule.",
                        )
                    )

        if len(cust_hist) >= int(cfg["minimum_customer_history"]) and len(item_hist) == 0:
            common_items = {}
            for hist in cust_hist:
                common_items[hist.item_no] = common_items.get(hist.item_no, 0) + 1
            top_items = sorted(common_items.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
            common_text = ", ".join(f"{item} ({count})" for item, count in top_items)
            exceptions.append(
                ExceptionRecord(
                    transaction_id=tx.transaction_id,
                    order_no=tx.order_no,
                    customer_no=tx.customer_no,
                    customer_name=tx.customer_name,
                    item_no=tx.item_no,
                    item_description=tx.item_description,
                    exception_type="UNUSUAL_ITEM",
                    severity="HIGH",
                    actual=f"First observed purchase of {tx.item_no}",
                    expected=f"Common items: {common_text or 'n/a'}",
                    estimated_exposure=0.0,
                    special_pricing_protected=protected,
                    recommended_action="CONFIRM ITEM / UOM BEFORE PROCESSING",
                    explanation=(
                        f"Customer has {len(cust_hist)} prior transactions in the dataset but no prior "
                        f"purchase of item {tx.item_no}."
                    ),
                )
            )

        if len(item_hist) >= int(cfg["minimum_item_history"]):
            prior_gp = [h.gp_pct for h in item_hist]
            prior_sell = [h.unit_sell_price for h in item_hist if h.unit_sell_price > 0]
            median_gp = median(prior_gp)
            median_sell = median(prior_sell) if prior_sell else 0.0
            gp_std = pstdev(prior_gp) if len(prior_gp) >= 2 else 0.0

            low_gp_threshold = max(
                float(cfg["minimum_gp_floor_pct"]),
                median_gp - max(float(cfg["low_gp_drop_points"]), 2.0 * gp_std),
            )
            if tx.gp_pct < low_gp_threshold:
                target_sell = _price_to_restore_gp(tx.unit_cost, median_gp)
                exposure = 0.0 if target_sell is None else max(0.0, (target_sell - tx.unit_sell_price) * tx.quantity)
                exceptions.append(
                    ExceptionRecord(
                        transaction_id=tx.transaction_id,
                        order_no=tx.order_no,
                        customer_no=tx.customer_no,
                        customer_name=tx.customer_name,
                        item_no=tx.item_no,
                        item_description=tx.item_description,
                        exception_type="LOW_GP_ANOMALY",
                        severity="HIGH",
                        actual=f"{tx.gp_pct:.1f}% GP",
                        expected=f"Historical median {median_gp:.1f}% GP",
                        estimated_exposure=exposure,
                        special_pricing_protected=protected,
                        recommended_action=_action(protected, "REVIEW MARGIN BEFORE RELEASE", matched),
                        explanation=(
                            f"Current GP is {median_gp - tx.gp_pct:.1f} percentage points below the "
                            f"customer/item historical median."
                        ),
                    )
                )

            high_gp_threshold = median_gp + max(float(cfg["high_gp_jump_points"]), 2.0 * gp_std)
            if tx.gp_pct > high_gp_threshold:
                exceptions.append(
                    ExceptionRecord(
                        transaction_id=tx.transaction_id,
                        order_no=tx.order_no,
                        customer_no=tx.customer_no,
                        customer_name=tx.customer_name,
                        item_no=tx.item_no,
                        item_description=tx.item_description,
                        exception_type="HIGH_GP_ANOMALY",
                        severity="MEDIUM",
                        actual=f"{tx.gp_pct:.1f}% GP",
                        expected=f"Historical median {median_gp:.1f}% GP",
                        estimated_exposure=0.0,
                        special_pricing_protected=protected,
                        recommended_action="VERIFY COST / UOM",
                        explanation=(
                            f"Current GP is {tx.gp_pct - median_gp:.1f} percentage points above the "
                            f"customer/item historical median. High GP can indicate incorrect cost or UOM."
                        ),
                    )
                )

            if median_sell > 0:
                below_pct = ((median_sell - tx.unit_sell_price) / median_sell) * 100.0
                if below_pct >= float(cfg["sell_price_below_median_pct"]):
                    exposure = max(0.0, (median_sell - tx.unit_sell_price) * tx.quantity)
                    exceptions.append(
                        ExceptionRecord(
                            transaction_id=tx.transaction_id,
                            order_no=tx.order_no,
                            customer_no=tx.customer_no,
                            customer_name=tx.customer_name,
                            item_no=tx.item_no,
                            item_description=tx.item_description,
                            exception_type="SELL_BELOW_HISTORY",
                            severity="MEDIUM",
                            actual=f"${tx.unit_sell_price:.4f}",
                            expected=f"Historical median ${median_sell:.4f}",
                            estimated_exposure=exposure,
                            special_pricing_protected=protected,
                            recommended_action=_action(protected, "REVIEW QUOTED SELL PRICE", matched),
                            explanation=f"Sell price is {below_pct:.1f}% below the historical median.",
                        )
                    )

            last = item_hist[-1]
            cost_change = _pct_change(tx.unit_cost, last.unit_cost)
            sell_change = _pct_change(tx.unit_sell_price, last.unit_sell_price)
            if (
                cost_change is not None
                and cost_change >= float(cfg["cost_increase_pct"])
                and sell_change is not None
                and sell_change <= float(cfg["unchanged_sell_tolerance_pct"])
            ):
                exceptions.append(
                    ExceptionRecord(
                        transaction_id=tx.transaction_id,
                        order_no=tx.order_no,
                        customer_no=tx.customer_no,
                        customer_name=tx.customer_name,
                        item_no=tx.item_no,
                        item_description=tx.item_description,
                        exception_type="COST_UP_SELL_FLAT",
                        severity="HIGH",
                        actual=f"Cost {cost_change:+.1f}%; sell {sell_change:+.1f}%",
                        expected="Review whether supplier increase was addressed",
                        estimated_exposure=max(0.0, (tx.unit_cost - last.unit_cost) * tx.quantity),
                        special_pricing_protected=protected,
                        recommended_action=_action(protected, "REVIEW SUPPLIER COST PASS-THROUGH", matched),
                        explanation=(
                            "Unit cost increased materially while sell price stayed essentially flat "
                            "versus the previous customer/item transaction."
                        ),
                    )
                )

        customer_history.setdefault(tx.customer_no, []).append(tx)
        item_history.setdefault((tx.customer_no, tx.item_no), []).append(tx)

    return exceptions


def summarize(exceptions: Sequence[ExceptionRecord]) -> dict:
    by_type: Dict[str, int] = {}
    by_severity: Dict[str, int] = {}
    affected_orders = set()
    total_exposure = 0.0

    for exc in exceptions:
        by_type[exc.exception_type] = by_type.get(exc.exception_type, 0) + 1
        by_severity[exc.severity] = by_severity.get(exc.severity, 0) + 1
        affected_orders.add(exc.order_no)
        total_exposure += max(0.0, exc.estimated_exposure)

    return {
        "exception_count": len(exceptions),
        "affected_orders": len(affected_orders),
        "gross_flagged_exposure": round(total_exposure, 2),
        "by_type": dict(sorted(by_type.items())),
        "by_severity": dict(sorted(by_severity.items())),
        "note": "Gross flagged exposure can overlap when one transaction triggers multiple rules.",
    }


def write_exceptions_csv(exceptions: Sequence[ExceptionRecord], path: str | Path) -> None:
    rows = [exc.to_dict() for exc in exceptions]
    fieldnames = list(ExceptionRecord.__dataclass_fields__.keys())
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
