import pytest

from services.startup_validator import validate_startup_secrets


def _safe_env(monkeypatch):
    values = {
        "JWT_SECRET": "a" * 64,
        "ADMIN_EMAIL": "hub-admin@gamerpackaging.com",
        "ADMIN_PASSWORD": "UAT-only-strong-placeholder-123!",
        "MONGO_URL": "mongodb://mongodb:27017",
        "AUTO_CREATE_SALES_ORDER_ENABLED": "false",
        "ENABLE_OUT_OF_SCOPE_SALES_ROUTES": "false",
        "SALES_EMAIL_POLLING_ENABLED": "false",
        "BC_SALES_LINK_WRITE_ENABLED": "false",
        "INSIDE_SALES_PILOT_ENABLED": "false",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_safe_ap_warehouse_scope_starts(monkeypatch):
    _safe_env(monkeypatch)
    validate_startup_secrets()


def test_sales_auto_create_must_be_explicitly_false(monkeypatch):
    _safe_env(monkeypatch)
    monkeypatch.delenv("AUTO_CREATE_SALES_ORDER_ENABLED")
    with pytest.raises(RuntimeError, match="AUTO_CREATE_SALES_ORDER_ENABLED"):
        validate_startup_secrets()


@pytest.mark.parametrize(
    "flag",
    [
        "AUTO_CREATE_SALES_ORDER_ENABLED",
        "ENABLE_OUT_OF_SCOPE_SALES_ROUTES",
        "SALES_EMAIL_POLLING_ENABLED",
        "BC_SALES_LINK_WRITE_ENABLED",
        "INSIDE_SALES_PILOT_ENABLED",
    ],
)
def test_sales_activation_flags_block_startup(monkeypatch, flag):
    _safe_env(monkeypatch)
    monkeypatch.setenv(flag, "true")
    with pytest.raises(RuntimeError, match=flag):
        validate_startup_secrets()
