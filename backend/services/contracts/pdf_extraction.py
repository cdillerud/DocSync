"""Phase 4C(c) — Orchestrator: PDF bytes → ExtractionResult (preview shape).

Pipeline:
  1.  Bytes → text (services.contracts.pdf_text_extractor)
  2.  Text  → fields + per-line pricing (services.contracts.pdf_field_extractors)
  3.  Fields → ExtractionResult (this module): preview shape suitable for
      both dry-run (return-only) and commit (passed to
      ContractIntelligenceService.ingest_pdf_extraction).

Strict guarantees:
  * No DocuSign calls, no BC calls, no DB writes here.
  * No LLM calls, no network I/O.
  * Idempotent: calling twice with the same PDF + same agreement id
    yields identical preview output.
  * Ambiguity is **detected**, not silently resolved — the orchestrator
    surfaces same-key conflicts so the persistence layer can emit
    ``pdf_extraction_ambiguous`` exceptions.

Used by:
  * scripts.contracts_extract_pdf (CLI)
  * routers.contracts (HTTP endpoint)
  * ContractIntelligenceService.ingest_pdf_extraction (commit path)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from services.contracts.pdf_field_extractors import (
    ExtractedField,
    ExtractedLinePricing,
    extract_all_fields,
)
from services.contracts.pdf_text_extractor import (
    PDFExtractionError,
    extract_text_from_pdf,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AmbiguityNote:
    key: str
    candidates: List[Dict[str, Any]]


@dataclass
class ExtractionResult:
    """End-to-end preview of a PDF extraction.

    The orchestrator never writes to MongoDB. ``ingest_pdf_extraction``
    on :class:`ContractIntelligenceService` consumes this result.
    """

    agreement_id: str
    filename: Optional[str] = None
    page_count: int = 0
    bytes_size: int = 0
    text_chars: int = 0

    fields: List[ExtractedField] = field(default_factory=list)
    line_pricing: List[ExtractedLinePricing] = field(default_factory=list)
    ambiguities: List[AmbiguityNote] = field(default_factory=list)

    # If text extraction failed entirely, we surface a single error
    # string; the caller decides how to expose it (HTTP 4xx, CLI exit
    # code 3, exception row).
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # asdict on dataclass-of-dataclasses already cascades; nothing
        # extra needed — but normalize ExtractedField list which uses
        # ``extras`` dicts.
        return d

    @property
    def field_count(self) -> int:
        return len(self.fields)

    @property
    def has_ambiguity(self) -> bool:
        return bool(self.ambiguities)


# ---------------------------------------------------------------------------
# Public orchestrator
# ---------------------------------------------------------------------------


def run_extraction(
    *, agreement_id: str, data: bytes, filename: Optional[str] = None,
) -> ExtractionResult:
    """Drive the full PDF → fields pipeline. Pure, no DB, no I/O beyond
    in-memory pypdf parsing.

    Returns an :class:`ExtractionResult`. On unrecoverable text-extraction
    failure, ``result.error`` is populated and ``fields`` is empty —
    callers decide whether to raise / 4xx / log.
    """
    if not agreement_id:
        raise ValueError("agreement_id is required for PDF extraction")

    try:
        extracted = extract_text_from_pdf(data)
    except PDFExtractionError as exc:
        return ExtractionResult(
            agreement_id=agreement_id,
            filename=filename,
            page_count=0,
            bytes_size=len(data) if data else 0,
            text_chars=0,
            error=str(exc),
        )

    raw = extract_all_fields(extracted.full_text)
    fields: List[ExtractedField] = list(raw["fields"])
    line_pricing: List[ExtractedLinePricing] = list(raw["line_pricing"])

    ambiguities = _detect_ambiguities(fields)

    return ExtractionResult(
        agreement_id=agreement_id,
        filename=filename,
        page_count=extracted.page_count,
        bytes_size=extracted.bytes_size,
        text_chars=len(extracted.full_text),
        fields=fields,
        line_pricing=line_pricing,
        ambiguities=ambiguities,
    )


def _detect_ambiguities(fields: List[ExtractedField]) -> List[AmbiguityNote]:
    """Two distinct values for the same ``key`` → ambiguity.

    For ``moq`` we collapse on the parsed ``quantity`` so legitimate
    re-statements ("MOQ: 25,000 EA" appearing twice) do not falsely
    flag. For ``payment_term_discount`` the de-dup key is the full
    (pct, early_days, net_days) tuple.
    """
    by_key: Dict[str, List[ExtractedField]] = defaultdict(list)
    for f in fields:
        by_key[f.key].append(f)
    out: List[AmbiguityNote] = []
    for key, group in by_key.items():
        if len(group) < 2:
            continue
        # Collapse identical structured values.
        seen_signatures: set = set()
        unique = []
        for f in group:
            sig = _signature_for(f)
            if sig in seen_signatures:
                continue
            seen_signatures.add(sig)
            unique.append(f)
        if len(unique) < 2:
            continue
        out.append(AmbiguityNote(
            key=key,
            candidates=[
                {
                    "value": f.value,
                    "confidence": f.confidence,
                    "raw_text": f.raw_text,
                }
                for f in unique
            ],
        ))
    return out


def _signature_for(f: ExtractedField) -> str:
    """Stable signature for an extracted field. Used to collapse
    duplicates that should not be considered ambiguous."""
    if isinstance(f.value, dict):
        items = sorted(f.value.items(), key=lambda kv: kv[0])
        return f"{f.key}::" + "|".join(f"{k}={v}" for k, v in items)
    return f"{f.key}::{f.value}"
