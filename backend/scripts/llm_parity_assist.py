"""
LLM-assisted parity matching — second-pass judge for Square9-vs-Hub
documents that the regex/token matcher in square9_hub_ap_parity_report.py
could not confidently match.

Why this exists (2026-07-16): every fix made to the parity matcher
tonight was the same shape — find one edge case (a single-letter invoice
prefix, a vendor name with a digit in it, a reversed number/letter
order), hand-write one more regex pattern. That doesn't generalize: the
next new vendor naming convention needs another hand-written pattern.
Meanwhile the live document-processing pipeline (invoice_extractor.py,
ai_classifier.py) already uses Gemini extensively and successfully for
exactly this kind of fuzzy, semantic judgment call. This module brings
that same capability to the parity-matching step itself.

Design, deliberately conservative given this feeds the real cutover
match-rate metric:
  1. Candidate generation stays cheap, deterministic Python (no LLM) —
     for each Square9 doc the regex matcher scored as no_match, find a
     small set of plausible Hub candidates using loose token/date
     signals. This keeps LLM calls bounded (tens, not thousands) and
     keeps the search space small enough for the model to reason about
     well.
  2. Only Square9 docs that already have at least one candidate are
     sent to the LLM at all — no candidates means nothing worth asking
     about, and the row is left as no_match exactly as before.
  3. The LLM is asked to judge conservatively and only report a match
     when it re-identifies genuine shared evidence (same invoice number
     in a different format, matching amount, matching vendor +
     narrow date window) — not "these seem similar."
  4. A confidence floor (LLM_MATCH_CONFIDENCE_FLOOR) is applied on top
     of the model's own judgment before a row is ever promoted to
     llm_assisted_match — the model saying "maybe" is not enough.
  5. Any failure — missing API key, network error, malformed JSON,
     unexpected response shape — degrades to "no rows changed," never
     to a crash. This runs inside the production readiness chain; it
     must never be able to take the whole check down.
  6. Every promoted match is labeled with its own distinct bucket
     (llm_assisted_match) and carries the model's reasoning string in
     the output row, so this is always visibly separate from the
     deterministic regex matches, never silently mixed in.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

# Confidence floor applied on top of the model's own self-reported
# confidence before a match is accepted. Deliberately high — a false
# positive here silently inflates the real cutover-readiness number,
# which is worse than leaving a genuine match unclaimed for a human to
# review in Bucket C.
LLM_MATCH_CONFIDENCE_FLOOR = 0.80

MAX_CANDIDATES_PER_DOC = 3
BATCH_SIZE = 15

SYSTEM_MESSAGE = (
    "You are an expert at reconciling business documents across two "
    "filing systems that use inconsistent naming conventions. You will "
    "be shown a document from System A (Square9) and one or more "
    "candidate documents from System B (Hub) that a cheap heuristic "
    "flagged as plausibly related. For each Square9 document, decide "
    "whether ANY of its candidates is genuinely the same underlying "
    "invoice or shipment document — just filed under a different name, "
    "OCR'd differently, or formatted differently. Be conservative: only "
    "report a match when you can point to real shared evidence (the "
    "same invoice number in a different format, a matching dollar "
    "amount, or a matching vendor plus a close date). Superficial "
    "filename similarity alone is not evidence. If no candidate is a "
    "confident match, say so. Respond with valid JSON only, no "
    "markdown, matching this exact shape: "
    '{"verdicts": [{"square9_name": "<exact name given>", '
    '"matched_hub_doc_id": "<candidate doc_id, or null>", '
    '"confidence": <0.0-1.0>, "reasoning": "<one sentence>"}]}'
)


def _stopword_tokens(name: str) -> set:
    """Cheap tokenization for loose candidate generation - not the same
    strict token extraction used for the deterministic matcher, just
    enough to find plausible neighbors."""
    name = re.sub(r"\.(pdf|xlsx?|docx?|png|jpe?g|tiff?|pst)$", "", name, flags=re.I)
    tokens = re.findall(r"[A-Za-z0-9]+", name.lower())
    return {t for t in tokens if len(t) >= 3}


def find_loose_candidates(
    sq,
    hub_docs: List[Any],
    already_matched_ids: set,
    max_candidates: int = MAX_CANDIDATES_PER_DOC,
) -> List[Any]:
    """Cheap, deterministic candidate generation - no LLM call here.
    Looser than the strict score_pair() buckets on purpose: this only
    needs to narrow ~2000 Hub docs down to a handful of plausible
    neighbors for the LLM to actually reason about, not decide the
    match itself."""
    sq_tokens = _stopword_tokens(sq.name)
    sq_modified = getattr(sq, "modified", None)

    scored: List[Tuple[float, Any]] = []
    for h in hub_docs:
        if h.doc_id in already_matched_ids:
            continue
        hub_tokens = _stopword_tokens(h.file_name)
        overlap = sq_tokens & hub_tokens
        score = float(len(overlap))
        if not overlap:
            # No shared token at all - only keep as a candidate if the
            # dates are close, since that's the only remaining signal.
            if sq_modified and h.created_utc:
                delta_days = abs((sq_modified - h.created_utc).total_seconds()) / 86400
                if delta_days <= 3:
                    score = 0.3
                else:
                    continue
            else:
                continue
        if sq_modified and h.created_utc:
            delta_days = abs((sq_modified - h.created_utc).total_seconds()) / 86400
            if delta_days <= 14:
                score += max(0.0, (14 - delta_days) / 14) * 0.5
        scored.append((score, h))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [h for _, h in scored[:max_candidates]]


def _hub_summary(h) -> Dict[str, Any]:
    return {
        "doc_id": h.doc_id,
        "file_name": h.file_name,
        "vendor_canonical": h.vendor_canonical or None,
        "invoice_number_clean": h.invoice_number_clean or None,
        "amount_float": h.amount_float,
        "created_utc": h.created_utc.isoformat() if h.created_utc else None,
        "email_sender": h.email_sender or None,
        "sharepoint_folder_path": h.sharepoint_folder_path or None,
    }


def _square_summary(sq) -> Dict[str, Any]:
    parent_path = ""
    if isinstance(sq.raw, dict):
        parent_path = (sq.raw.get("parent_path") or "").strip()
    return {
        "name": sq.name,
        "parent_path": parent_path,
        "modified": sq.modified.isoformat() if sq.modified else None,
    }


async def _judge_batch(
    batch: List[Tuple[Any, List[Any]]],
) -> List[Dict[str, Any]]:
    """One LLM call covering up to BATCH_SIZE Square9 docs, each with
    its own small candidate list. Returns the raw parsed verdict list,
    or an empty list on any failure - callers must not assume this
    returns one verdict per input."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage

    payload = {
        "documents": [
            {
                "square9_document": _square_summary(sq),
                "candidates": [_hub_summary(h) for h in candidates],
            }
            for sq, candidates in batch
        ]
    }

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"parity_llm_assist_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        system_message=SYSTEM_MESSAGE,
    ).with_model("gemini", "gemini-2.5-pro")

    prompt = (
        "Judge each Square9 document against its candidates and return "
        "the JSON verdicts shape described in your instructions.\n\n"
        + json.dumps(payload, indent=2)
    )

    response = await chat.send_message(UserMessage(text=prompt))
    response_text = str(response).strip()

    if response_text.startswith("```"):
        lines = response_text.split("\n")
        json_lines = []
        in_json = False
        for line in lines:
            if line.startswith("```"):
                in_json = not in_json
                continue
            if in_json:
                json_lines.append(line)
        response_text = "\n".join(json_lines).strip()

    if response_text.startswith("{"):
        json_str = response_text
    elif "{" in response_text:
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        json_str = response_text[start:end]
    else:
        raise ValueError(f"No JSON object found in LLM response: {response_text[:200]}")

    data = json.loads(json_str)
    verdicts = data.get("verdicts", [])
    if not isinstance(verdicts, list):
        raise ValueError(f"Expected 'verdicts' to be a list, got {type(verdicts)}")
    return verdicts


async def _run_llm_assist_async(
    unmatched_with_candidates: List[Tuple[Any, List[Any]]],
) -> Dict[str, Dict[str, Any]]:
    """Runs all batches sequentially (not concurrently) - deliberately
    conservative on rate/cost for a first version of this capability.
    Returns square9_name -> verdict dict, filtered to accepted matches
    only (confidence >= LLM_MATCH_CONFIDENCE_FLOOR and a non-null
    matched_hub_doc_id that was actually among that doc's candidates)."""
    accepted: Dict[str, Dict[str, Any]] = {}

    candidate_ids_by_name: Dict[str, set] = {
        sq.name: {h.doc_id for h in candidates}
        for sq, candidates in unmatched_with_candidates
    }

    for i in range(0, len(unmatched_with_candidates), BATCH_SIZE):
        batch = unmatched_with_candidates[i:i + BATCH_SIZE]
        try:
            verdicts = await _judge_batch(batch)
        except Exception as e:
            logger.warning(
                "llm_parity_assist: batch %d-%d failed, skipping (no rows "
                "changed for this batch): %s",
                i, i + len(batch), e,
            )
            continue

        for v in verdicts:
            try:
                name = v.get("square9_name")
                matched_id = v.get("matched_hub_doc_id")
                confidence = float(v.get("confidence") or 0.0)
            except (TypeError, ValueError):
                continue
            if not name or not matched_id:
                continue
            if confidence < LLM_MATCH_CONFIDENCE_FLOOR:
                continue
            valid_ids = candidate_ids_by_name.get(name)
            if valid_ids is None or matched_id not in valid_ids:
                # Model hallucinated a doc_id outside what it was shown -
                # reject rather than trust it.
                logger.warning(
                    "llm_parity_assist: rejecting verdict for %r - "
                    "matched_hub_doc_id %r was not among its candidates",
                    name, matched_id,
                )
                continue
            accepted[name] = {
                "matched_hub_doc_id": matched_id,
                "confidence": confidence,
                "reasoning": (v.get("reasoning") or "").strip(),
            }

    return accepted


def run_llm_assist(
    square_docs_no_match: List[Any],
    hub_docs: List[Any],
    already_matched_ids: set,
) -> Dict[str, Dict[str, Any]]:
    """Synchronous entry point for the (synchronous) parity report
    script. Returns square9_name -> {matched_hub_doc_id, confidence,
    reasoning} for accepted matches only. Returns {} on any failure,
    including a missing API key - never raises, this must not be able
    to break the readiness chain."""
    if not EMERGENT_LLM_KEY:
        logger.warning(
            "llm_parity_assist: EMERGENT_LLM_KEY not configured, skipping "
            "LLM-assisted matching (regex-only results unchanged)"
        )
        return {}

    pairs: List[Tuple[Any, List[Any]]] = []
    for sq in square_docs_no_match:
        candidates = find_loose_candidates(sq, hub_docs, already_matched_ids)
        if candidates:
            pairs.append((sq, candidates))

    if not pairs:
        return {}

    try:
        return asyncio.run(_run_llm_assist_async(pairs))
    except Exception as e:
        logger.warning(
            "llm_parity_assist: run_llm_assist failed entirely, skipping "
            "(regex-only results unchanged): %s", e,
        )
        return {}
