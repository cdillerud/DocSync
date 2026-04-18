"""
GPI Document Hub — Unified Validation Service
─────────────────────────────────────────────

Single canonical entry point for ALL document validation + readiness.
Replaces ad-hoc call chains scattered across server.py, routers, and
multiple doc-type-specific validators.

Architecturally corresponds to step 6 (VALIDATE) of the canonical
pipeline described in /app/GPI_Hub_Architectural_Review.md §4.

This is a FACADE that delegates to the existing validators (no
behavioral change). It exists so callers stop importing 4+ services
directly, and so we have one seam to evolve validation logic without
touching every caller.

Public API
──────────
  await validate_document(doc_id, policy_hint=None) -> ValidationBundle

where ValidationBundle is a dict with:
  {
    "doc_id": str,
    "doc_type": str,
    "policy_hint": str,        # "pilot_sales" | "ap_invoice" | "generic"
    "bc_prod": dict | None,    # BC Production cross-validation result
    "readiness": dict | None,  # readiness evaluation (doc-agnostic)
    "pilot_readiness": dict | None,  # pilot profile comparison (sales only)
    "errors": [str],
    "ran_stages": [str],
  }

Lightweight helpers mirror the existing low-level APIs so callers can
migrate incrementally:
  await run_bc_prod_validation(doc_id)
  await run_readiness(doc_id)
  await run_pilot_readiness(doc_id)

Never writes to BC. Pure read-side + local metadata persistence.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Policy hints — maps doc_type to the validation stages that apply
# ─────────────────────────────────────────────────────────────

POLICY_STAGES: Dict[str, list] = {
    # Inside Sales Pilot documents (Purchase Order, SO Confirmation)
    # Pilot flow runs bc_prod + pilot_readiness only; the generic
    # `readiness` stage is handled by the main intake pipeline.
    "pilot_sales": ["bc_prod", "pilot_readiness", "intake_learning"],
    # Generic Sales Order (non-pilot)
    "sales_order": ["bc_prod", "readiness", "intake_learning"],
    # AP side — intake learning picks up historical qty/price signals too
    "ap_invoice": ["readiness", "intake_learning"],
    "purchase_order": ["readiness", "intake_learning"],
    # Warehouse / shipping
    "warehouse": ["readiness"],
    # Fallback: just readiness
    "generic": ["readiness"],
}


def _infer_policy_hint(doc: Dict[str, Any]) -> str:
    """Given a persisted doc record, infer which validation stages to run."""
    if doc.get("inside_sales_pilot"):
        return "pilot_sales"
    dt = (doc.get("doc_type") or "").lower()
    if dt in ("sales_order", "sales order", "so_confirmation", "sales order confirmation"):
        return "sales_order"
    if dt in ("invoice", "ap_invoice", "vendor_invoice"):
        return "ap_invoice"
    if dt in ("purchase_order", "po"):
        return "purchase_order"
    if dt in ("bol", "packing_slip", "warehouse"):
        return "warehouse"
    return "generic"


# ─────────────────────────────────────────────────────────────
# Thin delegators (one per underlying validator)
# ─────────────────────────────────────────────────────────────

async def run_bc_prod_validation(doc_id: str) -> Dict[str, Any]:
    """Run BC Production cross-validation (customer / order / items / amount)."""
    from services.bc_prod_validator import validate_document_against_bc
    return await validate_document_against_bc(doc_id)


async def run_readiness(doc_id: str) -> Dict[str, Any]:
    """Run generic readiness evaluation (doc-agnostic)."""
    from services.document_readiness_service import evaluate_and_persist
    return await evaluate_and_persist(doc_id)


async def run_pilot_readiness(doc_id: str) -> Dict[str, Any]:
    """Run pilot profile-comparison review (Sales-pilot only)."""
    from services.pilot_readiness_review_service import review_pilot_document
    return await review_pilot_document(doc_id)


async def run_intake_learning(doc_id: str) -> Dict[str, Any]:
    """Run BC intake-learning orchestrator (Giovanni-style pattern learning).

    Generalises the C-10250 blanket-PO workflow so every ingested doc
    picks up learned customer patterns, qty bounds, and suggested
    recurring lines. Stores result under `intake_insights` on the doc.
    """
    from services.sales_intake_learning_service import run_intake_learning as _run
    return await _run(doc_id)


# ─────────────────────────────────────────────────────────────
# Canonical entry point
# ─────────────────────────────────────────────────────────────

async def validate_document(
    doc_id: str,
    policy_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run the full validation bundle for a document.

    If policy_hint is not supplied, it is inferred from the doc's
    stored doc_type / pilot flag. This is the ONE call site that
    every ingestion path and every retry path should use.
    """
    from deps import get_db
    db = get_db()

    doc = await db.hub_documents.find_one(
        {"id": doc_id},
        {"_id": 0, "id": 1, "doc_type": 1, "inside_sales_pilot": 1},
    )
    if not doc:
        return {
            "doc_id": doc_id,
            "error": f"Document {doc_id} not found",
            "ran_stages": [],
        }

    hint = policy_hint or _infer_policy_hint(doc)
    stages = POLICY_STAGES.get(hint, POLICY_STAGES["generic"])

    bundle: Dict[str, Any] = {
        "doc_id": doc_id,
        "doc_type": doc.get("doc_type"),
        "policy_hint": hint,
        "bc_prod": None,
        "readiness": None,
        "pilot_readiness": None,
        "intake_learning": None,
        "errors": [],
        "ran_stages": [],
    }

    stage_runners = {
        "bc_prod": ("bc_prod", run_bc_prod_validation),
        "readiness": ("readiness", run_readiness),
        "pilot_readiness": ("pilot_readiness", run_pilot_readiness),
        "intake_learning": ("intake_learning", run_intake_learning),
    }

    for stage in stages:
        key, runner = stage_runners[stage]
        try:
            bundle[key] = await runner(doc_id)
            bundle["ran_stages"].append(stage)
        except Exception as e:
            msg = f"{stage}: {type(e).__name__}: {e}"
            bundle["errors"].append(msg)
            logger.warning("[UnifiedValidation] %s stage failed for %s: %s", stage, doc_id[:8], msg)

    logger.info(
        "[UnifiedValidation] doc=%s policy=%s stages=%s errors=%d",
        doc_id[:8], hint, bundle["ran_stages"], len(bundle["errors"]),
    )
    return bundle


# Re-export for convenience so callers can switch their single import:
#   from services.unified_validation_service import validate_document
# replaces separate imports of bc_prod_validator / document_readiness_service /
# pilot_readiness_review_service.
__all__ = [
    "validate_document",
    "run_bc_prod_validation",
    "run_readiness",
    "run_pilot_readiness",
    "run_intake_learning",
    "POLICY_STAGES",
]
