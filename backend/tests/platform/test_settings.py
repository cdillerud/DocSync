import pytest

from hub_platform.bootstrap.settings import (
    ConfigurationError,
    HubSettings,
)


def minimum_environment() -> dict[str, str]:
    return {
        "MONGO_URL": "mongodb://localhost:27017",
        "DB_NAME": "gpi_hub_test",
    }


def test_loads_minimum_configuration() -> None:
    settings = HubSettings.from_environment(minimum_environment())

    assert settings.mongo_url == "mongodb://localhost:27017"
    assert settings.db_name == "gpi_hub_test"
    assert settings.runtime_mode == "SHADOW"
    assert settings.demo_mode is True
    assert settings.email_polling_enabled is False


def test_requires_mongo_url() -> None:
    environment = minimum_environment()
    del environment["MONGO_URL"]

    with pytest.raises(ConfigurationError, match="MONGO_URL"):
        HubSettings.from_environment(environment)


def test_rejects_invalid_boolean() -> None:
    environment = minimum_environment()
    environment["DEMO_MODE"] = "occasionally"

    with pytest.raises(ConfigurationError, match="Invalid boolean"):
        HubSettings.from_environment(environment)


def test_rejects_invalid_ai_threshold() -> None:
    environment = minimum_environment()
    environment["AI_CLASSIFICATION_THRESHOLD"] = "1.5"

    with pytest.raises(ConfigurationError):
        HubSettings.from_environment(environment)


def test_normalizes_runtime_mode() -> None:
    environment = minimum_environment()
    environment["HUB_RUNTIME_MODE"] = "pilot_read_only"

    settings = HubSettings.from_environment(environment)

    assert settings.runtime_mode == "PILOT_READ_ONLY"
