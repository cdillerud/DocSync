"""Phase 4C(c) — Tests for the pypdf-backed PDF text extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.contracts.pdf_text_extractor import (
    PDFExtractionError,
    extract_text_from_pdf,
)


_FIXTURES = Path(__file__).parent / "fixtures" / "contracts" / "pdfs"


class TestExtractTextHappyPath:
    def test_extract_bragg_supply_excerpt(self):
        data = (_FIXTURES / "bragg_supply_excerpt.pdf").read_bytes()
        result = extract_text_from_pdf(data)
        assert result.page_count == 1
        assert result.bytes_size == len(data)
        assert result.full_text
        assert "Minimum Order Quantity" in result.full_text
        assert "FOB Garden Grove" in result.full_text
        assert "1% / 10 net 30" in result.full_text

    def test_extract_tooling_amortization(self):
        data = (_FIXTURES / "tooling_amortization_excerpt.pdf").read_bytes()
        result = extract_text_from_pdf(data)
        assert result.page_count == 1
        assert "Tooling cost" in result.full_text
        assert "amortized" in result.full_text.lower()

    def test_extract_volume_tiers(self):
        data = (_FIXTURES / "volume_commitment_with_tiers.pdf").read_bytes()
        result = extract_text_from_pdf(data)
        assert result.page_count == 1
        assert "5% off above 50,000" in result.full_text

    def test_pages_list_alignment(self):
        data = (_FIXTURES / "bragg_supply_excerpt.pdf").read_bytes()
        result = extract_text_from_pdf(data)
        assert len(result.pages) == result.page_count
        # Form-feed separator preserves page count for downstream regex.
        assert result.full_text.count("\f") == result.page_count - 1


class TestExtractTextErrorPaths:
    def test_empty_payload(self):
        with pytest.raises(PDFExtractionError, match="Empty"):
            extract_text_from_pdf(b"")

    def test_bytes_not_a_pdf(self):
        with pytest.raises(PDFExtractionError, match="unreadable"):
            extract_text_from_pdf(b"This is not a PDF.")

    def test_truncated_pdf(self):
        # First few bytes of a real PDF, truncated mid-stream.
        with pytest.raises(PDFExtractionError):
            extract_text_from_pdf(b"%PDF-1.4\n%abc\n")
