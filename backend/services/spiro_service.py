"""
GPI Document Hub — Spiro CRM Integration Service

Connects to Spiro.ai to:
  1. Look up customers by name or email domain
  2. Find matching opportunities/quotes by company
  3. Match incoming POs against Spiro quotes

Uses OAuth 2.0 with automatic token refresh.
"""

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

import httpx

from deps import get_db

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

SPIRO_CLIENT_ID = os.environ.get("SPIRO_CLIENT_ID", "")
SPIRO_CLIENT_SECRET = os.environ.get("SPIRO_CLIENT_SECRET", "")
SPIRO_REFRESH_TOKEN = os.environ.get("SPIRO_REFRESH_TOKEN", "")
SPIRO_API_BASE = os.environ.get("SPIRO_API_BASE", "https://api.spiro.ai/api/v1")
SPIRO_OAUTH_URL = os.environ.get("SPIRO_OAUTH_URL", "https://engine.spiro.ai/oauth/token")

SPIRO_ENABLED = bool(SPIRO_CLIENT_ID and SPIRO_CLIENT_SECRET and SPIRO_REFRESH_TOKEN)

# In-memory token cache
_token_cache: Dict[str, Any] = {
    "access_token": None,
    "refresh_token": SPIRO_REFRESH_TOKEN,
    "expires_at": 0,
}
_token_lock = asyncio.Lock()


# ─────────────────────────────────────────────────────────────
# TOKEN MANAGEMENT
# ─────────────────────────────────────────────────────────────

async def _refresh_token() -> str:
    """Refresh the Spiro access token using the refresh token."""
    async with _token_lock:
        # Double-check after acquiring lock
        if _token_cache["access_token"] and _token_cache["expires_at"] > datetime.now(timezone.utc).timestamp() + 60:
            return _token_cache["access_token"]

        refresh = _token_cache.get("refresh_token") or SPIRO_REFRESH_TOKEN
        if not refresh:
            raise ValueError("No Spiro refresh token configured")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                SPIRO_OAUTH_URL,
                json={
                    "client_id": SPIRO_CLIENT_ID,
                    "client_secret": SPIRO_CLIENT_SECRET,
                    "refresh_token": refresh,
                    "grant_type": "refresh_token",
                },
                headers={"Content-Type": "application/json"},
            )

        if resp.status_code != 200:
            logger.error("[Spiro] Token refresh failed (%d): %s", resp.status_code, resp.text[:200])
            raise ValueError(f"Spiro token refresh failed: {resp.status_code}")

        data = resp.json()
        _token_cache["access_token"] = data["access_token"]
        _token_cache["expires_at"] = data.get("created_at", 0) + data.get("expires_in", 86400)
        if data.get("refresh_token"):
            _token_cache["refresh_token"] = data["refresh_token"]
            # Persist rotated refresh token to DB for durability
            db = get_db()
            await db.spiro_config.update_one(
                {"key": "refresh_token"},
                {"$set": {"value": data["refresh_token"], "updated_at": datetime.now(timezone.utc).isoformat()}},
                upsert=True,
            )

        logger.info("[Spiro] Token refreshed (user=%s)", data.get("user_email", "unknown"))
        return _token_cache["access_token"]


async def _get_token() -> str:
    """Get a valid access token, refreshing if needed."""
    if _token_cache["access_token"] and _token_cache["expires_at"] > datetime.now(timezone.utc).timestamp() + 60:
        return _token_cache["access_token"]
    return await _refresh_token()


async def _spiro_get(path: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
    """Make an authenticated GET request to the Spiro API."""
    token = await _get_token()
    url = f"{SPIRO_API_BASE.rstrip('/')}/{path.lstrip('/')}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            url,
            params=params or {},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "X-Api-Version": "1",
            },
        )

    if resp.status_code == 401:
        # Token expired mid-flight — refresh and retry once
        token = await _refresh_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                url,
                params=params or {},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "X-Api-Version": "1",
                },
            )

    if resp.status_code != 200:
        logger.warning("[Spiro] API error %d on %s: %s", resp.status_code, path, resp.text[:200])
        return {"error": f"Spiro API {resp.status_code}", "detail": resp.text[:200]}

    return resp.json()


# ─────────────────────────────────────────────────────────────
# COMPANY SEARCH
# ─────────────────────────────────────────────────────────────

async def search_company(name: str) -> List[Dict[str, Any]]:
    """Search Spiro companies by name (contains match)."""
    if not SPIRO_ENABLED:
        return []
    if not name or len(name) < 2:
        return []

    data = await _spiro_get("companies", {
        "filter[name_cont]": name,
        "per_page": 10,
    })
    if "error" in data:
        return []

    results = []
    for c in data.get("data", []):
        attr = c.get("attributes", {})
        custom = attr.get("custom", {})
        results.append({
            "spiro_id": c.get("id"),
            "name": attr.get("name"),
            "city": attr.get("city"),
            "state": attr.get("state"),
            "relationship_type": custom.get("relationship_type"),
            "external_id": attr.get("external_id"),
            "assigned_isr": (custom.get("assigned_isr") or {}).get("label"),
            "industries_served": custom.get("industries_served"),
            "website": attr.get("website"),
        })
    return results


async def search_company_by_email_domain(email: str) -> List[Dict[str, Any]]:
    """Search Spiro companies by website matching the email domain."""
    if not SPIRO_ENABLED or not email:
        return []

    domain = email.split("@")[-1].lower()
    if domain in ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com"):
        return []

    data = await _spiro_get("companies", {
        "filter[website_cont]": domain,
        "per_page": 5,
    })
    if "error" in data:
        return []

    results = []
    for c in data.get("data", []):
        attr = c.get("attributes", {})
        custom = attr.get("custom", {})
        results.append({
            "spiro_id": c.get("id"),
            "name": attr.get("name"),
            "website": attr.get("website"),
            "relationship_type": custom.get("relationship_type"),
            "external_id": attr.get("external_id"),
            "assigned_isr": (custom.get("assigned_isr") or {}).get("label"),
            "match_method": "email_domain",
        })
    return results


# ─────────────────────────────────────────────────────────────
# OPPORTUNITY / QUOTE SEARCH
# ─────────────────────────────────────────────────────────────

async def get_company_opportunities(company_name: str) -> List[Dict[str, Any]]:
    """Get opportunities (quotes) for a company from Spiro."""
    if not SPIRO_ENABLED or not company_name:
        return []

    # Use first significant word(s) for search
    search_term = company_name.strip()
    if len(search_term) < 3:
        return []

    data = await _spiro_get("opportunities", {
        "filter[company_name_cont]": search_term,
        "per_page": 25,
    })
    if "error" in data:
        return []

    results = []
    for o in data.get("data", []):
        attr = o.get("attributes", {})
        custom = attr.get("custom", {})
        results.append({
            "spiro_id": o.get("id"),
            "name": attr.get("name"),
            "amount": attr.get("amount"),
            "close_date": attr.get("close_at"),
            "description": attr.get("description"),
            "status": custom.get("status_reason"),
            "rating": custom.get("rating"),
            "est_annual_volume": custom.get("est_annual_volume"),
            "unit_type": custom.get("unit_type"),
            "probability": custom.get("probability"),
            "assigned_isr": (custom.get("assigned_isr") or {}).get("label"),
            "updated_at": attr.get("updated_at"),
        })
    return results


async def get_quotes_for_company(company_name: str) -> List[Dict[str, Any]]:
    """Get quotes from the Spiro Quotes module for a company."""
    if not SPIRO_ENABLED or not company_name:
        return []

    data = await _spiro_get("quotes", {
        "filter[company_name_cont]": company_name,
        "per_page": 25,
    })
    if "error" in data:
        return []

    results = []
    for q in data.get("data", []):
        attr = q.get("attributes", {})
        results.append({
            "spiro_id": q.get("id"),
            "name": attr.get("name"),
            "total": attr.get("total"),
            "status": attr.get("status"),
            "created_at": attr.get("created_at"),
            "updated_at": attr.get("updated_at"),
        })
    return results


# ─────────────────────────────────────────────────────────────
# PO → SPIRO MATCH ENGINE
# ─────────────────────────────────────────────────────────────

async def match_document_to_spiro(doc_id: str) -> Dict[str, Any]:
    """
    Match a document (PO/order) against Spiro:
      1. Search company by customer name
      2. Fall back to email domain search
      3. Get opportunities for matched company
      4. Try to match by PO number, amount, or description

    Stores result as `spiro_match` on the document.
    """
    if not SPIRO_ENABLED:
        return {"skipped": True, "reason": "Spiro integration not configured"}

    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"error": f"Document {doc_id} not found"}

    ext = doc.get("sales_pilot_extraction") or {}
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}

    customer_name = ext.get("customer_name") or ef.get("customer") or nf.get("customer")
    sender_email = doc.get("email_sender") or ext.get("sender") or ""
    po_number = ext.get("po_number") or ef.get("po_number") or nf.get("customer_po")
    amount = ext.get("total_amount") or nf.get("amount_float") or ef.get("total_amount")

    result: Dict[str, Any] = {
        "document_id": doc_id,
        "matched_at": datetime.now(timezone.utc).isoformat(),
        "company_match": None,
        "opportunities": [],
        "best_quote_match": None,
        "search_inputs": {
            "customer_name": customer_name,
            "sender_email": sender_email,
            "po_number": po_number,
            "amount": amount,
        },
    }

    # Step 1: Find company
    companies = []
    if customer_name:
        # Skip "Gamer Packaging" — that's us
        if "gamer" not in customer_name.lower():
            companies = await search_company(customer_name)

    if not companies and sender_email:
        companies = await search_company_by_email_domain(sender_email)

    if companies:
        best = companies[0]
        result["company_match"] = best

        # Step 2: Get opportunities
        company_search = best.get("name", customer_name)
        opps = await get_company_opportunities(company_search)
        result["opportunities"] = opps

        # Also try the quotes module
        quotes = await get_quotes_for_company(company_search)
        if quotes:
            result["quotes"] = quotes

        # Step 3: Try to match a specific opportunity
        if opps and po_number:
            best_match = _match_opportunity(opps, po_number, amount)
            if best_match:
                result["best_quote_match"] = best_match
    else:
        result["company_match"] = {"found": False, "searched": customer_name or sender_email}

    # Persist on document
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {"spiro_match": result}},
    )

    logger.info(
        "[Spiro] doc=%s company=%s opps=%d match=%s",
        doc_id[:8],
        (result["company_match"] or {}).get("name", "none"),
        len(result["opportunities"]),
        "YES" if result["best_quote_match"] else "no",
    )
    return result


def _match_opportunity(
    opportunities: List[Dict[str, Any]],
    po_number: Optional[str],
    amount: Optional[Any],
) -> Optional[Dict[str, Any]]:
    """Try to match PO/amount to an opportunity."""
    if not opportunities:
        return None

    po_clean = (po_number or "").strip().upper()
    amount_f = float(amount) if amount else 0

    # Try PO number in opportunity name/description
    for opp in opportunities:
        opp_name = (opp.get("name") or "").upper()
        opp_desc = (opp.get("description") or "").upper()
        if po_clean and (po_clean in opp_name or po_clean in opp_desc):
            return {**opp, "match_method": "po_in_name", "matched_po": po_clean}

    # Try amount match (within 10%)
    if amount_f > 0:
        for opp in opportunities:
            opp_amount = float(opp.get("amount") or 0)
            if opp_amount > 0:
                diff_pct = abs(amount_f - opp_amount) / opp_amount * 100
                if diff_pct <= 10:
                    return {**opp, "match_method": "amount_match", "amount_diff_pct": round(diff_pct, 1)}

    return None


# ─────────────────────────────────────────────────────────────
# BATCH MATCH
# ─────────────────────────────────────────────────────────────

async def match_all_pilot_documents(force: bool = False) -> Dict[str, Any]:
    """Run Spiro matching on all pilot documents that haven't been matched yet."""
    if not SPIRO_ENABLED:
        return {"skipped": True, "reason": "Spiro not configured"}

    db = get_db()

    query = {
        "inside_sales_pilot": True,
        "doc_type": "SALES_INVOICE",
    }
    if not force:
        query["$or"] = [
            {"spiro_match": {"$exists": False}},
            {"spiro_match": None},
        ]

    docs = await db.hub_documents.find(query, {"_id": 0, "id": 1}).to_list(500)

    results = {"total": len(docs), "matched": 0, "company_found": 0, "quote_matched": 0, "errors": 0}
    for doc in docs:
        try:
            r = await match_document_to_spiro(doc["id"])
            results["matched"] += 1
            if r.get("company_match") and r["company_match"].get("spiro_id"):
                results["company_found"] += 1
            if r.get("best_quote_match"):
                results["quote_matched"] += 1
        except Exception as e:
            results["errors"] += 1
            logger.error("[Spiro] Match error on %s: %s", doc["id"][:8], e)
        # Rate limit — be nice to Spiro API
        await asyncio.sleep(0.5)

    return results
