# AP Routing Mission

ACTIVE UNTIL THE IMMUTABLE GATE IS MET.

Before changing AP routing, read `docs/V117_LEARNED_AUTONOMY_CHARTER.md`.

Goal: replace Square9 templates with an AI-driven AP router that learns Gamer Accounting's human-confirmed decisions and reviewer corrections. The AI is the primary route selector. Learned performance and high-purity route-neutral workflow neighborhoods earn autonomy. Deterministic logic is only a fail-closed safety envelope and MUST NOT choose a replacement route.

Immutable promotion gate: 0 wrong automatic routes, 100% automatic-route accuracy, >=90% representative held-out automatic-route coverage, minimum 20 labels.

Frozen runtime-proven zero-wrong fallback: `6c455f1a027361115eba3ea9ecde989009bda76e`.

## Current checkpoint

First AI-primary runtime candidate `3d581ff6def9eb0d42733f35ca46ea1d2232de99` was genuinely runtime-proven with 83/83 focused regressions, certified backend continuity, read-only Accounting/BC access, and no Production mutation. Its held-out result was 58/58 review, 0 automatic routes, 0% coverage. That is NOT a promotion success. Offline analysis of the held-out rows showed the raw AI proposal was correct on 43/58 (74.14%), proving the immediate problem was both AI retrieval quality and an authority model that treated deliberately contradictory same-vendor examples as vendor-wide votes.

Current learned-autonomy candidate: `830bc9611f3e6c7bef12c66215ddd070214c593f` on `feature/ap-ai-learned-autonomy`. The active V117 control path overlays the frozen REV2 controller from control commit `b45ae78800b8f6666a6a105318cf0b7bf6fe6648`, preserving its certified backend selector, detached execution, bounded health checks, runtime replacement detection, read-only data behavior, and cleanup. Next configured focused target: 116 tests. Do not claim 116/116 until the certified runtime proves it.

Current candidate changes after the 0%-coverage run:
- hard max 8 actual human learning examples in the AI prompt;
- bounded semantic excerpts from those human examples so the AI sees why a historical case is relevant;
- route-neutral workflow features including W/WTR/WA/numeric reference families and stop-pay, detention, freight, dunnage, inventory, reconciliation, credit, return, cost-variance and related semantics;
- prompt retrieval is separated from authority: prompt may include boundary contrasts, but automatic authority comes from an independent nearest-neighbor human Accounting neighborhood;
- same-vendor high-purity neighborhoods can bootstrap autonomy for the AI's exact route;
- sparse/new vendors may use stricter cross-vendor semantic neighborhoods only when there is a current-document semantic/reference anchor;
- reviewer corrections are stronger contradictory evidence and block bootstrap authority;
- AI proposal accuracy/confidence bands are measured as shadow telemetry independently from the promotion gate;
- explicit W/WTR/WA filename reference families outrank incidental numeric BC references for the safety-family check;
- resolved BC-vendor mismatch is a safety veto only for logistics routes, so unrelated BC matches do not poison special Accounting queues;
- deterministic route substitution remains disabled; safety may only demote to review.

## Restarted sprint fast replay

The last certified run preserved 278 merged human Accounting labels at `/tmp/gpi-ap-routing-v117-evidence-snapshot.json`. The restarted sprint may reuse that snapshot only as a cache of already-hydrated human evidence. It is NOT a new routing authority and it does not bypass the stable train/holdout split or any promotion gate.

Snapshot replay is fail-closed. Before reuse it must pass expected GamerAccounting authority, maximum age 24 hours, minimum examples, current route-contract validity, route diversity, unique identities, active status, human-authoritative label provenance, and exclusion of holdout/test/validation or unreviewed AI-generated evidence. New snapshots carry an examples SHA256 digest; the previously preserved legacy snapshot may be replayed without a digest only after all other validation passes. Any validation failure visibly falls back to the full existing live read-only corpus build and targeted expansion.

The control overlay itself is inspectable and hash-verified. It reads `v117-rev3-entry-patch.ps1frag` and `v117-rev3-replay-transform.ps1frag` directly from the fetched control ref, verifies their pinned SHA256 values before execution, and then applies them to the immutable REV2 control baseline. The replay path skips both base SharePoint hydration and targeted expansion only when the snapshot validates; otherwise the old live path runs unchanged.

Never lower the immutable gate to create coverage. Improve the AI's learned context, evidence similarity, calibration, and earned authority instead. Never self-train from unreviewed AI predictions. Never recreate Square9 as vendor-specific Python templates. Reviewer corrections are stronger evidence than passive confirmations. Future agents/new chats must continue the fullest repo-safe sprint without pausing for approval and stop only for an actual execution or authorization boundary. Never touch Production without explicit authorization.