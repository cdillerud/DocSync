"""Customer Storage archetype module (Lane C Step 7).

Scope: gate-layer scaffolding for sales documents involving customer-
stored ware (GPI holding customer-owned inventory and releasing it on
instruction). Runtime behavior in Step 7: ZERO — gates are opt-in,
never auto-registered, never wired into the readiness pipeline.

AP S&H invoice-classification concerns (``STORAGE_HANDLING_KEYWORDS``
in ``services/freight_gl_routing_service.py``, folder routing's
``_is_storage_handling``) are a different lane and are NOT touched by
this package.
"""
