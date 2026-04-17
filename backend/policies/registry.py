"""
Policy registry — maps doc_type → PolicyModule instance.

One registration per policy module. Use `get_policy(doc_type)` to look up
the right policy. Falls back to the Archive policy for unknown types so no
document is ever silently dropped.
"""

import logging
from typing import Dict, List, Optional

from policies.base import PolicyModule

logger = logging.getLogger(__name__)


_POLICIES_BY_NAME: Dict[str, PolicyModule] = {}
_POLICIES_BY_DOC_TYPE: Dict[str, PolicyModule] = {}
_FALLBACK_POLICY_NAME: str = "archive"


def register_policy(policy: PolicyModule) -> None:
    """Register a policy module. Each doc_type maps to exactly one policy."""
    _POLICIES_BY_NAME[policy.policy_name] = policy
    for dt in policy.doc_types:
        existing = _POLICIES_BY_DOC_TYPE.get(dt)
        if existing and existing.policy_name != policy.policy_name:
            logger.warning(
                "[PolicyRegistry] doc_type=%s already mapped to %s — overwritten by %s",
                dt, existing.policy_name, policy.policy_name,
            )
        _POLICIES_BY_DOC_TYPE[dt] = policy
    logger.info(
        "[PolicyRegistry] Registered %s for doc_types=%s",
        policy.policy_name, policy.doc_types,
    )


def get_policy(doc_type: Optional[str]) -> PolicyModule:
    """Look up the policy for a given doc_type, falling back to archive."""
    if doc_type:
        policy = _POLICIES_BY_DOC_TYPE.get(doc_type.lower())
        if policy:
            return policy
    return _POLICIES_BY_NAME.get(_FALLBACK_POLICY_NAME) or _NullPolicy()


def list_policies() -> List[Dict[str, object]]:
    """Return a summary of all registered policies (for debugging / admin UI)."""
    return [
        {"name": p.policy_name, "doc_types": p.doc_types}
        for p in _POLICIES_BY_NAME.values()
    ]


class _NullPolicy(PolicyModule):
    policy_name = "null"
    doc_types: List[str] = []

    async def evaluate(self, doc, resolution=None, validation=None):
        from policies.base import PolicyResult
        return PolicyResult(
            doc_id=doc.get("id", ""),
            doc_type=doc.get("doc_type", ""),
            policy_name=self.policy_name,
            stage="unhandled",
            compliance=None,
            warnings=["No policy registered for this doc_type"],
        )


# ─────────────────────────────────────────────────────────────
# Auto-registration on module import
# ─────────────────────────────────────────────────────────────

def _bootstrap_policies() -> None:
    """Instantiate + register the 4 built-in policies.

    Keep imports lazy so circulars with server.py are impossible.
    """
    from policies.archive import ArchivePolicy
    from policies.warehouse import WarehousePolicy
    from policies.ap_invoice import APInvoicePolicy
    from policies.sales_order import SalesOrderPolicy

    register_policy(ArchivePolicy())
    register_policy(WarehousePolicy())
    register_policy(APInvoicePolicy())
    register_policy(SalesOrderPolicy())


_bootstrap_policies()
