# AP Routing Mission

ACTIVE UNTIL THE IMMUTABLE GATE IS MET.

Before changing AP routing, read `docs/V117_LEARNED_AUTONOMY_CHARTER.md`.

Goal: replace Square9 templates with an AI-driven AP router that learns Gamer Accounting's human-confirmed decisions and reviewer corrections. The AI is the primary route selector. Learned performance and high-purity human evidence earn autonomy. Deterministic logic is only a fail-closed safety envelope and MUST NOT choose a replacement route.

Immutable promotion gate: 0 wrong automatic routes, 100% automatic-route accuracy, >=90% representative held-out automatic-route coverage, minimum 20 labels.

Frozen runtime-proven zero-wrong fallback: `6c455f1a027361115eba3ea9ecde989009bda76e`.

## Runtime progression

First AI-primary candidate `3d581ff6def9eb0d42733f35ca46ea1d2232de99` was runtime-proven with 83/83 focused regressions and 0% coverage. Raw AI proposal accuracy was 43/58 (74.14%).

Learned-neighborhood candidate `830bc9611f3e6c7bef12c66215ddd070214c593f` was runtime-proven with 116/116 focused regressions. On the 278-label 220-train / 58-holdout split it reached 14 autos / 24.14% coverage but produced one wrong auto: Ball credit memo `6363143`, expected `DO NOT PAY`, auto-routed to `Vendor Credit Memos/Ball Detention Credits`.

Candidate `025d0ac203e8a950f853918fd40b1a038ce19824` reached 120/120 focused regressions, but the same Ball reversal remained wrong. That run proved the reversal rule itself was not the root problem: the old corpus hydrator extracted PDF text for transient context and then discarded it before writing the supervised evidence example/snapshot.

The semantic-evidence repair persisted a bounded raw-text excerpt plus versioned route-neutral semantics (`v117-semantic-v1`) before deleting the temporary PDF, required semantic-complete SHA256 snapshots, and bound both balanced corpus hydration and targeted vendor expansion to the semantic-preserving hydrator.

## Current runtime-proven checkpoint: zero wrong restored

Feature `502678f47bf2f373b0a7c19c915ba28ce6658f28` was runtime-proven on September 5, 2026 with:

- 128/128 focused regressions PASS;
- certified backend unchanged and healthy before/after;
- semantic schema `v117-semantic-v1` ACTIVE;
- validated SHA256 evidence replay;
- 291 human Accounting labels;
- 232 TRAIN / 59 held-out;
- raw AI proposals correct 45/59 = 76.27%;
- 13 automatic routes;
- 46 reviews;
- 22.03% automatic-route coverage;
- 100% automatic-route accuracy;
- 0 wrong automatic routes;
- promotion result `FAIL_COVERAGE` only;
- no Production mutation.

This is the first learned-autonomy runtime after the semantic-evidence repair to restore the immutable safety side of the gate.

Ball `6363143` now behaves correctly. The held-out document exposes `reversal_or_void`; the AI proposes `DO NOT PAY`; ordinary detention-credit history is counted as exception-mismatched support; and the result safely remains review because exception-matched human support has not earned autonomy. The old wrong Ball Detention Credits auto-route is gone.

## Current blocker: proposal quality and earned coverage

Coverage is now the only promotion blocker, but authority tuning alone cannot solve it. The AI is currently correct on 45/59 held-out documents (76.27%), so AI-owned exact routes cannot reach >=90% automatic coverage until proposal accuracy itself rises to at least 54/59 on this split.

The current run contains 32 correct AI proposals that were still reviewed, including 13 `DO NOT PAY` cases, Ball warehouse orders, Tumalo/Rhonda Issues, S&H approval leaves, freight process states, WTR transfer, Canpack/Ball dropship, and credit-memo workflows. These are authority opportunities only after preserving zero-wrong behavior.

The 14 wrong raw proposals expose proposal-level weaknesses rather than a single vendor template problem. Representative failure classes include:

- dynamic-child overspecialization (`Dropship International/114022` when Accounting uses the parent);
- BC process-state overreach (`Ready to process Purch Inv` / `Sales Order not posted` inferred from generic open/posted status);
- generic S&H parent vs exact approver leaf;
- generic correction or sales-shipment evidence incorrectly driving `DO NOT PAY`;
- transfer/warehouse receipt semantics collapsing into generic return/special handling;
- credit memo purpose confused with DNP or specialized credit leaves;
- generic storage/freight semantics overriding GPI-specific workflows.

## Current coverage candidate

Current feature candidate: `5d59fbb95fe9581e0db6c77dc98f78f78264bbf8` on `feature/ap-ai-learned-autonomy`.

The candidate adds two complementary learned mechanisms without lowering any gate or allowing route substitution.

### 1. Full TRAIN prompt context

The model still receives at most eight raw human examples. In addition it now receives a bounded aggregate summary of the full human TRAIN set containing:

- current route-neutral semantic features and reference family;
- same-vendor route distributions;
- same-vendor + same-document-type route distributions;
- matching reference-family route distributions;
- bounded nearest-human route observations with relevance, vendor/type/reference counts and shared semantics;
- observed parent-vs-dynamic-child usage for contract-declared dynamic route prefixes.

This summary is PROMPT CONTEXT ONLY. It does not recommend, authorize, or substitute a route.

The AI-primary prompt now explicitly enforces learned GPI workflow granularity:

- verified BC/order references alone do not justify a dynamic child;
- dynamic children require comparable human TRAIN evidence using dynamic children;
- process-state leaves such as `Ready to process Purch Inv` and `Sales Order not posted` require comparable human-labelled evidence, not BC state alone;
- do not stop at a generic workflow parent when comparable human labels consistently use a child;
- `DO NOT PAY` is exceptional and must not be inferred merely from generic correction, sales-shipment/missing-PO evidence, a credit memo, or unrelated historical DNP cases;
- credit memo alone does not imply DNP or a specialized credit child;
- WTR/WA/W structural families must be interpreted with human workflow evidence rather than generic return/freight semantics.

### 2. High-specificity human anchor authority

Nearest-neighbor authority remains unchanged. A second authority path may confirm ONLY the AI's exact proposed route when a deliberately tiny route-neutral anchor has broad unanimous human TRAIN support.

Eligible anchors are intentionally restricted to:

- `explicit_stop_pay`;
- `wtr_reference`;
- `wa_reference`.

Generic freight, return, storage, credit, inventory, detention, W/numeric references, vendor identity, filenames, etc. cannot use this path.

Anchor authority requires at least five human TRAIN supports for the AI's exact route, zero contradictory Accounting routes, and zero reviewer-correction contradictions. Any conflicting human route blocks the anchor path and also prevents a neighborhood from bypassing that high-specificity conflict. The mechanism never chooses a route and remains subject to the normal deterministic safety envelope afterward.

## Next configured proof

Active control code commit: `e95f4e932b926f0a648d3278a20065f51ab76492` on `migration/gpi-hub-dedicated-vm`. Later documentation commits may advance the branch head while this exact code pin remains the execution authority.

Feature pin:
`5d59fbb95fe9581e0db6c77dc98f78f78264bbf8`

Entry-fragment SHA256:
`CE0346D72867D9C6807AA6A12AE0EE210460055E01621DA04946F0F126D980F1`

Replay-transform SHA256:
`EDAF2B455F7F903E82E418DE38642C39E9AF79094042EDD1185797049064A7C6`

Next focused regression target: **142 tests**. Do not claim 142/142 or any coverage/accuracy improvement until certified runtime proves it.

The 291-label semantic-complete snapshot is already valid, so the next correct run should normally use validated fast replay rather than rebuilding the corpus, provided the snapshot remains within its 24-hour age limit and passes all integrity/authority/schema checks. Any validation failure must still fail closed to the live read-only rebuild.

Desired next telemetry includes the aggregate TRAIN-context activation, high-specificity anchor authority measurements, raw proposal accuracy, anchor-earned auto count, zero-wrong metrics, and full held-out rows. Promotion remains impossible unless every immutable gate passes.

## Non-negotiable architecture rules

Never lower the immutable gate to create coverage. Improve AI learned context, semantic discrimination, calibration and earned human authority instead. Never self-train from unreviewed AI predictions. Never recreate Square9 as vendor-specific Python templates. Reviewer corrections are stronger evidence than passive confirmations. Deterministic safety may only demote the AI's exact route to review and must never select a replacement route. Future agents/new chats must continue the fullest repo-safe sprint without pausing for approval and stop only for an actual execution or authorization boundary. Never touch Production without explicit authorization.
