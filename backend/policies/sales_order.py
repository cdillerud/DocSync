"""
Sales Order policy — handles Sales pilot + non-pilot sales documents.

Combines three layers of state that already exist on a pilot document:
  1. bc_prod_validation      — BC cross-reference scores
  2. spiro_match             — CRM reconciliation
  3. so_rules_evaluation     — Sales Order Rules Engine compliance

Pilot docs are ALWAYS held at stage="pilot_review" (no auto-creation of
BC sales orders — that's the hard constraint of the pilot). Non-pilot
sales docs route according to their readiness state.
"""

from typing import Any, Dict, Optional

from policies.base import PolicyModule, PolicyResult


class SalesOrderPolicy(PolicyModule):
    policy_name = "sales_order"
    doc_types = [
        "sales_order",
        "sales order",
        "purchase_order",          # incoming customer PO is a sales doc for us
        "po",
        "so_confirmation",
        "sales order confirmation",
    ]

    async def evaluate(
        self,
        doc: Dict[str, Any],
        resolution: Optional[Dict[str, Any]] = None,
        validation: Optional[Dict[str, Any]] = None,
    ) -> PolicyResult:
        is_pilot = bool(doc.get("inside_sales_pilot"))

        bc_prod = (validation or {}).get("bc_prod") or doc.get("bc_prod_validation") or {}
        so_rules = doc.get("so_rules_evaluation") or {}
        spiro = doc.get("spiro_match") or {}
        readiness = (validation or {}).get("readiness") or doc.get("readiness") or {}

        bc_score = bc_prod.get("overall_score", 0)
        rules_status = so_rules.get("status") or so_rules.get("compliance")
        spiro_status = spiro.get("status")

        warnings: list = []
        blocking: list = []

        if not bc_prod.get("customer_match", {}).get("found"):
            blocking.append("customer_not_in_bc")
        if not bc_prod.get("order_lookup", {}).get("found"):
            warnings.append("order_not_matched_in_bc")
        if spiro_status and spiro_status != "matched":
            warnings.append(f"spiro_status:{spiro_status}")

        # Pilot constraint: ingest-only, never auto-create SO in BC
        if is_pilot:
            actions = [{"type": "hold_for_pilot_review"}]
            stage = "pilot_review"
            compliance = rules_status or "advisory"
            explanation = (
                "Inside Sales Pilot: document held for human review. "
                "No BC sales-order creation is performed by this policy."
            )
        else:
            # Non-pilot: route based on readiness
            status = readiness.get("status", "needs_review")
            if status in ("ready_auto_draft", "ready_auto_link") and not blocking:
                actions = [{"type": "create_sales_order"}]
                stage = "ready_to_post"
                compliance = "compliant"
            elif blocking:
                actions = [{"type": "route_to_exception"}]
                stage = "exception"
                compliance = "blocked"
            else:
                actions = [{"type": "route_to_review"}]
                stage = "needs_review"
                compliance = "advisory"
            explanation = f"Sales order routed from readiness={status}."

        return PolicyResult(
            doc_id=doc.get("id", ""),
            doc_type=doc.get("doc_type", "sales_order"),
            policy_name=self.policy_name,
            stage=stage,
            compliance=compliance,
            actions=actions,
            warnings=warnings,
            blocking_reasons=blocking,
            explanation=explanation,
            raw={
                "bc_score": bc_score,
                "rules_status": rules_status,
                "spiro_status": spiro_status,
                "is_pilot": is_pilot,
            },
        )
