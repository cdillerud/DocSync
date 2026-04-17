"""
Inventory XLS Column Mapper + Row Normalizer
─────────────────────────────────────────────

Phase B of the inventory XLS pipeline. Given a classified sheet + its parsed
headers/rows (from file_ingestion_service.parse_excel), produce a canonical
mapping + normalized row list ready for the staging collection.

Lookup order (highest confidence wins):
  1. Learned mapping   — prior approved mapping for same (sender, filename_pattern, header_hash)
  2. Heuristic mapping — regex on normalized header names
  3. LLM fallback      — Claude Haiku via Emergent LLM Key when heuristic coverage <80%

NEVER writes to the ledger. Returns a staging payload only.
"""

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Canonical fields we can map into.
CANONICAL_FIELDS = [
    "item",              # SKU / part number
    "item_description",  # free text description
    "qty",               # quantity delta (signed)
    "warehouse",         # location / plant
    "ownership_type",    # customer_owned | gamer_reserved | mixed
    "uom",               # unit of measure
    "reference",         # PO#/SO#/ASN#
    "effective_date",    # as-of date for balance math
    "notes",
]

REQUIRED_FIELDS = {"item", "qty"}

# Heuristic regex patterns — header normalized to lowercase alphanumeric + underscore.
_HEURISTIC_RULES = {
    "item": [
        r"^item$", r"^sku$", r"^part$", r"^part_number$", r"^item_number$",
        r"^item_no$", r"^product$", r"^product_code$", r"^gamer_item",
    ],
    "item_description": [
        r"^description$", r"^item_description$", r"^product_description$",
        r"^desc$", r"^product_name$",
    ],
    "qty": [
        r"^qty$", r"^quantity$", r"^qty_ordered$", r"^qty_received$",
        r"^on_hand$", r"^available$", r"^balance$", r"^stock$", r"^planned_qty$",
        r"^forecast_qty$", r"^shipped_qty$", r"^actual_qty$", r"^committed$",
    ],
    "warehouse": [
        r"^warehouse$", r"^location$", r"^plant$", r"^site$", r"^whse$",
        r"^facility$", r"^ship_from$",
    ],
    "uom": [r"^uom$", r"^unit$", r"^unit_of_measure$", r"^units$", r"^u_o_m$"],
    "reference": [
        r"^po$", r"^po_number$", r"^po_no$", r"^customer_po$",
        r"^so$", r"^so_number$", r"^so_no$", r"^order_number$",
        r"^asn$", r"^asn_number$", r"^reference$", r"^ref$",
    ],
    "effective_date": [
        r"^date$", r"^as_of$", r"^as_of_date$", r"^snapshot_date$",
        r"^effective_date$", r"^posting_date$", r"^receipt_date$",
        r"^ship_date$", r"^shipped_date$", r"^delivery_date$",
    ],
    "ownership_type": [r"^ownership$", r"^ownership_type$", r"^owned_by$"],
    "notes": [r"^notes$", r"^comments$", r"^remarks$"],
}


@dataclass
class ColumnMap:
    """Mapping from canonical field → source header (case-insensitive)."""

    mapping: Dict[str, str]                       # canonical → source header
    confidence: float                             # 0–1
    source: str                                   # "learned" | "heuristic" | "llm" | "hybrid"
    missing_required: List[str] = field(default_factory=list)
    unmapped_headers: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mapping": self.mapping,
            "confidence": self.confidence,
            "source": self.source,
            "missing_required": self.missing_required,
            "unmapped_headers": self.unmapped_headers,
        }


def _normalize(h: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", (h or "").strip().lower()).strip("_")


def compute_header_hash(headers: List[str]) -> str:
    """Stable hash of header names (sorted, normalized) for learned-mapping lookup."""
    sig = "|".join(sorted(_normalize(h) for h in headers if h))
    return hashlib.sha256(sig.encode("utf-8")).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────
# Tier 1: learned mapping (DB lookup)
# ─────────────────────────────────────────────────────────────

async def _lookup_learned_mapping(
    db,
    sender_domain: Optional[str],
    filename: str,
    header_hash: str,
) -> Optional[ColumnMap]:
    query: Dict[str, Any] = {"header_hash": header_hash}
    if sender_domain:
        query["sender_domain"] = sender_domain
    learned = await db.inv_xls_learned_mappings.find_one(query, {"_id": 0})
    if not learned:
        return None
    cm = learned.get("column_map") or {}
    return ColumnMap(
        mapping=cm,
        confidence=min(0.99, 0.80 + 0.05 * learned.get("approval_count", 1)),
        source="learned",
        missing_required=[f for f in REQUIRED_FIELDS if f not in cm],
        unmapped_headers=[],
        raw={"approval_count": learned.get("approval_count", 1)},
    )


# ─────────────────────────────────────────────────────────────
# Tier 2: heuristic mapping
# ─────────────────────────────────────────────────────────────

def _heuristic_mapping(headers: List[str]) -> ColumnMap:
    mapping: Dict[str, str] = {}
    norm_to_orig = {_normalize(h): h for h in headers if h}
    for canonical, patterns in _HEURISTIC_RULES.items():
        for p in patterns:
            rx = re.compile(p)
            for norm, orig in norm_to_orig.items():
                if rx.match(norm):
                    mapping.setdefault(canonical, orig)
                    break
    # Fallback: if we have description but no item, that's OK — description will
    # be used as item at normalization time.
    missing = [f for f in REQUIRED_FIELDS if f not in mapping]
    if "item" in missing and "item_description" in mapping:
        # Don't list as blocking, but record via a softer flag in raw.
        missing.remove("item")
    unmapped = [orig for norm, orig in norm_to_orig.items() if orig not in mapping.values()]
    # Confidence = fraction of required hit + some bonus for optional coverage
    required_hit = 1.0 - (len(missing) / max(1, len(REQUIRED_FIELDS)))
    optional_hit = len(mapping) / max(1, len(CANONICAL_FIELDS))
    confidence = round(0.6 * required_hit + 0.4 * optional_hit, 2)
    return ColumnMap(
        mapping=mapping,
        confidence=confidence,
        source="heuristic",
        missing_required=missing,
        unmapped_headers=unmapped,
    )


# ─────────────────────────────────────────────────────────────
# Tier 3: LLM fallback (Claude Haiku via Emergent LLM Key)
# ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You map spreadsheet column headers to canonical inventory fields.

CANONICAL FIELDS (map zero or one source header to each):
- item:              SKU / part / product code
- item_description:  free-text item description
- qty:               signed quantity delta
- warehouse:         location / plant
- ownership_type:    customer_owned / gamer_reserved / mixed
- uom:               unit of measure (EA, CS, LB, etc.)
- reference:         PO / SO / ASN number
- effective_date:    posting / as-of / snapshot date
- notes:             free-text note or comment

RULES:
1. Return ONLY JSON — no preamble, no commentary.
2. Only include canonical fields where you have ≥70% confidence.
3. Source header values are case-insensitive; echo them exactly as given.
4. If a header is unmapped, omit it.
"""


async def _llm_mapping(
    headers: List[str],
    sample_rows: List[Dict[str, Any]],
    classification: str,
) -> Optional[ColumnMap]:
    """Ask Claude Haiku to map ambiguous headers. Returns None if LLM unavailable."""
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        logger.warning("[XLSParser] EMERGENT_LLM_KEY not set — skipping LLM fallback")
        return None
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except ImportError:
        logger.warning("[XLSParser] emergentintegrations not installed — skipping LLM fallback")
        return None

    session_id = f"xls-mapping-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    chat = LlmChat(api_key=api_key, session_id=session_id, system_message=_SYSTEM_PROMPT).with_model(
        "anthropic", "claude-haiku-4-5-20251001",
    )

    preview = sample_rows[:3] if sample_rows else []
    prompt = json.dumps({
        "classification": classification,
        "headers": headers,
        "sample_rows": preview,
        "required_fields": sorted(REQUIRED_FIELDS),
        "canonical_fields": CANONICAL_FIELDS,
    }, ensure_ascii=False, default=str)

    try:
        response = await chat.send_message(UserMessage(text=prompt))
    except Exception as e:
        logger.warning("[XLSParser] LLM call failed: %s", e)
        return None

    # Extract JSON body tolerantly
    body = response.strip() if isinstance(response, str) else str(response)
    m = re.search(r"\{[\s\S]*\}", body)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None

    mapping = {k: v for k, v in data.items() if k in CANONICAL_FIELDS and isinstance(v, str) and v.strip()}
    missing = [f for f in REQUIRED_FIELDS if f not in mapping]
    unmapped = [h for h in headers if h not in mapping.values()]
    confidence = 0.75 if not missing else 0.50
    return ColumnMap(
        mapping=mapping,
        confidence=confidence,
        source="llm",
        missing_required=missing,
        unmapped_headers=unmapped,
        raw={"llm_response": body[:500]},
    )


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

async def build_column_map(
    db,
    headers: List[str],
    sample_rows: List[Dict[str, Any]],
    classification: str,
    sender_domain: Optional[str] = None,
    filename: str = "",
    force_llm: bool = False,
) -> ColumnMap:
    """Produce the best available column map for a spreadsheet.

    Tier cascade: learned → heuristic → (if coverage<80% or force_llm) merge LLM.
    """
    header_hash = compute_header_hash(headers)

    # Tier 1 — learned
    learned = await _lookup_learned_mapping(db, sender_domain, filename, header_hash)
    if learned and not learned.missing_required and not force_llm:
        logger.info("[XLSParser] Using learned mapping (confidence=%.2f)", learned.confidence)
        return learned

    # Tier 2 — heuristic
    heuristic = _heuristic_mapping(headers)

    # If heuristic is solid, done.
    if heuristic.confidence >= 0.8 and not heuristic.missing_required and not force_llm:
        logger.info("[XLSParser] Using heuristic mapping (confidence=%.2f)", heuristic.confidence)
        return heuristic

    # Tier 3 — LLM fallback, merged with heuristic
    llm = await _llm_mapping(headers, sample_rows, classification)
    if llm is None:
        logger.info("[XLSParser] Heuristic-only (LLM unavailable, confidence=%.2f)", heuristic.confidence)
        return heuristic

    merged: Dict[str, str] = dict(heuristic.mapping)
    for k, v in llm.mapping.items():
        merged.setdefault(k, v)
    missing = [f for f in REQUIRED_FIELDS if f not in merged]
    confidence = round(max(heuristic.confidence, llm.confidence) + (0.05 if not missing else 0.0), 2)
    return ColumnMap(
        mapping=merged,
        confidence=min(0.95, confidence),
        source="hybrid",
        missing_required=missing,
        unmapped_headers=[h for h in headers if h not in merged.values()],
        raw={"heuristic": heuristic.to_dict(), "llm": llm.to_dict()},
    )


# ─────────────────────────────────────────────────────────────
# Row normalization
# ─────────────────────────────────────────────────────────────

_DATE_FORMATS = [
    "%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%d/%m/%Y", "%b %d, %Y",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
]


def _parse_date(val: Any) -> Optional[str]:
    if val in (None, ""):
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=val.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()
    s = str(val).strip()
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    return None


def _parse_number(val: Any) -> Optional[float]:
    if val in (None, ""):
        return None
    try:
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).replace(",", "").replace("$", "").strip()
        if s.lower() in ("-", "n/a", "null"):
            return None
        return float(s)
    except (TypeError, ValueError):
        return None


def extract_effective_date_from_filename(filename: str) -> Optional[str]:
    """Try to extract an 'as of' date from filenames like 'Open Orders As Of 2026-03-18.xlsx'."""
    patterns = [
        r"(\d{4})[-_.](\d{1,2})[-_.](\d{1,2})",  # 2026-03-18
        r"(\d{1,2})[-_.](\d{1,2})[-_.](\d{4})",  # 03-18-2026
        r"(\d{1,2})[-_.](\d{1,2})[-_.](\d{2})",  # 03-18-26
    ]
    s = filename or ""
    for p in patterns:
        m = re.search(p, s)
        if not m:
            continue
        parts = m.groups()
        try:
            if len(parts[0]) == 4:
                y, mo, d = int(parts[0]), int(parts[1]), int(parts[2])
            elif len(parts[2]) == 4:
                mo, d, y = int(parts[0]), int(parts[1]), int(parts[2])
            else:
                mo, d, y = int(parts[0]), int(parts[1]), 2000 + int(parts[2])
            return datetime(y, mo, d, tzinfo=timezone.utc).isoformat()
        except (ValueError, IndexError):
            continue
    return None


def normalize_rows(
    rows: List[Dict[str, Any]],
    column_map: ColumnMap,
    classification: str,
    filename_effective_date: Optional[str] = None,
    default_warehouse: str = "MAIN",
    default_uom: str = "units",
    default_ownership: str = "customer_owned",
) -> Dict[str, Any]:
    """Apply a column_map to raw parsed rows, producing staging-ready dicts.

    Returns: {
        "rows": [ {item, qty, ...} ],
        "row_errors": [ {row_num, reason} ],
        "stats": {...},
    }
    """
    out: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    cm = column_map.mapping

    # Fallback: if `item` is not mapped but `item_description` IS, use
    # description as the item identifier (legit for inventory summaries).
    item_fallback_to_description = "item" not in cm and "item_description" in cm

    for idx, raw in enumerate(rows, start=1):
        # Lookup each canonical value via the mapped source header
        def _get(field: str) -> Any:
            src = cm.get(field)
            if not src:
                return None
            return raw.get(src, raw.get(str(src).strip(), None))

        item = _get("item")
        desc_val = _get("item_description")
        if (item is None or str(item).strip() == "") and item_fallback_to_description and desc_val:
            item = desc_val
        qty = _parse_number(_get("qty"))

        if item is None or str(item).strip() == "":
            errors.append({"row": idx, "reason": "missing item"})
            continue
        if qty is None:
            errors.append({"row": idx, "reason": "missing or unparseable qty"})
            continue
        if qty == 0:
            errors.append({"row": idx, "reason": "qty is zero"})
            continue

        effective_date = _parse_date(_get("effective_date")) or filename_effective_date

        out.append({
            "item": str(item).strip()[:120],  # cap to keep ledger clean
            "item_description": str(desc_val or "").strip(),
            "qty": qty,
            "warehouse": str(_get("warehouse") or default_warehouse).strip() or default_warehouse,
            "uom": str(_get("uom") or default_uom).strip() or default_uom,
            "ownership_type": str(_get("ownership_type") or default_ownership).strip() or default_ownership,
            "reference": str(_get("reference") or "").strip(),
            "effective_date": effective_date,
            "notes": str(_get("notes") or "").strip(),
            "_raw_row_index": idx,
        })

    return {
        "rows": out,
        "row_errors": errors,
        "stats": {
            "total_rows": len(rows),
            "parsed": len(out),
            "failed": len(errors),
            "success_rate": round(len(out) / len(rows), 2) if rows else 0,
        },
    }
