import pytest

from services.startup_validator import validate_startup_secrets


def _safe_env(monkeypatch):
    values = {
        "DEMO_MODE": "false",
        "JWT_SECRET": "a" * 64,
        "ADMIN_EMAIL": "hub-admin@gamerpackaging.com",
        "ADMIN_PASSWORD": "UAT-only-strong-placeholder-123!",
        "MONGO_URL": "mongodb://mongodb:27017",
        "BC_HUB_API_KEY": "b" * 64,
        "AUTO_CREATE_SALES_ORDER_ENABLED": "false",
        "ENABLE_OUT_OF_SCOPE_SALES_ROUTES": "false",
        "SALES_EMAIL_POLLING_ENABLED": "false",
        "BC_SALES_LINK_WRITE_ENABLED": "false",
        "INSIDE_SALES_PILOT_ENABLED": "false",
        "GRAPH_WEBHOOK_ENABLED": "false",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_safe_ap_warehouse_scope_starts(monkeypatch):
    _safe_env(monkeypatch)
    validate_startup_secrets()


def test_missing_ap_auto_post_flag_is_forced_off(monkeypatch):
    _safe_env(monkeypatch)
    monkeypatch.delenv("AUTO_POST_ENABLED", raising=False)
    validate_startup_secrets()
    assert __import__("os").environ["AUTO_POST_ENABLED"] == "false"


def test_explicit_ap_auto_post_can_be_enabled_for_controlled_uat(monkeypatch):
    _safe_env(monkeypatch)
    monkeypatch.setenv("AUTO_POST_ENABLED", "true")
    validate_startup_secrets()
    assert __import__("os").environ["AUTO_POST_ENABLED"] == "true"


def test_sales_auto_create_must_be_explicitly_false(monkeypatch):
    _safe_env(monkeypatch)
    monkeypatch.delenv("AUTO_CREATE_SALES_ORDER_ENABLED")
    with pytest.raises(RuntimeError, match="AUTO_CREATE_SALES_ORDER_ENABLED"):
        validate_startup_secrets()


def test_non_demo_runtime_requires_bc_hub_machine_key(monkeypatch):
    _safe_env(monkeypatch)
    monkeypatch.delenv("BC_HUB_API_KEY")
    with pytest.raises(RuntimeError, match="BC_HUB_API_KEY"):
        validate_startup_secrets()


def test_short_or_placeholder_machine_key_is_rejected(monkeypatch):
    _safe_env(monkeypatch)
    for value in ("changeme", "gpi-hub-key", "short"):
        monkeypatch.setenv("BC_HUB_API_KEY", value)
        with pytest.raises(RuntimeError, match="BC_HUB_API_KEY"):
            validate_startup_secrets()


@pytest.mark.parametrize(
    "flag",
    [
        "AUTO_CREATE_SALES_ORDER_ENABLED",
        "ENABLE_OUT_OF_SCOPE_SALES_ROUTES",
        "SALES_EMAIL_POLLING_ENABLED",
        "BC_SALES_LINK_WRITE_ENABLED",
        "INSIDE_SALES_PILOT_ENABLED",
        "GRAPH_WEBHOOK_ENABLED",
    ],
)
def test_prohibited_parity_activation_flags_block_startup(monkeypatch, flag):
    _safe_env(monkeypatch)
    monkeypatch.setenv(flag, "true")
    with pytest.raises(RuntimeError, match=flag):
        validate_startup_secrets()
