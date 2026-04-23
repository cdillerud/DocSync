"""Pytest for Lane C Step 3A — unified exception-queue taxonomy.

Covers:
  1. §6.1 enumeration: exactly 10 categories, stable order.
  2. Default severity per §6.1 semantics (intentional_send_skip=info, etc.).
  3. ``build_exception`` pure constructor:
     - defaults severity from type
     - accepts explicit severity override
     - rejects unknown exception_type with ValueError
     - stamps created_utc when omitted
     - accepts explicit created_utc for deterministic comparisons
  4. ExceptionRecord immutability (frozen dataclass; evidence is read-only).
  5. Structural guardrail: no imports of
     ``workflows.batch.exception_queues`` anywhere outside the
     ``workflows/batch/`` package and this test file.
"""

from pathlib import Path

import pytest

from workflows.batch.exception_queues import (
    DEFAULT_SEVERITY,
    EXCEPTION_TYPES,
    ExceptionRecord,
    build_exception,
)


SIGNED_SCOPE_ORDER = (
    "missing_master_data",
    "duplicate_invoice_risk",
    "low_inventory",
    "missing_freight_docs",
    "receipt_invoice_mismatch",
    "cost_mismatch",
    "location_division_mismatch",
    "partial_post",
    "archived_doc_collision",
    "intentional_send_skip",
)


# ---------------------------------------------------------------------------
# 1. Enumeration
# ---------------------------------------------------------------------------

class TestEnumeration:
    def test_exactly_ten_types(self):
        assert len(EXCEPTION_TYPES) == 10

    def test_order_matches_signed_scope_6_1(self):
        assert tuple(EXCEPTION_TYPES) == SIGNED_SCOPE_ORDER

    def test_no_duplicates(self):
        assert len(EXCEPTION_TYPES) == len(set(EXCEPTION_TYPES))

    def test_severity_map_covers_every_type(self):
        assert set(DEFAULT_SEVERITY.keys()) == set(EXCEPTION_TYPES)

    def test_severity_map_is_readonly(self):
        # MappingProxyType raises TypeError on mutation.
        with pytest.raises(TypeError):
            DEFAULT_SEVERITY["missing_master_data"] = "block"   # type: ignore[index]


# ---------------------------------------------------------------------------
# 2. Default severity per §6.1
# ---------------------------------------------------------------------------

class TestDefaultSeverity:
    def test_intentional_send_skip_is_info_per_6_1(self):
        # §6.1 explicitly classifies zero-amount send skips as info so they
        # don't pollute failure dashboards.
        assert DEFAULT_SEVERITY["intentional_send_skip"] == "info"

    @pytest.mark.parametrize(
        "exc_type",
        [
            "duplicate_invoice_risk",
            "receipt_invoice_mismatch",
            "cost_mismatch",
            "partial_post",
            "archived_doc_collision",
        ],
    )
    def test_integrity_failures_are_block(self, exc_type):
        assert DEFAULT_SEVERITY[exc_type] == "block"

    @pytest.mark.parametrize(
        "exc_type",
        [
            "missing_master_data",
            "low_inventory",
            "missing_freight_docs",
            "location_division_mismatch",
        ],
    )
    def test_operator_workqueue_items_are_warn(self, exc_type):
        assert DEFAULT_SEVERITY[exc_type] == "warn"


# ---------------------------------------------------------------------------
# 3. build_exception constructor
# ---------------------------------------------------------------------------

class TestBuildException:
    def test_builds_record_with_default_severity(self):
        rec = build_exception(
            "doc-1",
            "missing_master_data",
            detail="vendor_no missing",
        )
        assert isinstance(rec, ExceptionRecord)
        assert rec.doc_id == "doc-1"
        assert rec.exception_type == "missing_master_data"
        assert rec.severity == "warn"
        assert rec.detail == "vendor_no missing"
        assert rec.evidence == {}
        assert rec.source_step is None
        assert rec.gate_id is None
        assert rec.created_utc  # stamped

    def test_explicit_severity_override_wins(self):
        rec = build_exception(
            "doc-2",
            "missing_master_data",
            detail="upgraded",
            severity="block",
        )
        assert rec.severity == "block"

    def test_intentional_send_skip_defaults_info(self):
        rec = build_exception(
            "doc-3",
            "intentional_send_skip",
            detail="zero-amount Posted doc; audit-only",
        )
        assert rec.severity == "info"

    def test_unknown_type_raises_value_error(self):
        with pytest.raises(ValueError) as excinfo:
            build_exception(
                "doc-x",
                "not_a_real_type",  # type: ignore[arg-type]
                detail="should fail",
            )
        assert "not_a_real_type" in str(excinfo.value)

    def test_evidence_snapshot_is_isolated_from_caller(self):
        mutable = {"po_number": "111279", "variance_usd": 42.50}
        rec = build_exception(
            "doc-4",
            "cost_mismatch",
            detail="variance over threshold",
            evidence=mutable,
        )
        # Caller mutation must not leak into the record.
        mutable["po_number"] = "999999"
        assert rec.evidence["po_number"] == "111279"

    def test_evidence_on_record_is_readonly(self):
        rec = build_exception(
            "doc-5",
            "low_inventory",
            detail="on-hand=0",
            evidence={"item_no": "ABC"},
        )
        with pytest.raises(TypeError):
            rec.evidence["item_no"] = "XYZ"   # type: ignore[index]

    def test_explicit_created_utc_is_honored(self):
        pinned = "2026-02-15T12:00:00+00:00"
        a = build_exception(
            "doc-6",
            "partial_post",
            detail="3 of 5 lines",
            created_utc=pinned,
        )
        b = build_exception(
            "doc-6",
            "partial_post",
            detail="3 of 5 lines",
            created_utc=pinned,
        )
        # Deterministic construction with pinned timestamp → equal records.
        assert a == b
        assert a.created_utc == pinned

    def test_source_step_and_gate_id_pass_through(self):
        rec = build_exception(
            "doc-7",
            "archived_doc_collision",
            detail="already archived",
            source_step="send_posted_docs",
            gate_id="phase_4_gate.drain_regression",
        )
        assert rec.source_step == "send_posted_docs"
        assert rec.gate_id == "phase_4_gate.drain_regression"


# ---------------------------------------------------------------------------
# 4. ExceptionRecord immutability
# ---------------------------------------------------------------------------

class TestRecordImmutability:
    def test_record_is_frozen(self):
        rec = build_exception("doc-f", "low_inventory", detail="d")
        with pytest.raises(Exception):
            rec.severity = "block"   # type: ignore[misc]

    def test_equality_structural(self):
        pinned = "2026-02-15T12:00:00+00:00"
        a = build_exception("doc-e", "cost_mismatch", detail="d", created_utc=pinned)
        b = build_exception("doc-e", "cost_mismatch", detail="d", created_utc=pinned)
        assert a == b

    def test_records_with_different_timestamps_are_unequal(self):
        a = build_exception(
            "doc-t",
            "cost_mismatch",
            detail="d",
            created_utc="2026-02-15T12:00:00+00:00",
        )
        b = build_exception(
            "doc-t",
            "cost_mismatch",
            detail="d",
            created_utc="2026-02-15T12:00:01+00:00",
        )
        assert a != b


# ---------------------------------------------------------------------------
# 5. Structural guardrail — unwired
# ---------------------------------------------------------------------------

class TestUnwiredGuardrail:
    """Step 3A is foundation-only; Step 3B is the first consumer.

    The module must not be imported from anywhere in the backend outside
    the ``workflows/batch/`` package and this test file. Fails the moment
    an unintentional import sneaks in.
    """

    def test_no_external_imports_of_exception_queues(self):
        backend_root = Path(__file__).resolve().parent.parent  # /app/backend
        allowed_prefixes = (
            backend_root / "workflows" / "batch",
            backend_root / "tests" / "test_exception_queues_taxonomy.py",
            backend_root / "tests" / "test_eod_controller.py",
        )

        needles = (
            "workflows.batch.exception_queues",
            "from workflows.batch import exception_queues",
        )

        offenders: list[str] = []
        for py in backend_root.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            if any(str(py).startswith(str(prefix)) for prefix in allowed_prefixes):
                continue
            try:
                text = py.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for needle in needles:
                if needle in text:
                    offenders.append(f"{py} -> {needle!r}")
                    break

        assert offenders == [], (
            "workflows.batch.exception_queues must stay UNWIRED until "
            "Lane C Step 3B. Offending files:\n  " + "\n  ".join(offenders)
        )

    def test_package_init_reexports_are_internal_only(self):
        """workflows.batch.__init__ may reexport from the submodule —
        that is *inside* the allowed prefix, so the guardrail above does
        not flag it. This test simply proves the reexport shape exists
        and nothing more than the declared surface leaks."""
        import workflows.batch as pkg

        assert set(pkg.__all__) == {
            "ExceptionType",
            "Severity",
            "EXCEPTION_TYPES",
            "DEFAULT_SEVERITY",
            "ExceptionRecord",
            "build_exception",
        }
