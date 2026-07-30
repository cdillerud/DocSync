# Guardrails for removal of dead server router placeholders.

from __future__ import annotations

import ast
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
SERVER_PATH = BACKEND_DIR / "server.py"
MAIN_PATH = BACKEND_DIR / "main.py"
EXPECTED_SERVER_MAX = 2983

REMOVED_NAMES = {
    "ap_review_router",
    "spiro_router",
    "sharepoint_migration_router",
    "sharepoint_migration_module",
}


def _tree(path: Path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _top_level_names(path: Path):
    names = set()

    for node in _tree(path).body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)

        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target]
            )

            for target in targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)

    return names


def test_dead_server_router_placeholders_are_absent():
    names = _top_level_names(SERVER_PATH)

    assert not (REMOVED_NAMES & names)


def test_main_owns_ap_review_and_spiro_router_registration():
    tree = _tree(MAIN_PATH)
    imports = set()
    included = set()

    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imports.add(
                    (
                        node.module,
                        alias.name,
                        alias.asname or alias.name,
                    )
                )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        if not (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "app"
            and node.func.attr == "include_router"
            and node.args
            and isinstance(node.args[0], ast.Name)
        ):
            continue

        included.add(node.args[0].id)

    assert (
        "routers.ap_review",
        "ap_review_router",
        "ap_review_router",
    ) in imports

    assert (
        "routers.spiro",
        "spiro_router",
        "spiro_router",
    ) in imports

    assert "ap_review_router" in included
    assert "spiro_router" in included


def test_no_production_module_uses_removed_server_surface():
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
                        "server.py loads removed router symbol "
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


def test_authoritative_router_modules_exist():
    assert (BACKEND_DIR / "routers" / "ap_review.py").exists()
    assert (BACKEND_DIR / "routers" / "spiro.py").exists()


def test_migration_candidate_indexes_are_preserved():
    source = SERVER_PATH.read_text(encoding="utf-8")

    assert (
        'await db.migration_candidates.create_index('
        '"source_item_id", unique=True)'
        in source
    )
    assert (
        'await db.migration_candidates.create_index("status")'
        in source
    )
    assert (
        'await db.migration_candidates.create_index("doc_type")'
        in source
    )
    assert "Migration candidate indexes initialized" in source
    assert "if sharepoint_migration_module:" not in source


def test_server_line_count_is_monotonic():
    total = sum(
        1
        for _ in SERVER_PATH.open(
            "r",
            encoding="utf-8",
        )
    )

    assert total <= EXPECTED_SERVER_MAX
