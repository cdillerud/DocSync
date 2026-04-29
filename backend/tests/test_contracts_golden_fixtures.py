"""Phase 3.2 — Golden-fixture regression for the agreement normalizer.

Discovers every ``*.json`` file under
``backend/tests/fixtures/docusign/`` and runs the normalizer against each
one. Every file represents a real (sanitized) DocuSign Connect SIM payload.

Empty today by design: until the user drops a sanitized fixture in via the
runbook (Step 5), pytest collects zero parametrized cases and skips
gracefully. The moment a fixture lands, every test below runs without any
test-side change.

For richer per-fixture assertions (e.g. "this MSA must produce 3 terms"),
add an entry to ``_FIXTURE_EXPECTATIONS`` keyed by the fixture filename.

Run:
    cd /app/backend && python -m pytest tests/test_contracts_golden_fixtures.py -q
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from services.contracts.agreement_normalizer import normalize_envelope


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "docusign"


def _discover_fixtures() -> List[Path]:
    if not _FIXTURES_DIR.is_dir():
        return []
    return sorted(p for p in _FIXTURES_DIR.glob("*.json")
                  if not p.name.startswith("_"))


_FIXTURES = _discover_fixtures()
_IDS = [p.stem for p in _FIXTURES]


# Optional per-fixture expectations. Add entries as you commit fixtures:
#   "acme_msa__completed": {
#       "min_parties": 2,
#       "min_terms": 3,
#       "min_pricing_lines": 1,
#       "expected_status": "completed",
#   }
_FIXTURE_EXPECTATIONS: Dict[str, Dict[str, Any]] = {}


def _load(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Default checks — applied to every discovered fixture
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _FIXTURES, reason="No DocuSign golden fixtures present yet.")
@pytest.mark.parametrize("fixture_path", _FIXTURES, ids=_IDS)
class TestGoldenFixtures:

    def test_normalizer_accepts_payload(self, fixture_path: Path):
        payload = _load(fixture_path)
        # Should not raise. ValueError = irrecoverable shape problem.
        n = normalize_envelope(payload, event_id=f"golden::{fixture_path.stem}")
        assert n is not None

    def test_envelope_id_resolved(self, fixture_path: Path):
        n = normalize_envelope(_load(fixture_path))
        assert n.agreement.provider_envelope_id, (
            "normalizer accepted the payload but produced no provider_envelope_id"
        )

    def test_status_is_known(self, fixture_path: Path):
        n = normalize_envelope(_load(fixture_path))
        assert n.agreement.status != "unknown", (
            f"status mapped to 'unknown' for fixture {fixture_path.name}; "
            "extend _STATUS_MAP in agreement_normalizer.py"
        )

    def test_at_least_one_party(self, fixture_path: Path):
        n = normalize_envelope(_load(fixture_path))
        assert n.parties, (
            "normalizer produced zero parties — the fixture's "
            "envelopeSummary.recipients shape may not match what the parser expects"
        )

    def test_warnings_json_serializable(self, fixture_path: Path):
        n = normalize_envelope(_load(fixture_path))
        # Must round-trip through json (used when persisting to Mongo).
        json.dumps(n.warnings, default=str)

    def test_persisted_shape_json_serializable(self, fixture_path: Path):
        n = normalize_envelope(_load(fixture_path))
        # All children must round-trip cleanly (mode='json' is what we
        # actually call before insert_one).
        json.dumps(n.agreement.model_dump(mode="json"))
        for row in n.parties + n.terms + n.pricing + n.documents:
            json.dumps(row.model_dump(mode="json"))

    def test_per_fixture_expectations(self, fixture_path: Path):
        """Optional pinned assertions; only runs if the fixture has an entry
        in ``_FIXTURE_EXPECTATIONS``."""
        exp = _FIXTURE_EXPECTATIONS.get(fixture_path.stem)
        if not exp:
            pytest.skip("no pinned expectations for this fixture")
        n = normalize_envelope(_load(fixture_path))
        if "min_parties" in exp:
            assert len(n.parties) >= exp["min_parties"], (
                f"expected >= {exp['min_parties']} parties, got {len(n.parties)}"
            )
        if "min_terms" in exp:
            assert len(n.terms) >= exp["min_terms"]
        if "min_pricing_lines" in exp:
            assert len(n.pricing) >= exp["min_pricing_lines"]
        if "expected_status" in exp:
            assert n.agreement.status == exp["expected_status"]
        if "min_documents" in exp:
            assert len(n.documents) >= exp["min_documents"]


# ---------------------------------------------------------------------------
# Sanity test for the harness itself — runs even when no fixtures present
# ---------------------------------------------------------------------------

class TestHarness:

    def test_fixtures_dir_exists(self):
        assert _FIXTURES_DIR.is_dir(), (
            f"expected {_FIXTURES_DIR} to exist (created by Phase 3.2 setup)"
        )

    def test_readme_present(self):
        # The README documents the redaction contract; ensure it's not lost.
        assert (_FIXTURES_DIR / "README.md").is_file(), (
            "tests/fixtures/docusign/README.md is missing — see Phase 3.2 runbook"
        )

    def test_discovery_returns_only_json(self):
        # README.md and __init__.py must NOT be picked up as fixtures.
        for p in _FIXTURES:
            assert p.suffix == ".json"
            assert not p.name.startswith("_")
            assert p.name.lower() != "readme.md"
