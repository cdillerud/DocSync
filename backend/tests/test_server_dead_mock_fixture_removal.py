# Guardrails for removal of dead server mock/demo fixtures.

from __future__ import annotations

import ast
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
SERVER_PATH = BACKEND_DIR / "server.py"
EXPECTED_SERVER_MAX = 2955

REMOVED_NAMES = {
    "FOLDER_MAP",
    "MOCK_COMPANIES",
    "MOCK_SALES_ORDERS",
}

REQUIRED_TOKEN_HELPERS = {
    "get_graph_token",
    "get_email_token",
    "get_bc_token",
}

REQUIRED_FOLDER_IMPORTS = {
    "determine_folder_path",
    "get_all_folder_paths",
    "get_folder_structure_summary",
    "FOLDER_STRUCTURE",
    "VENDOR_FOLDER_MAPPING",
}


def _tree(path: Path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _top_level_assignments(path: Path):
    names = set()

    for node in _tree(path).body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue

        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
        )

        names.update(
            target.id
            for target in targets
            if isinstance(target, ast.Name)
        )

    return names


def test_dead_server_fixture_assignments_are_absent():
    names = _top_level_assignments(SERVER_PATH)

    assert not (REMOVED_NAMES & names)


def test_no_production_module_uses_removed_fixture_surface():
    violations = []

    for path in BACKEND_DIR.rglob("*.py"):
        if "tests" in path.parts:
            continue

        try:
            tree = _tree(path)
        except (SyntaxError, UnicodeDecodeError):
            continue

        if path == SERVER_PATH:
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Name)
                    and isinstance(node.ctx, ast.Load)
                    and node.id in REMOVED_NAMES
                ):
                    violations.append(
                        "server.py loads removed fixture "
                        f"{node.id} at line {node.lineno}"
                    )

            continue

        server_aliases = {"server"}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "server":
                        server_aliases.add(
                            alias.asname or "server"
                        )

            elif (
                isinstance(node, ast.ImportFrom)
                and node.module == "server"
            ):
                for alias in node.names:
                    if alias.name in REMOVED_NAMES:
                        violations.append(
                            f"{path.relative_to(BACKEND_DIR)} "
                            f"imports {alias.name} from server"
                        )

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in server_aliases
                and node.attr in REMOVED_NAMES
            ):
                violations.append(
                    f"{path.relative_to(BACKEND_DIR)} "
                    f"references {node.value.id}.{node.attr}"
                )

    assert not violations, "\n".join(
        sorted(set(violations))
    )


def test_microsoft_token_helpers_are_preserved():
    tree = _tree(SERVER_PATH)

    function_names = {
        node.name
        for node in tree.body
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        )
    }

    assert REQUIRED_TOKEN_HELPERS <= function_names


def test_authoritative_folder_routing_imports_are_preserved():
    imports = set()

    for node in _tree(SERVER_PATH).body:
        if not (
            isinstance(node, ast.ImportFrom)
            and node.module
            == "services.folder_routing_service"
        ):
            continue

        imports.update(
            alias.asname or alias.name
            for alias in node.names
        )

    assert REQUIRED_FOLDER_IMPORTS <= imports


def test_server_line_count_is_monotonic():
    total = sum(
        1
        for _ in SERVER_PATH.open(
            "r",
            encoding="utf-8",
        )
    )

    assert total <= EXPECTED_SERVER_MAX
