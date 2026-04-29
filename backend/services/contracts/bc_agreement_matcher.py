"""Read-only / advisory BC matcher for normalized agreements.

Phase 2 scope (per signed declaration):
    * Match parties → BC customers + vendors.
    * Match pricing rows → BC items.
    * Confidence-scored. Auto-confirm only at very high confidence
      (>= AUTO_CONFIRM_THRESHOLD). Lower scores produce ``proposed`` links;
      below MIN_PROPOSE_THRESHOLD produces an exception row instead of a link.
    * NEVER writes to BC. NEVER updates customers / vendors / items.

Architecture:
    * The matcher is decoupled from any specific BC client. It accepts a
      ``BCLookupRepository`` Protocol. Production wiring will pass a thin
      adapter over the existing BC reference cache; tests pass an in-memory
      stub. This keeps the matcher pure and trivially unit-testable.
    * Output is a tuple ``(links, exceptions)`` of unsaved Pydantic models.
      The orchestrator persists them and emits matching audit rows.

Thresholds (Phase 3):
    * Defaults are 0.95 auto-confirm / 0.80 propose.
    * Override per-environment via env vars:
        CONTRACT_MATCH_AUTO_CONFIRM_THRESHOLD
        CONTRACT_MATCH_PROPOSE_THRESHOLD
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple

from models.contracts import (
    AgreementBCLink,
    AgreementException,
    AgreementParty,
    AgreementPricing,
    BCLinkStatus,
    BCLinkType,
    ExceptionCode,
    MatchMethod,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Thresholds — env-overridable, fail-soft on bad values
# ---------------------------------------------------------------------------

_DEFAULT_AUTO_CONFIRM = 0.95
_DEFAULT_PROPOSE = 0.80


def _env_threshold(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        v = float(raw)
    except (TypeError, ValueError):
        logger.warning("invalid %s=%r, falling back to %s", name, raw, default)
        return default
    if not (0.0 <= v <= 1.0):
        logger.warning("%s=%s out of [0,1], falling back to %s", name, v, default)
        return default
    return v


AUTO_CONFIRM_THRESHOLD: float = _env_threshold(
    "CONTRACT_MATCH_AUTO_CONFIRM_THRESHOLD", _DEFAULT_AUTO_CONFIRM,
)
MIN_PROPOSE_THRESHOLD: float = _env_threshold(
    "CONTRACT_MATCH_PROPOSE_THRESHOLD", _DEFAULT_PROPOSE,
)
EXCEPTION_THRESHOLD: float = MIN_PROPOSE_THRESHOLD


# ---------------------------------------------------------------------------
# Repository protocol — production adapter wraps the existing BC ref cache
# ---------------------------------------------------------------------------

@dataclass
class BCCandidate:
    """Lightweight match candidate. ``score`` is 0..1, repository-supplied."""

    no: str
    name: str
    score: float
    method: MatchMethod = "fuzzy"
    extra: Dict[str, Any] = field(default_factory=dict)


class BCLookupRepository(Protocol):
    """Source of BC candidates. Implementations decide their own search logic."""

    async def find_customer_candidates(
        self, *, name: Optional[str], email: Optional[str], limit: int = 5,
    ) -> List[BCCandidate]: ...

    async def find_vendor_candidates(
        self, *, name: Optional[str], email: Optional[str], limit: int = 5,
    ) -> List[BCCandidate]: ...

    async def find_item_candidates(
        self, *, label: Optional[str], description: Optional[str], limit: int = 5,
    ) -> List[BCCandidate]: ...


# ---------------------------------------------------------------------------
# Matcher
# ---------------------------------------------------------------------------

@dataclass
class MatchResult:
    links: List[AgreementBCLink] = field(default_factory=list)
    exceptions: List[AgreementException] = field(default_factory=list)


class BCAgreementMatcher:
    """Pure stateless service that emits link proposals + exceptions."""

    def __init__(
        self,
        repo: BCLookupRepository,
        *,
        auto_confirm_threshold: float = AUTO_CONFIRM_THRESHOLD,
        min_propose_threshold: float = MIN_PROPOSE_THRESHOLD,
    ) -> None:
        self.repo = repo
        self.auto_confirm_threshold = auto_confirm_threshold
        self.min_propose_threshold = min_propose_threshold

    # ----- Public entry point -------------------------------------------

    async def match(
        self,
        *,
        agreement_id: str,
        parties: List[AgreementParty],
        pricing: List[AgreementPricing],
    ) -> MatchResult:
        result = MatchResult()

        seen_party_links: set[Tuple[str, str]] = set()  # (link_type, bc_no)

        for party in parties:
            if party.role not in ("signer", "sender", "carbon_copy", "approver"):
                # Internal-only roles (witness, agent) skipped for matching.
                continue

            # Skip parties without any usable identity.
            if not (party.name or party.organization or party.email):
                continue

            # Try customer + vendor lookups in parallel-ish (sequential is fine
            # for Phase 2 — the repo is the bottleneck).
            customer_candidates = await self.repo.find_customer_candidates(
                name=party.organization or party.name,
                email=party.email,
                limit=3,
            )
            vendor_candidates = await self.repo.find_vendor_candidates(
                name=party.organization or party.name,
                email=party.email,
                limit=3,
            )

            await self._emit_party_links(
                agreement_id=agreement_id,
                party=party,
                link_type="customer",
                bc_entity="customers",
                candidates=customer_candidates,
                seen=seen_party_links,
                result=result,
            )
            await self._emit_party_links(
                agreement_id=agreement_id,
                party=party,
                link_type="vendor",
                bc_entity="vendors",
                candidates=vendor_candidates,
                seen=seen_party_links,
                result=result,
            )

        # Pricing → items
        for line in pricing:
            await self._emit_item_link(
                agreement_id=agreement_id,
                pricing=line,
                result=result,
            )

        return result

    # ----- Helpers -------------------------------------------------------

    async def _emit_party_links(
        self,
        *,
        agreement_id: str,
        party: AgreementParty,
        link_type: BCLinkType,
        bc_entity: str,
        candidates: List[BCCandidate],
        seen: set[Tuple[str, str]],
        result: MatchResult,
    ) -> None:
        if not candidates:
            # Only emit "party_unmatched" exceptions for the customer side
            # by default — vendor-side mismatches are common and noisy
            # (every signer is unlikely to be both customer AND vendor).
            if link_type == "customer":
                result.exceptions.append(AgreementException(
                    agreement_id=agreement_id,
                    code="party_unmatched",
                    severity="medium",
                    details={
                        "link_type": link_type,
                        "party_role": party.role,
                        "party_name": party.name,
                        "party_org": party.organization,
                        "party_email": party.email,
                    },
                    related_party_id=party.id,
                ))
            return

        top = max(candidates, key=lambda c: c.score)
        if top.score < self.min_propose_threshold:
            # Below the propose floor: exception, no link.
            result.exceptions.append(AgreementException(
                agreement_id=agreement_id,
                code="party_unmatched",
                severity="medium" if link_type == "customer" else "low",
                details={
                    "link_type": link_type,
                    "best_candidate_no": top.no,
                    "best_candidate_name": top.name,
                    "best_score": top.score,
                    "party_name": party.name,
                    "party_org": party.organization,
                },
                related_party_id=party.id,
            ))
            return

        key = (link_type, top.no)
        if key in seen:
            # Same BC entity already linked once for this agreement
            # (e.g., two signers from same company). Skip the dup.
            return
        seen.add(key)

        status: BCLinkStatus = (
            "auto_confirmed" if top.score >= self.auto_confirm_threshold
            else "proposed"
        )
        result.links.append(AgreementBCLink(
            agreement_id=agreement_id,
            link_type=link_type,
            bc_entity=bc_entity,
            bc_no=top.no,
            bc_name_snapshot=top.name,
            match_method=top.method,
            confidence=top.score,
            status=status,
            party_id=party.id,
            linked_by="system",
            notes=(
                f"matched_party_role={party.role}; "
                f"candidates_considered={len(candidates)}"
            ),
        ))

    async def _emit_item_link(
        self,
        *,
        agreement_id: str,
        pricing: AgreementPricing,
        result: MatchResult,
    ) -> None:
        if not (pricing.item_label or pricing.description):
            result.exceptions.append(AgreementException(
                agreement_id=agreement_id,
                code="item_unmatched",
                severity="low",
                details={
                    "line_no": pricing.line_no,
                    "reason": "missing item_label and description",
                },
                related_pricing_id=pricing.id,
            ))
            return

        candidates = await self.repo.find_item_candidates(
            label=pricing.item_label,
            description=pricing.description,
            limit=3,
        )
        if not candidates:
            result.exceptions.append(AgreementException(
                agreement_id=agreement_id,
                code="item_unmatched",
                severity="medium",
                details={
                    "line_no": pricing.line_no,
                    "item_label": pricing.item_label,
                    "description": pricing.description,
                },
                related_pricing_id=pricing.id,
            ))
            return

        top = max(candidates, key=lambda c: c.score)
        if top.score < self.min_propose_threshold:
            result.exceptions.append(AgreementException(
                agreement_id=agreement_id,
                code="item_unmatched",
                severity="medium",
                details={
                    "line_no": pricing.line_no,
                    "best_candidate_no": top.no,
                    "best_candidate_name": top.name,
                    "best_score": top.score,
                    "item_label": pricing.item_label,
                },
                related_pricing_id=pricing.id,
            ))
            return

        status: BCLinkStatus = (
            "auto_confirmed" if top.score >= self.auto_confirm_threshold
            else "proposed"
        )
        result.links.append(AgreementBCLink(
            agreement_id=agreement_id,
            link_type="item",
            bc_entity="items",
            bc_no=top.no,
            bc_name_snapshot=top.name,
            match_method=top.method,
            confidence=top.score,
            status=status,
            pricing_id=pricing.id,
            linked_by="system",
            notes=f"line_no={pricing.line_no}; item_label={pricing.item_label!r}",
        ))


# ---------------------------------------------------------------------------
# Default in-memory repository for tests + offline operation
# ---------------------------------------------------------------------------

@dataclass
class InMemoryBCRepository:
    """Stub repo used by tests and dev. Tokenizes names and computes a simple
    Jaccard similarity score against label tokens. Production code injects
    a real BC-backed repo instead.
    """

    customers: List[Dict[str, Any]] = field(default_factory=list)
    vendors: List[Dict[str, Any]] = field(default_factory=list)
    items: List[Dict[str, Any]] = field(default_factory=list)

    async def find_customer_candidates(self, *, name, email, limit=5):
        return self._search(self.customers, name=name, email=email, limit=limit)

    async def find_vendor_candidates(self, *, name, email, limit=5):
        return self._search(self.vendors, name=name, email=email, limit=limit)

    async def find_item_candidates(self, *, label, description, limit=5):
        # Item search keys are item_label / description.
        candidates = self._search(self.items, name=label, email=None, limit=limit * 2)
        if not candidates and description:
            candidates = self._search(self.items, name=description, email=None,
                                      limit=limit * 2)
        return candidates[:limit]

    @staticmethod
    def _tokens(text: Optional[str]) -> set[str]:
        if not text:
            return set()
        return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) >= 2}

    def _search(self, source, *, name, email, limit):
        if not source:
            return []
        query_tokens = self._tokens(name)
        results: List[BCCandidate] = []
        for row in source:
            row_name = row.get("name") or row.get("display_name") or ""
            row_email = (row.get("email") or "").lower()
            row_tokens = self._tokens(row_name)
            if not query_tokens and not email:
                continue

            method: MatchMethod = "fuzzy"
            score = 0.0

            if email and row_email and email.lower() == row_email:
                score = max(score, 0.97)
                method = "exact_name"

            if query_tokens and row_tokens:
                inter = len(query_tokens & row_tokens)
                union = len(query_tokens | row_tokens)
                jaccard = inter / union if union else 0.0
                # Boost when one is a subset of the other (e.g., "Acme" vs "Acme Inc.")
                if query_tokens.issubset(row_tokens) or row_tokens.issubset(query_tokens):
                    jaccard = max(jaccard, 0.92)
                if jaccard >= 1.0:
                    method = "exact_name"
                elif jaccard >= 0.75:
                    method = "normalized"
                score = max(score, jaccard)

            if score > 0:
                results.append(BCCandidate(
                    no=str(row.get("no") or row.get("number") or row.get("id")),
                    name=row_name,
                    score=round(score, 4),
                    method=method,
                ))

        results.sort(key=lambda c: c.score, reverse=True)
        return results[:limit]
