from __future__ import annotations

import ast
from pathlib import Path


TESTS = Path(__file__).resolve().parent

TARGETS = (
    "test_step_4d1_enum_constant_substitution_parity.py",
    "test_step_4d2a_upload_dir_migration_parity.py",
    "test_step_4d2b_db_migration_parity.py",
    "test_step_4d3a_auto_clear_substitution_parity.py",
    "test_step_4d3b_event_service_substitution_parity.py",
    "test_step_4d3c_pilot_config_substitution_parity.py",
    "test_step_4d3d_auto_resolution_substitution_parity.py",
    "test_step_4d4a_derive_workflow_status_substitution_parity.py",
    "test_step_4d4b_update_vendor_profile_substitution_parity.py",
    "test_step_4d5_emit_intake_events_body_move_parity.py",
    "test_step_4d6_update_ap_workflow_status_body_move_parity.py",
    "test_tier3_substitution_4c3_parity.py",
)

HELPERS = {
    "_intake_func_node",
    "_intake_func_source",
}

CANONICAL = "document_bytes_intake_service"
LEGACY = "document_handlers"


def test_historical_intake_locator_helpers_use_canonical_owner():
    audited = 0

    for filename in TARGETS:
        path = TESTS / filename
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        helpers = [
            node
            for node in tree.body
            if isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            )
            and node.name in HELPERS
        ]

        assert helpers, filename

        for helper in helpers:
            segment = ast.get_source_segment(source, helper) or ""
            assert CANONICAL in segment, (filename, helper.name)
            assert LEGACY not in segment, (filename, helper.name)
            audited += 1

    assert audited >= len(TARGETS)


def test_canonical_intake_function_exists():
    from services import document_bytes_intake_service

    assert hasattr(
        document_bytes_intake_service,
        "intake_document_from_bytes",
    )
