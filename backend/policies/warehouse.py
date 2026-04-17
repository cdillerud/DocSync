"""
Warehouse policy — handles BOLs, packing slips, and shipment-related documents.

For now this policy is a thin wrapper that reports the doc's current
validation state. Full auto-clear / BOL-matching logic currently lives in
`server.py` (lines 2065-2228) and will be migrated here in a follow-up pass.
"""

from typing import Any, Dict, Optional

from policies.base import PolicyModule, PolicyResult


class WarehousePolicy(PolicyModule):
    policy_name = "warehouse"
    doc_types = [
        "bol",
        "packing_slip",
        "warehouse",
        "shipment",
        "delivery_note",
    ]

    async def evaluate(
        self,
        doc: Dict[str, Any],
        resolution: Optional[Dict[str, Any]] = None,
        validation: Optional[Dict[str, Any]] = None,
    ) -> PolicyResult:
        readiness = (validation or {}).get("readiness") or {}
        status = readiness.get("status", "needs_review")

        stage_map = {
            "ready_auto_draft": "auto_clear_eligible",
            "ready_auto_link": "auto_clear_eligible",
            "needs_review": "needs_review",
            "ambiguous": "needs_review",
            "exception": "exception",
        }
        stage = stage_map.get(status, "needs_review")

        return PolicyResult(
            doc_id=doc.get("id", ""),
            doc_type=doc.get("doc_type", "warehouse"),
            policy_name=self.policy_name,
            stage=stage,
            compliance=readiness.get("recommended_action"),
            warnings=list(readiness.get("warning_reasons", [])),
            blocking_reasons=list(readiness.get("blocking_reasons", [])),
            explanation="Warehouse policy — BOL matching + auto-clear logic "
                        "is currently handled by server.py; this policy "
                        "surfaces the readiness state.",
            raw={"readiness_status": status},
        )
