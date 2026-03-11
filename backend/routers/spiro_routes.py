"""
GPI Document Hub — Spiro Integration Router (Thin Wrapper)

Extracts /spiro/* routes from server.py during modular refactor.
These routes delegate to server.py handlers that call the Spiro CRM API.
"""

from fastapi import APIRouter
import server

router = APIRouter(prefix="/spiro", tags=["Spiro CRM"])

# POST /spiro/match-vendor
router.add_api_route("/match-vendor", server.spiro_match_vendor, methods=["POST"])

# GET /spiro/search-companies
router.add_api_route("/search-companies", server.spiro_search_companies, methods=["GET"])

# GET /spiro/freight-carriers
router.add_api_route("/freight-carriers", server.spiro_get_freight_carriers, methods=["GET"])

# POST /spiro/is-freight-carrier
router.add_api_route("/is-freight-carrier", server.spiro_is_freight_carrier, methods=["POST"])
