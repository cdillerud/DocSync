from __future__ import annotations

import base64
import json
import os
from typing import Any

from fastapi import HTTPException, Request


TRUE_VALUES = {
    "1",
    "true",
    "yes",
    "on",
}


TENANT_CLAIM_TYPES = (
    "tid",
    "http://schemas.microsoft.com/identity/claims/tenantid",
)

CLIENT_CLAIM_TYPES = (
    "azp",
    "appid",
    "http://schemas.microsoft.com/identity/claims/appid",
)


def easy_auth_principal_required() -> bool:
    return (
        os.getenv(
            "GPI_REQUIRE_EASYAUTH_PRINCIPAL",
            "1",
        )
        .strip()
        .lower()
        in TRUE_VALUES
    )


def _decode_principal(
    encoded: str,
) -> dict[str, Any]:
    value = encoded.strip()

    if not value:
        raise ValueError(
            "EasyAuth principal header was blank."
        )

    # Base64 content may omit trailing padding.
    padding = "=" * (-len(value) % 4)

    try:
        decoded = base64.b64decode(
            value + padding,
            validate=True,
        )
    except Exception as exc:
        raise ValueError(
            "EasyAuth principal header was not valid base64."
        ) from exc

    try:
        payload = json.loads(
            decoded.decode("utf-8")
        )
    except Exception as exc:
        raise ValueError(
            "EasyAuth principal header did not contain valid JSON."
        ) from exc

    if not isinstance(payload, dict):
        raise ValueError(
            "EasyAuth principal payload was not an object."
        )

    return payload


def _claims_by_type(
    principal: dict[str, Any],
) -> dict[str, list[str]]:
    raw_claims = principal.get("claims")

    if not isinstance(raw_claims, list):
        raise ValueError(
            "EasyAuth principal payload did not contain a claims array."
        )

    claims: dict[str, list[str]] = {}

    for item in raw_claims:
        if not isinstance(item, dict):
            continue

        claim_type = str(
            item.get("typ") or ""
        ).strip()

        claim_value = str(
            item.get("val") or ""
        ).strip()

        if not claim_type or not claim_value:
            continue

        claims.setdefault(
            claim_type,
            [],
        ).append(
            claim_value
        )

    return claims


def _first_claim(
    claims: dict[str, list[str]],
    claim_types: tuple[str, ...],
) -> str:
    for claim_type in claim_types:
        values = claims.get(
            claim_type,
            [],
        )

        if values:
            return values[0]

    return ""


def require_inbound_principal(
    request: Request,
) -> dict[str, Any]:
    if not easy_auth_principal_required():
        return {
            "authentication": "disabled-for-local-development",
        }

    expected_tenant = (
        os.getenv(
            "GPI_INBOUND_TENANT_ID",
            ""
        )
        .strip()
        .lower()
    )

    if not expected_tenant:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "inbound_auth_not_configured",
                "message": (
                    "Inbound EasyAuth protection is enabled, but "
                    "GPI_INBOUND_TENANT_ID is not configured."
                ),
                "retryPrepare": False,
            },
        )

    encoded_principal = request.headers.get(
        "x-ms-client-principal"
    )

    if not encoded_principal:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "authentication_required",
                "message": (
                    "An authenticated Microsoft Entra identity "
                    "is required."
                ),
                "retryPrepare": False,
            },
            headers={
                "WWW-Authenticate": "Bearer",
            },
        )

    try:
        principal = _decode_principal(
            encoded_principal
        )

        claims = _claims_by_type(
            principal
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_authenticated_principal",
                "message": str(exc),
                "retryPrepare": False,
            },
            headers={
                "WWW-Authenticate": "Bearer",
            },
        ) from exc

    tenant_id = _first_claim(
        claims,
        TENANT_CLAIM_TYPES,
    ).lower()

    if not tenant_id:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "tenant_claim_missing",
                "message": (
                    "The authenticated principal does not contain "
                    "a tenant identifier."
                ),
                "retryPrepare": False,
            },
        )

    if tenant_id != expected_tenant:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "tenant_not_allowed",
                "message": (
                    "The authenticated principal belongs to a "
                    "different Microsoft Entra tenant."
                ),
                "retryPrepare": False,
            },
        )

    allowed_client_id = (
        os.getenv(
            "GPI_INBOUND_ALLOWED_CLIENT_ID",
            ""
        )
        .strip()
        .lower()
    )

    client_id = _first_claim(
        claims,
        CLIENT_CLAIM_TYPES,
    ).lower()

    if allowed_client_id:
        if not client_id:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "client_claim_missing",
                    "message": (
                        "The authenticated principal does not "
                        "contain a calling application identifier."
                    ),
                    "retryPrepare": False,
                },
            )

        if client_id != allowed_client_id:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "client_not_allowed",
                    "message": (
                        "The authenticated calling application "
                        "is not allowed to use this API."
                    ),
                    "retryPrepare": False,
                },
            )

    return {
        "authentication": "app-service-easyauth",
        "tenantId": tenant_id,
        "clientId": client_id or None,
        "principal": principal,
    }