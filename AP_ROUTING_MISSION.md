# AP Routing Mission

ACTIVE UNTIL THE IMMUTABLE GATE IS MET.

Before changing AP routing, read `docs/V117_LEARNED_AUTONOMY_CHARTER.md`.

Goal: replace Square9 templates with an AI-driven AP router that learns Gamer Accounting's human-confirmed decisions and reviewer corrections. The AI is the primary route selector. Learned performance and high-purity route-neutral workflow neighborhoods earn autonomy. Deterministic logic is only a fail-closed safety envelope and MUST NOT choose a replacement route.

Immutable promotion gate: 0 wrong automatic routes, 100% automatic-route accuracy, >=90% representative held-out automatic-route coverage, minimum 20 labels.

Frozen runtime-proven zero-wrong fallback: `6c455f1a027361115eba3ea9ecde989009bda76e`.

## Runtime progression

First AI-primary runtime candidate `3d581ff6def9eb0d42733f35ca46ea1d2232de99` was genuinely runtime-proven with 83/83 focused regressions, certified backend continuity, read-only Accounting/BC access, and no Production mutation. Its held-out result was 58/58 review, 0 automatic routes, 0% coverage. Offline analysis of the held-out rows showed the raw AI proposal was correct on 43/58 (74.14%).

The first learned-neighborhood fast-replay candidate `830bc9611f3e6c7bef12c66215ddd070214c593f` was runtime-proven with 116/116 focused regressions. The 278-label replay preserved the stable 220-train / 58-holdout evaluation split. Raw AI proposal accuracy was 45/58 (77.59%). Promotion measured 14 automatic routes, 44 reviews, 24.14% coverage, 92.86% automatic-route accuracy, and one wrong automatic route. The gate correctly failed with `FAIL_WRONG_AUTO_ROUTE`.

The wrong auto was Ball invoice/credit memo `6363143`: Accounting truth was `DO NOT PAY`, while the AI proposed and learned authority auto-approved `Vendor Credit Memos/Ball Detention Credits`. The actual current-document text contains both normal detention-credit semantics and the exceptional transaction instruction `Reversing this credit memo as per the request...`.

Candidate `7a983c610b206cff2d059f7a009a6d63bd15d4d0` introduced a route-neutral reversal/void semantic boundary, but its first certified attempt stopped at 118/120 focused tests because explicit stop-pay had also been treated as an exception-matched workflow. No held-out evaluation ran. Candidate `025d0ac203e8a950f853918fd40b1a038ce19824` narrowed exception matching to `reversal_or_void` only and restored the mature explicit-DNP contract.

Candidate `025d0ac203e8a950f853918fd40b1a038ce19824` then ran successfully through 120/120 focused regressions on September 4, 2026. The existing 278-label snapshot replay validated and the source backend remained unchanged and healthy. The held-out result was 58 documents, 12 automatic routes, 46 reviews, 20.69% coverage, 91.67% automatic-route accuracy, one wrong automatic route, and `FAIL_WRONG_AUTO_ROUTE`. Raw AI proposal accuracy was 42/58 (72.41%). The same Ball `6363143` document remained the sole wrong automatic route.

## Root cause proven after the 120/120 run

The reversal policy itself was not receiving the semantic evidence it was designed to use. `ap_routing_corpus_service.hydrate_accounting_label()` extracted up to five PDF pages / 12,000 characters into `document['raw_text']` for context work, but the subsequent `prepare_routing_example()` payload omitted that raw text and omitted any durable semantic feature snapshot. The local source file was then deleted. As a result, the old 278-label snapshot was cryptographically valid but semantically incomplete.

That explains the runtime/unit-test mismatch: unit tests could see `Reversing this credit memo...`, while replayed held-out evidence typically retained only filename, classification fields, BC context and route label. The old replay therefore continued treating Ball `6363143` as an ordinary detention credit and saw five same-vendor detention examples as pure support.

Targeted vendor expansion had the same risk because `ap_routing_corpus_expansion_service.py` imported `hydrate_accounting_label` by value. The current controller therefore binds BOTH the route-balanced base corpus builder and targeted expansion to the semantic-preserving hydrator.

## Current candidate: semantic-complete learned evidence

Current feature head: `502678f47bf2f373b0a7c19c915ba28ce6658f28` on `feature/ap-ai-learned-autonomy`.

The candidate introduces a versioned route-neutral semantic evidence contract:

- semantic schema: `v117-semantic-v1`;
- bounded `raw_text_excerpt` is retained before the temporary source file is deleted;
- `learned_semantic_features` and `learned_reference_family` are persisted as route-neutral evidence;
- semantic schema/features are mirrored in `extracted_fields` so held-out reconstruction cannot silently discard them;
- semantic derivation never inspects or selects a route label;
- stored semantic features are accepted only from the exact known schema and known feature vocabulary;
- `reversal_or_void` remains the exceptional authority boundary, while explicit stop-pay retains its existing safety behavior;
- held-out telemetry now exposes current semantic features, exceptional workflow features, exception support, exception mismatches, and semantic schema;
- evidence snapshot replay now REQUIRES the exact semantic schema and a SHA256 digest;
- legacy/digest-less or semantically incomplete snapshots are intentionally rejected and force a live read-only rebuild;
- both base corpus hydration and targeted vendor expansion are bound to `hydrate_accounting_label_with_semantics`;
- no deterministic route substitution was added and no vendor-specific routing template was added.

The new semantic evidence regression layer adds eight tests for persistence, replay, route-label independence, schema rejection, mirror validation, SHA verification, stored reversal behavior, and preserved explicit-DNP behavior. The next configured focused target is **128 tests**. Do not claim 128/128 until the certified runtime proves it.

## Current control plane

The final semantic-evidence entry fragment is pinned by SHA256:
`39165FED128063D4107CF3DA922B604E6212EE67E44B97202CC8226C82D2A6D8`.

The replay-transform SHA256 remains:
`EDAF2B455F7F903E82E418DE38642C39E9AF79094042EDD1185797049064A7C6`.

The control wrapper code commit that pins feature `502678f47bf2f373b0a7c19c915ba28ce6658f28`, focused target 128, the semantic schema, and the fragment hash is `f996fcecc97254c5298fba7509ad599e98dda142`. Later documentation-only commits may advance the control branch head; the launcher must use the current fetched control head while these exact code pins remain unchanged.

## Next certified run behavior

The currently stored 278-label snapshot predates `v117-semantic-v1`. Its rejection is EXPECTED and is a safety PASS, not a regression. A correct next run should show a reason equivalent to:

`V117_EVIDENCE_REPLAY=REJECTED;reason=semantic_feature_schema_mismatch:missing!=v117-semantic-v1`

followed by:

`V117_LIVE_CORPUS_REBUILD=USED`

The live rebuild remains read-only against GamerAccounting and Business Central. It may take hours and must not be interrupted. After the base corpus and targeted expansion finish, the newly written snapshot must carry `semantic_feature_schema=v117-semantic-v1` plus its examples SHA256. Future candidate reruns can use fast replay again as long as that snapshot validates.

For Ball `6363143`, the next held-out telemetry should visibly include `reversal_or_void` in current/exceptional semantic features. Ordinary detention-credit examples lacking reversal semantics must move into exception-mismatch support and must not grant autonomy to the detention route. The system does not need to force a replacement route; safe review is acceptable unless the AI's exact route has genuinely earned exception-matched authority.

The immutable gate remains unchanged. Even after zero wrong automatic routes are restored, 20.69% measured coverage is far below the required 90%, so subsequent sprints must immediately target correct-but-reviewed AI proposals by improving learned context, semantic discrimination, calibration and earned authority, never by lowering thresholds.

## Non-negotiable architecture rules

Never lower the immutable gate to create coverage. Improve the AI's learned context, evidence similarity, calibration, and earned authority instead. Never self-train from unreviewed AI predictions. Never recreate Square9 as vendor-specific Python templates. Reviewer corrections are stronger evidence than passive confirmations. Deterministic safety may only demote the AI's exact route to review and must never select a replacement route. Future agents/new chats must continue the fullest repo-safe sprint without pausing for approval and stop only for an actual execution or authorization boundary. Never touch Production without explicit authorization.
