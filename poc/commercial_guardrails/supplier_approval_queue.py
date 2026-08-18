from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .supplier_margin_impact import SupplierMarginImpact


@dataclass(frozen=True)
class SupplierApprovalItem:
    supplier_name: str
    supplier_item_no: str
    gpi_item_no: str
    uom: str
    effective_date: str
    supplier_current_cost: float | None
    supplier_new_cost: float | None
    supplier_cost_delta: float | None
    supplier_cost_delta_pct: float | None
    affected_customers: int
    protected_customers: int
    trailing_quantity: float
    trailing_sales: float
    estimated_margin_erosion: float
    max_gp_drop_points: float
    min_projected_gp_pct: float
    top_customer_no: str
    top_customer_erosion: float
    pricing_approvers: tuple[str, ...]
    queue_status: str
    action: str
    source_file: str
    source_row: int
    decision: str = ""
    decision_by: str = ""
    decision_notes: str = ""

    def to_dict(self) -> dict:
        return {
            "queue_status": self.queue_status,
            "supplier_name": self.supplier_name,
            "supplier_item_no": self.supplier_item_no,
            "gpi_item_no": self.gpi_item_no,
            "uom": self.uom,
            "effective_date": self.effective_date,
            "supplier_current_cost": self.supplier_current_cost,
            "supplier_new_cost": self.supplier_new_cost,
            "supplier_cost_delta": self.supplier_cost_delta,
            "supplier_cost_delta_pct": self.supplier_cost_delta_pct,
            "affected_customers": self.affected_customers,
            "protected_customers": self.protected_customers,
            "trailing_quantity": self.trailing_quantity,
            "trailing_sales": self.trailing_sales,
            "estimated_margin_erosion": self.estimated_margin_erosion,
            "max_gp_drop_points": self.max_gp_drop_points,
            "min_projected_gp_pct": self.min_projected_gp_pct,
            "top_customer_no": self.top_customer_no,
            "top_customer_erosion": self.top_customer_erosion,
            "pricing_approvers": ", ".join(self.pricing_approvers),
            "action": self.action,
            "source_file": self.source_file,
            "source_row": self.source_row,
            "decision": self.decision,
            "decision_by": self.decision_by,
            "decision_notes": self.decision_notes,
        }


def build_supplier_approval_queue(
    impacts: Sequence[SupplierMarginImpact],
) -> list[SupplierApprovalItem]:
    """Build a human approval queue from actionable supplier cost impacts only.

    REVIEW and REJECT supplier rows are intentionally excluded. They must be resolved
    upstream before they can appear in the approval queue.
    """
    queue: list[SupplierApprovalItem] = []

    for impact in impacts:
        if impact.status != "IMPACT_READY":
            continue

        staged = impact.comparison.staged
        customers = list(impact.customer_impacts)
        protected = [row for row in customers if row.special_pricing_protected]
        approvers = tuple(
            sorted(
                {
                    approver
                    for row in protected
                    for approver in row.pricing_approvers
                    if approver
                }
            )
        )
        top_customer = max(
            customers,
            key=lambda row: row.estimated_margin_erosion,
            default=None,
        )

        if protected:
            queue_status = "PROTECTED_REVIEW"
            action = "REVIEW SPECIAL PRICING BEFORE APPROVING SUPPLIER COST CHANGE"
        else:
            queue_status = "PENDING_APPROVAL"
            action = "REVIEW SUPPLIER COST CHANGE AND CUSTOMER MARGIN EXPOSURE"

        queue.append(
            SupplierApprovalItem(
                supplier_name=staged.supplier_name,
                supplier_item_no=staged.supplier_item_no,
                gpi_item_no=staged.gpi_item_no,
                uom=staged.uom,
                effective_date=staged.effective_date.isoformat() if staged.effective_date else "",
                supplier_current_cost=staged.current_cost,
                supplier_new_cost=staged.new_cost,
                supplier_cost_delta=impact.cost_delta,
                supplier_cost_delta_pct=impact.cost_delta_pct,
                affected_customers=len(customers),
                protected_customers=len(protected),
                trailing_quantity=impact.trailing_quantity,
                trailing_sales=impact.trailing_sales,
                estimated_margin_erosion=impact.estimated_margin_erosion,
                max_gp_drop_points=max((row.gp_drop_points for row in customers), default=0.0),
                min_projected_gp_pct=min((row.projected_gp_pct for row in customers), default=0.0),
                top_customer_no=top_customer.customer_no if top_customer else "",
                top_customer_erosion=top_customer.estimated_margin_erosion if top_customer else 0.0,
                pricing_approvers=approvers,
                queue_status=queue_status,
                action=action,
                source_file=staged.source_file,
                source_row=staged.source_row,
            )
        )

    queue.sort(
        key=lambda row: (
            0 if row.queue_status == "PROTECTED_REVIEW" else 1,
            -row.estimated_margin_erosion,
            row.gpi_item_no,
        )
    )
    return queue


def summarize_supplier_approval_queue(rows: Sequence[SupplierApprovalItem]) -> dict:
    return {
        "items": len(rows),
        "protected_items": sum(row.queue_status == "PROTECTED_REVIEW" for row in rows),
        "affected_customers": sum(row.affected_customers for row in rows),
        "protected_customers": sum(row.protected_customers for row in rows),
        "estimated_margin_erosion": sum(row.estimated_margin_erosion for row in rows),
    }


def write_supplier_approval_queue_csv(
    rows: Sequence[SupplierApprovalItem],
    path: str | Path,
) -> None:
    data = [row.to_dict() for row in rows]
    if not data:
        Path(path).write_text("", encoding="utf-8")
        return

    fieldnames = list(data[0].keys())
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)
