from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests


BC_RESOURCE = "https://api.businesscentral.dynamics.com"
BC_SCOPE = f"{BC_RESOURCE}/.default"


class BusinessCentralConfigurationError(RuntimeError):
    pass


class BusinessCentralAuthenticationError(RuntimeError):
    pass


class BusinessCentralApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class BusinessCentralSettings:
    tenant_id: str
    environment_name: str
    company_id: str
    client_id: str
    client_secret: str

    @classmethod
    def from_environment(cls) -> "BusinessCentralSettings":
        values = {
            "tenant_id": os.getenv("GPI_BC_TENANT_ID", "").strip(),
            "environment_name": os.getenv(
                "GPI_BC_ENVIRONMENT_NAME", ""
            ).strip(),
            "company_id": os.getenv("GPI_BC_COMPANY_ID", "").strip(),
            "client_id": os.getenv("GPI_BC_CLIENT_ID", "").strip(),
            "client_secret": os.getenv(
                "GPI_BC_CLIENT_SECRET", ""
            ).strip(),
        }

        missing = [
            name
            for name, value in values.items()
            if not value
        ]

        if missing:
            raise BusinessCentralConfigurationError(
                "Missing Business Central settings: "
                + ", ".join(missing)
            )

        if (
            values["environment_name"]
            != "Sandbox_NoZetadocs_UAT"
        ):
            raise BusinessCentralConfigurationError(
                "This client is UAT-only. "
                "Expected Sandbox_NoZetadocs_UAT."
            )

        return cls(**values)


class BusinessCentralClient:
    def __init__(
        self,
        settings: BusinessCentralSettings,
        *,
        timeout_seconds: int = 60,
    ) -> None:
        self.settings = settings
        self.timeout_seconds = timeout_seconds

    @property
    def token_url(self) -> str:
        return (
            "https://login.microsoftonline.com/"
            f"{self.settings.tenant_id}"
            "/oauth2/v2.0/token"
        )

    def api_base_url_for(
        self,
        api_group: str,
        api_version: str = "v1.0",
    ) -> str:
        group = api_group.strip("/")
        version = api_version.strip("/")
        if not group or not version:
            raise BusinessCentralConfigurationError(
                "Business Central API group and version are required."
            )

        return (
            f"{BC_RESOURCE}/v2.0/"
            f"{self.settings.tenant_id}/"
            f"{self.settings.environment_name}/"
            f"api/gpi/{group}/{version}/"
            f"companies({self.settings.company_id})"
        )

    @property
    def api_base_url(self) -> str:
        return self.api_base_url_for("packagingQuotes")

    def acquire_access_token(self) -> str:
        response = requests.post(
            self.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.settings.client_id,
                "client_secret": self.settings.client_secret,
                "scope": BC_SCOPE,
            },
            timeout=self.timeout_seconds,
        )

        if response.status_code != 200:
            raise BusinessCentralAuthenticationError(
                "Business Central token acquisition failed "
                f"with HTTP {response.status_code}."
            )

        payload = response.json()
        token = payload.get("access_token")

        if not isinstance(token, str) or not token.strip():
            raise BusinessCentralAuthenticationError(
                "Microsoft Entra did not return an access token."
            )

        return token

    def headers(self) -> dict[str, str]:
        return {
            "Authorization":
                f"Bearer {self.acquire_access_token()}",
            "Accept": "application/json",
        }

    def get_api_json(
        self,
        api_group: str,
        relative_path: str,
        *,
        api_version: str = "v1.0",
    ) -> dict[str, Any]:
        response = requests.get(
            f"{self.api_base_url_for(api_group, api_version)}/"
            f"{relative_path.lstrip('/')}",
            headers=self.headers(),
            timeout=self.timeout_seconds,
        )

        if response.status_code >= 400:
            raise BusinessCentralApiError(
                "Business Central GET failed "
                f"with HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )

        payload = response.json()

        if not isinstance(payload, dict):
            raise BusinessCentralApiError(
                "Business Central returned a non-object JSON payload."
            )

        return payload

    def get_json(
        self,
        relative_path: str,
    ) -> dict[str, Any]:
        return self.get_api_json(
            "packagingQuotes",
            relative_path,
        )

    def patch_json(
        self,
        relative_path: str,
        *,
        body: dict[str, Any],
        etag: str,
    ) -> dict[str, Any] | None:
        headers = self.headers()
        headers["If-Match"] = etag
        headers["Content-Type"] = "application/json"

        response = requests.patch(
            f"{self.api_base_url}/{relative_path.lstrip('/')}",
            headers=headers,
            json=body,
            timeout=self.timeout_seconds,
        )

        if response.status_code >= 400:
            raise BusinessCentralApiError(
                "Business Central PATCH failed "
                f"with HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )

        if not response.content:
            return None

        payload = response.json()

        if not isinstance(payload, dict):
            raise BusinessCentralApiError(
                "Business Central PATCH returned "
                "a non-object JSON payload."
            )

        return payload

    def post_json(
        self,
        relative_path: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        headers = self.headers()
        headers["Content-Type"] = "application/json"

        response = requests.post(
            f"{self.api_base_url}/{relative_path.lstrip('/')}",
            headers=headers,
            json={} if body is None else body,
            timeout=self.timeout_seconds,
        )

        if response.status_code >= 400:
            raise BusinessCentralApiError(
                "Business Central POST failed "
                f"with HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )

        if not response.content:
            return None

        payload = response.json()

        if not isinstance(payload, dict):
            raise BusinessCentralApiError(
                "Business Central POST returned "
                "a non-object JSON payload."
            )

        return payload
