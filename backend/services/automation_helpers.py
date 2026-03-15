"""
GPI Document Hub - Decisioning & Automation Shared Helpers

Canonical utilities used across the decisioning and automation domain:
  - Timestamp generation
  - Activity record creation
  - Document update builder (enforces updated_utc)
  - Eligibility check result types

Consumers:
  - decision_policy_service  (activity creation, timestamps)
  - auto_resolution_service  (document updates, timestamps)
  - auto_clear_service       (eligibility results, timestamps)
  - auto_post_service        (document updates, timestamps)
  - automation_rules_service (timestamps)
"""

import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ACTIVITIES_COLLECTION = "activities"


# ---------------------------------------------------------------------------
# 1. Timestamp helper
# ---------------------------------------------------------------------------

def utcnow() -> str:
    """Return the current UTC time as an ISO-8601 string.

    Single source of truth for timestamp formatting across the automation
    domain.  Replaces ~50 inline ``datetime.now(timezone.utc).isoformat()``
    calls.
    """
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 2. Activity record creation
# ---------------------------------------------------------------------------

async def create_activity(
    db,
    entity_id: str,
    entity_type: str,
    activity_type: str,
    title: str,
    body: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    created_by: str = "system",
) -> Dict[str, Any]:
    """Insert a canonical activity record and return it (without ``_id``).

    This is the single place that writes to the ``activities`` collection so
    every caller produces identically-shaped audit records.
    """
    now = utcnow()
    record = {
        "activity_id": f"ACT-{uuid.uuid4().hex[:8].upper()}",
        "entity_type": entity_type,
        "entity_id": entity_id,
        "activity_type": activity_type,
        "title": title,
        "body": body,
        "created_by": created_by,
        "created_at": now,
        "metadata": metadata or {},
    }
    await db[ACTIVITIES_COLLECTION].insert_one(record.copy())
    record.pop("_id", None)
    return record


# ---------------------------------------------------------------------------
# 3. Document update builder
# ---------------------------------------------------------------------------

def build_document_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Build a ``$set`` dict for a hub_documents update.

    Automatically appends ``updated_utc`` so callers can never forget it.
    Removes ``_id`` if accidentally included.
    """
    fields.pop("_id", None)
    fields["updated_utc"] = utcnow()
    return fields


async def apply_document_update(
    db,
    doc_id: str,
    fields: Dict[str, Any],
) -> None:
    """Apply a ``$set`` update to ``hub_documents`` for *doc_id*.

    Wraps :func:`build_document_update` and executes the write.
    """
    update = build_document_update(fields)
    await db.hub_documents.update_one({"id": doc_id}, {"$set": update})


# ---------------------------------------------------------------------------
# 4. Eligibility check results
# ---------------------------------------------------------------------------

@dataclass
class EligibilityCheck:
    """Outcome of a single eligibility check."""
    name: str
    passed: bool
    value: Any = None
    threshold: Any = None
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check": self.name,
            "passed": self.passed,
            "value": self.value,
            "threshold": self.threshold,
            "message": self.message,
        }


@dataclass
class EligibilityResult:
    """Aggregate outcome of an eligibility evaluation."""
    eligible: bool
    decision: str          # e.g. "cleared", "needs_review", "blocked"
    reason: str
    checks: List[EligibilityCheck] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "eligible": self.eligible,
            "decision": self.decision,
            "reason": self.reason,
            "checks": [c.to_dict() for c in self.checks],
            "all_passed": self.all_passed,
            "metadata": self.metadata,
        }
