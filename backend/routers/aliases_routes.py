"""
GPI Document Hub — Vendor Aliases Router (Thin Wrapper)

Extracts /aliases/* routes from server.py during modular refactor.
"""

from fastapi import APIRouter
import server

router = APIRouter(prefix="/aliases", tags=["Vendor Aliases"])

# GET /aliases/vendors
router.add_api_route("/vendors", server.get_vendor_aliases, methods=["GET"])

# POST /aliases/vendors
router.add_api_route("/vendors", server.create_vendor_alias, methods=["POST"])

# DELETE /aliases/vendors/{alias_id}
router.add_api_route("/vendors/{alias_id}", server.delete_vendor_alias, methods=["DELETE"])

# GET /aliases/vendors/suggest
router.add_api_route("/vendors/suggest", server.suggest_alias_creation, methods=["GET"])
