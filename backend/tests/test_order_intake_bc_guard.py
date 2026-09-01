"""Safety tests for the Order Intake Business Central test gateway."""

import pytest

import order_intake.bc_test_gateway as gateway_module
from order_intake.bc_test_gateway import (
    APPROVED_ENVIRONMENT,
    OrderIntakeBCGuardError,
    OrderIntakeBCTestGateway,
    TEST_EXTERNAL_DOC_PREFIX,
    WRITE_FLAG_NAME,
)


def _credentials(monkeypatch):
    monkeypatch.setattr(gateway_module, "BC_CLIENT_ID", "test-client")
    monkeypatch.setattr(gateway_module, "BC_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(gateway_module, "BC_TENANT_ID", "test-tenant")


def test_wrong_environment_is_blocked(monkeypatch):
    _credentials(monkeypatch)
    monkeypatch.setenv("BC_ENVIRONMENT", "Production")
    gateway = OrderIntakeBCTestGateway()

    with pytest.raises(OrderIntakeBCGuardError, match="restricted"):
        gateway.assert_target_environment()


def test_approved_environment_allows_read_precondition(monkeypatch):
    _credentials(monkeypatch)
    monkeypatch.setenv("BC_ENVIRONMENT", APPROVED_ENVIRONMENT)
    gateway = OrderIntakeBCTestGateway()

    gateway.assert_target_environment()


def test_write_flag_is_required(monkeypatch):
    _credentials(monkeypatch)
    monkeypatch.setenv("BC_ENVIRONMENT", APPROVED_ENVIRONMENT)
    monkeypatch.delenv(WRITE_FLAG_NAME, raising=False)
    gateway = OrderIntakeBCTestGateway()

    with pytest.raises(OrderIntakeBCGuardError, match="write testing is disabled"):
        gateway.assert_write_enabled()


def test_write_flag_enables_only_guarded_test_path(monkeypatch):
    _credentials(monkeypatch)
    monkeypatch.setenv("BC_ENVIRONMENT", APPROVED_ENVIRONMENT)
    monkeypatch.setenv(WRITE_FLAG_NAME, "true")
    gateway = OrderIntakeBCTestGateway()

    gateway.assert_write_enabled()


def test_external_document_must_be_test_tagged():
    with pytest.raises(OrderIntakeBCGuardError, match=TEST_EXTERNAL_DOC_PREFIX):
        OrderIntakeBCTestGateway._validate_test_external_document("65194")

    OrderIntakeBCTestGateway._validate_test_external_document("AITEST-65194")
