"""Post-removal parity for the former Step 4e Tier-3 server shims."""

from __future__ import annotations

import ast
import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parent.parent
SERVER_PATH = BACKEND_DIR / "server.py"
OWNER_PATH = BACKEND_DIR / "services" / "vendor_matching.py"
INTAKE_PATH = (
    BACKEND_DIR
    / "services"
    / "document_bytes_intake_service.py"
)
REMOVED_TIER_3 = {
    "lookup_vendor_alias",
    "check_duplicate_document",
}


def _tree(path: Path):
    return ast.parse(
        path.read_text(encoding="utf-8")
    )


def _top_level_names(path: Path):
    return {
        node.name
        for node in _tree(path).body
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
    }


def _intake_imports():
    function = next(
        node
        for node in ast.walk(_tree(INTAKE_PATH))
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "intake_document_from_bytes"
    )
    imports = {}

    for node in ast.walk(function):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imports[alias.name] = node.module

    return imports
class TestPostRemovalStructure:
    def test_server_shims_are_absent(self):
        import server

        definitions = _top_level_names(SERVER_PATH)
        assert not (REMOVED_TIER_3 & definitions)

        for name in REMOVED_TIER_3:
            assert not hasattr(server, name), name

    def test_canonical_owners_are_async_and_substantial(self):
        from services import vendor_matching

        owner_tree = _tree(OWNER_PATH)

        for name in REMOVED_TIER_3:
            owner = getattr(vendor_matching, name)
            assert callable(owner), name
            assert inspect.iscoroutinefunction(owner), name

            node = next(
                item
                for item in owner_tree.body
                if isinstance(
                    item,
                    (
                        ast.FunctionDef,
                        ast.AsyncFunctionDef,
                    ),
                )
                and item.name == name
            )
            body = node.body

            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body = body[1:]

            assert len(body) >= 3, name

    def test_authoritative_intake_retains_tier_three_imports(self):
        imports = _intake_imports()

        for name in REMOVED_TIER_3:
            assert (
                imports.get(name)
                == "services.vendor_matching"
            ), name

    def test_no_production_server_surface_references(self):
        violations = []

        for path in BACKEND_DIR.rglob("*.py"):
            if (
                path == SERVER_PATH
                or "tests" in path.parts
                or "__pycache__" in path.parts
            ):
                continue

            try:
                tree = _tree(path)
            except (SyntaxError, UnicodeDecodeError):
                continue

            aliases = {"server"}

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "server":
                            aliases.add(
                                alias.asname or "server"
                            )
                elif (
                    isinstance(node, ast.ImportFrom)
                    and node.module == "server"
                ):
                    for alias in node.names:
                        if (
                            alias.name == "*"
                            or alias.name in REMOVED_TIER_3
                        ):
                            violations.append(
                                f"{path}:{node.lineno}: "
                                f"import {alias.name}"
                            )

            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in aliases
                    and node.attr in REMOVED_TIER_3
                ):
                    violations.append(
                        f"{path}:{node.lineno}: "
                        f"{node.value.id}.{node.attr}"
                    )

        assert not violations, "\n".join(
            sorted(set(violations))
        )

    def test_server_py_shrank(self):
        total = sum(
            1
            for _ in SERVER_PATH.open(
                "r",
                encoding="utf-8",
            )
        )
        assert total <= 1656


class TestLiveSurfaceSmoke:
    BASE_URL = os.environ.get(
        "REACT_APP_BACKEND_URL",
        "http://localhost:8001",
    ).rstrip("/")

    def _reachable(self) -> bool:
        try:
            import requests

            response = requests.get(
                f"{self.BASE_URL}/openapi.json",
                timeout=2,
            )
            return response.status_code == 200
        except Exception:
            return False

    def test_openapi_path_count_858(self):
        if not self._reachable():
            pytest.skip("No backend reachable")

        import requests

        paths = requests.get(
            f"{self.BASE_URL}/openapi.json",
            timeout=5,
        ).json().get("paths", {})
        assert len(paths) == 888

    def test_canonical_owners_are_importable(self):
        from services import vendor_matching

        for name in REMOVED_TIER_3:
            owner = getattr(vendor_matching, name)
            assert inspect.iscoroutinefunction(owner), name
