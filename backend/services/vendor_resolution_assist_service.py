"""
GPI Document Hub - LLM-Assisted Vendor Resolution Ranking

When fuzzy matching produces multiple candidate vendors and cannot
confidently pick one, this service asks the LLM to rank the shortlist.
Read-only — never writes to the database.
"""

import json
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

from services.llm_router import get_provider
from services.providers.base_provider import LLMProviderError

logger = logging.getLogger(__name__)

MAX_CANDIDATES = 10


@dataclass
class VendorRankingResult:
    selected_vendor_id: Optional[str]
    selected_vendor_name: Optional[str]
    confidence: float
    reason: str
    candidates_evaluated: int
    model_used: str
    generated_at: str
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


async def rank_vendor_candidates(
    vendor_raw: str,
    candidates: List[Dict[str, Any]],
    document_context: Optional[Dict[str, Any]] = None,
) -> VendorRankingResult:
    generated_at = datetime.now(timezone.utc).isoformat()

    # --- trivial early returns ---
    if not candidates:
        return VendorRankingResult(
            selected_vendor_id=None,
            selected_vendor_name=None,
            confidence=0.0,
            reason="No candidates provided",
            candidates_evaluated=0,
            model_used="none",
            generated_at=generated_at,
            error="No candidates provided",
        )

    if len(candidates) == 1:
        c = candidates[0]
        return VendorRankingResult(
            selected_vendor_id=c.get("vendor_id"),
            selected_vendor_name=c.get("vendor_name"),
            confidence=1.0,
            reason="Only one candidate",
            candidates_evaluated=1,
            model_used="none",
            generated_at=generated_at,
        )

    # --- cap at top-10 by match_score ---
    ranked = sorted(candidates, key=lambda x: float(x.get("match_score", 0)), reverse=True)[:MAX_CANDIDATES]

    # --- obtain provider ---
    try:
        provider = get_provider("classification")
    except LLMProviderError as e:
        return VendorRankingResult(
            selected_vendor_id=None,
            selected_vendor_name=None,
            confidence=0.0,
            reason="",
            candidates_evaluated=len(ranked),
            model_used="none",
            generated_at=generated_at,
            error=str(e),
        )

    model_used = type(provider).__name__

    # --- build prompt ---
    candidate_lines = []
    valid_ids = set()
    for i, c in enumerate(ranked, 1):
        vid = c.get("vendor_id", "")
        vname = c.get("vendor_name", "")
        aliases = c.get("aliases", [])
        score = c.get("match_score", "")
        valid_ids.add(vid)
        alias_str = f', aliases: {", ".join(aliases)}' if aliases else ""
        score_str = f", match_score: {score}" if score else ""
        candidate_lines.append(f"  {i}. vendor_id=\"{vid}\", vendor_name=\"{vname}\"{alias_str}{score_str}")

    doc_ctx = ""
    if document_context:
        parts = []
        for k in ("doc_type", "invoice_number_clean", "amount_float"):
            v = document_context.get(k)
            if v is not None:
                parts.append(f"{k}: {v}")
        if parts:
            doc_ctx = "\nDocument context: " + ", ".join(parts)

    system_prompt = (
        "You are a vendor-name disambiguation expert for a business document hub. "
        "Given a raw vendor string from a document and a shortlist of candidate vendors "
        "from the master database, select the single best match. "
        "Respond ONLY with a JSON object in this exact schema:\n"
        '{\n'
        '  "selected_vendor_id": "string or null",\n'
        '  "confidence": 0.0,\n'
        '  "reason": "one sentence explaining the match"\n'
        '}\n'
        "If none of the candidates is a reasonable match, set selected_vendor_id to null "
        "and confidence below 0.3. Do not include any text outside the JSON object."
    )

    user_prompt = (
        f'Raw vendor string from document: "{vendor_raw}"\n'
        f"{doc_ctx}\n\n"
        f"Candidate vendors:\n"
        + "\n".join(candidate_lines)
    )

    try:
        raw = await provider.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            session_id=f"vendor_rank_{vendor_raw[:30]}",
            expect_json=True,
        )
        logger.info("Vendor ranking raw response: %s", raw)

        # parse JSON
        text = raw.strip()
        if text.startswith("{"):
            json_str = text
        elif "{" in text:
            json_str = text[text.find("{"):text.rfind("}") + 1]
        else:
            raise ValueError(f"No JSON found in response: {text[:200]}")

        data = json.loads(json_str)
        sel_id = data.get("selected_vendor_id")
        conf = float(data.get("confidence", 0.0))
        reason = data.get("reason", "")

        # --- safety check ---
        if sel_id is not None and sel_id not in valid_ids:
            return VendorRankingResult(
                selected_vendor_id=None,
                selected_vendor_name=None,
                confidence=0.0,
                reason=reason,
                candidates_evaluated=len(ranked),
                model_used=model_used,
                generated_at=generated_at,
                error="Model selected vendor not in candidate list",
            )

        sel_name = None
        if sel_id is not None:
            for c in ranked:
                if c.get("vendor_id") == sel_id:
                    sel_name = c.get("vendor_name")
                    break

        return VendorRankingResult(
            selected_vendor_id=sel_id,
            selected_vendor_name=sel_name,
            confidence=max(0.0, min(1.0, conf)),
            reason=reason,
            candidates_evaluated=len(ranked),
            model_used=model_used,
            generated_at=generated_at,
        )

    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Failed to parse vendor ranking response: %s", e)
        return VendorRankingResult(
            selected_vendor_id=None,
            selected_vendor_name=None,
            confidence=0.0,
            reason="",
            candidates_evaluated=len(ranked),
            model_used=model_used,
            generated_at=generated_at,
            error="Failed to parse model response",
        )

    except LLMProviderError as e:
        logger.error("LLM provider error during vendor ranking: %s", e)
        return VendorRankingResult(
            selected_vendor_id=None,
            selected_vendor_name=None,
            confidence=0.0,
            reason="",
            candidates_evaluated=len(ranked),
            model_used=model_used,
            generated_at=generated_at,
            error=str(e),
        )

    except Exception as e:
        logger.error("Vendor ranking failed: %s", e)
        return VendorRankingResult(
            selected_vendor_id=None,
            selected_vendor_name=None,
            confidence=0.0,
            reason="",
            candidates_evaluated=len(ranked),
            model_used=model_used,
            generated_at=generated_at,
            error=str(e),
        )
