import pytest

from services.sharepoint_write_guard_service import (
    SharePointProductionWriteBlocked,
    check_sharepoint_write_protection,
    is_production_sharepoint_target,
)


def test_test_target_is_not_production():
    assert is_production_sharepoint_target(
        target="test", site_path="/sites/GPI-DocumentHub-Test"
    ) is False


def test_named_production_target_is_detected():
    assert is_production_sharepoint_target(
        target="production", site_path="/sites/GPI-DocumentHub-Test"
    ) is True


def test_effective_gamer_accounting_path_is_detected_even_if_target_says_test():
    assert is_production_sharepoint_target(
        target="test", site_path="/sites/GamerAccounting"
    ) is True


def test_production_write_block_defaults_fail_closed(monkeypatch):
    monkeypatch.delenv("SHAREPOINT_BLOCK_PRODUCTION_WRITES", raising=False)
    with pytest.raises(SharePointProductionWriteBlocked, match="Production write blocked"):
        check_sharepoint_write_protection(
            "upload_to_sharepoint",
            target="production",
            site_path="/sites/GamerAccounting",
        )


def test_explicit_false_allows_authorized_cutover_write(monkeypatch):
    monkeypatch.setenv("SHAREPOINT_BLOCK_PRODUCTION_WRITES", "false")
    check_sharepoint_write_protection(
        "upload_to_sharepoint",
        target="production",
        site_path="/sites/GamerAccounting",
    )


def test_uat_write_allowed_while_production_block_enabled(monkeypatch):
    monkeypatch.setenv("SHAREPOINT_BLOCK_PRODUCTION_WRITES", "true")
    check_sharepoint_write_protection(
        "write_sharepoint_parity_metadata",
        target="test",
        site_path="/sites/GPI-DocumentHub-Test",
    )
