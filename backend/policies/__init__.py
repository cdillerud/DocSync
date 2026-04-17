"""
GPI Document Hub — Policy Modules
──────────────────────────────────

Each document type has exactly one PolicyModule that encapsulates its
type-specific business rules.  Policy modules are the ONLY point of
divergence in the canonical pipeline — every earlier step (ingest,
classify, extract, normalize, resolve, validate) is shared.

See /app/GPI_Hub_Architectural_Review.md §2.3 for the design rationale.

Public API:
    from policies import get_policy
    policy = get_policy(doc_type)
    result = await policy.evaluate(doc, resolution, validation)
"""

from policies.base import PolicyModule, PolicyResult
from policies.registry import get_policy, register_policy, list_policies

__all__ = [
    "PolicyModule",
    "PolicyResult",
    "get_policy",
    "register_policy",
    "list_policies",
]
