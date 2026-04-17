"""
AP Invoice policy — handles vendor invoices through the full AP workflow.

For now this policy is a thin wrapper reporting the validation + readiness
state as decided by the shared validation service. The full vendor-match
enforcement, draft PI preview, line-distribution, and auto-post logic
currently lives in `server.py` (lines 3333-3634) and will be migrated here
in the follow-up pass.
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
