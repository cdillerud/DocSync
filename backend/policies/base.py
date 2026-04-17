"""
PolicyModule base class + PolicyResult type.

A PolicyModule is a thin wrapper around doc-type-specific business rules.
It receives a fully-resolved + validated document and decides:
  1. What stage/status the document is in
  2. What actions (if any) should be executed next
  3. What compliance/warning flags apply

Policy modules do NOT perform extraction, classification, entity resolution,
or BC writes directly — those are earlier pipeline stages or action handlers.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PolicyResult:
    """Outcome of a policy evaluation for a single document."""

    doc_id: str
    doc_type: str
    policy_name: str
    stage: str                               # e.g. "ready_to_post", "needs_review", "exception"
    compliance: Optional[str] = None         # e.g. "compliant", "advisory", "blocked", None
    actions: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    blocking_reasons: List[str] = field(default_factory=list)
    explanation: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "doc_type": self.doc_type,
            "policy_name": self.policy_name,
            "stage": self.stage,
            "compliance": self.compliance,
            "actions": self.actions,
            "warnings": self.warnings,
            "blocking_reasons": self.blocking_reasons,
            "explanation": self.explanation,
            "raw": self.raw,
        }


class PolicyModule:
    """
    Base class every policy module extends.

    Subclasses override:
      - `policy_name` (str)
      - `doc_types` (list[str]) — the doc_types this policy handles
      - `async def evaluate(self, doc, resolution, validation) -> PolicyResult`
      - (optional) `async def get_actions(self, doc, evaluation) -> list`
    """

    policy_name: str = "base"
    doc_types: List[str] = []

    async def evaluate(
        self,
        doc: Dict[str, Any],
        resolution: Optional[Dict[str, Any]] = None,
        validation: Optional[Dict[str, Any]] = None,
    ) -> PolicyResult:
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement evaluate()"
        )

    async def get_actions(
        self,
        doc: Dict[str, Any],
        evaluation: PolicyResult,
    ) -> List[Dict[str, Any]]:
        """Default: return the actions already decided in evaluate()."""
        return evaluation.actions
