"""Phase 4C(c) — Deterministic synthetic PDF builder for test fixtures.

This script regenerates the three `.pdf` fixtures that exercise the
PDF body extractors. Run only when the regex patterns evolve and the
fixtures need refreshed text.

Usage (host or VM, inside the backend Python env):

    python -m tests.fixtures.contracts.pdfs._build_fixtures

The generated PDFs are committed to git so CI never depends on this
runner; the script exists purely so a future maintainer can regenerate
them in one command.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

# pypdf does NOT directly emit text PDFs from raw strings — but
# reportlab is heavy. We build minimal, single-stream PDFs by hand.
# The output is intentionally simple (Helvetica, single page, no
# images) so pypdf round-trips them deterministically.

_HERE = Path(__file__).parent


def _build_pdf(text_blocks: list[str]) -> bytes:
    """Return raw PDF bytes for a single-page document.

    ``text_blocks`` is a list of paragraphs; the builder emits each on
    its own line at 12pt Helvetica with 16pt leading.
    """
    # Compose the page content stream. PDF text operators:
    #   BT ... ET    text object
    #   Tf           set font
    #   Td           move to position
    #   TJ / Tj      show text
    lines = []
    lines.append("BT")
    lines.append("/F1 11 Tf")
    lines.append("50 760 Td")
    lines.append("14 TL")
    for i, block in enumerate(text_blocks):
        # Escape PDF text ops: \, (, )
        safe = (
            block.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        )
        if i == 0:
            lines.append(f"({safe}) Tj")
        else:
            lines.append("T*")
            lines.append(f"({safe}) Tj")
    lines.append("ET")
    content_stream = "\n".join(lines).encode("latin-1")

    objects: list[bytes] = []

    def _obj(num: int, body: bytes) -> bytes:
        return f"{num} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"

    # 1: catalog
    objects.append(_obj(1, b"<< /Type /Catalog /Pages 2 0 R >>"))
    # 2: pages
    objects.append(_obj(2, b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>"))
    # 3: page
    objects.append(_obj(
        3,
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    ))
    # 4: content stream
    objects.append(
        _obj(
            4,
            (
                f"<< /Length {len(content_stream)} >>\nstream\n".encode("latin-1")
                + content_stream
                + b"\nendstream"
            ),
        )
    )
    # 5: font
    objects.append(_obj(5, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"))

    # Assemble file with xref table.
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]  # entry 0 is always free
    for body in objects:
        offsets.append(out.tell())
        out.write(body)
    xref_pos = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    out.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.write(f"{offset:010d} 00000 n \n".encode("latin-1"))
    out.write(b"trailer\n")
    out.write(f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode("latin-1"))
    out.write(b"startxref\n")
    out.write(f"{xref_pos}\n".encode("latin-1"))
    out.write(b"%%EOF\n")
    return out.getvalue()


# ---------------------------------------------------------------------------
# Fixture content (intentionally synthetic; no real customer data)
# ---------------------------------------------------------------------------


FIXTURE_BRAGG_SUPPLY = [
    "Synthetic Supply Schedule (Test Fixture, Not Real Contract)",
    "",
    "Incoterm: FOB Garden Grove, CA. Freight prepaid by Buyer.",
    "Minimum Order Quantity: 25,000 EA per shipment.",
    "Payment Terms: 1% / 10 net 30.",
    "",
    "Item ACME-WIDGET-12 MOQ: 5000",
    "Item ACME-GASKET-08 MOQ: 12,500",
    "",
    "End of synthetic supply schedule.",
]


FIXTURE_TOOLING_AMORT = [
    "Synthetic Tooling Schedule (Test Fixture, Not Real Contract)",
    "",
    "Tooling cost: $45,000.",
    "Amortized over the first 250,000 units at $0.18 / unit.",
    "Buyer commits to purchase 100,000 units per year.",
    "",
    "End of synthetic tooling schedule.",
]


FIXTURE_VOLUME_TIERS = [
    "Synthetic Volume Discount Schedule (Test Fixture, Not Real Contract)",
    "",
    "Customer commits to purchase 500,000 cases per year.",
    "5% off above 50,000 cases.",
    "10% off above 250,000 cases.",
    "Payment Terms: 2/15 net 45.",
    "Shipping Terms: DAP Chicago, IL.",
    "",
    "End of synthetic volume schedule.",
]


_FIXTURES = {
    "bragg_supply_excerpt.pdf": FIXTURE_BRAGG_SUPPLY,
    "tooling_amortization_excerpt.pdf": FIXTURE_TOOLING_AMORT,
    "volume_commitment_with_tiers.pdf": FIXTURE_VOLUME_TIERS,
}


def main() -> int:
    for name, blocks in _FIXTURES.items():
        path = _HERE / name
        path.write_bytes(_build_pdf(blocks))
        print(f"wrote {path} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
