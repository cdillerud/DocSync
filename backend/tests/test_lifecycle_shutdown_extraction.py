"""
Regression coverage for lifecycle shutdown extraction.
"""

from __future__ import annotations

from pathlib import Path
import ast
import asyncio
from unittest.mock import Mock

import pytest


BACKEND_DIR = (
    Path(__file__).resolve().parent.parent
)


class TestSourceExtraction:
    def test_server_shutdown_is_thin_delegate(self):
        tree = ast.parse(
            (
                BACKEND_DIR / "server.py"
            ).read_text()
        )

        shutdown_node = next(
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name
                == "shutdown_db_client"
            )
        )

        imports = [
            node
            for node in ast.walk(
                shutdown_node
            )
            if (
                isinstance(
                    node,
                    ast.ImportFrom,
                )
                and node.module
                == "services.lifecycle_service"
                and any(
                    alias.name
                    == "shutdown_application"
                    for alias in node.names
                )
            )
        ]

        calls = [
            node
            for node in ast.walk(
                shutdown_node
            )
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "shutdown_application"
            )
        ]

        assert len(imports) == 1
        assert len(calls) == 1

    def test_canonical_service_closes_once(self):
        tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_service.py"
            ).read_text()
        )

        close_calls = [
            node
            for node in ast.walk(tree)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Attribute,
                )
                and isinstance(
                    node.func.value,
                    ast.Name,
                )
                and node.func.value.id
                == "client"
                and node.func.attr == "close"
            )
        ]

        assert len(close_calls) == 1


class TestCanonicalShutdown:
    @pytest.mark.asyncio
    async def test_stops_every_resource_once(self):
        from services.lifecycle_service import (
            shutdown_application,
        )

        async def wait_forever():
            await asyncio.Event().wait()

        tasks = [
            asyncio.create_task(
                wait_forever()
            )
            for _ in range(4)
        ]

        await asyncio.sleep(0)

        cache = Mock()
        auto_resolve = Mock()
        client = Mock()
        logger = Mock()

        get_cache_service = Mock(
            return_value=cache
        )

        get_auto_resolve_service = Mock(
            return_value=auto_resolve
        )

        await shutdown_application(
            dynamic_mailbox_task=tasks[0],
            email_polling_task=tasks[1],
            sales_polling_task=tasks[2],
            pilot_summary_task=tasks[3],
            get_cache_service=(
                get_cache_service
            ),
            get_auto_resolve_service=(
                get_auto_resolve_service
            ),
            client=client,
            logger=logger,
        )

        assert all(
            task.cancelled()
            for task in tasks
        )

        get_cache_service.assert_called_once_with()
        get_auto_resolve_service.assert_called_once_with()
        cache.stop_background_sync.assert_called_once_with()
        auto_resolve.stop.assert_called_once_with()
        client.close.assert_called_once_with()

        assert logger.info.call_count == 4

    @pytest.mark.asyncio
    async def test_ignores_none_and_completed_tasks(self):
        from services.lifecycle_service import (
            shutdown_application,
        )

        async def finish():
            return "done"

        completed = asyncio.create_task(
            finish()
        )

        await completed

        cache = Mock()
        auto_resolve = Mock()
        client = Mock()
        logger = Mock()

        await shutdown_application(
            dynamic_mailbox_task=None,
            email_polling_task=completed,
            sales_polling_task=None,
            pilot_summary_task=None,
            get_cache_service=Mock(
                return_value=cache
            ),
            get_auto_resolve_service=Mock(
                return_value=auto_resolve
            ),
            client=client,
            logger=logger,
        )

        assert completed.done()
        assert not completed.cancelled()
        assert logger.info.call_count == 0
        cache.stop_background_sync.assert_called_once_with()
        auto_resolve.stop.assert_called_once_with()
        client.close.assert_called_once_with()


class TestServerCompatibilitySeam:
    @pytest.mark.asyncio
    async def test_server_passes_current_resources(
        self,
        monkeypatch,
    ):
        import server
        import services.lifecycle_service as lifecycle

        sentinels = {
            "dynamic": object(),
            "email": object(),
            "sales": object(),
            "pilot": object(),
            "client": object(),
            "logger": object(),
        }

        cache_getter = Mock()
        auto_getter = Mock()

        monkeypatch.setattr(
            server,
            "_dynamic_mailbox_polling_task",
            sentinels["dynamic"],
        )

        monkeypatch.setattr(
            server,
            "_email_polling_task",
            sentinels["email"],
        )

        monkeypatch.setattr(
            server,
            "_sales_polling_task",
            sentinels["sales"],
        )

        monkeypatch.setattr(
            server,
            "_pilot_summary_task",
            sentinels["pilot"],
        )

        monkeypatch.setattr(
            server,
            "get_cache_service",
            cache_getter,
        )

        monkeypatch.setattr(
            server,
            "get_auto_resolve_service",
            auto_getter,
        )

        monkeypatch.setattr(
            server,
            "client",
            sentinels["client"],
        )

        monkeypatch.setattr(
            server,
            "logger",
            sentinels["logger"],
        )

        captured = {}

        async def fake_shutdown_application(
            **kwargs,
        ):
            captured.update(kwargs)

        monkeypatch.setattr(
            lifecycle,
            "shutdown_application",
            fake_shutdown_application,
        )

        await server.shutdown_db_client()

        assert captured == {
            "dynamic_mailbox_task": (
                sentinels["dynamic"]
            ),
            "email_polling_task": (
                sentinels["email"]
            ),
            "sales_polling_task": (
                sentinels["sales"]
            ),
            "pilot_summary_task": (
                sentinels["pilot"]
            ),
            "get_cache_service": (
                cache_getter
            ),
            "get_auto_resolve_service": (
                auto_getter
            ),
            "client": sentinels["client"],
            "logger": sentinels["logger"],
        }
