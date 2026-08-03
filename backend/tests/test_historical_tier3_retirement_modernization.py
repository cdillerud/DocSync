from __future__ import annotations
import ast
import inspect
from pathlib import Path

TARGET = Path(__file__).resolve().parent / "test_tier3_substitution_4c3_parity.py"
TIER3 = {"lookup_vendor_alias", "check_duplicate_document"}

def test_tier3_retirement_expectation_source_is_current():
    source = TARGET.read_text(encoding="utf-8")
    tree = ast.parse(source)
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    assert "TestServerShimUntouched" not in classes
    assert "TestServerShimRetired" in classes
    assert "test_runtime_identity_server_shim_delegates" not in source
    assert "test_server_shim_is_thin_shim_post_4c3" not in source
    assert "test_lazy_server_import_no_longer_lists_tier3" not in source
    assert "test_runtime_owner_is_callable_and_server_shim_is_absent" in source
    assert "test_server_shim_is_absent_from_runtime_and_source" in source
    assert "test_server_import_cascade_contains_no_tier3_names" in source

def test_tier3_runtime_owners_exist_and_server_shims_are_absent():
    import server
    from services import vendor_matching
    for name in TIER3:
        assert callable(getattr(vendor_matching, name))
        assert not hasattr(server, name)

def test_tier3_server_source_has_no_top_level_shim_definitions():
    import server
    tree = ast.parse(inspect.getsource(server))
    top_level_defs = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not (TIER3 & top_level_defs)

def test_tier3_intake_uses_authoritative_owner_without_server_import():
    from services import document_bytes_intake_service
    source = inspect.getsource(
        document_bytes_intake_service.intake_document_from_bytes
    )
    tree = ast.parse(source)
    import_sources = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            import_sources[alias.name] = node.module
    for name in TIER3:
        assert import_sources.get(name) == "services.vendor_matching"
    server_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "server"
        for alias in node.names
    }
    assert not (TIER3 & server_names)
