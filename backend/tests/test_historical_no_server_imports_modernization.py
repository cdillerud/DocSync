import ast, inspect
from pathlib import Path
TESTS=Path(__file__).resolve().parent
TARGETS=(
"test_step_4d1_enum_constant_substitution_parity.py",
"test_step_4d2a_upload_dir_migration_parity.py",
"test_step_4d3a_auto_clear_substitution_parity.py",
"test_step_4d3b_event_service_substitution_parity.py",
"test_step_4d3c_pilot_config_substitution_parity.py",
"test_step_4d3d_auto_resolution_substitution_parity.py",
"test_step_4d5_emit_intake_events_body_move_parity.py",
"test_step_4d6_update_ap_workflow_status_body_move_parity.py",
"test_step_4d8_reverse_arrow_cleanup_parity.py",
)
STALE={
"test_lazy_server_import_no_longer_lists_4d1_symbols",
"test_lazy_server_import_no_longer_lists_upload_dir",
"test_lazy_server_import_no_longer_lists_4d3a_symbols",
"test_lazy_server_import_no_longer_lists_4d3b_symbols",
"test_lazy_server_import_no_longer_lists_4d3c_symbols",
"test_lazy_server_import_no_longer_lists_4d3d_symbol",
"test_lazy_tuple_now_four_private_helpers",
"test_lazy_tuple_now_three_private_helpers",
"test_lazy_tuple_still_two_entries",
}
def test_nine_files_use_final_invariant():
    for f in TARGETS:
        tree=ast.parse((TESTS/f).read_text(encoding="utf-8"))
        names={n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
        assert not (STALE & names), (f,sorted(STALE&names))
        assert "test_intake_has_no_lazy_server_imports" in names
def test_canonical_intake_has_no_server_imports():
    from services import document_bytes_intake_service
    tree=ast.parse(inspect.getsource(document_bytes_intake_service.intake_document_from_bytes))
    imports=[n for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and n.module=="server"]
    assert not imports
