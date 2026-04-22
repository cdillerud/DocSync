"""
Line Item Reconciliation — shared helper

When an invoice line item carries a `total` (line extended amount) alongside
`quantity` and `unit_price`, the line is self-consistent only if
`quantity * unit_price == total`. Some invoices — notably freight carriers
with weight/class/rate columns — produce line items where the LLM extractor
populates `quantity` with a weight value and `unit_price` with a rate that
does not truly represent "per-unit cost", yielding a `quantity * unit_price`
product that disagrees with the printed line total by orders of magnitude.

The printed `total` is the ground truth (it's what the vendor is invoicing).
This helper normalizes the trio (`quantity`, `unit_price`, `total`) so that
`quantity * unit_price == total` holds, preserving `quantity` semantics
whenever possible and collapsing to `qty=1` only as a last resort.

This module is imported by:
  - services/vendor_invoice_profile_service.build_smart_pi_lines
    (catches pre-computed/stored lines at PI-build time)
  - services/invoice_extractor.extract_invoice_data
    (catches bad LLM extractions before they enter MongoDB)
"""

from typing import Dict, Optional, Tuple


# Keys we check on a raw line (supports snake_case and camelCase variants
# the LLM / BC payload builders use).
_QTY_KEYS = ("quantity", "qty")
_UNIT_PRICE_KEYS = ("unit_price", "unitCost", "unit_cost", "rate")
_TOTAL_KEYS = ("total", "amount", "line_total", "extended_amount")


def _first_numeric(li: Dict, keys: Tuple[str, ...]) -> Optional[float]:
    """Return the first numeric value found under `keys` in `li`, else None."""
    for k in keys:
        if k in li and li[k] is not None:
            try:
                return float(li[k])
            except (ValueError, TypeError):
                continue
    return None


def reconcile_line_amounts(li: Dict) -> Tuple[float, float, Optional[Dict]]:
    """Reconcile a line item's (quantity, unit_price, total) to be self-consistent.

    The line's printed ``total`` is treated as authoritative. When
    ``quantity * unit_price`` disagrees with ``total`` beyond tolerance
    (max of $0.01 or 0.1% of total), the reconciliation strategy is:

      * ``quantity > 0``  -> ``unit_cost = total / quantity``
        (preserves quantity semantics for BC audit)
      * ``quantity <= 0`` -> ``quantity = 1, unit_cost = total``

    When ``total`` is absent or zero, no reconciliation is possible; the
    raw values are returned (with ``quantity`` defaulted to 1 if missing).

    Returns:
        (qty, unit_cost, info) where ``info`` is ``None`` when no
        reconciliation was required, else a dict carrying the raw values
        and a human-readable reason. Callers are expected to surface
        ``info`` in audit trails / UI when non-None.
    """
    qty_raw = _first_numeric(li, _QTY_KEYS)
    unit_cost = _first_numeric(li, _UNIT_PRICE_KEYS)
    total = _first_numeric(li, _TOTAL_KEYS)

    # Missing qty is ambiguous — try the implicit qty=1 assumption first.
    # If unit_cost alone matches total (within tolerance) we treat the line
    # as self-consistent rather than flagging a reconciliation.
    qty_was_missing = qty_raw is None
    qty = qty_raw if qty_raw is not None else 0.0
    if unit_cost is None:
        unit_cost = 0.0

    # No total field available -> cannot reconcile. Return raw values with
    # qty defaulted to 1 so downstream multiplication doesn't collapse the
    # line to zero. If unit_cost is also zero there's nothing to post.
    if total is None or total == 0:
        if qty <= 0:
            qty = 1.0
        return qty, unit_cost, None

    # Fast path: qty was missing and unit_cost*1 already equals total.
    if qty_was_missing and abs(unit_cost - total) <= max(0.01, abs(total) * 0.001):
        return 1.0, unit_cost, None

    computed_extended = qty * unit_cost
    tolerance = max(0.01, abs(total) * 0.001)

    if abs(computed_extended - total) <= tolerance:
        if qty <= 0:
            qty = 1.0
        return qty, unit_cost, None

    # Reconcile. Trust `total`.
    if qty > 0:
        derived_unit_cost = total / qty
        info = {
            "raw_qty": qty,
            "raw_unit_price": unit_cost,
            "raw_total": total,
            "reason": (
                f"qty*unit_price ({computed_extended:.4f}) "
                f"!= total ({total:.2f}); derived unit_cost = total/qty"
            ),
            "strategy": "preserve_qty",
        }
        return qty, derived_unit_cost, info

    info = {
        "raw_qty": qty,
        "raw_unit_price": unit_cost,
        "raw_total": total,
        "reason": "qty missing/zero; collapsed to qty=1, unit_cost=total",
        "strategy": "collapse_to_unit",
    }
    return 1.0, total, info


def format_reconcile_suffix(info: Dict) -> str:
    """Build a human-readable audit suffix to append to a BC line description.

    Example output:
        "[reconciled: qty=2600 x rate=$2.7768 = $7,219.68]"
    """
    qty = info.get("raw_qty", 0)
    rate = info.get("raw_total", 0) / qty if qty else info.get("raw_total", 0)
    total = info.get("raw_total", 0)
    return f"[reconciled: qty={qty:g} x rate=${rate:,.4f} = ${total:,.2f}]"
