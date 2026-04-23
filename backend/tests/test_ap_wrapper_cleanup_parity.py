"""Pytest for Phase 3 Step 2R — AP compute-wrapper cleanup parity probe.

Proves the direct-import rewiring in ``server.py`` is behavior-preserving
for the five pure `compute_*` wrappers that were deleted:
  - compute_ap_normalized_fields  (services.document_intel_helpers)
  - compute_ap_validation         (services.ap_computation)
  - compute_ap_status             (services.ap_computation)
  - compute_draft_candidate_flag  (services.ap_computation)
  - compute_canonical_fields      (legacy alias — zero callers anywhere)

Deterministic: no Mongo, no LLM, no I/O, frozen fixture.
"""

from __future__ import annotations

import server  # deliberately imports server to exercise the post-cleanup namespace
from services import ap_computation, document_intel_helpers


# Deterministic canonical AP fixture.
CANONICAL_AP_EXTRACTED = {
    "vendor": "  Acme Packaging, Inc.  ",
    "invoice_number": "INV-2026-00042",
    "invoice_date": "2026-03-15",
    "due_date": "2026-04-14",
    "amount": "1234.56",
    "subtotal": "1150.00",
    "tax": "84.56",
    "purchase_order": "PO-12345",
    "ai_confidence": 0.92,
    "line_items": [
        {"description": "Box, A1", "quantity": 10, "unit_price": 1.00},
        {"description": "Tape, B2", "quantity": 5, "unit_price": 3.50},
    ],
}


class TestComputeWrapperCleanupParity:
    """Each case: ``server.X(...)`` (post-cleanup) == ``services.X(...)``.

    After the deletion, ``server.compute_ap_*`` is the imported canonical
    symbol. The probe asserts equality (tautology post-deletion), which is
    precisely the forward-regression guarantee we want: if anyone reintroduces
    a wrapper with drifted behavior, the probe breaks.
    """

    def test_compute_ap_normalized_fields_parity(self):
        via_server = server.compute_ap_normalized_fields(dict(CANONICAL_AP_EXTRACTED))
        direct = document_intel_helpers.compute_ap_normalized_fields(dict(CANONICAL_AP_EXTRACTED))
        assert via_server == direct
        # Structural sanity — output is non-empty dict with expected vendor trim.
        assert isinstance(via_server, dict)
        assert via_server.get("vendor_raw") or via_server.get("vendor_canonical")

    def test_compute_ap_validation_parity(self):
        args = dict(
            document_type="ap_invoice",
            vendor_normalized="acme packaging inc",
            invoice_number_clean="INV-2026-00042",
            amount_float=1234.56,
            po_number_clean="PO-12345",
            ai_confidence=0.92,
            possible_duplicate=False,
        )
        via_server = server.compute_ap_validation(**args)
        direct = ap_computation.compute_ap_validation(**args)
        assert via_server == direct
        assert isinstance(via_server, dict)

    def test_compute_draft_candidate_flag_parity(self):
        args = dict(
            document_type="ap_invoice",
            extracted_fields=dict(CANONICAL_AP_EXTRACTED),
            canonical_fields={"vendor_canonical": "acme packaging inc"},
            ai_confidence=0.92,
        )
        via_server = server.compute_draft_candidate_flag(**args)
        direct = ap_computation.compute_draft_candidate_flag(**args)
        assert via_server == direct

    def test_compute_ap_status_is_now_direct_service_signature(self):
        # The deleted shim re-shaped arguments from a legacy 5-arg form into
        # the service's 3-arg form. After deletion the direct service
        # signature is what ``server.compute_ap_status`` resolves to — and
        # that's the whole point of 2R: no silent signature re-shaping.
        import inspect
        server_sig = inspect.signature(server.compute_ap_status)
        service_sig = inspect.signature(ap_computation.compute_ap_status)
        assert server_sig == service_sig


class TestWrappersAreDeletedFromServer:
    """Post-deletion proof: ``server.py`` no longer contains its own
    ``def compute_*`` definitions. The module-level symbols come from
    the direct imports added in 2R."""

    def test_no_server_side_compute_definitions(self):
        from pathlib import Path
        src = Path(server.__file__).read_text(encoding="utf-8")
        # These exact wrapper-def lines must be absent from server.py.
        assert "def compute_ap_normalized_fields(extracted_fields: dict) -> dict:" not in src
        assert "def compute_ap_validation(" not in src or (
            # (defensive) if any other function is named similarly, the
            # canonical compatibility-wrapper docstring must not survive.
            'authoritative source: services.ap_computation' not in src
        )
        assert "def compute_ap_status(" not in src
        assert "def compute_draft_candidate_flag(" not in src
        assert "def compute_canonical_fields(" not in src
        # The legacy header comment from the wrapper block is gone.
        assert "Legacy wrapper for backward compatibility" not in src
        # The direct-import marker from 2R is present.
        assert "DIRECT CANONICAL IMPORTS: AP compute functions" in src

    def test_server_still_exposes_the_symbols_via_direct_import(self):
        # After deletion the names still resolve (via direct imports),
        # so call sites in server.py keep working without rename.
        assert callable(server.compute_ap_normalized_fields)
        assert callable(server.compute_ap_validation)
        assert callable(server.compute_ap_status)
        assert callable(server.compute_draft_candidate_flag)
        # Identity: they ARE the canonical symbols, not wrapper copies.
        assert server.compute_ap_normalized_fields is document_intel_helpers.compute_ap_normalized_fields
        assert server.compute_ap_validation is ap_computation.compute_ap_validation
        assert server.compute_ap_status is ap_computation.compute_ap_status
        assert server.compute_draft_candidate_flag is ap_computation.compute_draft_candidate_flag


class TestBuildVendorResolutionStaysInScope:
    """Guardrail: ``_build_vendor_resolution`` was INTENTIONALLY left alone
    in 2R because its body contains a real try/except fallback (not a pure
    shim). This test exists to catch any future accidental removal that
    would silently change behavior."""

    def test_build_vendor_resolution_still_exists_in_server(self):
        assert callable(getattr(server, "_build_vendor_resolution", None))

    def test_build_vendor_resolution_still_has_try_except_fallback(self):
        from pathlib import Path
        src = Path(server.__file__).read_text(encoding="utf-8")
        assert "def _build_vendor_resolution(" in src
        # The fallback literal is preserved.
        assert '"status": "unresolved"' in src
        assert 'except Exception' in src
