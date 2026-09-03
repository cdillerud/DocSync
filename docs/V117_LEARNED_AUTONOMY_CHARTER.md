# V117 Learned Autonomy Charter

Status: ACTIVE UNTIL THE IMMUTABLE PROMOTION GATE IS MET

## Mission

Replace Square9's brittle templates with an AI-driven AP routing system that learns Gamer Accounting's actual routing decisions and reviewer corrections, earns increasing autonomy from demonstrated performance, and safely routes at least 90% of representative held-out AP documents with 100% automatic-route accuracy and zero wrong automatic routes.

The AI is the primary routing intelligence. Deterministic code is a safety envelope, not the steering wheel.

This charter is durable project authority. Future agents, new chats, and developers MUST read it before changing AP routing behavior. Do not silently revert to vendor-specific routing templates or a deterministic rule tree.

## Immutable promotion gate

Never lower these gates to make a candidate pass:

- zero wrong automatic routes
- 100% automatic-route accuracy
- at least 90% held-out automatic-route coverage
- default minimum labeled examples: 20

Coverage means the percentage of representative held-out documents that the system is willing to route automatically. A review decision is a safe abstention, not a wrong route.

## Frozen safety fallback

The last runtime-proven zero-wrong deterministic fallback is:

- feature commit: `6c455f1a027361115eba3ea9ecde989009bda76e`
- focused regressions: 49/49 PASS
- holdouts: 62
- automatic: 26
- review: 36
- coverage: 41.94%
- automatic-route accuracy: 100%
- wrong automatic routes: 0
- measured gate: FAIL_COVERAGE only

Treat this commit as a rollback/fallback baseline. Do not keep expanding it as the primary routing architecture.

## Architectural rule

The intended flow is:

1. Extract the current document and authoritative context.
2. Retrieve relevant TRAIN-ONLY human-confirmed Gamer Accounting examples, including corrections and meaningful contradictions.
3. The AI chooses the proposed route and explains its evidence.
4. Learned autonomy measures whether this kind of AI decision has earned the right to act.
5. A small deterministic safety envelope may demote the result to review.
6. Deterministic safety MUST NOT choose a replacement route.
7. Human acceptance/correction becomes new authoritative learning evidence.
8. Untouched held-out labels grade the system externally.

The learned-autonomy layer MUST preserve the AI's proposed route. It may grant authority or abstain. It may not substitute a different route.

## Evidence hierarchy

Highest authority:

1. Current-document explicit instructions and authoritative current context.
2. Reviewer corrections from Gamer Accounting.
3. Human-confirmed final Gamer Accounting placements.
4. Repeated relevant human-confirmed historical examples.
5. Read-only Business Central context and document/reference evidence.
6. Historical NAV/Zetadocs material for context and coverage only.
7. AI inference.

AI-generated predictions are NEVER training authority merely because the AI previously generated them. A prediction becomes learning evidence only after a human resolves it through confirmation or correction.

Reviewer corrections carry more weight than ordinary confirmations because they encode a known decision boundary.

## Learning behavior

The system should learn patterns such as vendor, document type, route family, semantic meaning, current references, and authoritative context from human outcomes rather than from hard-coded customer/vendor templates.

A wrong result should normally create a stronger learning example and reduce/suspend autonomy for that learned pattern. It should not automatically result in another vendor-specific `if` statement.

Unknown, contradictory, low-evidence, or historically unreliable patterns should remain review until they earn authority.

## Autonomy tiers

Use three conceptual tiers:

- `review`: insufficient or contradictory learned authority; human decision required.
- `guarded`: promising learned pattern, but insufficient proven performance for automatic action. In V117 this remains review while metadata is recorded.
- `earned_auto`: sufficient relevant human evidence and demonstrated performance to permit the AI's proposed route to execute automatically.

A prior wrong human-resolved outcome for the same learned pattern suspends `earned_auto` until the pattern has enough new evidence to re-earn authority under the configured policy.

## Deterministic safety envelope

Deterministic safety exists only for broad, non-negotiable hazards. It may demote an AI auto result to review. It must not infer another route.

Examples of durable safety boundaries discovered during V117 include:

- explicit current-document stop-pay language cannot be overridden by a payable workflow
- an unsupported child workflow cannot be invented from parent-route history alone
- a non-AP operational document cannot blindly inherit invoice routing authority
- ordinary numeric references alone are insufficient authority for automatic routing
- a cross-vendor exact-reference conflict remains review when the AI relied on foreign evidence
- contradictory authoritative current context remains review

Do not turn these examples into a growing vendor-specific template library.

## Held-out integrity

- Split training evidence from held-out truth before retrieval or routing.
- The current holdout label must never be included in examples, performance calibration, or route authority.
- Performance/calibration may use only previously human-resolved TRAIN evidence.
- The evaluator must report the AI route separately from the autonomy decision and any safety demotion.
- Never use test labels to improve the same test decision.

## Performance and autonomy

Autonomy is earned from actual AI-versus-human outcomes, not static route frequency alone.

For a learned pattern record:

- human-resolved observations
- AI correct outcomes
- AI wrong outcomes
- recent accuracy
- conservative confidence/lower bound where sufficient data exists
- correction count
- contradiction count
- pattern suspension status

A historical wrong for a pattern is material negative evidence. High model confidence alone is never sufficient for autonomy.

## Reviewer feedback contract

Persist enough provenance to reconstruct learning truth:

- document identity
- vendor identity
- document type
- references
- AI proposed route
- AI confidence/reason when available
- final human route
- accepted vs corrected
- reviewer identity when available
- resolution timestamp
- source: `reviewer_confirmation` or `reviewer_correction`
- human-evidence weight

No Production writes are authorized by this charter. V117 learning/evaluation work remains read-only unless Chad explicitly authorizes a write path.

## V117 learned-autonomy sprint sequence

1. Persist this charter and root mission pointer.
2. Implement relevant correction-first TRAIN example retrieval.
3. Implement human feedback provenance helpers.
4. Implement AI-vs-human performance calibration.
5. Implement learned-autonomy authority that cannot replace the AI route.
6. Add broad learned-autonomy and safety regressions.
7. Wire the V117 evaluator so AI routing is primary, learned autonomy grants/abstains, and deterministic safety only demotes.
8. Preserve source-runtime fingerprinting, read-only corpus access, BC write blocks, temp staging, and cleanup proof.
9. Pin the control branch to the exact candidate SHA.
10. Run the normal desktop launcher and measure the unchanged promotion gate.
11. If any wrong automatic route appears, suspend the responsible learned pattern or improve learning/retrieval before seeking more coverage.
12. If zero wrong remains, increase coverage by improving learned evidence/retrieval/calibration, not by lowering thresholds.

## Continuation rule

Do not pause between repo-safe sprint steps to ask for approval. Complete the fullest safe sprint possible, commit it, verify scope, and stop only when external/local runtime execution is required or an actual safety/authorization boundary is reached.

This mission remains active until the immutable promotion gate is met and the AI-driven routing architecture is operationally proven.