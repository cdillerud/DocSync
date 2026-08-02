from __future__ import annotations

import ast
from pathlib import Path


BACKEND = Path(__file__).resolve().parent.parent
SERVER = BACKEND / "server.py"
MAX_SERVER_LINES = 1699

REMOVED = {
    "upload_to_sharepoint":
        ("services/sharepoint_service.py", "upload_to_sharepoint"),
    "ensure_sharepoint_folder_exists":
        ("services/sharepoint_service.py", "ensure_sharepoint_folder_exists"),
    "upload_to_sharepoint_with_routing":
        ("services/sharepoint_service.py", "upload_to_sharepoint_with_routing"),
    "create_sharing_link":
        ("services/sharepoint_service.py", "create_sharing_link"),
    "get_bc_companies":
        ("services/bc_api_helpers.py", "get_bc_companies"),
    "get_bc_sales_orders":
        ("services/bc_api_helpers.py", "get_bc_sales_orders"),
    "link_document_to_bc":
        ("services/bc_link_service.py", "link_document_to_bc"),
    "check_duplicate_purchase_invoice":
        ("services/bc_draft_service.py", "check_duplicate_purchase_invoice"),
}


def parse(path: Path):
    return ast.parse(path.read_text(encoding="utf-8"))


def top_level_names(path: Path):
    return {
        node.name
        for node in parse(path).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_removed_server_wrappers_are_absent():
    assert not (set(REMOVED) & top_level_names(SERVER))


def test_canonical_owner_definitions_are_present():
    for name, (relative_path, owner_name) in REMOVED.items():
        owner_path = BACKEND / relative_path
        assert owner_path.exists(), name
        assert owner_name in top_level_names(owner_path), name


def test_no_production_module_imports_removed_server_wrappers():
    violations = []

    for path in BACKEND.rglob("*.py"):
        if (
            path == SERVER
            or "tests" in path.parts
            or "__pycache__" in path.parts
        ):
            continue

        try:
            tree = parse(path)
        except (SyntaxError, UnicodeDecodeError):
            continue

        aliases = {"server"}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "server":
                        aliases.add(alias.asname or "server")

            elif (
                isinstance(node, ast.ImportFrom)
                and node.module == "server"
            ):
                for alias in node.names:
                    if alias.name == "*" or alias.name in REMOVED:
                        violations.append(
                            f"{path.relative_to(BACKEND)}:"
                            f"{node.lineno} imports {alias.name}"
                        )

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in aliases
                and node.attr in REMOVED
            ):
                violations.append(
                    f"{path.relative_to(BACKEND)}:"
                    f"{node.lineno} references "
                    f"{node.value.id}.{node.attr}"
                )

    assert not violations, "\n".join(sorted(set(violations)))


def test_shim_audit_no_longer_lists_removed_create_sharing_link():
    audit = (
        BACKEND / "tests" / "audit_shim_substitution.py"
    ).read_text(encoding="utf-8")

    assert (
        '("create_sharing_link", "services.sharepoint_service")'
        not in audit
    )


def test_server_line_count_is_monotonic():
    count = sum(
        1
        for _ in SERVER.open("r", encoding="utf-8")
    )

    assert count <= MAX_SERVER_LINES
