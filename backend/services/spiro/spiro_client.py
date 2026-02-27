"""
GPI Document Hub - Spiro API Client

Handles OAuth token management and API communication with Spiro CRM.
All secrets are read from environment variables.

OAuth Flow:
1. Initial authorization: Use authorization_code grant with code from browser redirect
2. Subsequent calls: Use stored access_token, refresh when expired
3. Token refresh: Use refresh_token grant when access_token expires

API Style: JSON:API (data array with id, type, attributes, relationships)
"""

import os
import json
import logging
import httpx
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

SPIRO_OAUTH_URL = "https://engine.spiro.ai/oauth/token"
SPIRO_API_BASE = "https://api.spiro.ai/api/v1"

# Rate limiting settings
SPIRO_REQUEST_TIMEOUT = 30
SPIRO_MAX_RETRIES = 3
SPIRO_RETRY_DELAY = 1.0  # seconds

# Token file for persistent storage (in container, use env var path or default)
SPIRO_TOKEN_FILE = os.environ.get("SPIRO_TOKEN_FILE", "/app/backend/data/spiro_token.json")


# =============================================================================
# FEATURE FLAG
# =============================================================================

def is_spiro_enabled() -> bool:
    """Check if Spiro integration is enabled via feature flag."""
    return os.environ.get("SPIRO_INTEGRATION_ENABLED", "false").lower() in ("true", "1", "yes")


# =============================================================================
# TOKEN MANAGEMENT
# =============================================================================

class SpiroTokenManager:
    """
    Manages Spiro OAuth tokens with persistent storage and automatic refresh.
    
    Token storage format:
    {
        "access_token": "...",
        "refresh_token": "...",
        "expires_at": "2026-02-27T12:00:00Z",
        "token_type": "Bearer"
    }
    """
    
    def __init__(self):
        self._token_data: Optional[Dict] = None
        self._load_token()
    
    def _load_token(self):
        """Load token from persistent storage."""
        try:
            if os.path.exists(SPIRO_TOKEN_FILE):
                with open(SPIRO_TOKEN_FILE, 'r') as f:
                    self._token_data = json.load(f)
                    logger.debug("Loaded Spiro token from file")
        except Exception as e:
            logger.warning("Failed to load Spiro token file: %s", str(e))
            self._token_data = None
    
    def _save_token(self):
        """Save token to persistent storage."""
        if not self._token_data:
            return
        try:
            # Ensure directory exists
            Path(SPIRO_TOKEN_FILE).parent.mkdir(parents=True, exist_ok=True)
            with open(SPIRO_TOKEN_FILE, 'w') as f:
                json.dump(self._token_data, f, indent=2)
            logger.debug("Saved Spiro token to file")
        except Exception as e:
            logger.warning("Failed to save Spiro token file: %s", str(e))
    
    def get_access_token(self) -> Optional[str]:
        """Get current access token if valid."""
        if not self._token_data:
            return None
        
        # Check expiration
        expires_at = self._token_data.get("expires_at")
        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                # Add 60 second buffer
                if datetime.now(timezone.utc) >= exp_dt - timedelta(seconds=60):
                    logger.debug("Spiro access token expired or expiring soon")
                    return None
            except Exception:
                pass
        
        return self._token_data.get("access_token")
    
    def get_refresh_token(self) -> Optional[str]:
        """Get refresh token for token renewal."""
        if not self._token_data:
            return None
        return self._token_data.get("refresh_token")
    
    def update_token(self, token_response: Dict):
        """Update stored token from OAuth response."""
        expires_in = token_response.get("expires_in", 3600)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        
        self._token_data = {
            "access_token": token_response.get("access_token"),
            "refresh_token": token_response.get("refresh_token", self.get_refresh_token()),
            "expires_at": expires_at.isoformat(),
            "token_type": token_response.get("token_type", "Bearer"),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        self._save_token()
        logger.info("Spiro token updated, expires at %s", expires_at.isoformat())
    
    def clear_token(self):
        """Clear stored token (for logout or error recovery)."""
        self._token_data = None
        if os.path.exists(SPIRO_TOKEN_FILE):
            try:
                os.remove(SPIRO_TOKEN_FILE)
            except Exception:
                pass


# =============================================================================
# SPIRO API CLIENT
# =============================================================================

class SpiroClient:
    """
    Spiro API client with OAuth handling and pagination support.
    
    Usage:
        client = SpiroClient()
        contacts = await client.list_contacts(page=1, per_page=100)
        company = await client.get_company_by_id("12345")
    """
    
    def __init__(self):
        self.token_manager = SpiroTokenManager()
        self._client_id = os.environ.get("SPIRO_CLIENT_ID")
        self._client_secret = os.environ.get("SPIRO_CLIENT_SECRET")
        self._redirect_uri = os.environ.get("SPIRO_REDIRECT_URI", "http://localhost:8001/api/spiro/callback")
    
    def is_configured(self) -> bool:
        """Check if Spiro credentials are configured."""
        return bool(self._client_id and self._client_secret)
    
    async def _refresh_token(self) -> bool:
        """Refresh the access token using refresh_token grant."""
        refresh_token = self.token_manager.get_refresh_token()
        if not refresh_token:
            logger.error("No refresh token available for Spiro")
            return False
        
        if not self._client_id or not self._client_secret:
            logger.error("Spiro client credentials not configured")
            return False
        
        try:
            async with httpx.AsyncClient(timeout=SPIRO_REQUEST_TIMEOUT) as client:
                resp = await client.post(
                    SPIRO_OAUTH_URL,
                    json={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token"
                    }
                )
                
                if resp.status_code == 200:
                    token_data = resp.json()
                    self.token_manager.update_token(token_data)
                    logger.info("Spiro token refreshed successfully")
                    return True
                else:
                    logger.error("Spiro token refresh failed: %d - %s", resp.status_code, resp.text[:200])
                    return False
                    
        except Exception as e:
            logger.error("Spiro token refresh error: %s", str(e))
            return False
    
    async def exchange_authorization_code(self, code: str) -> bool:
        """
        Exchange authorization code for access/refresh tokens.
        Called once after user authorizes the app in browser.
        """
        if not self._client_id or not self._client_secret:
            logger.error("Spiro client credentials not configured")
            return False
        
        try:
            async with httpx.AsyncClient(timeout=SPIRO_REQUEST_TIMEOUT) as client:
                resp = await client.post(
                    SPIRO_OAUTH_URL,
                    json={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "code": code,
                        "redirect_uri": self._redirect_uri,
                        "grant_type": "authorization_code"
                    }
                )
                
                if resp.status_code == 200:
                    token_data = resp.json()
                    self.token_manager.update_token(token_data)
                    logger.info("Spiro authorization code exchanged successfully")
                    return True
                else:
                    logger.error("Spiro auth code exchange failed: %d - %s", resp.status_code, resp.text[:200])
                    return False
                    
        except Exception as e:
            logger.error("Spiro auth code exchange error: %s", str(e))
            return False
    
    async def _get_valid_token(self) -> Optional[str]:
        """Get a valid access token, refreshing if necessary."""
        token = self.token_manager.get_access_token()
        if token:
            return token
        
        # Try to refresh
        if await self._refresh_token():
            return self.token_manager.get_access_token()
        
        return None
    
    async def _api_request(
        self, 
        method: str, 
        endpoint: str, 
        params: Optional[Dict] = None,
        json_body: Optional[Dict] = None
    ) -> Optional[Dict]:
        """
        Make an authenticated API request to Spiro.
        
        Returns parsed JSON response or None on error.
        """
        token = await self._get_valid_token()
        if not token:
            logger.error("No valid Spiro token available")
            return None
        
        url = f"{SPIRO_API_BASE}{endpoint}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Api-Version": "1"  # Required by Spiro API
        }
        
        for attempt in range(SPIRO_MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=SPIRO_REQUEST_TIMEOUT) as client:
                    if method.upper() == "GET":
                        resp = await client.get(url, headers=headers, params=params)
                    elif method.upper() == "POST":
                        resp = await client.post(url, headers=headers, params=params, json=json_body)
                    else:
                        logger.error("Unsupported HTTP method: %s", method)
                        return None
                    
                    if resp.status_code == 200:
                        return resp.json()
                    elif resp.status_code == 401:
                        # Token might be invalid, try refresh
                        logger.warning("Spiro API returned 401, attempting token refresh")
                        if await self._refresh_token():
                            token = self.token_manager.get_access_token()
                            headers["Authorization"] = f"Bearer {token}"
                            continue
                        else:
                            logger.error("Spiro token refresh failed after 401")
                            return None
                    elif resp.status_code == 429:
                        # Rate limited
                        logger.warning("Spiro API rate limited, waiting before retry")
                        import asyncio
                        await asyncio.sleep(SPIRO_RETRY_DELAY * (attempt + 1))
                        continue
                    else:
                        logger.error("Spiro API error: %d - %s", resp.status_code, resp.text[:300])
                        return None
                        
            except httpx.TimeoutException:
                logger.warning("Spiro API timeout on attempt %d", attempt + 1)
                continue
            except Exception as e:
                logger.error("Spiro API request error: %s", str(e))
                return None
        
        logger.error("Spiro API request failed after %d attempts", SPIRO_MAX_RETRIES)
        return None
    
    # =========================================================================
    # CONTACTS API
    # =========================================================================
    
    async def list_contacts(
        self, 
        page: int = 1, 
        per_page: int = 100,
        updated_since: Optional[datetime] = None
    ) -> Optional[Dict]:
        """
        List contacts with pagination.
        
        Returns JSON:API response with data array and meta.pagination.
        """
        params = {
            "page[number]": page,
            "page[size]": per_page
        }
        
        if updated_since:
            params["filter[updated_at][gte]"] = updated_since.isoformat()
        
        return await self._api_request("GET", "/contacts", params=params)
    
    async def get_contact_by_id(self, contact_id: str) -> Optional[Dict]:
        """Get a single contact by ID."""
        return await self._api_request("GET", f"/contacts/{contact_id}")
    
    # =========================================================================
    # COMPANIES API
    # =========================================================================
    
    async def list_companies(
        self, 
        page: int = 1, 
        per_page: int = 100,
        updated_since: Optional[datetime] = None
    ) -> Optional[Dict]:
        """
        List companies/accounts with pagination.
        
        Returns JSON:API response with data array and meta.pagination.
        """
        params = {
            "page[number]": page,
            "page[size]": per_page
        }
        
        if updated_since:
            params["filter[updated_at][gte]"] = updated_since.isoformat()
        
        return await self._api_request("GET", "/companies", params=params)
    
    async def get_company_by_id(self, company_id: str) -> Optional[Dict]:
        """Get a single company by ID."""
        return await self._api_request("GET", f"/companies/{company_id}")
    
    # =========================================================================
    # OPPORTUNITIES API
    # =========================================================================
    
    async def list_opportunities(
        self, 
        page: int = 1, 
        per_page: int = 100,
        updated_since: Optional[datetime] = None
    ) -> Optional[Dict]:
        """
        List opportunities/deals with pagination.
        
        Returns JSON:API response with data array and meta.pagination.
        """
        params = {
            "page[number]": page,
            "page[size]": per_page
        }
        
        if updated_since:
            params["filter[updated_at][gte]"] = updated_since.isoformat()
        
        return await self._api_request("GET", "/opportunities", params=params)
    
    async def get_opportunity_by_id(self, opportunity_id: str) -> Optional[Dict]:
        """Get a single opportunity by ID."""
        return await self._api_request("GET", f"/opportunities/{opportunity_id}")
    
    # =========================================================================
    # CUSTOM OBJECTS API
    # =========================================================================
    
    async def list_custom_objects(
        self, 
        object_type: str,
        page: int = 1, 
        per_page: int = 100
    ) -> Optional[Dict]:
        """
        List custom objects by type.
        
        Args:
            object_type: The custom object type name
        """
        params = {
            "page[number]": page,
            "page[size]": per_page
        }
        
        return await self._api_request("GET", f"/custom_objects/{object_type}", params=params)


# =============================================================================
# SINGLETON ACCESS
# =============================================================================

_spiro_client: Optional[SpiroClient] = None

def get_spiro_client() -> SpiroClient:
    """Get the singleton Spiro client instance."""
    global _spiro_client
    if _spiro_client is None:
        _spiro_client = SpiroClient()
    return _spiro_client
