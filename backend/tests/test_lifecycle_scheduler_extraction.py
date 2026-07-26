"""
Regression coverage for lifecycle scheduler extraction.
"""

from __future__ import annotations

from pathlib import Path
import ast
import asyncio
import hashlib
import inspect
import sys
from types import ModuleType
from unittest.mock import AsyncMock, Mock

import pytest


BACKEND_DIR = (
    Path(__file__).resolve().parent.parent
)

EXPECTED_BODY_HASH = (
    "842b0098912ac669bf2428f96825b854c76e4b68efa7ac0c460a889bd93d6000"
)


def _body_hash(function_node):
    module = ast.Module(
        body=function_node.body,
        type_ignores=[],
    )

    return hashlib.sha256(
        ast.dump(
            module,
            include_attributes=False,
        ).encode("utf-8")
    ).hexdigest()


class TestSourceExtraction:
    def test_server_uses_canonical_coroutine(
        self,
    ):
        tree = ast.parse(
            (
                BACKEND_DIR / "server.py"
            ).read_text()
        )

        startup = next(
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name == "startup"
            )
        )

        nested = [
            node
            for node in startup.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name
                == "_startup_sync_status"
            )
        ]

        imports = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(
                    node,
                    ast.ImportFrom,
                )
                and node.module
                == (
                    "services."
                    "lifecycle_scheduler_service"
                )
                and any(
                    alias.name
                    == "startup_sync_status"
                    for alias in node.names
                )
            )
        ]

        assert nested == []
        assert len(imports) == 1

    def test_registry_name_and_ownership_preserved(
        self,
    ):
        tree = ast.parse(
            (
                BACKEND_DIR / "server.py"
            ).read_text()
        )

        startup = next(
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name == "startup"
            )
        )

        wrappers = []

        for node in ast.walk(startup):
            if not (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "register_background_task"
            ):
                continue

            task_names = [
                keyword.value.value
                for keyword in node.keywords
                if (
                    keyword.arg == "name"
                    and isinstance(
                        keyword.value,
                        ast.Constant,
                    )
                )
            ]

            if task_names == [
                "startup_sync_status"
            ]:
                wrappers.append(node)

        assert len(wrappers) == 1

        wrapper = wrappers[0]

        assert len(wrapper.args) == 1

        create_task = wrapper.args[0]

        assert isinstance(
            create_task,
            ast.Call,
        )

        assert isinstance(
            create_task.func,
            ast.Attribute,
        )

        assert (
            create_task.func.attr
            == "create_task"
        )

        coroutine_call = (
            create_task.args[0]
        )

        assert isinstance(
            coroutine_call,
            ast.Call,
        )

        assert isinstance(
            coroutine_call.func,
            ast.Name,
        )

        assert (
            coroutine_call.func.id
            == "startup_sync_status"
        )

        logger_keywords = [
            keyword
            for keyword
            in coroutine_call.keywords
            if (
                keyword.arg == "logger"
                and isinstance(
                    keyword.value,
                    ast.Name,
                )
                and keyword.value.id
                == "logger"
            )
        ]

        assert len(logger_keywords) == 1

    def test_canonical_body_matches_original(
        self,
    ):
        tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
            ).read_text()
        )

        function = next(
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name
                == "startup_sync_status"
            )
        )

        assert (
            _body_hash(function)
            == EXPECTED_BODY_HASH
        )

    def test_service_has_no_server_or_task_ownership(
        self,
    ):
        tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
            ).read_text()
        )

        server_imports = [
            node
            for node in ast.walk(tree)
            if (
                isinstance(
                    node,
                    ast.ImportFrom,
                )
                and node.module
                in {
                    "server",
                    "backend.server",
                }
            )
            or (
                isinstance(
                    node,
                    ast.Import,
                )
                and any(
                    alias.name
                    in {
                        "server",
                        "backend.server",
                    }
                    for alias in node.names
                )
            )
        ]

        create_tasks = [
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
                == "asyncio"
                and node.func.attr
                == "create_task"
            )
        ]

        assert server_imports == []
        assert create_tasks == []

    def test_canonical_signature(self):
        from services.lifecycle_scheduler_service import (
            startup_sync_status,
        )

        signature = inspect.signature(
            startup_sync_status
        )

        assert list(
            signature.parameters
        ) == ["logger"]

        assert (
            signature.parameters[
                "logger"
            ].kind
            is inspect.Parameter.KEYWORD_ONLY
        )


def install_readiness_module(
    monkeypatch,
    sync_function,
):
    import routers

    readiness_module = ModuleType(
        "routers.readiness"
    )

    readiness_module.sync_readiness_to_status = (
        sync_function
    )

    monkeypatch.setitem(
        sys.modules,
        "routers.readiness",
        readiness_module,
    )

    monkeypatch.setattr(
        routers,
        "readiness",
        readiness_module,
        raising=False,
    )


class TestRuntimeBehavior:
    @pytest.mark.asyncio
    async def test_logs_autofiled_documents(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock()
        sync = AsyncMock(
            return_value={
                "total_fixed": 3,
            }
        )

        install_readiness_module(
            monkeypatch,
            sync,
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        logger = Mock()

        await scheduler.startup_sync_status(
            logger=logger
        )

        sleep.assert_awaited_once_with(30)
        sync.assert_awaited_once_with()

        logger.info.assert_called_once_with(
            "[Startup] Sync-status auto-filed "
            "%d docs that were ready but "
            "sitting in inbox",
            3,
        )

        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_logs_clean_inbox(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock()
        sync = AsyncMock(
            return_value={
                "total_fixed": 0,
            }
        )

        install_readiness_module(
            monkeypatch,
            sync,
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        logger = Mock()

        await scheduler.startup_sync_status(
            logger=logger
        )

        logger.info.assert_called_once_with(
            "[Startup] Sync-status check: "
            "inbox is clean, no docs to "
            "auto-file"
        )

        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_is_nonfatal(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock()
        error = RuntimeError(
            "simulated readiness failure"
        )

        sync = AsyncMock(
            side_effect=error
        )

        install_readiness_module(
            monkeypatch,
            sync,
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        logger = Mock()

        await scheduler.startup_sync_status(
            logger=logger
        )

        logger.warning.assert_called_once_with(
            "[Startup] Sync-status "
            "auto-run failed: %s",
            error,
        )


class TestPeriodicSyncStatusExtraction:
    def test_server_uses_canonical_periodic_coroutine(
        self,
    ):
        tree = ast.parse(
            (
                BACKEND_DIR / "server.py"
            ).read_text()
        )

        startup = next(
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name == "startup"
            )
        )

        nested = [
            node
            for node in startup.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name
                == "_periodic_sync_status"
            )
        ]

        imports = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(
                    node,
                    ast.ImportFrom,
                )
                and node.module
                == (
                    "services."
                    "lifecycle_scheduler_service"
                )
                and any(
                    alias.name
                    == "periodic_sync_status"
                    for alias in node.names
                )
            )
        ]

        assert nested == []
        assert len(imports) == 1

    def test_periodic_registry_ownership_preserved(
        self,
    ):
        tree = ast.parse(
            (
                BACKEND_DIR / "server.py"
            ).read_text()
        )

        startup = next(
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name == "startup"
            )
        )

        wrappers = []

        for node in ast.walk(startup):
            if not (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "register_background_task"
            ):
                continue

            names = [
                keyword.value.value
                for keyword in node.keywords
                if (
                    keyword.arg == "name"
                    and isinstance(
                        keyword.value,
                        ast.Constant,
                    )
                )
            ]

            if names == [
                "periodic_sync_status"
            ]:
                wrappers.append(node)

        assert len(wrappers) == 1

        create_task = wrappers[0].args[0]

        assert isinstance(
            create_task,
            ast.Call,
        )

        assert isinstance(
            create_task.func,
            ast.Attribute,
        )

        assert (
            create_task.func.attr
            == "create_task"
        )

        coroutine_call = (
            create_task.args[0]
        )

        assert isinstance(
            coroutine_call,
            ast.Call,
        )

        assert isinstance(
            coroutine_call.func,
            ast.Name,
        )

        assert (
            coroutine_call.func.id
            == "periodic_sync_status"
        )

        logger_keywords = [
            keyword
            for keyword
            in coroutine_call.keywords
            if (
                keyword.arg == "logger"
                and isinstance(
                    keyword.value,
                    ast.Name,
                )
                and keyword.value.id
                == "logger"
            )
        ]

        assert len(logger_keywords) == 1

    def test_periodic_body_matches_original(
        self,
    ):
        tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
            ).read_text()
        )

        function = next(
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name
                == "periodic_sync_status"
            )
        )

        assert (
            _body_hash(function)
            == "6545fc7060f4024d7410a7c17f6fb2b26c9f10213af853b5684fc2530581c766"
        )

    def test_periodic_signature(self):
        from services.lifecycle_scheduler_service import (
            periodic_sync_status,
        )

        signature = inspect.signature(
            periodic_sync_status
        )

        assert list(
            signature.parameters
        ) == ["logger"]

        assert (
            signature.parameters[
                "logger"
            ].kind
            is inspect.Parameter.KEYWORD_ONLY
        )


class TestPeriodicSyncStatusRuntime:
    @pytest.mark.asyncio
    async def test_logs_fixed_documents(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock(
            side_effect=[
                None,
                asyncio.CancelledError(),
            ]
        )

        sync = AsyncMock(
            return_value={
                "total_fixed": 4,
            }
        )

        install_readiness_module(
            monkeypatch,
            sync,
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        logger = Mock()

        with pytest.raises(
            asyncio.CancelledError
        ):
            await scheduler.periodic_sync_status(
                logger=logger
            )

        assert sleep.await_count == 2

        assert (
            sleep.await_args_list[
                0
            ].args
            == (120,)
        )

        assert (
            sleep.await_args_list[
                1
            ].args
            == (30 * 60,)
        )

        sync.assert_awaited_once_with()

        logger.info.assert_called_once_with(
            "[PeriodicSync] Sync-status "
            "auto-filed %d docs",
            4,
        )

        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_zero_changes_is_quiet(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock(
            side_effect=[
                None,
                asyncio.CancelledError(),
            ]
        )

        sync = AsyncMock(
            return_value={
                "total_fixed": 0,
            }
        )

        install_readiness_module(
            monkeypatch,
            sync,
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        logger = Mock()

        with pytest.raises(
            asyncio.CancelledError
        ):
            await scheduler.periodic_sync_status(
                logger=logger
            )

        logger.info.assert_not_called()
        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_is_nonfatal(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock(
            side_effect=[
                None,
                asyncio.CancelledError(),
            ]
        )

        error = RuntimeError(
            "simulated periodic failure"
        )

        sync = AsyncMock(
            side_effect=error
        )

        install_readiness_module(
            monkeypatch,
            sync,
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        logger = Mock()

        with pytest.raises(
            asyncio.CancelledError
        ):
            await scheduler.periodic_sync_status(
                logger=logger
            )

        logger.warning.assert_called_once_with(
            "[PeriodicSync] Sync-status "
            "failed: %s",
            error,
        )
