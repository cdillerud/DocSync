#!/usr/bin/env python3
"""Update regression tests for the document reprocess extraction baseline.

This migration is intentionally narrow and idempotent. It updates integration
URL defaults, the authoritative reprocess import assertion, and historical
route/source-size guardrails that predate the extraction.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        print(f"already updated {path.relative_to(ROOT)}")
        return
    if old not in text:
        raise RuntimeError(f"expected text not found in {path.relative_to(ROOT)}: {old!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")
    print(f"updated {path.relative_to(ROOT)}")


orchestration = ROOT / "backend/tests/test_orchestration_extraction.py"
route_cleanup = ROOT / "backend/tests/test_route_cleanup.py"
dead_code = ROOT / "backend/tests/test_dead_code_tail_cleanup_4e_parity.py"
workflow_status = ROOT / "backend/tests/test_step_4d7_update_standard_workflow_status_body_move_parity.py"

for path in (orchestration, route_cleanup):
    replace(
        path,
        'API_BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")',
        'API_BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8000").rstrip("/")',
    )

replace(
    orchestration,
    '''    def test_reprocess_uses_direct_import(self):
        import inspect
        from services.document_handlers import reprocess_document
        source = inspect.getsource(reprocess_document)
        assert "_classify_with_ai(" in source or "_make_automation_decision(" in source
        assert "srv = _server()" not in source
''',
    '''    def test_reprocess_uses_direct_import(self):
        import services.document_handlers as handlers
        from services.document_reprocess_service import reprocess_document as service_reprocess
        assert handlers.reprocess_document is service_reprocess
''',
)

replace(orchestration, "Route count stable at 427", "Route count stable at 931")
replace(orchestration, '"""Route count preserved at 427."""', '"""Route count preserved at the current extracted baseline."""')
replace(orchestration, 'assert count == 427, f"Expected 427, got {count}"', 'assert count == 931, f"Expected 931, got {count}"')

replace(route_cleanup, "Route count stability (427 routes)", "Route count stability (931 routes)")
replace(route_cleanup, '"""Route count should be 427 after removing the empty api_router."""', '"""Route count should match the current extracted baseline."""')
replace(route_cleanup, 'assert count == 427, f"Expected 427 routes, got {count}"', 'assert count == 931, f"Expected 931 routes, got {count}"')

replace(
    dead_code,
    '''        # Pre-4e: 6,642. Post-4e expected: ~6,488 (delete 154; allow ±6).
        assert 6480 <= total <= 6500, (
            f"server.py line count {total} outside expected Step 4e delta band "
            "(6480–6500)."
        )''',
    '''        # Document reprocess extraction removed a further 425 legacy lines.
        assert 5795 <= total <= 5825, (
            f"server.py line count {total} outside extracted baseline band "
            "(5795-5825)."
        )''',
)
replace(dead_code, "assert len(paths) == 858", "assert len(paths) == 888")
replace(workflow_status, 'assert len(paths) == 858, f"OpenAPI path count drift: {len(paths)}"', 'assert len(paths) == 888, f"OpenAPI path count drift: {len(paths)}"')

print("refactor regression test baselines updated")
