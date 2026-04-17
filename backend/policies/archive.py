"""
Archive policy — for docs that should NOT trigger any BC / pipeline action.
Example: certificates, RFQs with no follow-up, marketing attachments.

This is the fallback policy for unknown doc_types.
"""

from typing import Any, Dict, Optional

from policies.base import PolicyModule, PolicyResult


class ArchivePolicy(PolicyModule):
    policy_name = "archive"
    doc_types = [
        "archive",
        "certificate",
        "rfq",
        "marketing",
        "other",
        "unknown",
    ]

    async def evaluate(
        self,
        doc: Dict[str, Any],
        resolution: Optional[Dict[str, Any]] = None,
        validation: Optional[Dict[str, Any]] = None,
    ) -> PolicyResult:
        return PolicyResult(
            doc_id=doc.get("id", ""),
            doc_type=doc.get("doc_type", "unknown"),
            policy_name=self.policy_name,
            stage="archived",
            compliance="not_applicable",
            actions=[{"type": "archive"}],
            explanation="Document archived — no downstream processing required.",
        )
