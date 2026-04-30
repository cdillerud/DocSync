"""Phase 4C(c) — Thin pypdf wrapper for legacy agreement PDFs.

Single responsibility: bytes → text. The wrapper:
  * Uses ``pypdf`` (already in requirements.txt; no new deps).
  * Returns full plaintext + per-page text + page count.
  * Soft-fails to a structured ``PDFExtractionError`` on bad bytes,
    encrypted PDFs we cannot decrypt, or empty documents — callers up
    the stack convert that into a low-severity exception row.
  * Performs no LLM calls, no network I/O, no file-system writes.

Used by:
  * ``services.contracts.pdf_extraction`` (orchestrator)
  * ``scripts.contracts_extract_pdf`` (CLI)
  * ``routers.contracts`` (HTTP endpoint)
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import List

logger = logging.getLogger(__name__)


class PDFExtractionError(ValueError):
    """Raised when a PDF cannot be parsed or decrypted."""


@dataclass
class ExtractedPDFText:
    """Result of extracting raw text from a PDF document.

    ``full_text`` is the concatenation of all pages joined by form-feed
    (``\\f``) so per-page boundaries survive downstream regex passes
    that need to anchor to a specific page.
    """

    page_count: int
    pages: List[str] = field(default_factory=list)
    full_text: str = ""
    bytes_size: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.full_text.strip()


def extract_text_from_pdf(data: bytes) -> ExtractedPDFText:
    """Extract plaintext from PDF bytes using pypdf.

    Raises:
        PDFExtractionError: on unreadable / encrypted-but-undecryptable
            input, or when the PDF parses but yields no extractable text
            (likely a scanned image PDF — outside Phase 4C(c) scope).
    """
    if not data:
        raise PDFExtractionError("Empty PDF payload (0 bytes).")

    try:
        from pypdf import PdfReader  # local import keeps module load light
    except ImportError as exc:  # pragma: no cover  — pypdf is in requirements
        raise PDFExtractionError(f"pypdf not installed: {exc}") from exc

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001  — pypdf raises a wide variety
        raise PDFExtractionError(f"unreadable PDF: {exc}") from exc

    if reader.is_encrypted:
        # Try the empty password (some encrypted-but-unprotected PDFs).
        try:
            ok = reader.decrypt("")
        except Exception:  # noqa: BLE001
            ok = 0
        if not ok:
            raise PDFExtractionError(
                "encrypted PDF — Phase 4C(c) does not handle "
                "password-protected documents",
            )

    pages: List[str] = []
    for i, page in enumerate(reader.pages):
        try:
            txt = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("pypdf page %d extract_text failed: %s", i, exc)
            txt = ""
        pages.append(txt)

    full_text = "\f".join(pages)
    result = ExtractedPDFText(
        page_count=len(pages),
        pages=pages,
        full_text=full_text,
        bytes_size=len(data),
    )

    if result.is_empty:
        raise PDFExtractionError(
            "PDF parsed but no text extractable (likely a scanned image; "
            "Phase 4C(c) is text-based extraction only).",
        )

    return result
