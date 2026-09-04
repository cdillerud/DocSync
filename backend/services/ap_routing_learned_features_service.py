"""Route-neutral document features for learned AP routing.

These features improve example retrieval and learned-authority similarity. They
never inspect route names and never select a route. They describe the current
business document: reference shape, document purpose, and semantic markers.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Set


def _flatten(value: Any, *, limit: int = 80) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        chunks = []
        for key, item in list(value.items())[:limit]:
            chunks.append(str(key))
            chunks.append(_flatten(item, limit=limit))
        return " ".join(chunks)
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten(item, limit=limit) for item in list(value)[:limit])
    return str(value)


def document_text(document: Dict[str, Any]) -> str:
    return " ".join(
        [
            str(document.get("file_name") or ""),
            str(document.get("raw_text") or document.get("raw_text_excerpt") or "")[:20000],
            _flatten(document.get("extracted_fields") or {}),
            _flatten(document.get("normalized_fields") or {}),
        ]
    )


def reference_family(document: Dict[str, Any]) -> str:
    """Return a structural reference family without mapping it to a route."""
    file_name = str(document.get("file_name") or "").replace("\\", "/").rsplit("/", 1)[-1]
    upper = file_name.upper()
    if re.search(r"(?<![A-Z0-9])WTR\s*[-_ ]?\d{2,7}(?![A-Z0-9])", upper):
        return "wtr_reference"
    if re.search(r"(?<![A-Z0-9])WA\s*[-_ ]?\d{2,7}(?![A-Z0-9])", upper):
        return "wa_reference"
    if re.search(r"(?<![A-Z0-9])W\d{4,7}[A-Z]?(?![A-Z0-9])", upper):
        return "w_reference"

    stem = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", file_name).strip()
    first = re.split(r"[_\s]+", stem, maxsplit=1)[0].strip("-") if stem else ""
    if re.fullmatch(r"\d{4,7}[A-Z]?", first, flags=re.IGNORECASE):
        return "numeric_reference"
    if re.fullmatch(r"[A-Z]{1,3}\d{3,7}[A-Z]?", first, flags=re.IGNORECASE):
        return "alpha_reference"
    return "descriptor_or_none"


_SEMANTIC_PATTERNS = {
    "explicit_stop_pay": re.compile(
        r"\b(?:do\s+not\s+pay|don['’]?t\s+pay|dont\s+pay|do\s+not\s+process|hold\s+payment)\b",
        re.IGNORECASE,
    ),
    "replacement_or_offset": re.compile(
        r"\b(?:replaced\s+by|replacement|offset|issued\s+in\s+error|wrong\s+cost|cost\s+is\s+wrong)\b",
        re.IGNORECASE,
    ),
    "reversal_or_void": re.compile(
        r"(?:\b(?:reversing|reverse|reversed|reversal)\b.{0,40}\b(?:credit\s+memo|invoice)\b)"
        r"|(?:\b(?:credit\s+memo|invoice)\b.{0,40}\b(?:reversing|reverse|reversed|reversal|voided|cancelled|canceled)\b)"
        r"|(?:\b(?:voided|cancelled|canceled)\b.{0,40}\b(?:credit\s+memo|invoice)\b)",
        re.IGNORECASE,
    ),
    "detention": re.compile(r"\bdetention\b", re.IGNORECASE),
    "storage_accessorial": re.compile(
        r"\b(?:yard\s+storage|storage\s+(?:fee|charge|cost)|accessorial|demurrage|layover|lumper|redelivery)\b",
        re.IGNORECASE,
    ),
    "freight": re.compile(r"\bfreight\b", re.IGNORECASE),
    "dunnage": re.compile(r"\bdunnage\b", re.IGNORECASE),
    "inventory": re.compile(r"\binventory\b", re.IGNORECASE),
    "reconciliation": re.compile(r"\b(?:reconciliation|reconcile|reconcil(?:e|iation)|\brecon\b)\b", re.IGNORECASE),
    "credit_document": re.compile(r"\b(?:credit\s+memo|credit\s+for|vendor\s+credit)\b", re.IGNORECASE),
    "return": re.compile(r"\b(?:return|returned|returns)\b", re.IGNORECASE),
    "quality_or_claim": re.compile(r"\b(?:quality\s+claim|claim|replacement)\b", re.IGNORECASE),
    "cost_variance": re.compile(r"\bcost\s+variance\b", re.IGNORECASE),
    "bol": re.compile(r"\b(?:BOL|bill\s+of\s+lading)\b", re.IGNORECASE),
    "international": re.compile(r"\b(?:international|customs|ocean\s+freight|import|export)\b", re.IGNORECASE),
}


def semantic_features(document: Dict[str, Any]) -> Set[str]:
    text = document_text(document)
    return {name for name, pattern in _SEMANTIC_PATTERNS.items() if pattern.search(text)}


def feature_similarity(current: Dict[str, Any], example: Dict[str, Any]) -> Dict[str, Any]:
    """Score route-neutral workflow similarity and expose auditable features."""
    current_ref = reference_family(current)
    example_ref = reference_family(example)
    current_sem = semantic_features(current)
    example_sem = semantic_features(example)
    score = 0.0
    signals = []

    current_type = str(current.get("document_type") or current.get("suggested_job_type") or "").strip().lower()
    example_type = str(example.get("document_type") or example.get("suggested_job_type") or "").strip().lower()
    if current_type and example_type:
        if current_type == example_type:
            score += 2.0
            signals.append("document_type_match")
        else:
            score -= 1.5
            signals.append("document_type_mismatch")

    structural = {"wtr_reference", "wa_reference", "w_reference", "numeric_reference", "alpha_reference"}
    if current_ref in structural and example_ref in structural:
        if current_ref == example_ref:
            score += 5.0
            signals.append("reference_family_match")
        else:
            score -= 3.0
            signals.append("reference_family_mismatch")

    overlap = current_sem.intersection(example_sem)
    if overlap:
        score += min(5.0, 1.25 * len(overlap))
        signals.extend(f"semantic:{name}" for name in sorted(overlap))

    # These features are unusually discriminating workflow evidence. Penalizing
    # a mismatch improves retrieval without assigning either side to a route.
    for feature, penalty in {
        "explicit_stop_pay": 4.0,
        "replacement_or_offset": 4.0,
        "reversal_or_void": 4.0,
        "detention": 2.5,
        "inventory": 2.0,
        "dunnage": 1.5,
        "cost_variance": 2.0,
        "quality_or_claim": 1.5,
    }.items():
        if (feature in current_sem) != (feature in example_sem):
            score -= penalty
            signals.append(f"semantic_mismatch:{feature}")

    return {
        "score": round(score, 4),
        "current_reference_family": current_ref,
        "example_reference_family": example_ref,
        "current_semantic_features": sorted(current_sem),
        "example_semantic_features": sorted(example_sem),
        "shared_semantic_features": sorted(overlap),
        "signals": signals,
    }
