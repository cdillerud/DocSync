"""
GPI Document Hub - Classification Pipeline

Five-stage pipeline with explicit quality gates between each stage.
No stage can silently swallow failures.

Stages:
  1. PARSE      - Extract text from the document file
  2. CLASSIFY   - Determine document type (heuristic-first, then LLM)
  3. EXTRACT    - Pull structured fields from document (always LLM)
  4. VALIDATE   - Check extracted data against BC / business rules
  5. ROUTE      - Decide: auto-clear, review, or block

Each stage returns a typed StageResult.  If a quality gate fails, the
pipeline records WHY and stops advancing.  Downstream stages see a clear
"not_run" status instead of inheriting garbage from a failed upstream.
"""

import os
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("classification_pipeline")

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/backend/uploads"))
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")


# =========================================================================
# Result types
# =========================================================================

class StageStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"      # Upstream failure prevented this stage
    NOT_RUN = "not_run"


@dataclass
class StageResult:
    stage: str
    status: StageStatus
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    quality_gate_passed: bool = False
    duration_ms: int = 0


@dataclass
class PipelineResult:
    """Aggregated result from all 5 stages."""
    document_id: str
    stages: Dict[str, StageResult] = field(default_factory=dict)
    final_status: str = "incomplete"   # passed | failed | incomplete
    failure_stage: Optional[str] = None
    failure_reason: Optional[str] = None

    # Convenience accessors populated after pipeline runs
    document_type: str = "Unknown"
    classification_confidence: float = 0.0
    classification_method: str = ""
    extracted_fields: Dict[str, Any] = field(default_factory=dict)
    meaningful_field_count: int = 0
    validation_results: Dict[str, Any] = field(default_factory=dict)
    automation_decision: str = "manual"
    automation_reasoning: str = ""
    readiness_status: str = "blocked"
    readiness_score: int = 0
    readiness_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "final_status": self.final_status,
            "failure_stage": self.failure_stage,
            "failure_reason": self.failure_reason,
            "document_type": self.document_type,
            "classification_confidence": self.classification_confidence,
            "classification_method": self.classification_method,
            "extracted_fields": self.extracted_fields,
            "meaningful_field_count": self.meaningful_field_count,
            "validation_results": self.validation_results,
            "automation_decision": self.automation_decision,
            "automation_reasoning": self.automation_reasoning,
            "readiness_status": self.readiness_status,
            "readiness_score": self.readiness_score,
            "readiness_reasons": self.readiness_reasons,
            "stages": {
                name: {
                    "status": sr.status.value,
                    "quality_gate_passed": sr.quality_gate_passed,
                    "error": sr.error,
                    "duration_ms": sr.duration_ms,
                }
                for name, sr in self.stages.items()
            },
        }


# =========================================================================
# Stage 1: PARSE
# =========================================================================

def _resolve_file_path(doc_id: str, doc: Dict[str, Any]) -> Optional[str]:
    """Find the on-disk file for this document."""
    for key in ("local_file_path", "file_path"):
        fp = doc.get(key)
        if fp and os.path.exists(str(fp)):
            return str(fp)
    candidate = UPLOAD_DIR / doc_id
    if candidate.exists():
        return str(candidate)
    return None


def stage_parse(doc_id: str, doc: Dict[str, Any]) -> StageResult:
    """Extract text content from the document file."""
    t0 = datetime.now(timezone.utc)
    file_path = _resolve_file_path(doc_id, doc)

    if not file_path:
        return StageResult(
            stage="parse",
            status=StageStatus.FAILED,
            error=f"No file on disk for document {doc_id}. "
                  f"Checked local_file_path, file_path, UPLOAD_DIR/{doc_id}.",
            quality_gate_passed=False,
            duration_ms=_ms_since(t0),
        )

    file_name = doc.get("file_name", "unknown")
    ext = file_name.lower().rsplit(".", 1)[-1] if "." in file_name else ""
    text_content = ""
    page_count = 1

    if ext == "pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(file_path)
            page_count = len(reader.pages)
            for i in range(min(page_count, 3)):
                page_text = reader.pages[i].extract_text() or ""
                text_content += page_text + "\n"
        except Exception as e:
            # PDF parsing failed — but the LLM can still read the file directly.
            # Mark text as empty so we proceed with file-based LLM extraction.
            logger.warning(
                "[PARSE] PDF text extraction failed for %s: %s — "
                "LLM will process file directly", doc_id, e,
            )
            text_content = ""
            page_count = 1
    else:
        try:
            with open(file_path, "r", errors="replace") as f:
                text_content = f.read(10000)
        except Exception as e:
            return StageResult(
                stage="parse",
                status=StageStatus.FAILED,
                error=f"File read failed: {e}",
                quality_gate_passed=False,
                duration_ms=_ms_since(t0),
            )

    text_content = text_content.strip()

    # Quality gate: we need EITHER text content OR a file the LLM can read
    # Scanned PDFs may have no extractable text but the LLM can still process them
    has_text = len(text_content) >= 10
    has_file = file_path is not None

    if not has_text and not has_file:
        return StageResult(
            stage="parse",
            status=StageStatus.FAILED,
            error="No text extracted and no file available for LLM processing.",
            data={"file_path": file_path, "text_length": len(text_content),
                  "page_count": page_count},
            quality_gate_passed=False,
            duration_ms=_ms_since(t0),
        )

    if not has_text:
        logger.info(
            "[PARSE] doc=%s No extractable text (%d chars) — LLM will process file directly",
            doc_id, len(text_content),
        )

    logger.info(
        "[PARSE] doc=%s pages=%d text_length=%d file=%s",
        doc_id, page_count, len(text_content), file_path,
    )
    return StageResult(
        stage="parse",
        status=StageStatus.PASSED,
        data={
            "file_path": file_path,
            "file_name": file_name,
            "text_content": text_content,
            "page_count": page_count,
            "ext": ext,
        },
        quality_gate_passed=True,
        duration_ms=_ms_since(t0),
    )


# =========================================================================
# Stage 2: CLASSIFY
# =========================================================================

def stage_classify_heuristic(
    text_content: str, file_name: str
) -> Optional[Dict[str, Any]]:
    """Run deterministic heuristics for fast classification.

    Returns {"document_type", "confidence", "method"} or None.
    """
    from services.document_intel_helpers import (
        _CREDIT_MEMO_PATTERNS,
        _INVOICE_TEXT_PATTERNS,
        _PL_FILENAME_PATTERNS,
        _PL_TEXT_PATTERNS,
        _WR_FILENAME_PATTERNS,
        _WR_TEXT_PATTERNS,
        _BOL_FILENAME_PATTERNS,
        _BOL_TEXT_PATTERNS,
    )

    fn_lower = file_name.lower()
    first_page = text_content[:3000]

    # Order matters: most specific first

    # 1. Credit memo (text)
    if _CREDIT_MEMO_PATTERNS.findall(first_page):
        return {"document_type": "Credit_Memo", "confidence": 0.94,
                "method": "heuristic:credit_memo_text"}

    # 2. Packing list (filename then text)
    if _PL_FILENAME_PATTERNS.search(fn_lower):
        return {"document_type": "Shipping_Document", "confidence": 0.95,
                "method": "heuristic:packing_list_filename"}
    if _PL_TEXT_PATTERNS.findall(first_page):
        return {"document_type": "Shipping_Document", "confidence": 0.92,
                "method": "heuristic:packing_list_text"}

    # 3. Warehouse receipt (filename then text)
    if _WR_FILENAME_PATTERNS.search(fn_lower):
        return {"document_type": "Warehouse_Receipt", "confidence": 0.95,
                "method": "heuristic:warehouse_receipt_filename"}
    if _WR_TEXT_PATTERNS.findall(first_page):
        return {"document_type": "Warehouse_Receipt", "confidence": 0.90,
                "method": "heuristic:warehouse_receipt_text"}

    # 4. BOL (filename then text) — but not if it's also a packing list
    if _BOL_FILENAME_PATTERNS.search(fn_lower):
        return {"document_type": "Shipping_Document", "confidence": 0.95,
                "method": "heuristic:bol_filename"}
    if len(_BOL_TEXT_PATTERNS.findall(first_page)) >= 2:
        return {"document_type": "Shipping_Document", "confidence": 0.92,
                "method": "heuristic:bol_text"}

    # 5. AP Invoice (text) — must have 2+ indicators and NOT be a BOL/PL
    if not _PL_FILENAME_PATTERNS.search(fn_lower) and not _BOL_FILENAME_PATTERNS.search(fn_lower):
        if len(_INVOICE_TEXT_PATTERNS.findall(first_page)) >= 2:
            return {"document_type": "AP_Invoice", "confidence": 0.92,
                    "method": "heuristic:ap_invoice_text"}

    return None


async def stage_classify_llm(
    file_path: str, file_name: str, page_count: int
) -> StageResult:
    """Use Gemini to classify the document type."""
    t0 = datetime.now(timezone.utc)

    if not EMERGENT_LLM_KEY:
        return StageResult(
            stage="classify",
            status=StageStatus.FAILED,
            error="EMERGENT_LLM_KEY not configured",
            quality_gate_passed=False,
            duration_ms=_ms_since(t0),
        )

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage, FileContentWithMimeType
        from services.document_intel_helpers import _CLASSIFY_SYSTEM_PROMPT

        ext = file_name.lower().rsplit(".", 1)[-1] if "." in file_name else ""
        mime_map = {
            "pdf": "application/pdf", "png": "image/png",
            "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "tiff": "image/tiff", "txt": "text/plain",
        }
        mime_type = mime_map.get(ext, "text/plain")

        # For multi-page PDFs, send only page 1
        actual_path = file_path
        temp_path = None
        if ext == "pdf" and page_count > 1:
            try:
                from services.document_intel_helpers import _extract_first_page_pdf
                actual_path, temp_path, _ = _extract_first_page_pdf(file_path)
            except Exception:
                actual_path = file_path

        # Build dynamic prompt with learned examples
        dynamic_prompt = _CLASSIFY_SYSTEM_PROMPT
        try:
            from services.classification_feedback_service import (
                build_few_shot_prompt_section,
                build_vendor_hints_prompt_section,
            )
            few_shot = await build_few_shot_prompt_section()
            if few_shot:
                dynamic_prompt += "\n" + few_shot
            vendor_hint = await build_vendor_hints_prompt_section(file_name)
            if vendor_hint:
                dynamic_prompt += "\n" + vendor_hint
        except Exception:
            pass

        # Add feedback loop context — learned corrections from user interactions
        try:
            from services.feedback_loop_service import build_feedback_context_for_prompt
            from deps import get_db
            feedback_db = get_db()
            feedback_context = await build_feedback_context_for_prompt(feedback_db)
            if feedback_context:
                dynamic_prompt += "\n\n" + feedback_context
        except Exception:
            pass

        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"classify-{uuid.uuid4()}",
            system_message=dynamic_prompt,
        ).with_model("gemini", "gemini-3-flash-preview")

        file_content = FileContentWithMimeType(
            file_path=actual_path, mime_type=mime_type
        )

        bundle_note = ""
        if page_count > 1:
            bundle_note = (
                f" NOTE: This is page 1 of a {page_count}-page document bundle. "
                "Classify based on THIS page only."
            )

        response = await chat.send_message(UserMessage(
            text=(
                "Please analyze this business document. "
                "Classify the document and extract all relevant fields. "
                "Also extract routing fields: is_international, is_tooling, "
                "is_storage_handling, is_credit_memo, is_dunnage, freight_direction."
                + bundle_note
                + " Respond with JSON only."
            ),
            file_contents=[file_content],
        ))

        if temp_path:
            try:
                os.remove(temp_path)
            except Exception:
                pass

        import json
        response_text = response.strip()
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            json_lines = []
            in_json = False
            for line in lines:
                if line.startswith("```json"):
                    in_json = True
                    continue
                if line.startswith("```") and in_json:
                    break
                if in_json:
                    json_lines.append(line)
            response_text = "\n".join(json_lines)

        result = json.loads(response_text)

        doc_type = result.get("document_type", "Unknown")
        confidence = float(result.get("confidence", 0.0))
        extracted = result.get("extracted_fields", {})

        logger.info(
            "[CLASSIFY:LLM] type=%s conf=%.2f fields=%d pages=%d",
            doc_type, confidence, len(extracted), page_count,
        )

        return StageResult(
            stage="classify",
            status=StageStatus.PASSED,
            data={
                "document_type": doc_type,
                "confidence": confidence,
                "method": "llm:gemini-3-flash-preview",
                "reasoning": result.get("reasoning", ""),
                "llm_extracted_fields": extracted,
                "page_count": page_count,
            },
            quality_gate_passed=confidence >= 0.30,
            duration_ms=_ms_since(t0),
        )

    except Exception as e:
        logger.error("[CLASSIFY:LLM] failed: %s", e)
        if "temp_path" in dir() and temp_path:
            try:
                os.remove(temp_path)
            except Exception:
                pass
        return StageResult(
            stage="classify",
            status=StageStatus.FAILED,
            error=str(e),
            quality_gate_passed=False,
            duration_ms=_ms_since(t0),
        )


async def stage_classify(
    parse_result: StageResult, doc: Dict[str, Any]
) -> StageResult:
    """Run classification: heuristic first, then LLM.

    The LLM is ALWAYS called (for extraction), but if a heuristic
    matches, the heuristic's type/confidence take priority.
    """
    t0 = datetime.now(timezone.utc)
    text_content = parse_result.data["text_content"]
    file_name = parse_result.data["file_name"]
    file_path = parse_result.data["file_path"]
    page_count = parse_result.data["page_count"]

    # Only run heuristics if we have text to analyze
    heuristic = None
    if text_content and len(text_content) >= 10:
        heuristic = stage_classify_heuristic(text_content, file_name)

    # Always call LLM for classification + extraction
    llm_result = await stage_classify_llm(file_path, file_name, page_count)

    if heuristic:
        # Heuristic provides type; LLM provides extraction fields
        doc_type = heuristic["document_type"]
        confidence = heuristic["confidence"]
        method = heuristic["method"]
        llm_fields = {}
        if llm_result.status == StageStatus.PASSED:
            llm_fields = llm_result.data.get("llm_extracted_fields", {})
            method += "+llm"

        logger.info(
            "[CLASSIFY] Heuristic=%s (%.2f) + LLM fields=%d",
            doc_type, confidence, len(llm_fields),
        )
        return StageResult(
            stage="classify",
            status=StageStatus.PASSED,
            data={
                "document_type": doc_type,
                "confidence": confidence,
                "method": method,
                "reasoning": "Heuristic classification, LLM extraction",
                "llm_extracted_fields": llm_fields,
                "page_count": page_count,
            },
            quality_gate_passed=True,
            duration_ms=_ms_since(t0),
        )

    # No heuristic — use LLM result
    if llm_result.status == StageStatus.PASSED:
        return StageResult(
            stage="classify",
            status=llm_result.status,
            data=llm_result.data,
            error=llm_result.error,
            quality_gate_passed=llm_result.quality_gate_passed,
            duration_ms=_ms_since(t0),
        )

    # Both failed
    return StageResult(
        stage="classify",
        status=StageStatus.FAILED,
        error=f"Heuristic: no match. LLM: {llm_result.error}",
        quality_gate_passed=False,
        duration_ms=_ms_since(t0),
    )


# =========================================================================
# Stage 3: EXTRACT (quality gate on meaningful fields)
# =========================================================================

def stage_extract(
    classify_result: StageResult, doc: Dict[str, Any]
) -> StageResult:
    """Assemble and validate extracted fields.

    The LLM already returned fields during classify; this stage merges
    them with any existing document fields, then enforces the quality gate.
    """
    t0 = datetime.now(timezone.utc)

    llm_fields = classify_result.data.get("llm_extracted_fields", {})
    existing_fields = doc.get("extracted_fields") or {}

    # Merge: LLM fields take priority, but keep existing non-empty values
    merged = {**existing_fields}
    for k, v in llm_fields.items():
        if v:  # Only override with non-empty values
            merged[k] = v

    # Also pull in top-level document fields
    for raw_key, clean_key in [
        ("vendor_raw", "vendor"), ("amount_raw", "amount"),
        ("invoice_number_raw", "invoice_number"),
    ]:
        if doc.get(raw_key) and not merged.get(clean_key):
            merged[clean_key] = doc[raw_key]
    if doc.get("po_number_clean") and not merged.get("po_number"):
        merged["po_number"] = doc["po_number_clean"]
    if doc.get("invoice_number_clean") and not merged.get("invoice_number"):
        merged["invoice_number"] = doc["invoice_number_clean"]

    # Quality gate: count MEANINGFUL fields (exclude metadata)
    meaningful = {
        k: v for k, v in merged.items()
        if v and not k.endswith("_detected_by")
    }
    meaningful_count = len(meaningful)

    # Minimum varies by type, but we need at least 1 real field
    min_fields = 1
    doc_type = classify_result.data.get("document_type", "Unknown")
    if doc_type in ("AP_Invoice", "Credit_Memo"):
        min_fields = 2  # Need at least vendor + one other field
    elif doc_type in ("Shipping_Document", "Warehouse_Receipt"):
        min_fields = 1  # At least one shipping field

    gate_passed = meaningful_count >= min_fields

    if not gate_passed:
        logger.warning(
            "[EXTRACT] Quality gate FAILED: %d meaningful fields (need %d) for %s",
            meaningful_count, min_fields, doc_type,
        )

    logger.info(
        "[EXTRACT] doc_type=%s total_fields=%d meaningful=%d gate=%s",
        doc_type, len(merged), meaningful_count,
        "PASSED" if gate_passed else "FAILED",
    )

    return StageResult(
        stage="extract",
        status=StageStatus.PASSED if gate_passed else StageStatus.FAILED,
        data={
            "extracted_fields": merged,
            "meaningful_count": meaningful_count,
            "min_required": min_fields,
        },
        error=None if gate_passed else (
            f"Only {meaningful_count} meaningful fields extracted "
            f"(need {min_fields}). Document may be a scan without OCR "
            f"or the AI could not parse it."
        ),
        quality_gate_passed=gate_passed,
        duration_ms=_ms_since(t0),
    )


# =========================================================================
# Stage 4: VALIDATE
# =========================================================================

async def stage_validate(
    doc_type: str, extracted_fields: Dict[str, Any]
) -> StageResult:
    """Run BC validation on extracted fields."""
    t0 = datetime.now(timezone.utc)

    try:
        from models.document_types import DEFAULT_JOB_TYPES
        from services.bc_validation_service import validate_bc_match

        job_config = DEFAULT_JOB_TYPES.get(doc_type)
        if not job_config:
            for k, v in DEFAULT_JOB_TYPES.items():
                if k.upper().replace("_", "") == doc_type.upper().replace("_", ""):
                    job_config = v
                    break
            if not job_config:
                job_config = DEFAULT_JOB_TYPES.get("AP_Invoice", {})

        validation_results = await validate_bc_match(
            doc_type, extracted_fields, job_config
        )

        gate_passed = validation_results.get("all_passed", False)

        logger.info(
            "[VALIDATE] type=%s all_passed=%s checks=%d warnings=%d",
            doc_type, gate_passed,
            len(validation_results.get("checks", [])),
            len(validation_results.get("warnings", [])),
        )

        return StageResult(
            stage="validate",
            status=StageStatus.PASSED if gate_passed else StageStatus.FAILED,
            data={"validation_results": validation_results, "job_config": job_config},
            error=None if gate_passed else "BC validation failed",
            quality_gate_passed=gate_passed,
            duration_ms=_ms_since(t0),
        )

    except Exception as e:
        logger.error("[VALIDATE] failed: %s", e)
        return StageResult(
            stage="validate",
            status=StageStatus.FAILED,
            error=str(e),
            data={"validation_results": {
                "all_passed": False, "checks": [],
                "error": str(e),
            }},
            quality_gate_passed=False,
            duration_ms=_ms_since(t0),
        )


# =========================================================================
# Stage 5: ROUTE
# =========================================================================

def stage_route(
    classification_confidence: float,
    validation_results: Dict[str, Any],
    extracted_fields: Dict[str, Any],
    doc_type: str,
    job_config: Dict[str, Any],
) -> StageResult:
    """Determine automation decision and readiness."""
    t0 = datetime.now(timezone.utc)

    try:
        from services.document_intel_helpers import make_automation_decision

        decision, reasoning, metadata = make_automation_decision(
            job_config, classification_confidence, validation_results
        )

        # Import the readiness derivation from the intelligence service
        from services.document_intelligence_service import _derive_automation_readiness

        readiness = _derive_automation_readiness(
            classification_confidence=classification_confidence,
            extracted_fields=extracted_fields,
            doc_type=doc_type,
            validation_results=validation_results,
            automation_decision=decision,
        )

        logger.info(
            "[ROUTE] decision=%s readiness=%s score=%d",
            decision, readiness["status"], readiness["score"],
        )

        return StageResult(
            stage="route",
            status=StageStatus.PASSED,
            data={
                "automation_decision": decision,
                "automation_reasoning": reasoning,
                "readiness_status": readiness["status"],
                "readiness_score": readiness["score"],
                "readiness_reasons": readiness["reasons"],
            },
            quality_gate_passed=True,
            duration_ms=_ms_since(t0),
        )

    except Exception as e:
        logger.error("[ROUTE] failed: %s", e)
        return StageResult(
            stage="route",
            status=StageStatus.FAILED,
            error=str(e),
            data={
                "automation_decision": "manual",
                "automation_reasoning": f"Routing failed: {e}",
                "readiness_status": "blocked",
                "readiness_score": 0,
                "readiness_reasons": [f"routing_error: {e}"],
            },
            quality_gate_passed=False,
            duration_ms=_ms_since(t0),
        )


# =========================================================================
# Pipeline orchestrator
# =========================================================================

async def run_pipeline(doc_id: str, doc: Dict[str, Any]) -> PipelineResult:
    """Run the full 5-stage classification pipeline.

    Returns a PipelineResult with clear status for each stage.
    Stops advancing when a quality gate fails, but still records
    all attempted stages.
    """
    result = PipelineResult(document_id=doc_id)
    existing_type = doc.get("suggested_job_type") or doc.get("doc_type") or "Unknown"
    existing_confidence = doc.get("ai_confidence", 0.0)

    # ----- Stage 1: PARSE -----
    parse = stage_parse(doc_id, doc)
    result.stages["parse"] = parse

    if not parse.quality_gate_passed:
        logger.warning("[PIPELINE] PARSE failed for %s: %s", doc_id, parse.error)
        result.final_status = "failed"
        result.failure_stage = "parse"
        result.failure_reason = parse.error
        # Preserve existing data
        result.document_type = existing_type
        result.classification_confidence = existing_confidence
        result.extracted_fields = doc.get("extracted_fields") or {}
        return result

    # ----- Stage 2: CLASSIFY -----
    classify = await stage_classify(parse, doc)
    result.stages["classify"] = classify

    if classify.status == StageStatus.PASSED:
        result.document_type = classify.data.get("document_type", existing_type)
        result.classification_confidence = classify.data.get("confidence", existing_confidence)
        result.classification_method = classify.data.get("method", "")
    else:
        logger.warning("[PIPELINE] CLASSIFY failed for %s: %s", doc_id, classify.error)
        result.final_status = "failed"
        result.failure_stage = "classify"
        result.failure_reason = classify.error
        result.document_type = existing_type
        result.classification_confidence = existing_confidence
        result.extracted_fields = doc.get("extracted_fields") or {}
        return result

    # ----- Stage 3: EXTRACT -----
    extract = stage_extract(classify, doc)
    result.stages["extract"] = extract
    result.extracted_fields = extract.data.get("extracted_fields", {})
    result.meaningful_field_count = extract.data.get("meaningful_count", 0)

    # ----- Stage 3b: VENDOR INFERENCE FALLBACK -----
    # If vendor wasn't extracted by LLM, try filename/number pattern inference + BC cross-ref
    vendor_field = result.extracted_fields.get("vendor", "")
    if not vendor_field or vendor_field.lower() in ("", "unknown", "n/a"):
        try:
            from services.vendor_inference_service import infer_vendor_async
            from deps import get_db
            db = get_db()
            file_name = doc.get("file_name") or doc.get("original_filename") or ""
            batch_id = doc.get("batch_id") or doc.get("email_message_id")
            inferred_vendor, infer_method = await infer_vendor_async(
                db, file_name, result.extracted_fields, batch_id
            )
            if inferred_vendor:
                result.extracted_fields["vendor"] = inferred_vendor
                result.extracted_fields["vendor_inferred_by"] = infer_method
                logger.info(
                    "[PIPELINE] Vendor inferred for %s: %s (method=%s)",
                    doc_id, inferred_vendor, infer_method,
                )
        except Exception as e:
            logger.debug("[PIPELINE] Vendor inference skipped: %s", e)

    if not extract.quality_gate_passed:
        logger.warning(
            "[PIPELINE] EXTRACT quality gate failed for %s: %s",
            doc_id, extract.error,
        )
        # Don't stop the pipeline for low extraction — still validate and route
        # but record the failure for visibility

    # ----- Stage 4: VALIDATE -----
    validate = await stage_validate(result.document_type, result.extracted_fields)
    result.stages["validate"] = validate
    result.validation_results = validate.data.get("validation_results", {})

    # ----- Stage 5: ROUTE -----
    job_config = validate.data.get("job_config", {})
    route = stage_route(
        result.classification_confidence,
        result.validation_results,
        result.extracted_fields,
        result.document_type,
        job_config,
    )
    result.stages["route"] = route
    result.automation_decision = route.data.get("automation_decision", "manual")
    result.automation_reasoning = route.data.get("automation_reasoning", "")
    result.readiness_status = route.data.get("readiness_status", "blocked")
    result.readiness_score = route.data.get("readiness_score", 0)
    result.readiness_reasons = route.data.get("readiness_reasons", [])

    # ----- Determine final status -----
    all_passed = all(
        s.quality_gate_passed for s in result.stages.values()
    )
    any_failed = any(
        s.status == StageStatus.FAILED for s in result.stages.values()
    )

    if all_passed:
        result.final_status = "passed"
    elif any_failed:
        result.final_status = "failed"
        # Find first failure
        for name in ["parse", "classify", "extract", "validate", "route"]:
            sr = result.stages.get(name)
            if sr and sr.status == StageStatus.FAILED:
                result.failure_stage = name
                result.failure_reason = sr.error
                break
    else:
        result.final_status = "passed"  # All ran, no hard failures

    logger.info(
        "[PIPELINE] doc=%s final=%s type=%s conf=%.2f fields=%d decision=%s "
        "stages: %s",
        doc_id, result.final_status, result.document_type,
        result.classification_confidence, result.meaningful_field_count,
        result.automation_decision,
        " | ".join(
            f"{n}:{s.status.value}" for n, s in result.stages.items()
        ),
    )

    return result


# =========================================================================
# Helpers
# =========================================================================

def _ms_since(t0: datetime) -> int:
    return int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
