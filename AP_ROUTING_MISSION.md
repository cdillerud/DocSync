# AP Routing Mission

ACTIVE UNTIL THE IMMUTABLE GATE IS MET.

Before changing AP routing, read `docs/V117_LEARNED_AUTONOMY_CHARTER.md`.

Goal: replace Square9 templates with an AI-driven AP router that learns Gamer Accounting's human-confirmed decisions and reviewer corrections. The AI is the primary route selector. Learned performance and high-purity route-neutral workflow neighborhoods earn autonomy. Deterministic logic is only a fail-closed safety envelope and MUST NOT choose a replacement route.

Immutable promotion gate: 0 wrong automatic routes, 100% automatic-route accuracy, >=90% representative held-out automatic-route coverage, minimum 20 labels.

Frozen runtime-proven zero-wrong fallback: `6c455f1a027361115eba3ea9ecde989009bda76e`.

## Current checkpoint

First AI-primary runtime candidate `3d581ff6def9eb0d42733f35ca46ea1d2232de99` was genuinely runtime-proven with 83/83 focused regressions, certified backend continuity, read-only Accounting/BC access, and no Production mutation. Its held-out result was 58/58 review, 0 automatic routes, 0% coverage. Offline analysis of the held-out rows showed the raw AI proposal was correct on 43/58 (74.14%).

The restarted fast-replay candidate `830bc9611f3e6c7bef12c66215ddd070214c593f` was then genuinely runtime-proven on September 4, 2026 with 116/116 focused regressions, the certified backend unchanged and healthy, read-only Accounting/BC behavior, and no Production mutation. The validated snapshot replay reused 278 previously hydrated human Accounting labels and preserved the stable 220-train / 58-holdout evaluation split. Raw AI proposal accuracy improved to 45/58 (77.59%). The promotion result was 14 automatic routes, 44 reviews, 24.14% coverage, 92.86% automatic-route accuracy, and one wrong automatic route. The immutable gate correctly failed with `FAIL_WRONG_AUTO_ROUTE`.

The sole wrong automatic route was Ball invoice/credit memo `6363143`: Accounting truth was `DO NOT PAY`, while the AI proposed and learned authority auto-approved `Vendor Credit Memos/Ball Detention Credits`. The current-document text contains both ordinary detention-credit semantics and the exceptional transaction instruction `Reversing this credit memo as per the request...`. The old neighborhood model treated five ordinary same-vendor detention-credit examples as pure authority and did not recognize transaction reversal as a workflow boundary.

Current learned-autonomy candidate: `7a983c610b206cff2d059f7a009a6d63bd15d4d0` on `feature/ap-ai-learned-autonomy`. The active control logic commit is `1f441704cc8313d2bcf37b6b55691932582f760c` on `migration/gpi-hub-dedicated-vm`. Next configured focused target: 120 tests. Do not claim 120/120 or any improved held-out metric until the certified runtime proves it.

Current candidate changes:
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
- deterministic route substitution remains disabled; safety may only demote to review;
- route-neutral `reversal_or_void` semantics now identify reversed, voided, or cancelled invoice/credit transactions;
- `explicit_stop_pay`, `replacement_or_offset`, and `reversal_or_void` are exceptional workflow features;
- when the current document carries an exceptional workflow feature, ordinary proposed-route neighbors that lack the same exception no longer count as autonomy support;
- exception-matched human support can still earn autonomy, so the repair is learned and general rather than a Ball/vendor-specific template.

## Restarted sprint fast replay

The certified run preserved 278 merged human Accounting labels at `/tmp/gpi-ap-routing-v117-evidence-snapshot.json`. The replay path may reuse that snapshot only as a cache of already-hydrated human evidence. It is NOT a new routing authority and it does not bypass the stable train/holdout split or any promotion gate.

Snapshot replay is fail-closed. Before reuse it must pass expected GamerAccounting authority, maximum age 24 hours, minimum examples, current route-contract validity, route diversity, unique identities, active status, human-authoritative label provenance, and exclusion of holdout/test/validation or unreviewed AI-generated evidence. New snapshots carry an examples SHA256 digest; a legacy snapshot may be replayed without a digest only after all other validation passes. Any validation failure visibly falls back to the full existing live read-only corpus build and targeted expansion.

The control overlay itself is inspectable and hash-verified. It reads `v117-rev3-entry-patch.ps1frag` and `v117-rev3-replay-transform.ps1frag` directly from the fetched control ref, verifies their pinned SHA256 values before execution, and then applies them to the immutable REV2 control baseline at `b45ae78800b8f6666a6a105318cf0b7bf6fe6648`. The replay path skips both base SharePoint hydration and targeted expansion only when the snapshot validates; otherwise the old live path runs unchanged.

Never lower the immutable gate to create coverage. Improve the AI's learned context, evidence similarity, calibration, and earned authority instead. Never self-train from unreviewed AI predictions. Never recreate Square9 as vendor-specific Python templates. Reviewer corrections are stronger evidence than passive confirmations. Future agents/new chats must continue the fullest repo-safe sprint without pausing for approval and stop only for an actual execution or authorization boundary. Never touch Production without explicit authorization.