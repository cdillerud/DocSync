"""Bounded supporting-page reference extraction for multi-page business documents.

Page 1 remains authoritative for primary document classification. Pages 2-5 may
supply supporting references needed for BC resolution/routing (POs, BOLs,
shipments, receipts, generic labeled references). This service never changes
`document_type`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
DEFAULT_MODEL = os.environ.get("AP_ROUTING_MODEL", "gemini-2.5-pro")
MAX_SUPPORTING_PAGES = int(os.environ.get("DOC_BUNDLE_SUPPORTING_MAX_PAGES", "4"))

_REFERENCE_FIELDS = (
    "po_numbers",
    "order_numbers",
    "bol_numbers",
    "shipment_numbers",
    "receipt_numbers",
    "reference_numbers",
    "pro_numbers",
    "load_numbers",
)

_LABEL_PATTERNS = {
    "po_numbers": [
        re.compile(r"\b(?:purchase\s+order|customer\s+p\.?o\.?|gamer\s+po|p\.?o\.?)\s*(?:no\.?|number|#)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9_./-]{3,24})", re.I),
    ],
    "order_numbers": [
        re.compile(r"\border\s*(?:no\.?|number|#)\s*[:#-]?\s*([A-Z0-9][A-Z0-9_./-]{3,24})", re.I),
    ],
    "bol_numbers": [
        re.compile(r"\b(?:bill\s+of\s+lading|b/?l|bol)\s*(?:no\.?|number|#)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9_./ -]{3,40})", re.I),
    ],
    "shipment_numbers": [
        re.compile(r"\bshipment\s*(?:no\.?|number|#)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9_./-]{3,24})", re.I),
    ],
    "receipt_numbers": [
        re.compile(r"\breceipt\s*(?:no\.?|number|#)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9_./-]{3,24})", re.I),
    ],
    "reference_numbers": [
        re.compile(r"\breference\s*(?:no\.?|number|#)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9_./-]{3,40})", re.I),
    ],
    "pro_numbers": [
        re.compile(r"\bpro\s*(?:no\.?|number|#)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9_./-]{3,24})", re.I),
    ],
    "load_numbers": [
        re.compile(r"\bload\s*(?:no\.?|number|#)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9_./-]{3,24})", re.I),
    ],
}


def _empty_refs() -> Dict[str, List[Dict[str, Any]]]:
    return {field: [] for field in _REFERENCE_FIELDS}


def _dedupe(values: List[str]) -> List[str]:
    seen = set()
    out = []
    for value in values:
        cleaned = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n,;|")
        if not cleaned:
            continue
        key = cleaned.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _regex_supporting_refs(page_texts: List[Dict[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, List[Dict[str, Any]]] = _empty_refs()
    for page in page_texts:
        page_no = int(page["page"])
        text = str(page.get("text") or "")
        for field, patterns in _LABEL_PATTERNS.items():
            for pattern in patterns:
                for match in pattern.finditer(text[:12000]):
                    value = re.split(r"\s{2,}|\n", match.group(1))[0].strip()
                    if value:
                        result[field].append(
                            {"value": value, "page": page_no, "source": "labeled_regex"}
                        )
    for field in _REFERENCE_FIELDS:
        deduped = []
        seen = set()
        for item in result[field]:
            key = str(item["value"]).upper()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        result[field] = deduped
    return result


def _extract_page_text_and_pdf(file_path: str) -> tuple[int, List[Dict[str, Any]], Optional[str]]:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(file_path)
    page_count = len(reader.pages)
    if page_count <= 1:
        return page_count, [], None

    end = min(page_count, 1 + MAX_SUPPORTING_PAGES)
    page_texts = []
    writer = PdfWriter()
    for idx in range(1, end):
        page = reader.pages[idx]
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        page_texts.append({"page": idx + 1, "text": text[:12000]})
        writer.add_page(page)

    tmp = tempfile.NamedTemporaryFile(prefix="gpi-supporting-", suffix=".pdf", delete=False)
    tmp_path = tmp.name
    tmp.close()
    with open(tmp_path, "wb") as handle:
        writer.write(handle)
    return page_count, page_texts, tmp_path


def _strip_json_fence(text: str) -> str:
    value = str(text or "").strip()
    if not value.startswith("```"):
        return value
    lines = value.splitlines()
    body = []
    inside = False
    for line in lines:
        s = line.strip()
        if s.startswith("```json") or (s == "```" and not inside):
            inside = True
            continue
        if s == "```" and inside:
            break
        if inside:
            body.append(line)
    return "\n".join(body).strip()


def _normalize_model_refs(data: Dict[str, Any]) -> Dict[str, Any]:
    output: Dict[str, List[Dict[str, Any]]] = _empty_refs()
    for field in _REFERENCE_FIELDS:
        values = data.get(field) or []
        if not isinstance(values, list):
            values = [values]
        for item in values:
            if isinstance(item, dict):
                value = item.get("value")
                page = item.get("page")
                label = item.get("label")
            else:
                value, page, label = item, None, None
            if value:
                output[field].append(
                    {
                        "value": str(value).strip(),
                        "page": page,
                        "label": label,
                        "source": "supporting_page_ai",
                    }
                )
    return output


def _merge_refs(*sources: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, List[Dict[str, Any]]] = _empty_refs()
    for source in sources:
        for field in _REFERENCE_FIELDS:
            for item in source.get(field) or []:
                merged[field].append(dict(item))
    for field in _REFERENCE_FIELDS:
        seen = set()
        unique = []
        for item in merged[field]:
            key = str(item.get("value") or "").strip().upper()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(item)
        merged[field] = unique
    return merged


async def extract_supporting_references(
    file_path: str,
    file_name: str,
    *,
    primary_document_type: str,
    primary_fields: Optional[Dict[str, Any]] = None,
    model: str = DEFAULT_MODEL,
    llm_enabled: bool = True,
) -> Dict[str, Any]:
    """Extract supporting references without changing primary classification.

    Supporting-page extraction is a PDF-only concept in this service. Image
    files are already single primary documents for this pipeline, so they return
    an empty supporting-reference bundle instead of being sent through pypdf.
    """
    if Path(file_path).suffix.lower() != ".pdf":
        return {
            "primary_document_type": primary_document_type,
            "primary_document_type_locked": True,
            "page_count": 1,
            "supporting_pages_scanned": [],
            "references": _empty_refs(),
            "regex_reference_count": 0,
            "ai_reference_count": 0,
            "model_error": None,
            "primary_fields_preserved": dict(primary_fields or {}),
            "supporting_scan_skipped_reason": "non_pdf_primary",
        }

    page_count = 0
    page_texts: List[Dict[str, Any]] = []
    temp_pdf: Optional[str] = None
    try:
        page_count, page_texts, temp_pdf = _extract_page_text_and_pdf(file_path)
        regex_refs = _regex_supporting_refs(page_texts)
        model_refs: Dict[str, Any] = _empty_refs()
        model_error = None

        if temp_pdf and llm_enabled and EMERGENT_LLM_KEY:
            try:
                from emergentintegrations.llm.chat import LlmChat, UserMessage, FileContentWithMimeType

                chat = LlmChat(
                    api_key=EMERGENT_LLM_KEY,
                    session_id=f"supporting-refs-{uuid.uuid4()}",
                    system_message=(
                        "Extract labeled business references from supporting pages only. "
                        "Do not classify the document and do not infer unlabeled numbers. Return JSON only."
                    ),
                ).with_model("gemini", model)
                file_content = FileContentWithMimeType(
                    file_path=temp_pdf,
                    mime_type="application/pdf",
                )
                prompt = (
                    f"Primary document type is already locked as {primary_document_type}. "
                    "These are supporting pages 2 onward. Extract only explicitly supported references. "
                    "Preserve labels distinctly; never map a generic Reference # into BOL/shipment unless the page labels it that way. "
                    "Return JSON with arrays of objects {value,page,label} for: "
                    + ", ".join(_REFERENCE_FIELDS)
                    + ". JSON only."
                )
                raw = await chat.send_message(UserMessage(text=prompt, file_contents=[file_content]))
                parsed = json.loads(_strip_json_fence(raw))
                model_refs = _normalize_model_refs(parsed)
            except Exception as exc:
                model_error = f"{type(exc).__name__}:{exc}"[:500]
                logger.warning("Supporting-page AI reference extraction failed for %s: %s", file_name, model_error)

        merged = _merge_refs(regex_refs, model_refs)
        return {
            "primary_document_type": primary_document_type,
            "primary_document_type_locked": True,
            "page_count": page_count,
            "supporting_pages_scanned": [p["page"] for p in page_texts],
            "references": merged,
            "regex_reference_count": sum(len(v) for v in regex_refs.values()),
            "ai_reference_count": sum(len(v) for v in model_refs.values()),
            "model_error": model_error,
            "primary_fields_preserved": dict(primary_fields or {}),
        }
    finally:
        if temp_pdf:
            try:
                os.remove(temp_pdf)
            except OSError:
                pass
