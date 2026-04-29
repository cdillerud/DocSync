"""Service-level integration adapters (Phase 1 scaffold).

This package hosts thin, env-driven clients for external providers used by
the Contract Intelligence module. Phase 1 ships a DocuSign scaffold with
NO live API calls — the goal is to land structure, env wiring, JWT claim
construction, and HMAC validation utilities so Phase 2 can drop in the
webhook receiver and read-only envelope fetchers without further plumbing.
"""
