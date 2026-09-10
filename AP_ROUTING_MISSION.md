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

Feature `502678f47bf2f373b0a7c19c915ba28ce6658f28` was then runtime-proven on September 5, 2026 with 128/128 focused regressions, 291 labels, 232 TRAIN / 59 held-out, 45/59 raw AI proposals correct, 13 autos, 22.03% coverage, 100% automatic-route accuracy, 0 wrong autos, and `FAIL_COVERAGE` only. Ball `6363143` was correctly recognized as `reversal_or_void` and safely held for review instead of being auto-routed to Ball Detention Credits.

## Current runtime-proven checkpoint: proposal quality jumped, safety held

Feature `5d59fbb95fe9581e0db6c77dc98f78f78264bbf8` was runtime-proven on September 10, 2026.

The previous semantic snapshot was stale, so the controller correctly rejected replay and performed a live read-only Accounting/BC rebuild. The rebuild discovered 2,889 Accounting files, selected 180 balanced examples, hydrated 165, recorded 15 hydration failures, then completed targeted vendor expansion at 149/149 with zero expansion failures. The resulting semantic-complete snapshot contains 314 human Accounting labels and the evaluation split is 255 TRAIN / 59 held-out.

Runtime result:

- 142/142 focused regressions PASS;
- certified backend unchanged and healthy before/after;
- semantic schema `v117-semantic-v1` ACTIVE;
- full TRAIN prompt context ACTIVE;
- high-specificity human anchor authority ACTIVE;
- raw AI proposals correct 52/59 = 88.14%;
- wrong raw AI proposals: 7;
- 15 automatic routes;
- 44 reviews;
- 25.42% automatic-route coverage;
- 100% automatic-route accuracy;
- 0 wrong automatic routes;
- promotion result `FAIL_COVERAGE` only;
- no Production mutation.

Compared with the previous zero-wrong checkpoint, the full-TRAIN prompt context improved raw proposal accuracy from 45/59 to 52/59, a gain of seven correct proposals and 11.87 percentage points, while automatic safety remained perfect. Automatic coverage improved from 22.03% to 25.42%.

The confidence telemetry is also materially stronger: >=95% confidence proposals were 38/39 correct (97.44%), and >=98% confidence proposals were 27/27 correct. Confidence alone is not promotion authority; these values are diagnostic evidence only.

## Current mathematical blocker

On a 59-document evaluation set, >=90% coverage requires at least 54 automatic routes. The AI currently proposes the correct exact route on 52/59. Therefore no authority policy can legitimately reach the immutable 90% coverage gate on this set until at least two additional raw AI errors are corrected.

There are also 37 correct AI proposals still being held for review. The next sprint must therefore improve both proposal discrimination and learned authority. It must not create coverage by weakening the immutable promotion gate.

The seven remaining raw proposal failures represent generic workflow-discrimination problems: WA assembly vs Dropship family, S&H owner/approver assignment, WTR/warehouse-transfer semantics, generic credit memo vs DNP, storage/accessorial vs DNP, and storage workflow vs Warehouse family. These are being addressed as general route-neutral workflow rules, not vendor-specific templates.

## Current candidate: TRAIN corroboration plus safety-scope correction

Current feature candidate: `a2b2111cde741c840c19573e0e50c311c98f95dd` on `feature/ap-ai-learned-autonomy`.

This candidate retains every existing neighborhood threshold and the immutable promotion gate. It adds one new learned authority view, sharpens the AI prompt, and narrows two deterministic safety rules that were proven to create false review decisions.

### TRAIN-only corroboration authority

`ap_routing_corroboration_authority_service.py` may confirm ONLY the AI's exact route. It never selects or substitutes a route. It considers only human TRAIN examples and only route-neutral slices:

- same vendor + same document type at large high purity;
- same vendor + same document type + structural reference family;
- same vendor + same document type + discriminating semantic signature;
- an exceptionally strict cross-vendor slice requiring document type + structural reference family + discriminating semantics.

Static same-vendor/reference corroboration requires at least five exact-route human supports and >=85% purity; broader same-vendor/type support requires at least five and >=90% purity. Dynamic children require >=98% model confidence, at least three exact human supports, and 100% purity. Reviewer-correction contradictions block corroboration. Generic global route frequency cannot earn autonomy.

This authority path cannot grant `DO NOT PAY` without explicit current stop-pay evidence and cannot bypass a `reversal_or_void` exception boundary. High-specificity DNP remains governed by the existing explicit-stop-pay anchor authority.

### Prompt discrimination repairs

The AI prompt now makes the following business-workflow distinctions explicit:

- approver/processor child folders are ownership assignments, not generic meanings of storage/freight terms;
- same-vendor ownership evidence outranks a cross-vendor approver example;
- a generic credit memo without current invalidation evidence must not become DNP from one historical DNP or a sales-shipment mismatch;
- storage/accessorial language by itself is not stop-pay evidence;
- a WA-prefixed reference is a warehouse-assembly family and must never cross into Dropship;
- a plain numeric BC/order reference does not determine warehouse vs dropship.

### Safety-scope corrections

The prior safety envelope treated any plain numeric BC order reference as `standard_order` and therefore automatically contradictory to every Warehouse route. Runtime evidence proved that premise false. The candidate removes that numeric-reference veto while retaining explicit W/WA/WTR -> Dropship family vetoes.

Resolved BC-vendor mismatch and cross-vendor exact-reference dependency are now applied only when the document type actually represents a payable supplier identity, such as AP invoice or credit memo. Shipping documents and warehouse receipts commonly expose customer/warehouse/carrier/ship-to parties in a generic vendor field, so those fields cannot safely be interpreted as payable-vendor conflicts.

For an exact DNP proposal with a current explicit stop-pay instruction and already-earned unanimous human stop-pay anchor authority, an incidental foreign BC reference or ordinary unresolved BC context no longer defeats the direct stop-pay evidence. Actual model/parse/invalid-route failures remain fail-closed.

## Next configured proof

Feature pin:
`a2b2111cde741c840c19573e0e50c311c98f95dd`

Entry-fragment SHA256:
`5B4B46952D94E1725D38C829E6F7CC513EEC0B584853457309B5F060EC71789F`

Replay-transform SHA256:
`EDAF2B455F7F903E82E418DE38642C39E9AF79094042EDD1185797049064A7C6`

Next focused regression target: **158 tests**. Do not claim 158/158 or any coverage/accuracy improvement until certified runtime proves it.

The September 10 semantic-complete 314-label snapshot is fresh. The next correct run should normally use validated fast replay, skipping the multi-hour live rebuild, provided the snapshot remains within its 24-hour age limit and passes authority/schema/SHA validation.

Desired telemetry includes raw proposal accuracy, `train_corroboration_auto_count`, high-specificity anchor auto count, corroboration slice/purity/support for each held-out row, automatic coverage/accuracy, wrong-auto count, and source-runtime continuity.

## Evaluation-integrity note

The stable 59-document split has now been inspected repeatedly during engineering. It remains useful as a regression/development evaluation set, but repeated tuning means it must not be treated as the sole final blind proof of generalization. Before Production cutover, the immutable promotion gate must also be demonstrated on a fresh representative blind holdout epoch or equivalent shadow set that was not used to choose candidate behavior. This strengthens the existing gate; it does not replace or lower it.

## Non-negotiable architecture rules

Never lower the immutable gate to create coverage. Improve AI learned context, semantic discrimination, calibration and earned human authority instead. Never self-train from unreviewed AI predictions. Never recreate Square9 as vendor-specific Python templates. Reviewer corrections are stronger evidence than passive confirmations. Deterministic safety may only demote the AI's exact route to review and must never select a replacement route. Future agents/new chats must continue the fullest repo-safe sprint without pausing for approval and stop only for an actual execution or authorization boundary. Never touch Production without explicit authorization.
