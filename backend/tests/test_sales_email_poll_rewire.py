"""
Regression tests for direct sales-email polling service wiring.
"""

from __future__ import annotations

from pathlib import Path
import ast

import pytest


BACKEND_DIR = (
    Path(__file__).resolve().parent.parent
)


class TestSourceWiring:
    def test_server_wrapper_is_removed(self):
        tree = ast.parse(
            (
                BACKEND_DIR / "server.py"
            ).read_text()
        )

        definitions = {
            node.name
            for node in tree.body
            if isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            )
        }

        assert (
            "run_sales_email_poll"
            not in definitions
        )

    def test_sales_module_uses_canonical_service(self):
        tree = ast.parse(
            (
                BACKEND_DIR
                / "sales_module.py"
            ).read_text()
        )

        server_imports = []
        canonical_imports = []

        for node in ast.walk(tree):
            if not isinstance(
                node,
                ast.ImportFrom,
            ):
                continue

            imported_names = {
                alias.name
                for alias in node.names
            }

            if (
                node.module
                in {
                    "server",
                    "backend.server",
                }
                and "run_sales_email_poll"
                in imported_names
            ):
                server_imports.append(
                    node.lineno
                )

            if (
                node.module
                == (
                    "services."
                    "email_polling_service"
                )
                and "run_sales_email_poll"
                in imported_names
            ):
                canonical_imports.append(
                    node.lineno
                )

        assert server_imports == []
        assert len(canonical_imports) == 1


class TestTriggerBehavior:
    @pytest.mark.asyncio
    async def test_trigger_calls_canonical_service(
        self,
        monkeypatch,
    ):
        import sales_module
        import services.email_polling_service as service

        expected = {
            "success": True,
            "source": "canonical-service",
        }

        async def fake_poll():
            return expected

        monkeypatch.setattr(
            service,
            "run_sales_email_poll",
            fake_poll,
        )

        monkeypatch.setitem(
            sales_module._sales_email_config,
            "mailbox",
            "sales@example.com",
        )

        result = await (
            sales_module
            .trigger_sales_email_poll()
        )

        assert result == expected
