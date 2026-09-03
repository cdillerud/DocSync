# V117 Learned Autonomy Charter

Status: ACTIVE UNTIL THE IMMUTABLE PROMOTION GATE IS MET.

## Mission
Replace Square9's brittle templates with an AI-driven AP routing system that learns Gamer Accounting's actual routing decisions and reviewer corrections, earns increasing autonomy from demonstrated performance, and safely routes at least 90% of representative held-out AP documents with 100% automatic-route accuracy and zero wrong automatic routes.

The AI is the primary routing intelligence. Deterministic code is a safety envelope, not the steering wheel. Future agents, new chats, and developers MUST read this charter before changing AP routing behavior.

## Immutable promotion gate
- zero wrong automatic routes
- 100% automatic-route accuracy
- at least 90% held-out automatic-route coverage
- default minimum labeled examples: 20

Never lower these gates to make a candidate pass.

## Frozen safety fallback
Runtime-proven zero-wrong fallback: `6c455f1a027361115eba3ea9ecde989009bda76e`.
Measured proof: 49/49 focused regressions; 62 holdouts; 26 automatic; 36 review; 41.94% coverage; 100% automatic-route accuracy; 0 wrong automatic routes; FAIL_COVERAGE only.

## Current learned architecture
Feature branch: `feature/ap-ai-learned-autonomy`.
Current pinned learned candidate: `8d762dbd120f5f7a69b9e72217eafe50be574637`.

Required flow:
1. Split TRAIN evidence from untouched held-out truth.
2. Retrieve relevant TRAIN-only human-confirmed Gamer Accounting examples, including corrections and meaningful contradictions.
3. AI selects the proposed route.
4. Learned autonomy decides whether that exact AI proposal has earned authority.
5. Deterministic safety may only demote to review. It must never substitute another route.
6. Human confirmations/corrections become future authoritative learning evidence.
7. Held-out truth grades the result externally.

## Evidence and learning rules
- Current-document explicit instructions and authoritative current context are highest-priority safety evidence.
- Reviewer corrections are stronger learning evidence than passive human confirmations.
- Human-confirmed Gamer Accounting placements are authoritative labels.
- BC context is read-only evidence.
- NAV/Zetadocs history is context/coverage only, never routing authority.
- AI-generated predictions NEVER become learning authority unless a human resolves them.
- A wrong human-resolved AI outcome materially reduces or suspends autonomy for that learned pattern.
- High model confidence alone is never enough for automatic authority.
- Unknown, contradictory, or weakly learned patterns remain review.

## Autonomy tiers
- `review`: insufficient or contradictory learned authority.
- `guarded`: promising but not proven enough; V117 still sends to review.
- `earned_auto`: sufficient relevant human evidence and demonstrated performance allow the AI's exact proposed route to act.

## Safety envelope
Safety policies must be broad and route-neutral. They may demote only. Durable examples include explicit stop-pay conflicts, unsupported child specialization, operational-document/invoice-history mismatch, weak ordinary numeric references, cross-vendor exact-reference reliance, and contradictory authoritative current context.

Do not create vendor-specific routing templates as the primary intelligence. A wrong case should normally become stronger learning evidence, not another vendor-specific `if` statement.

## Held-out integrity
Holdout labels must never enter prompt retrieval, autonomy evidence, calibration, or same-decision route authority. Performance calibration uses only previously human-resolved TRAIN outcomes.

## Continuation rule
Do not pause between repo-safe sprint steps for approval. Complete the fullest safe sprint possible, commit it, verify scope, and stop only when external/local runtime execution is required or an actual authorization boundary is reached. Production remains untouched unless explicitly authorized.

This mission remains active until the immutable promotion gate is met and the AI-driven routing architecture is operationally proven.