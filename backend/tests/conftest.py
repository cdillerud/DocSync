"""Shared pytest configuration for the backend test suite.

The repository contains two different kinds of tests:

* deterministic unit/component tests that should run on every machine; and
* legacy/live integration tests that make HTTP requests to a separately
  running deployment and depend on that deployment's current configuration.

Historically both groups ran together, which made ``pytest backend/tests``
report application regressions when the real cause was an unavailable or
intentionally reconfigured external service.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


# Unit tests for bc_sandbox_service explicitly exercise its built-in mock data.
# Set this before test modules import the service so a production .env file does
# not silently turn those deterministic tests into live Business Central calls.
os.environ["DEMO_MODE"] = "true"


LIVE_API_MODULES = {
    "test_audit_dashboard.py",
    "test_file_import.py",
    "test_generic_workflow_api.py",
    "test_generic_workflow_apis.py",
    "test_gpi_document_hub.py",
    "test_migration_api.py",
    "test_phase6_shadow_mode.py",
    "test_phase7_email_polling.py",
    "test_production_email_parser.py",
}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live-api",
        action="store_true",
        default=False,
        help="run tests that call a separately running DocSync API deployment",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live_api: requires a separately running and correctly configured API deployment",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    run_live = config.getoption("--run-live-api") or os.environ.get(
        "RUN_LIVE_API_TESTS", ""
    ).lower() in {"1", "true", "yes"}

    if run_live:
        return

    skip_live = pytest.mark.skip(
        reason="live API test; rerun with --run-live-api against the intended deployment"
    )

    for item in items:
        module_name = Path(str(item.fspath)).name
        if module_name in LIVE_API_MODULES:
            item.add_marker(pytest.mark.live_api)
            item.add_marker(skip_live)
