import pytest

from services import sales_order_bc_writer as writer


def test_write_environment_must_be_explicit(monkeypatch):
    monkeypatch.delenv(
        "SALES_ORDER_BC_WRITE_ENVIRONMENT",
        raising=False,
    )

    with pytest.raises(
        ValueError,
        match="must be explicitly configured",
    ):
        writer._configured_write_environment()


@pytest.mark.asyncio
async def test_explicit_write_company_id_avoids_discovery(
    monkeypatch,
):
    monkeypatch.setenv(
        "SALES_ORDER_BC_WRITE_ENVIRONMENT",
        "Sandbox_5_5_2026",
    )
    monkeypatch.setenv(
        "SALES_ORDER_BC_WRITE_COMPANY_ID",
        "sandbox-company-id",
    )

    environment, company_id = (
        await writer._resolve_write_target("unused-token")
    )

    assert environment == "Sandbox_5_5_2026"
    assert company_id == "sandbox-company-id"


def test_write_company_is_selected_by_exact_name():
    company_id = writer._select_write_company_id(
        [
            {
                "id": "wrong-id",
                "name": "Gamer Packaging Test",
                "displayName": "Gamer Packaging Test",
            },
            {
                "id": "correct-id",
                "name": "Gamer Packaging",
                "displayName": "Gamer Packaging",
            },
        ],
        "Gamer Packaging",
    )

    assert company_id == "correct-id"


def test_write_company_selection_rejects_missing_company():
    with pytest.raises(
        ValueError,
        match="Matches found: 0",
    ):
        writer._select_write_company_id(
            [
                {
                    "id": "other-id",
                    "name": "Other Company",
                    "displayName": "Other Company",
                }
            ],
            "Gamer Packaging",
        )
