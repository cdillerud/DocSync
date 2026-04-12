"""
GPI Document Hub - Document Decision Explainer Route

GET /api/documents/{document_id}/explain
Returns a plain-English explanation of why a document is in its current status.
"""

import logging
from fastapi import APIRouter, HTTPException, Header
from typing import Optional
from bson import ObjectId
from deps import get_db
from services.decision_explainer_service import explain_document_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Documents"])


def _verify_token(authorization: Optional[str]) -> str:
    """Minimal JWT verification matching the existing auth.py pattern."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1]
    try:
        import jwt as pyjwt
        import os
        secret = os.environ.get("JWT_SECRET", "gpi-hub-secret-key")
        payload = pyjwt.decode(token, secret, algorithms=["HS256"])
        return payload.get("sub", "unknown")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


@router.get("/{document_id}/explain")
async def explain_document(
    document_id: str,
    authorization: Optional[str] = Header(None),
):
    """Return a plain-English explanation of a document's current workflow state."""
    _verify_token(authorization)

    db = get_db()

    # Try string id first (the convention used everywhere)
    doc = await db.hub_documents.find_one({"id": document_id}, {"_id": 0})

    # Fallback: try as ObjectId
    if doc is None:
        try:
            doc = await db.hub_documents.find_one({"_id": ObjectId(document_id)}, {"_id": 0})
        except Exception:
            pass

    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    result = await explain_document_status(doc)
    return result.to_dict()
