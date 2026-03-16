"""
Automation Intelligence Router

Endpoints:
  GET  /api/automation/metrics                         — Automation metrics dashboard
  POST /api/automation/batch-evaluate                  — Batch evaluate intelligence
  GET  /api/documents/{id}/decision-explanation         — Decision explainability
  POST /api/documents/{id}/review-assist                — Reviewer assist suggestions
  POST /api/documents/{id}/accept-suggestion            — Accept a reviewer suggestion
  GET  /api/documents/{id}/automation-confidence        — Automation confidence detail
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

router = APIRouter(tags=["Automation Intelligence"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AcceptSuggestionRequest(BaseModel):
    action: str
    field: str
    value: str
    accepted_by: Optional[str] = "reviewer"


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@router.get("/automation/metrics")
async def automation_metrics():
    """Get automation intelligence metrics for the dashboard."""
    from services.automation_intelligence_service import get_automation_metrics
    return await get_automation_metrics()


# ---------------------------------------------------------------------------
# Batch evaluate
# ---------------------------------------------------------------------------

@router.post("/automation/batch-evaluate")
async def batch_evaluate(limit: int = Query(200, ge=1, le=1000)):
    """Batch evaluate automation intelligence for documents missing it."""
    from services.automation_intelligence_service import batch_evaluate_intelligence
    return await batch_evaluate_intelligence(limit=limit)


# ---------------------------------------------------------------------------
# Document-level endpoints
# ---------------------------------------------------------------------------

@router.get("/documents/{doc_id}/decision-explanation")
async def get_decision_explanation(doc_id: str):
    """Get structured decision explanation for a document."""
    from deps import get_db
    from services.automation_intelligence_service import (
        build_decision_explanation,
        compute_automation_confidence,
    )
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Return stored explanation if fresh, otherwise recompute
    stored = doc.get("decision_explanation")
    if stored:
        return stored

    explanation = build_decision_explanation(doc)
    # Persist for future reads
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {"decision_explanation": explanation}},
    )
    return explanation


@router.get("/documents/{doc_id}/automation-confidence")
async def get_automation_confidence(doc_id: str):
    """Get automation confidence breakdown for a document."""
    from deps import get_db
    from services.automation_intelligence_service import compute_automation_confidence
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    stored = doc.get("automation_confidence")
    if stored:
        return stored

    confidence = compute_automation_confidence(doc)
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {"automation_confidence": confidence}},
    )
    return confidence


@router.post("/documents/{doc_id}/review-assist")
async def review_assist(doc_id: str):
    """Generate reviewer assist suggestions for a document."""
    from deps import get_db
    from services.automation_intelligence_service import generate_review_suggestions
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    suggestions = generate_review_suggestions(doc)
    return {"doc_id": doc_id, "suggested_actions": suggestions}


@router.post("/documents/{doc_id}/accept-suggestion")
async def accept_suggestion(doc_id: str, body: AcceptSuggestionRequest):
    """Accept and apply a reviewer suggestion."""
    from services.automation_intelligence_service import accept_suggestion as _accept
    result = await _accept(doc_id, body.action, body.field, body.value, body.accepted_by)
    if "error" in result:
        raise HTTPException(
            status_code=404 if "not found" in result["error"].lower() else 400,
            detail=result["error"],
        )
    return result
