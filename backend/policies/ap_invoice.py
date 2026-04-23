"""
AP Invoice policy — handles vendor invoices through the full AP workflow.

For now this policy is a thin wrapper reporting the validation + readiness
state as decided by the shared validation service.

Compute-lane logic (``compute_ap_normalized_fields``, ``compute_ap_validation``,
``compute_ap_status``, ``compute_draft_candidate_flag``, vendor resolution) is
authoritative in ``services.ap_computation``, ``services.document_intel_helpers``,
and ``services.vendor_resolution_service``. No migration from ``server.py``
compute-lane is required. Auto-post orchestration and AP queue helpers remain
candidates for later signed Phase 3 steps.
"""

from typing import Any, Dict, Optional

from policies.base import PolicyModule, PolicyResult


class APInvoicePolicy(PolicyModule):
    policy_name = "ap_invoice"
    doc_types = [
        "invoice",
        "ap_invoice",
        "vendor_invoice",
        "purchase_invoice",
    ]

    async def evaluate(
        self,
        doc: Dict[str, Any],
        resolution: Optional[Dict[str, Any]] = None,
        validation: Optional[Dict[str, Any]] = None,
    ) -> PolicyResult:
        readiness = (validation or {}).get("readiness") or {}
        status = readiness.get("status", "needs_review")

        action_by_status = {
            "ready_auto_draft": [{"type": "auto_draft_pi"}],
            "ready_auto_link": [{"type": "link_to_existing_pi"}],
            "needs_review": [{"type": "route_to_review"}],
            "ambiguous": [{"type": "route_to_review"}],
            "exception": [{"type": "route_to_exception"}],
        }

        return PolicyResult(
            doc_id=doc.get("id", ""),
            doc_type=doc.get("doc_type", "invoice"),
            policy_name=self.policy_name,
            stage=status,
            compliance=readiness.get("recommended_action"),
            actions=list(action_by_status.get(status, [{"type": "route_to_review"}])),
            warnings=list(readiness.get("warning_reasons", [])),
            blocking_reasons=list(readiness.get("blocking_reasons", [])),
            explanation="AP policy — readiness-driven routing. Auto-draft "
                        "and auto-post logic still executed from server.py.",
            raw={"readiness_status": status},
        )
