"""
Regression tests for confidence calibration curve tightening (v2.5.3).

Bug observed on the live dashboard (2026-04-19):
    Confidence calibration band accuracies:
      0-50%:  93%  (1629 docs)
      50-70%: 97%  (1080 docs)
      70-85%: 98%  (52 docs)
      85-95%: 91%  (45 docs)  ← inverted: WORSE than 70-85%
      95-100%: 99% (2003 docs)

    The AI is specifically over-confident in the 85-95% window. Most of the
    failures in that band are docs with partial extraction (2/4 core fields)
    that used to get scale=1.0 (no penalty) because completeness=0.50 ≥ 0.50.

Fix: extend the penalty curve so 50%-complete docs get a mild (~12%) penalty,
pushing them one band down into 70-85% where manual review naturally catches
them. Full docs (>= 75% complete) still pass through untouched.
"""
from services.per_document_learning_service import compute_effective_confidence


def _doc(conf, fields=None, vendor_resolved=False):
    d = {"ai_confidence": conf, "extracted_fields": fields or {}}
    if vendor_resolved:
        d["vendor_canonical"] = "VENDOR_X"
    return d


# ─── Completeness = 1.0 (all 4 fields) ───
def test_fully_extracted_doc_no_penalty():
    fields = {"vendor": "Acme", "invoice_number": "I-1", "amount": 100, "invoice_date": "2026-01-01"}
    assert compute_effective_confidence(_doc(0.90, fields)) == 0.90
    assert compute_effective_confidence(_doc(0.87, fields)) == 0.87


# ─── Completeness = 0.75 (3 of 4 fields) ───
def test_75pct_complete_no_penalty():
    fields = {"vendor": "Acme", "invoice_number": "I-1", "amount": 100}
    # No invoice_date → 3/4 = 0.75 completeness
    assert compute_effective_confidence(_doc(0.90, fields)) == 0.90


# ─── Completeness = 0.50 (2 of 4 fields) — the target case ───
def test_50pct_complete_gets_mild_penalty():
    """The key fix: 2/4 fields used to get scale=1.0 (no penalty).
    Now it gets scale≈0.88 so 90% → ~79% → shifts out of 85-95% band."""
    fields = {"vendor": "Acme", "invoice_number": "I-1"}
    eff = compute_effective_confidence(_doc(0.90, fields))
    assert 0.75 < eff < 0.85, f"Expected mild penalty landing in 70-85% band, got {eff}"


def test_borderline_90pct_docs_shift_out_of_85_95_band():
    """A doc that used to land at 0.90 (85-95% band) now lands at ~0.79 (70-85%)."""
    fields = {"vendor": "Acme", "amount": 100}  # 2/4
    eff = compute_effective_confidence(_doc(0.90, fields))
    # 0.90 * 0.88 = 0.792 → now in 70-85% band
    assert eff < 0.85, f"Expected shift below 85%, got {eff}"
    assert eff >= 0.70, f"Expected stay above 70%, got {eff}"


# ─── Completeness = 0.25 (1 of 4 fields) ───
def test_25pct_complete_moderate_penalty():
    fields = {"vendor": "Acme"}  # 1/4
    eff = compute_effective_confidence(_doc(0.90, fields))
    # scale ~0.67 → 0.90 * 0.67 = 0.603
    assert 0.55 < eff < 0.68, f"Expected moderate penalty, got {eff}"


# ─── Completeness = 0.0 (zero fields) ───
def test_zero_extraction_heavy_penalty():
    eff = compute_effective_confidence(_doc(0.90, {}))
    # scale = 0.35 → 0.90 * 0.35 = 0.315
    assert 0.25 < eff < 0.40, f"Expected heavy penalty, got {eff}"


# ─── Vendor-resolved bonus still applies ───
def test_vendor_resolved_bonus_helps_low_extraction():
    """When extraction is poor but vendor was resolved via email/alias, give
    a 0.15 scale bonus — applies only when no vendor field was extracted."""
    fields = {"invoice_number": "I-1"}  # 1/4, no vendor field
    without = compute_effective_confidence(_doc(0.90, fields, vendor_resolved=False))
    with_resolved = compute_effective_confidence(_doc(0.90, fields, vendor_resolved=True))
    assert with_resolved > without, "Vendor-resolved bonus should raise effective conf"


# ─── Monotonicity: higher completeness always produces ≥ effective conf ───
def test_curve_is_monotonic():
    """Critical property: a doc with more extracted fields must not be
    penalized more than one with fewer. Prevents calibration weirdness."""
    all4 = {"vendor": "X", "invoice_number": "Y", "amount": 1, "invoice_date": "2026-01-01"}
    three = {"vendor": "X", "invoice_number": "Y", "amount": 1}
    two = {"vendor": "X", "invoice_number": "Y"}
    one = {"vendor": "X"}
    none: dict = {}
    confs = [
        compute_effective_confidence(_doc(0.90, none)),
        compute_effective_confidence(_doc(0.90, one)),
        compute_effective_confidence(_doc(0.90, two)),
        compute_effective_confidence(_doc(0.90, three)),
        compute_effective_confidence(_doc(0.90, all4)),
    ]
    for a, b in zip(confs, confs[1:]):
        assert a <= b + 1e-6, f"Non-monotonic: {confs}"


def test_zero_ai_confidence_stays_zero():
    assert compute_effective_confidence(_doc(0, {"vendor": "X"})) == 0.0


def test_98pct_fully_extracted_stays_in_95_100_band():
    """Regression: don't accidentally push 98%-confident fully-extracted
    docs out of the 95-100% band."""
    fields = {"vendor": "Acme", "invoice_number": "I-1", "amount": 100, "invoice_date": "2026-01-01"}
    assert compute_effective_confidence(_doc(0.98, fields)) >= 0.95
