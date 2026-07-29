# Guardrails for removal of the dead server legacy-auth surface.

from __future__ import annotations

import ast
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
SERVER_PATH = BACKEND_DIR / "server.py"
AUTH_ROUTER_PATH = BACKEND_DIR / "routers" / "auth.py"
AUTH_DEPS_PATH = (
    BACKEND_DIR
    / "services"
    / "auth_deps.py"
)
EXPECTED_SERVER_MAX = 2991

REMOVED_NAMES = {
    "auth_router",
    "pyjwt",
    "JWT_SECRET",
    "TEST_USER",
    "LoginRequest",
    "create_token",
}


def _tree(path: Path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _top_level_names(path: Path):
    names = set()

    for node in _tree(path).body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(
                    alias.asname
                    or alias.name.split(".")[0]
                )

        elif isinstance(node, ast.ImportFrom):
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

        elif isinstance(
            node,
            (
                ast.ClassDef,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        ):
            names.add(node.name)

    return names


def test_dead_server_legacy_auth_surface_is_absent():
    names = _top_level_names(SERVER_PATH)

    assert not (REMOVED_NAMES & names)


def test_authoritative_auth_router_and_dependencies_are_complete():
    auth_names = _top_level_names(AUTH_ROUTER_PATH)
    deps_names = _top_level_names(AUTH_DEPS_PATH)

    assert not (
        {
            "LoginRequest",
            "login",
            "logout",
            "get_me",
        }
        - auth_names
    )

    assert not (
        {
            "create_access_token",
            "get_current_user",
            "verify_password",
        }
        - deps_names
    )

    auth_source = AUTH_ROUTER_PATH.read_text(
        encoding="utf-8"
    )

    assert "users.find_one" in auth_source
    assert "verify_password" in auth_source
    assert "create_access_token" in auth_source


def test_no_production_module_uses_removed_server_auth_surface():
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
                        "server.py loads removed auth symbol "
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


def test_server_line_count_is_monotonic():
    total = sum(
        1
        for _ in SERVER_PATH.open(
            "r",
            encoding="utf-8",
        )
    )

    assert total <= EXPECTED_SERVER_MAX
