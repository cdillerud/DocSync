"""
GPI Document Hub - Developer Tools Routes

Validation-only endpoints that never write to the database.
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from deps import get_db
from services.invoice_extractor import EXTRACTION_PROMPT
from services.llm_router import get_provider
from services.providers.base_provider import LLMProviderError
from services.providers.emergent_provider import EmergentProvider
from services.providers.ollama_provider import OllamaProvider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dev", tags=["DevTools"])

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"

DIFF_FIELDS = [
    "invoice_number", "invoice_date", "due_date", "vendor_name",
    "po_number", "total_amount", "tax_amount", "currency",
]

MIME_MAP = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
}


# ---------- helpers ----------

def _verify_token(authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1]
    try:
        import jwt as pyjwt
        secret = os.environ.get("JWT_SECRET", "gpi-hub-secret-key")
        payload = pyjwt.decode(token, secret, algorithms=["HS256"])
        return payload.get("sub", "unknown")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def _detect_mime(file_path: Path) -> str:
    ext = file_path.suffix.lower()
    if ext in MIME_MAP:
        return MIME_MAP[ext]
    try:
        header = file_path.read_bytes()[:10]
        if header.startswith(b"%PDF"):
            return "application/pdf"
        if header[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        if header[:3] == b"\xff\xd8\xff":
            return "image/jpeg"
    except Exception:
        pass
    return "application/pdf"


def _parse_extraction(raw: str) -> Dict[str, Any]:
    """Parse JSON from an LLM response, tolerating markdown wrappers."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        body = []
        inside = False
        for line in lines:
            if line.startswith("```"):
                inside = not inside
                continue
            if inside:
                body.append(line)
        text = "\n".join(body).strip()
    if text.startswith("{"):
        return json.loads(text)
    if "{" in text:
        return json.loads(text[text.find("{"):text.rfind("}") + 1])
    raise ValueError(f"No JSON found in response: {text[:200]}")


def _norm(val: Any) -> Optional[str]:
    """Normalise a field value for comparison."""
    if val is None:
        return None
    return str(val).strip().lower()


def _build_diff(baseline: Optional[Dict], candidate: Optional[Dict]) -> Dict[str, Any]:
    agreed: List[str] = []
    disagreed: List[str] = []
    missing_in_candidate: List[str] = []
    missing_in_baseline: List[str] = []

    b = baseline or {}
    c = candidate or {}

    for field in DIFF_FIELDS:
        bv = _norm(b.get(field))
        cv = _norm(c.get(field))
        if bv is None and cv is None:
            agreed.append(field)
        elif bv is None and cv is not None:
            missing_in_baseline.append(field)
        elif bv is not None and cv is None:
            missing_in_candidate.append(field)
        elif bv == cv:
            agreed.append(field)
        else:
            disagreed.append(field)

    b_conf = float(b.get("confidence", 0) or 0)
    c_conf = float(c.get("confidence", 0) or 0)

    return {
        "fields_agreed": agreed,
        "fields_disagreed": disagreed,
        "fields_missing_in_candidate": missing_in_candidate,
        "fields_missing_in_baseline": missing_in_baseline,
        "confidence_delta": round(c_conf - b_conf, 4),
    }


async def _extract_with_emergent(api_key: str, model_name: str, file_path: str, mime_type: str, session_tag: str) -> Dict[str, Any]:
    """Vision-based extraction using emergentintegrations FileContentWithMimeType."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage, FileContentWithMimeType

    fc = FileContentWithMimeType(file_path=file_path, mime_type=mime_type)
    chat = LlmChat(
        api_key=api_key,
        session_id=session_tag,
        system_message="You are an expert invoice data extraction system. Always respond with valid JSON only.",
    ).with_model("gemini", model_name)
    resp = await chat.send_message(UserMessage(text=EXTRACTION_PROMPT, file_contents=[fc]))
    return _parse_extraction(str(resp))


async def _extract_with_ollama(provider: OllamaProvider, doc_text: str, session_tag: str) -> Dict[str, Any]:
    """Text-based extraction via Ollama complete()."""
    user_prompt = f"{EXTRACTION_PROMPT}\n\nDocument text:\n{doc_text[:8000]}"
    raw = await provider.complete(
        system_prompt="You are an expert invoice data extraction system. Always respond with valid JSON only.",
        user_prompt=user_prompt,
        session_id=session_tag,
        expect_json=True,
    )
    return _parse_extraction(raw)


# ---------- endpoint ----------

class CompareRequest(BaseModel):
    document_id: str


@router.post("/compare-extraction")
async def compare_extraction(
    body: CompareRequest,
    authorization: Optional[str] = Header(None),
):
    _verify_token(authorization)

    db = get_db()
    doc = await db.hub_documents.find_one({"id": body.document_id}, {"_id": 0})
    if doc is None:
        from bson import ObjectId
        try:
            doc = await db.hub_documents.find_one({"_id": ObjectId(body.document_id)}, {"_id": 0})
        except Exception:
            pass
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    doc_id = doc.get("id", body.document_id)
    file_name = doc.get("file_name", "unknown")
    file_path = UPLOAD_DIR / doc_id
    mime_type = _detect_mime(file_path) if file_path.exists() else "application/pdf"

    api_key = os.environ.get("EMERGENT_LLM_KEY", "")

    # ---- build extraction tasks ----
    async def run_baseline() -> Dict[str, Any]:
        t0 = time.monotonic()
        try:
            if not file_path.exists():
                raise LLMProviderError(f"File not on disk: {file_path}")
            if not api_key:
                raise LLMProviderError("EMERGENT_LLM_KEY not configured")
            result = await _extract_with_emergent(
                api_key, "gemini-2.0-flash", str(file_path), mime_type, f"compare_baseline_{doc_id}"
            )
            return {"provider": "emergent", "model": "gemini-2.0-flash", "result": result,
                    "elapsed_ms": round((time.monotonic() - t0) * 1000), "error": None}
        except Exception as exc:
            return {"provider": "emergent", "model": "gemini-2.0-flash", "result": {},
                    "elapsed_ms": round((time.monotonic() - t0) * 1000), "error": str(exc)}

    async def run_candidate() -> Dict[str, Any]:
        t0 = time.monotonic()
        try:
            provider = get_provider("extraction")
        except LLMProviderError as exc:
            return {"provider": "unknown", "model": "unknown", "result": {},
                    "elapsed_ms": round((time.monotonic() - t0) * 1000), "error": str(exc)}
        try:
            if isinstance(provider, EmergentProvider):
                if not file_path.exists():
                    raise LLMProviderError(f"File not on disk: {file_path}")
                result = await _extract_with_emergent(
                    api_key, provider._model_name, str(file_path), mime_type,
                    f"compare_candidate_{doc_id}",
                )
                return {"provider": "emergent", "model": provider._model_name, "result": result,
                        "elapsed_ms": round((time.monotonic() - t0) * 1000), "error": None}
            elif isinstance(provider, OllamaProvider):
                doc_text = doc.get("text_content") or doc.get("extracted_text") or ""
                if not doc_text:
                    ef = doc.get("extracted_fields") or {}
                    parts = [f"{k}: {v}" for k, v in ef.items() if v]
                    doc_text = "\n".join(parts) if parts else "(no text available)"
                result = await _extract_with_ollama(provider, doc_text, f"compare_candidate_{doc_id}")
                return {"provider": "ollama", "model": provider._model_name, "result": result,
                        "elapsed_ms": round((time.monotonic() - t0) * 1000), "error": None}
            else:
                raise LLMProviderError(f"Unsupported provider type: {type(provider).__name__}")
        except Exception as exc:
            pname = type(provider).__name__ if 'provider' in dir() else "unknown"
            return {"provider": pname, "model": getattr(provider, '_model_name', 'unknown'),
                    "result": {}, "elapsed_ms": round((time.monotonic() - t0) * 1000), "error": str(exc)}

    baseline_out, candidate_out = await asyncio.gather(run_baseline(), run_candidate())

    diff = _build_diff(
        baseline_out.get("result") if not baseline_out.get("error") else None,
        candidate_out.get("result") if not candidate_out.get("error") else None,
    )

    return {
        "document_id": doc_id,
        "file_name": file_name,
        "baseline": baseline_out,
        "candidate": candidate_out,
        "diff": diff,
    }


# ---------- vendor ranking test ----------

class VendorRankingRequest(BaseModel):
    vendor_raw: str
    candidates: List[Dict[str, Any]]
    document_context: Optional[Dict[str, Any]] = None


@router.post("/test-vendor-ranking")
async def test_vendor_ranking(
    body: VendorRankingRequest,
    authorization: Optional[str] = Header(None),
):
    """Test LLM-assisted vendor candidate ranking. Writes nothing."""
    _verify_token(authorization)

    from services.vendor_resolution_assist_service import rank_vendor_candidates

    result = await rank_vendor_candidates(
        vendor_raw=body.vendor_raw,
        candidates=body.candidates,
        document_context=body.document_context,
    )
    return result.to_dict()
