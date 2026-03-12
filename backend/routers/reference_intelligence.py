"""GPI Document Hub - Reference Intelligence Router (Domain 9)

Extracted from server.py with enhanced domain-aware scoring.
Complex route handlers remain in server.py; this router registers them
on a modular APIRouter via add_api_route.
"""

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Reference Intelligence"])


_routes_registered = False


def register_server_routes(app=None):
    """Register server.py reference intelligence handlers directly on the app.
    Called from main.py during startup after server module is fully loaded.
    """
    global _routes_registered
    if _routes_registered:
        return
    _routes_registered = True

    if app is None:
        logger.warning("No app provided to register_server_routes (ref_intel)")
        return

    import server

    # BC reference resolution (standalone)
    app.add_api_route(
        "/api/bc/resolve-reference", server.resolve_bc_reference,
        methods=["POST"], tags=["Reference Intelligence"],
        summary="Resolve a reference number against BC tables"
    )

    # Document-level reference resolution
    app.add_api_route(
        "/api/documents/{doc_id}/resolve-reference", server.resolve_document_reference,
        methods=["POST"], tags=["Reference Intelligence"],
        summary="Resolve PO/Order reference for a document"
    )

    # Full AI reference intelligence
    app.add_api_route(
        "/api/documents/{doc_id}/resolve-intelligence", server.resolve_document_intelligence,
        methods=["POST"], tags=["Reference Intelligence"],
        summary="Full AI-assisted reference intelligence resolution"
    )

    # Get stored results
    app.add_api_route(
        "/api/documents/{doc_id}/reference-intelligence", server.get_document_reference_intelligence,
        methods=["GET"], tags=["Reference Intelligence"],
        summary="Get stored reference intelligence data"
    )

    # Auto-resolve trigger
    app.add_api_route(
        "/api/documents/{doc_id}/auto-resolve", server.trigger_auto_resolve,
        methods=["POST"], tags=["Reference Intelligence"],
        summary="Trigger auto-resolution for a document"
    )

    # Matching debug
    app.add_api_route(
        "/api/documents/{doc_id}/matching-debug", server.get_matching_debug,
        methods=["GET"], tags=["Reference Intelligence"],
        summary="Get full matching diagnostics"
    )

    # Matching debug rerun
    app.add_api_route(
        "/api/documents/{doc_id}/matching-debug/rerun", server.rerun_matching_with_diagnostics,
        methods=["POST"], tags=["Reference Intelligence"],
        summary="Rerun matching with full diagnostics"
    )
