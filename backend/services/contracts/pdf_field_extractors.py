"""Phase 4C(c) — Deterministic regex field extractors for legacy agreement PDFs.

Five field families. Each extractor is independently testable and emits
zero or more :class:`ExtractedField` rows with a confidence in
[0.5, 0.95]. Below 0.5 → not emitted.

Confidence anchors (consistent across families):
  * 0.95  — labeled section heading + clean numeric/keyword match.
  * 0.85  — labeled inline match ("MOQ: 25,000 EA", "1% / 10 net 30").
  * 0.70  — body prose match using strong keyword + nearby number.
  * 0.55  — keyword present but value extraction relied on heuristics.
  * <0.50 — dropped.

Field families:
  1. freight terms (Incoterm + payer)
  2. minimum order quantity (header-level + per-line)
  3. volume commitment
  4. tooling amortization (lump sum + amortized per-unit cost)
  5. payment-term cash discount + volume tier discount

Ambiguity contract:
  When two distinct values match the same key in the same document,
  the extractor still emits both — the orchestrator decides whether to
  raise a ``pdf_extraction_ambiguous`` exception.

Strict guarantees:
  * Pure regex / Python; no LLM calls, no network I/O.
  * Inputs are arbitrary text; never crashes on malformed input.
  * Output is JSON-serializable (dataclass + ``asdict``).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ExtractedField:
    """A single field extracted from PDF body text.

    ``target`` selects the persistence collection downstream:
      * ``"term"``        → ``agreement_terms``
      * ``"obligation"``  → ``agreement_obligations``
      * ``"pricing"``     → ``agreement_pricing`` (line-level overlay)
    """

    target: str          # term | obligation | pricing
    key: str             # term_key, obligation_kind, or pricing_attribute
    value: Any           # parsed value (str / float / dict)
    raw_text: str        # the matched substring, kept verbatim for audit
    confidence: float
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExtractedLinePricing:
    """One pricing line discovered in the body. Phase 4C(c) only fills
    the MOQ/min_quantity overlay — full line items remain Navigator-side.

    ``line_no`` is 1-based and corresponds to the order of discovery
    within the page; orchestrator stitches with existing rows by line.
    """

    item_label: str
    min_quantity: Optional[float] = None
    raw_text: str = ""
    confidence: float = 0.7


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_float(value: str) -> Optional[float]:
    """Parse a number that may carry thousands separators / currency."""
    if value is None:
        return None
    cleaned = value.strip().replace(",", "").replace("$", "")
    # Drop trailing alpha (e.g. "25000 EA")
    cleaned = re.split(r"\s", cleaned)[0]
    try:
        return float(cleaned)
    except (TypeError, ValueError):
        return None


_INCOTERMS = (
    "EXW", "FCA", "FOB", "CFR", "CIF", "FAS",
    "CPT", "CIP", "DAP", "DPU", "DDP",
)


# ---------------------------------------------------------------------------
# 1. Freight terms (Incoterm + payer)
# ---------------------------------------------------------------------------


_FREIGHT_PAYER_PATTERN = re.compile(
    r"freight\s+(?P<who>prepaid|collect|prepay)\s+"
    r"(?:and\s+(?:add|charge)\s+)?"
    r"(?:by\s+)?(?P<by>buyer|seller|customer|supplier|vendor|consignee)?",
    re.IGNORECASE,
)


def extract_freight(text: str) -> List[ExtractedField]:
    """Extract Incoterm and freight-payer fields from body text."""
    out: List[ExtractedField] = []
    if not text:
        return out

    # 1a — Incoterm. Look for a labeled "Incoterm: FOB <city>" or a
    # standalone token surrounded by word boundaries near the keyword
    # "freight" / "shipping".
    label_pat = re.compile(
        r"(?:incoterm[s]?|shipping\s+terms?|freight\s+terms?)\s*[:=]\s*"
        r"(?P<term>[A-Z]{3})\b(?:\s+(?P<loc>[A-Za-z][A-Za-z ,\.]+?))?(?=\.|\n|;|$)",
        re.IGNORECASE,
    )
    for m in label_pat.finditer(text):
        term = m.group("term").upper()
        if term in _INCOTERMS:
            value = {"incoterm": term}
            loc = (m.group("loc") or "").strip(" ,.")
            if loc:
                value["named_place"] = loc
            out.append(ExtractedField(
                target="term",
                key="freight_inco_term",
                value=value,
                raw_text=m.group(0).strip(),
                confidence=0.95,
            ))
            break  # one canonical Incoterm per agreement

    # 1b — Bare incoterm without a label, scoped near a freight keyword.
    if not any(f.key == "freight_inco_term" for f in out):
        bare_pat = re.compile(
            r"\b(?P<term>" + "|".join(_INCOTERMS) + r")\b\s+"
            r"(?P<loc>[A-Z][A-Za-z]+(?:\s*,\s*[A-Z]{2})?)?",
        )
        # Only accept if the word "freight" / "shipping" appears within
        # 80 chars before the match.
        for m in bare_pat.finditer(text):
            window_start = max(0, m.start() - 80)
            window = text[window_start:m.start()].lower()
            if "freight" in window or "shipping" in window or "ship to" in window:
                value = {"incoterm": m.group("term")}
                loc = (m.group("loc") or "").strip()
                if loc:
                    value["named_place"] = loc
                out.append(ExtractedField(
                    target="term",
                    key="freight_inco_term",
                    value=value,
                    raw_text=m.group(0).strip(),
                    confidence=0.70,
                ))
                break

    # 1c — Freight payer.
    for m in _FREIGHT_PAYER_PATTERN.finditer(text):
        who = (m.group("who") or "").lower()
        by = (m.group("by") or "").lower()
        if not (who or by):
            continue
        out.append(ExtractedField(
            target="term",
            key="freight_payer",
            value={"payer": who or by, "subject": by or None},
            raw_text=m.group(0).strip(),
            confidence=0.85 if (who and by) else 0.70,
        ))
        break

    return out


# ---------------------------------------------------------------------------
# 2. MOQ — header-level + per-line
# ---------------------------------------------------------------------------


_MOQ_HEADER_PAT = re.compile(
    r"(?:minimum\s+order\s+quantity|MOQ)\s*[:=]?\s*"
    r"(?P<num>[\d][\d,\.]*)\s*"
    r"(?P<unit>EA|EACH|UNITS?|PCS?|PIECES?|PALLETS?|CASES?|BOXES?|BOTTLES?|LBS?|KG|KGS|TONS?|TONNE[S]?)?",
    re.IGNORECASE,
)


def extract_moq_header(text: str) -> List[ExtractedField]:
    """Extract a header-level MOQ statement."""
    out: List[ExtractedField] = []
    if not text:
        return out
    seen: set = set()
    for m in _MOQ_HEADER_PAT.finditer(text):
        num = _to_float(m.group("num"))
        if num is None or num <= 0:
            continue
        unit = (m.group("unit") or "").upper() or None
        key = (num, unit)
        if key in seen:
            continue
        seen.add(key)
        # Prefer the labeled form ("MOQ: ...") at higher confidence.
        confidence = 0.90 if ":" in m.group(0) or "=" in m.group(0) else 0.75
        out.append(ExtractedField(
            target="term",
            key="moq",
            value={"quantity": num, "unit": unit},
            raw_text=m.group(0).strip(),
            confidence=confidence,
        ))
    return out


_MOQ_LINE_PAT = re.compile(
    r"(?P<label>[A-Z][A-Za-z0-9 \-/&\.]{2,80}?)\s+"
    r"(?:MOQ|min\.?\s*qty|minimum\s*qty)\s*[:=]?\s*"
    r"(?P<num>[\d][\d,\.]*)",
    re.IGNORECASE,
)


def extract_moq_per_line(text: str) -> List[ExtractedLinePricing]:
    """Extract per-line MOQs scoped to a leading item label."""
    out: List[ExtractedLinePricing] = []
    if not text:
        return out
    for m in _MOQ_LINE_PAT.finditer(text):
        num = _to_float(m.group("num"))
        if num is None or num <= 0:
            continue
        label = m.group("label").strip()
        # Trim noise words sometimes left in the label
        label = re.sub(r"^(item|sku|product|line)\s*[:#]?\s*", "", label, flags=re.IGNORECASE)
        if not label:
            continue
        out.append(ExtractedLinePricing(
            item_label=label,
            min_quantity=num,
            raw_text=m.group(0).strip(),
            confidence=0.80,
        ))
    return out


# ---------------------------------------------------------------------------
# 3. Volume commitment
# ---------------------------------------------------------------------------


_VOLUME_COMMIT_PAT = re.compile(
    r"(?:customer|buyer|purchaser)\s+"
    r"(?:hereby\s+)?(?:agrees|commits|shall\s+commit)\s+"
    r"to\s+(?:purchase|order|buy)\s+"
    r"(?:a\s+(?:minimum|total)\s+of\s+)?"
    r"(?P<num>[\d][\d,\.]*)\s+"
    r"(?P<unit>units?|pieces?|cases?|pallets?|tons?|lbs?|kgs?|EA)\s*"
    r"(?:(?:per|each|/)\s*(?P<period_word>year|annum|month|quarter)"
    r"|(?P<period_adv>annually|monthly|quarterly|yearly))",
    re.IGNORECASE | re.DOTALL,
)


def extract_volume_commitment(text: str) -> List[ExtractedField]:
    out: List[ExtractedField] = []
    if not text:
        return out
    for m in _VOLUME_COMMIT_PAT.finditer(text):
        num = _to_float(m.group("num"))
        if num is None or num <= 0:
            continue
        period = (m.group("period_word") or m.group("period_adv") or "").lower()
        out.append(ExtractedField(
            target="obligation",
            key="volume_commitment",
            value={
                "quantity": num,
                "unit": (m.group("unit") or "").lower(),
                "period": period,
            },
            raw_text=re.sub(r"\s+", " ", m.group(0)).strip(),
            confidence=0.85,
        ))
    return out


# ---------------------------------------------------------------------------
# 4. Tooling amortization
# ---------------------------------------------------------------------------


_TOOLING_LUMP_PAT = re.compile(
    r"tooling\s+(?:cost|fee|charge|amount)\s*[:=]?\s*(?:of)?\s*"
    r"\$?\s*(?P<amt>[\d][\d,\.]*)",
    re.IGNORECASE,
)
_TOOLING_AMORT_PAT = re.compile(
    r"amortized?\s+over\s+"
    r"(?:the\s+)?(?:first\s+)?"
    r"(?P<units>[\d][\d,\.]*)\s+"
    r"(?P<unit>units?|pieces?|cases?|pallets?)"
    r"(?:[^.]{0,200}?\$\s*(?P<rate>[\d][\d\.,]*)\s*(?:/|per)\s*"
    r"(?:unit|piece|case|pallet))?",
    re.IGNORECASE | re.DOTALL,
)


def extract_tooling(text: str) -> List[ExtractedField]:
    """Extract tooling amortization. Two flavors:
      * lump sum only ("Tooling cost: $45,000")
      * lump sum + amortization schedule ("amortized over first 250,000 units")
    Emits a ``tooling_amortization`` obligation; if a per-unit rate is
    discovered, also emits a pricing overlay row carrying ``rate``.
    """
    out: List[ExtractedField] = []
    if not text:
        return out
    lump = None
    lump_raw = ""
    m = _TOOLING_LUMP_PAT.search(text)
    if m:
        lump = _to_float(m.group("amt"))
        lump_raw = m.group(0).strip()

    amort_match = _TOOLING_AMORT_PAT.search(text)
    if amort_match:
        units = _to_float(amort_match.group("units"))
        rate = _to_float(amort_match.group("rate")) if amort_match.group("rate") else None
        unit = (amort_match.group("unit") or "").lower().rstrip("s")
        # If the regex didn't catch a per-unit rate but we know the lump
        # sum, derive it for the pricing overlay.
        derived_rate = (lump / units) if (rate is None and lump and units) else None
        amort_value: Dict[str, Any] = {
            "units": units,
            "unit": unit,
            "lump_sum": lump,
            "rate_per_unit": rate or derived_rate,
            "rate_source": "explicit" if rate is not None else
                           ("derived" if derived_rate is not None else None),
        }
        out.append(ExtractedField(
            target="obligation",
            key="tooling_amortization",
            value=amort_value,
            raw_text=re.sub(r"\s+", " ", amort_match.group(0)).strip(),
            confidence=0.90 if rate is not None else 0.80,
        ))
        if amort_value["rate_per_unit"] is not None:
            out.append(ExtractedField(
                target="pricing",
                key="tooling_amortized_unit_rate",
                value={
                    "rate_per_unit": amort_value["rate_per_unit"],
                    "unit": unit,
                    "derived": rate is None,
                },
                raw_text=re.sub(r"\s+", " ", amort_match.group(0)).strip(),
                confidence=0.85 if rate is not None else 0.65,
            ))
    elif lump is not None:
        # Lump-sum only — surface as an obligation but lower confidence.
        out.append(ExtractedField(
            target="obligation",
            key="tooling_amortization",
            value={"lump_sum": lump, "rate_per_unit": None, "units": None},
            raw_text=lump_raw,
            confidence=0.70,
        ))
    return out


# ---------------------------------------------------------------------------
# 5. Discounts — payment-term cash + volume tier
# ---------------------------------------------------------------------------


_PAYMENT_DISCOUNT_PAT = re.compile(
    r"(?P<pct>\d{1,2}(?:\.\d{1,3})?)\s*%?\s*"
    r"(?:[/-]|\bdays?\s+)\s*"
    r"(?P<early>\d{1,3})\s*"
    r"(?:days?|d)?\s*[,;/]?\s*"
    r"(?:net|n)\s*[/]?\s*"
    r"(?P<net>\d{1,3})",
    re.IGNORECASE,
)


def extract_payment_term_discount(text: str) -> List[ExtractedField]:
    """Extract payment-term cash discounts ("1% / 10 net 30", "2/15 net 45")."""
    out: List[ExtractedField] = []
    if not text:
        return out
    seen: set = set()
    for m in _PAYMENT_DISCOUNT_PAT.finditer(text):
        pct = _to_float(m.group("pct"))
        early = _to_float(m.group("early"))
        net = _to_float(m.group("net"))
        if pct is None or early is None or net is None:
            continue
        # Sanity caps: cash-discount pct should fit in [0, 30], early <= net.
        if pct <= 0 or pct > 30 or early > net:
            continue
        key = (pct, early, net)
        if key in seen:
            continue
        seen.add(key)
        # Higher confidence when the literal "%" appears in the source.
        had_percent = "%" in m.group(0)
        out.append(ExtractedField(
            target="term",
            key="payment_term_discount",
            value={
                "discount_pct": pct,
                "early_days": int(early),
                "net_days": int(net),
            },
            raw_text=m.group(0).strip(),
            confidence=0.90 if had_percent else 0.80,
        ))
    return out


_VOLUME_TIER_PAT = re.compile(
    r"(?P<pct>\d{1,2}(?:\.\d{1,2})?)\s*%\s+(?:off|discount)\s+"
    r"(?:above|over|exceeding|on\s+orders?\s+(?:above|over))\s+"
    r"(?P<units>[\d][\d,\.]*)\s*"
    r"(?P<unit>units?|pieces?|cases?|pallets?)?",
    re.IGNORECASE,
)


def extract_volume_tier_discount(text: str) -> List[ExtractedField]:
    """Extract volume-tier discount tables ("5% off above 50,000 units")."""
    out: List[ExtractedField] = []
    if not text:
        return out
    tiers: List[Dict[str, Any]] = []
    seen: set = set()
    for m in _VOLUME_TIER_PAT.finditer(text):
        pct = _to_float(m.group("pct"))
        units = _to_float(m.group("units"))
        if pct is None or units is None or pct <= 0:
            continue
        unit = (m.group("unit") or "").lower().rstrip("s") or "unit"
        key = (pct, units, unit)
        if key in seen:
            continue
        seen.add(key)
        tiers.append({
            "discount_pct": pct,
            "threshold": units,
            "unit": unit,
            "raw": m.group(0).strip(),
        })
    if tiers:
        out.append(ExtractedField(
            target="term",
            key="volume_discount_tier",
            value={"tiers": tiers},
            raw_text="; ".join(t["raw"] for t in tiers),
            confidence=0.85,
        ))
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract_all_fields(text: str) -> Dict[str, Any]:
    """Run every extractor and return a structured result dict.

    Output shape:
        {
          "fields": List[ExtractedField],
          "line_pricing": List[ExtractedLinePricing],
        }

    Per-line MOQs always win over header MOQs of the same quantity:
    "Item ACME-WIDGET MOQ: 5000" should not also create a header-level
    MOQ row at 5,000.
    """
    fields: List[ExtractedField] = []
    fields.extend(extract_freight(text))

    line_pricing = extract_moq_per_line(text)
    line_qtys = {lp.min_quantity for lp in line_pricing if lp.min_quantity is not None}

    header_moqs = extract_moq_header(text)
    deduped_header = [
        f for f in header_moqs
        if not (
            isinstance(f.value, dict)
            and f.value.get("quantity") in line_qtys
        )
    ]
    fields.extend(deduped_header)

    fields.extend(extract_volume_commitment(text))
    fields.extend(extract_tooling(text))
    fields.extend(extract_payment_term_discount(text))
    fields.extend(extract_volume_tier_discount(text))
    return {
        "fields": fields,
        "line_pricing": line_pricing,
    }
