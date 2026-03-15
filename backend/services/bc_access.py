"""
GPI Document Hub - Shared BC Access Adapter

Canonical Business Central OAuth token management and company ID resolution.
Eliminates duplicate token/company logic across bc_reference_resolver and
unified_vendor_matcher.

Usage:
    adapter = BCAccessAdapter()          # reads env vars
    token   = await adapter.get_token()
    company = await adapter.get_company_id(token)
"""

import os
import logging
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

BC_API_BASE = "https://api.businesscentral.dynamics.com/v2.0"


class BCAccessAdapter:
    """Shared BC OAuth + company-ID helper.

    Reads credentials from environment once and caches the token for 50 min.
    """

    def __init__(
        self,
        tenant_id: str = None,
        client_id: str = None,
        client_secret: str = None,
        environment: str = None,
        target_company: str = None,
    ):
        self.tenant_id = tenant_id or os.environ.get("TENANT_ID") or os.environ.get("BC_PROD_TENANT_ID", "")
        self.client_id = client_id or os.environ.get("BC_CLIENT_ID") or os.environ.get("BC_SANDBOX_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("BC_CLIENT_SECRET") or os.environ.get("BC_SANDBOX_CLIENT_SECRET", "")
        self.environment = environment or os.environ.get("BC_PROD_ENVIRONMENT", "Production")
        self.target_company = target_company or os.environ.get("BC_COMPANY_NAME", "Gamer Packaging")

        self._token: Optional[str] = None
        self._token_expires: Optional[datetime] = None
        self._company_id: Optional[str] = None

    @property
    def has_credentials(self) -> bool:
        return bool(self.tenant_id and self.client_id and self.client_secret)

    # --------------------------------------------------------------------- #
    # Token
    # --------------------------------------------------------------------- #
    async def get_token(self) -> Optional[str]:
        """Return a cached or freshly-obtained BC OAuth2 token."""
        if self._token and self._token_expires and datetime.now(timezone.utc) < self._token_expires:
            return self._token

        if not self.has_credentials:
            logger.warning("[BCAccess] Missing credentials — cannot obtain token")
            return None

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "scope": "https://api.businesscentral.dynamics.com/.default",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self._token = data["access_token"]
                    self._token_expires = datetime.now(timezone.utc) + timedelta(minutes=50)
                    logger.info("[BCAccess] Token obtained (%s)", self.environment)
                    return self._token
                else:
                    logger.error("[BCAccess] Token error: %d %s", resp.status_code, resp.text[:200])
        except Exception as exc:
            logger.error("[BCAccess] Token error: %s", exc)

        return None

    # --------------------------------------------------------------------- #
    # Company ID
    # --------------------------------------------------------------------- #
    async def get_company_id(self, token: str = None) -> Optional[str]:
        """Return the BC company ID (cached after first successful lookup)."""
        if self._company_id:
            return self._company_id

        if token is None:
            token = await self.get_token()
        if not token:
            return None

        try:
            url = f"{BC_API_BASE}/{self.tenant_id}/{self.environment}/api/v2.0/companies"
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
                if resp.status_code != 200:
                    logger.error("[BCAccess] Company lookup: HTTP %d", resp.status_code)
                    return None

                companies = resp.json().get("value", [])

                # Prefer the target company
                for company in companies:
                    if self.target_company.lower() in company.get("name", "").lower():
                        self._company_id = company["id"]
                        logger.info("[BCAccess] Company: %s (%s)", company["name"], self._company_id[:8])
                        return self._company_id

                # Fall back to first non-test company
                for company in companies:
                    cname = company.get("name", "").lower()
                    if "test" not in cname and "blank" not in cname and cname.strip():
                        self._company_id = company["id"]
                        logger.info("[BCAccess] Company (fallback): %s", company["name"])
                        return self._company_id

                # Last resort
                if companies:
                    self._company_id = companies[0]["id"]
                    return self._company_id

        except Exception as exc:
            logger.error("[BCAccess] Company lookup error: %s", exc)

        return None

    def api_url(self, path: str, company_id: str = None) -> str:
        """Build a full BC API URL for a given resource path."""
        cid = company_id or self._company_id or ""
        return f"{BC_API_BASE}/{self.tenant_id}/{self.environment}/api/v2.0/companies({cid})/{path}"


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_bc_adapter: Optional[BCAccessAdapter] = None


def get_bc_adapter() -> BCAccessAdapter:
    """Return (or create) the shared BCAccessAdapter singleton."""
    global _bc_adapter
    if _bc_adapter is None:
        _bc_adapter = BCAccessAdapter()
    return _bc_adapter
