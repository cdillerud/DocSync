# Customer PDF Mapping Checkpoint — 2026-09-03

## Safety state

- Target: `PRE_GAMERDOCS_CUTOVER_20260831` / sandbox / Gamer Packaging only.
- Discovery runs were GET only.
- No extension mutation during discovery.
- No business-data write.
- No Sales Order action.
- Production hard blocked.

## Parser architecture correction

Customer PO quantity/UOM is immutable source evidence. It is not automatically a Business Central-ready transaction quantity/UOM. BC-ready quantity/UOM remains unresolved until an authoritative customer/item mapping proves either direct equivalence or a deterministic conversion.

Customer-stated price is comparison evidence only and is never pricing authority.

## Berner — PO 241355

Source evidence:

- customer PO: `241355`
- customer item reference: `811476`
- source quantity/UOM: `68,000 EA`
- source price: `243.43 THOU`
- requested receive date: `2026-07-20`

Archive/BC evidence:

- customer: `BERNER` / Berner Foods, Inc.
- archived Gamer Sales Order: `114600`
- BC item: `21759-858231`
- BC UOM setup: EA=1, M=1000, PALLET=3610, TRUCK=72200
- archived SO quantity/UOM: `72.2 M`
- Location: `00`
- archived SO price: `243.43`
- full posted history: 307 rows
- observed posted quantities: `61.37 M`, `72.2 M`
- latest rolling state: `72.2 M @ 243.43 / Location 00`

Conclusion: exact customer/item context is strong, but `68,000 EA -> 72.2 M` must NOT be hard-coded from one source PO. Berner quantity conversion remains REVIEW pending an explicit customer-item/packout rule or equivalent Business Central authority.

## Herdez — PO 4500063632

Source evidence:

- customer PO: `4500063632`
- Gamer vendor reference on customer system: `50001644`
- customer item reference: `000000000004003467`
- source display quantity/UOM: `195,888 THOUSAND`
- deterministic source normalization: `195.888 M`
- source price: `225.75 THOUSAND`
- requested delivery date: `2026-09-01`

Archive/BC evidence:

- exact BC customer: `HERDEZ` / Herdez SA DE CV
- linked Gamer Purchase Order: `117357`
- BC item: `20113526`
- linked quantity/UOM: `195.888 M`
- BC UOM setup: CS=636, EA=1, M=1000, PALLET=4452, TRUCK=195888
- full posted Sales Invoice Line history: 2 rows
- both posted rows: `195.888 M / Location 00 / Unit Price 259.44`
- rolling state: `195.888 M @ 259.44 / Location 00`

Conclusion: Herdez has strong transaction-level quantity/UOM corroboration for this exact item context, but the customer item reference is not a literal BC item number. Source price `225.75` differs from BC history `259.44`, reinforcing that BC must remain pricing authority.

## Remaining identity gates

Neither source reference is a literal BC item number:

- Berner `811476` -> no direct item-number match.
- Herdez `000000000004003467` -> no direct item-number match.

Business Central native Item Reference is the preferred authority for customer-specific item-number translation. Standard `customerShippingAddresses` returned 404 in this environment, so a read-only Ship-to Address API is also required.

## 0.1.0.9 diagnostic scope

Version `0.1.0.9` must preserve `0.1.0.8` resolver behavior unchanged and add only:

1. read-only Item Reference API;
2. read-only Ship-to Address API.

No new write permissions, resolver changes, release/ship/invoice/post behavior, or Production access are authorized.
