"""Phase 4C(c) — End-to-end orchestrator tests.

Drives PDF bytes through ``services.contracts.pdf_extraction.run_extraction``
and asserts the preview shape, ambiguity detection, and graceful error
paths.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from services.contracts.pdf_extraction import (
    AmbiguityNote,
    ExtractionResult,
    run_extraction,
)


_FIXTURES = Path(__file__).parent / "fixtures" / "contracts" / "pdfs"


def _load(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


class TestRunExtractionHappyPath:
    def test_bragg_supply_excerpt_full_pipeline(self):
        result = run_extraction(
            agreement_id="agr-bragg-1",
            data=_load("bragg_supply_excerpt.pdf"),
            filename="bragg_supply_excerpt.pdf",
        )
        assert isinstance(result, ExtractionResult)
        assert result.error is None
        assert result.page_count == 1
        assert result.bytes_size > 0
        assert result.text_chars > 0
        keys = {f.key for f in result.fields}
        assert "freight_inco_term" in keys
        assert "freight_payer" in keys
        assert "moq" in keys
        assert "payment_term_discount" in keys
        # Per-line MOQs split out cleanly.
        assert len(result.line_pricing) == 2

    def test_tooling_pdf_yields_obligation_and_pricing(self):
        result = run_extraction(
            agreement_id="agr-tooling-1",
            data=_load("tooling_amortization_excerpt.pdf"),
            filename="tooling_amortization_excerpt.pdf",
        )
        targets = {(f.target, f.key) for f in result.fields}
        assert ("obligation", "tooling_amortization") in targets
        assert ("pricing", "tooling_amortized_unit_rate") in targets
        assert ("obligation", "volume_commitment") in targets

    def test_volume_tier_pdf(self):
        result = run_extraction(
            agreement_id="agr-tiers-1",
            data=_load("volume_commitment_with_tiers.pdf"),
            filename="volume_commitment_with_tiers.pdf",
        )
        assert any(f.key == "volume_discount_tier" for f in result.fields)
        assert any(f.key == "freight_inco_term"
                   and f.value.get("incoterm") == "DAP" for f in result.fields)


class TestRunExtractionErrorPaths:
    def test_empty_payload(self):
        result = run_extraction(
            agreement_id="agr-x", data=b"", filename="empty.pdf",
        )
        assert result.error is not None
        assert result.fields == []
        assert result.line_pricing == []
        assert result.page_count == 0

    def test_garbage_bytes(self):
        result = run_extraction(
            agreement_id="agr-x", data=b"this is not a pdf", filename="bad.pdf",
        )
        assert result.error is not None
        assert "unreadable" in result.error or "PDF" in result.error

    def test_missing_agreement_id_raises(self):
        with pytest.raises(ValueError, match="agreement_id"):
            run_extraction(agreement_id="", data=b"...", filename="x.pdf")


class TestAmbiguity:
    def test_two_distinct_freight_payers_flagged_as_ambiguous(self):
        # Manually compose text with conflicting payer statements.
        text = (
            "Freight prepaid by Buyer. "
            "Notwithstanding the foregoing, freight collect by Seller."
        )
        from services.contracts.pdf_field_extractors import extract_freight
        # Both payers extract independently, but our public API only
        # picks the first. Confirm public extractor still returns a
        # single payer; ambiguity surfaces when a caller combines two
        # extracted ranges from a longer text — wire a synthetic test
        # by constructing fields manually.
        from services.contracts.pdf_field_extractors import ExtractedField
        from services.contracts.pdf_extraction import _detect_ambiguities  # type: ignore
        fields = [
            ExtractedField(
                target="term", key="freight_payer",
                value={"payer": "prepaid", "subject": "buyer"},
                raw_text="Freight prepaid by Buyer", confidence=0.85,
            ),
            ExtractedField(
                target="term", key="freight_payer",
                value={"payer": "collect", "subject": "seller"},
                raw_text="freight collect by Seller", confidence=0.85,
            ),
        ]
        ambiguities = _detect_ambiguities(fields)
        assert len(ambiguities) == 1
        amb = ambiguities[0]
        assert amb.key == "freight_payer"
        assert len(amb.candidates) == 2

    def test_identical_repeated_field_not_flagged(self):
        from services.contracts.pdf_field_extractors import ExtractedField
        from services.contracts.pdf_extraction import _detect_ambiguities  # type: ignore
        same_value = {"discount_pct": 1.0, "early_days": 10, "net_days": 30}
        fields = [
            ExtractedField(
                target="term", key="payment_term_discount",
                value=same_value, raw_text="1% / 10 net 30", confidence=0.9,
            ),
            ExtractedField(
                target="term", key="payment_term_discount",
                value=same_value, raw_text="1% 10 net 30", confidence=0.9,
            ),
        ]
        assert _detect_ambiguities(fields) == []


class TestIdempotencyOfPreview:
    def test_two_runs_produce_identical_preview(self):
        data = _load("bragg_supply_excerpt.pdf")
        r1 = run_extraction(
            agreement_id="agr-x", data=data, filename="bragg.pdf",
        ).to_dict()
        r2 = run_extraction(
            agreement_id="agr-x", data=data, filename="bragg.pdf",
        ).to_dict()
        assert r1 == r2
