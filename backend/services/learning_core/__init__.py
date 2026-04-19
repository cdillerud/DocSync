"""
GPI Document Hub — Learning Core
─────────────────────────────────

Shared plumbing for learning systems across the hub. Today this
package exposes:

  • events_service     — canonical unified event log (replaces
                         intake_learning_events / posting_learning_events
                         / learning_events over a 30-day dual-write window)

Future phases (U2+) will add fingerprint_service, pattern_health_service,
and a shared feedback ingest endpoint. See
/app/memory/CHANGELOG.md — v2.4.1 for the multi-phase rollout plan.
"""

from services.learning_core.events_service import (
    record_event,
    list_events,
    get_domain_summary,
    get_trend,
    DOMAINS,
    EVENTS_COLL,
)
from services.learning_core.fingerprint_service import (
    tokenize,
    build_fingerprint,
    get_or_build,
    invalidate,
    rebuild_all,
    find_similar,
    FINGERPRINTS_COLL,
    SCOPE_TYPES,
)
from services.learning_core.pattern_health_service import (
    get_health,
    run_hygiene,
    HEALTH_ADAPTERS,
    HYGIENE_ADAPTERS,
)
from services.learning_core.feedback_service import (
    record_unified_feedback,
    SCOPE_TYPES as FEEDBACK_SCOPE_TYPES,
)

__all__ = [
    # Events (U1)
    "record_event",
    "list_events",
    "get_domain_summary",
    "get_trend",
    "DOMAINS",
    "EVENTS_COLL",
    # Fingerprint (U2)
    "tokenize",
    "build_fingerprint",
    "get_or_build",
    "invalidate",
    "rebuild_all",
    "find_similar",
    "FINGERPRINTS_COLL",
    "SCOPE_TYPES",
    # Pattern health (U3)
    "get_health",
    "run_hygiene",
    "HEALTH_ADAPTERS",
    "HYGIENE_ADAPTERS",
    # Shared feedback ingest (U4)
    "record_unified_feedback",
    "FEEDBACK_SCOPE_TYPES",
]
