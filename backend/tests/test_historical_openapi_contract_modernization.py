from __future__ import annotations

import ast
from pathlib import Path


TESTS = Path(__file__).resolve().parent

TARGETS = (
    "test_dead_code_tail_cleanup_4e_parity.py",
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
    "test_step_4d7_update_standard_workflow_status_body_move_parity.py",
    "test_step_4d8_reverse_arrow_cleanup_parity.py",
    "test_tier3_substitution_4c3_parity.py",
)

REQUIRED_ROUTES = {
    "/api/documents/upload",
    "/api/documents/intake",
    "/api/documents/{doc_id}/preview-post",
    "/api/documents/batch-revalidate",
    "/api/documents/{doc_id}/reprocess",
}


def _modernized_methods():
    methods = []

    for filename in TARGETS:
        path = TESTS / filename
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        file_methods = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue

            if node.name.startswith("test_openapi_path_count_"):
                raise AssertionError(
                    f"stale exact path-count method remains: "
                    f"{path.name}:{node.lineno}:{node.name}"
                )

            if node.name != "test_openapi_required_routes_are_present":
                continue

            file_methods.append(
                (
                    path,
                    node,
                    ast.get_source_segment(source, node) or "",
                )
            )

        assert len(file_methods) == 1, (
            path.name,
            len(file_methods),
        )
        methods.extend(file_methods)

    return methods


def test_historical_openapi_contract_methods_are_modernized():
    methods = _modernized_methods()
    assert len(methods) == len(TARGETS) == 15

    for path, node, source in methods:
        assert "/openapi.json" in source, path.name
        assert "import requests" in source, path.name
        assert "required_routes" in source, path.name
        assert "missing = required_routes - set(paths)" in source, path.name
        assert 'getattr(self, "BASE_URL", None)' in source, path.name
        assert 'globals().get("BASE_URL")' in source, path.name
        assert 'f"{base_url}/openapi.json"' in source, path.name

        literal_routes = {
            child.value
            for child in ast.walk(node)
            if isinstance(child, ast.Constant)
            and isinstance(child.value, str)
            and child.value.startswith("/api/")
        }

        assert REQUIRED_ROUTES <= literal_routes, (
            path.name,
            sorted(REQUIRED_ROUTES - literal_routes),
        )


def test_historical_openapi_contract_has_no_exact_len_comparison():
    for path, node, _source in _modernized_methods():
        for child in ast.walk(node):
            if not isinstance(child, ast.Compare):
                continue

            values = [child.left, *child.comparators]
            has_len = any(
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "len"
                for value in values
            )
            has_integer = any(
                isinstance(value, ast.Constant)
                and isinstance(value.value, int)
                for value in values
            )

            assert not (has_len and has_integer), (
                path.name,
                child.lineno,
            )


def test_unrelated_backend_tests_are_out_of_scope():
    unrelated = (
        TESTS / "test_ap_queue_shadow_deletion_parity.py"
    )
    assert unrelated.exists()
    source = unrelated.read_text(encoding="utf-8")
    tree = ast.parse(source)

    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }

    assert "test_openapi_path_count_unchanged" in names
    assert unrelated.name not in TARGETS

