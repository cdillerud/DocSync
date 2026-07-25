from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv


class ConfigurationError(RuntimeError):
    """Raised when required Hub configuration is missing or invalid."""


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default

    normalized = value.strip().lower()

    if normalized in {"1", "true", "yes", "on"}:
        return True

    if normalized in {"0", "false", "no", "off"}:
        return False

    raise ConfigurationError(f"Invalid boolean configuration value: {value!r}")


def _as_int(
    value: str | None,
    *,
    default: int,
    minimum: int | None = None,
) -> int:
    if value is None or value.strip() == "":
        result = default
    else:
        try:
            result = int(value)
        except ValueError as exc:
            raise ConfigurationError(
                f"Invalid integer configuration value: {value!r}"
            ) from exc

    if minimum is not None and result < minimum:
        raise ConfigurationError(
            f"Configuration value must be at least {minimum}; received {result}"
        )

    return result


def _as_float(
    value: str | None,
    *,
    default: float,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if value is None or value.strip() == "":
        result = default
    else:
        try:
            result = float(value)
        except ValueError as exc:
            raise ConfigurationError(
                f"Invalid numeric configuration value: {value!r}"
            ) from exc

    if minimum is not None and result < minimum:
        raise ConfigurationError(
            f"Configuration value must be at least {minimum}; received {result}"
        )

    if maximum is not None and result > maximum:
        raise ConfigurationError(
            f"Configuration value must be no greater than {maximum}; "
            f"received {result}"
        )

    return result


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "").strip()

    if not value:
        raise ConfigurationError(
            f"Required environment variable {name} is not configured"
        )

    return value


@dataclass(frozen=True, slots=True)
class HubSettings:
    app_name: str
    app_environment: str
    app_version: str

    mongo_url: str
    db_name: str

    demo_mode: bool
    jwt_secret: str

    pilot_mode_enabled: bool
    runtime_mode: str

    ai_classification_enabled: bool
    ai_classification_threshold: float

    email_polling_enabled: bool
    email_polling_interval_minutes: int
    email_polling_user: str
    email_polling_lookback_minutes: int
    email_polling_max_messages: int
    email_polling_max_attachment_mb: int

    sales_email_polling_enabled: bool
    sales_email_polling_user: str
    sales_email_polling_interval_minutes: int

    tenant_id: str
    email_client_id: str
    email_client_secret: str

    bc_environment: str
    bc_company_name: str
    bc_client_id: str
    bc_client_secret: str

    graph_client_id: str
    graph_client_secret: str

    sharepoint_site_hostname: str
    sharepoint_site_path: str
    sharepoint_library_name: str

    enable_create_draft_header: bool

    @property
    def is_production(self) -> bool:
        return self.app_environment.lower() == "production"

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "HubSettings":
        env = environment or os.environ

        return cls(
            app_name=env.get("APP_NAME", "GPI Document Hub"),
            app_environment=env.get("APP_ENVIRONMENT", "development"),
            app_version=env.get("APP_VERSION", "2.0.0"),

            mongo_url=_required(env, "MONGO_URL"),
            db_name=_required(env, "DB_NAME"),

            demo_mode=_as_bool(env.get("DEMO_MODE"), default=True),
            jwt_secret=env.get("JWT_SECRET", "gpi-hub-secret-key"),

            pilot_mode_enabled=_as_bool(
                env.get("PILOT_MODE_ENABLED"),
                default=True,
            ),
            runtime_mode=env.get("HUB_RUNTIME_MODE", "SHADOW").upper(),

            ai_classification_enabled=_as_bool(
                env.get("AI_CLASSIFICATION_ENABLED"),
                default=True,
            ),
            ai_classification_threshold=_as_float(
                env.get("AI_CLASSIFICATION_THRESHOLD"),
                default=0.8,
                minimum=0.0,
                maximum=1.0,
            ),

            email_polling_enabled=_as_bool(
                env.get("EMAIL_POLLING_ENABLED"),
                default=False,
            ),
            email_polling_interval_minutes=_as_int(
                env.get("EMAIL_POLLING_INTERVAL_MINUTES"),
                default=5,
                minimum=1,
            ),
            email_polling_user=env.get("EMAIL_POLLING_USER", ""),
            email_polling_lookback_minutes=_as_int(
                env.get("EMAIL_POLLING_LOOKBACK_MINUTES"),
                default=60,
                minimum=1,
            ),
            email_polling_max_messages=_as_int(
                env.get("EMAIL_POLLING_MAX_MESSAGES"),
                default=25,
                minimum=1,
            ),
            email_polling_max_attachment_mb=_as_int(
                env.get("EMAIL_POLLING_MAX_ATTACHMENT_MB"),
                default=25,
                minimum=1,
            ),

            sales_email_polling_enabled=_as_bool(
                env.get("SALES_EMAIL_POLLING_ENABLED"),
                default=False,
            ),
            sales_email_polling_user=env.get(
                "SALES_EMAIL_POLLING_USER",
                "",
            ),
            sales_email_polling_interval_minutes=_as_int(
                env.get("SALES_EMAIL_POLLING_INTERVAL_MINUTES"),
                default=5,
                minimum=1,
            ),

            tenant_id=env.get("TENANT_ID", ""),
            email_client_id=env.get("EMAIL_CLIENT_ID", ""),
            email_client_secret=env.get("EMAIL_CLIENT_SECRET", ""),

            bc_environment=env.get("BC_ENVIRONMENT", ""),
            bc_company_name=env.get("BC_COMPANY_NAME", ""),
            bc_client_id=env.get("BC_CLIENT_ID", ""),
            bc_client_secret=env.get("BC_CLIENT_SECRET", ""),

            graph_client_id=env.get("GRAPH_CLIENT_ID", ""),
            graph_client_secret=env.get("GRAPH_CLIENT_SECRET", ""),

            sharepoint_site_hostname=env.get(
                "SHAREPOINT_SITE_HOSTNAME",
                "gamerpackaging.sharepoint.com",
            ),
            sharepoint_site_path=env.get(
                "SHAREPOINT_SITE_PATH",
                "/sites/GPI-DocumentHub-Test",
            ),
            sharepoint_library_name=env.get(
                "SHAREPOINT_LIBRARY_NAME",
                "Documents",
            ),

            enable_create_draft_header=_as_bool(
                env.get("ENABLE_CREATE_DRAFT_HEADER"),
                default=False,
            ),
        )


def load_environment_file(backend_root: Path | None = None) -> None:
    root = backend_root or Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env", override=False)


@lru_cache(maxsize=1)
def get_settings() -> HubSettings:
    load_environment_file()
    return HubSettings.from_environment()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
