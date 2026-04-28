# Functional Capability Audit — 2026-04-28

**Method:** Live read against production MongoDB (preview environment mirror) + router + service inventory + frontend page inventory. Read-only. No code changes.

**Bottom line first.**
The hub has a *huge* amount of code (72 routers, 155 services, 53 pages) and the AP capture pipeline is genuinely working. **But the system has been stuck in `shadow_mode` since 2026-02-15.** It's observing and learning, not autonomously executing. That, plus an unwired sales mailbox, plus empty inventory registries, is why the app feels less functional than it looks.

---

## 1. System posture (the big finding)

```
hub_settings.type            = "shadow_mode"
shadow_mode_started_at       = 2026-02-15T10:00:00Z   ← 10+ weeks
auto_post_settings.enabled   = true                    ← but gated by shadow_mode
BC_BLOCK_PRODUCTION_WRITES   = true                    ← in backend/.env
BC_WRITE_ENVIRONMENT         = Sandbox_11_3_2025       ← writes go to sandbox only
```

**What this means.** Every AP invoice that flows in gets captured, classified, validated, vendor-matched, BC-cross-checked, and marked `Completed`. **None of them actually post to production BC.** The `auto_post_enabled=true` flag is misleading — it's overridden by `shadow_mode` and `BC_BLOCK_PRODUCTION_WRITES=true`.

This is intentional from earlier phases (Lane A integrity gate). It is also the single biggest reason the app doesn't *feel* like it's replacing anything — Zetadocs/Square9 actually post to BC; the hub is observing.

---

## 2. What actually works today (verified from live data)

| Capability | Evidence | Status |
|---|---|---|
| AP email intake | 163 docs from `hub-ap-intake@gamerpackaging.com`, real `tumalocreek.local` message IDs | ✅ live |
| AI classification | 165 AP_INVOICE + 5 SALES_INVOICE + 13 OTHER classified | ✅ working (84% hit rate) |
| Field extraction | 605 vendor profiles built, 968 vendor aliases learned | ✅ working |
| BC reference cache | 278,817 BC reference records cached + 1,000 catalog items | ✅ live |
| Vendor matching | 605 invoice profiles + 968 aliases | ✅ working |
| Workflow events | 60,463 events recorded — full audit trail | ✅ working |
| SharePoint upload | 199 `Completed` docs (most archived to SP) | ✅ working |
| BC SO read sync | 42 `sales_open_order_headers` synced from BC | ✅ working |
| Spiro CRM read | 23,642 contacts + 7,200 companies cached | ✅ working |
| Customer master | 1,998 customers indexed | ✅ working |
| Frontend dashboards | Monitor / Governance / Inbox / SalesDashboard render with live data | ✅ working |
| Document detail UX | extracted-data card, readiness card, ownership evidence panel | ✅ working |

---

## 3. What's built but NOT exercised (zero production data despite shipped code)

| Capability | Code present | Live rows | Gap |
|---|---|---|---|
| Sales mailbox polling (`hub-sales-intake@gamerpackaging.com`) | ✅ enabled in `mailbox_sources` | **0 mail_intake_log rows** from it | mailbox configured but poller has never fetched a customer PO |
| SO drafts | ✅ `so_drafts`, `sales_order_draft_candidates` | 2 test rows + 0 | nothing has ever produced a real draft SO |
| Sales documents | ✅ `sales_documents` collection | 0 | sales-side ingest never wrote a row |
| Sales inventory positions | ✅ `sales_inventory_positions` collection | 0 | inventory-to-SO tie-in is unwired |
| Sales items / customers / customer-items | ✅ collections + UI | 0 / 0 / 0 | sales master never seeded |
| Sales pricing tiers / warehouses | ✅ collections | 0 / 0 | sales master never seeded |
| CP item registry (COW Lane C Step 1) | ✅ router + UI tab + 5 endpoints | 0 | nobody has registered a CP item |
| Consigned item registry (Lane C Step 2) | ✅ router + UI tab + 4 endpoints | 0 | nobody has registered a consigned item |
| AP learning suggestions / reviewer feedback | ✅ collections + dashboard | 0 / 0 | feedback loop never used by reviewers |
| SO learning suggestions / reviewer feedback | ✅ collections + dashboard | 0 / 0 | same |
| Customer posting profiles | ✅ collection + service | 0 | per-customer learning never wrote |
| Inside Sales pilot runs | ✅ router + page | 0 | pilot button exists, never run |
| EOD controller (P0.6) | ✅ router | 0 | scheduler not wired |
| Unknown-doc reclaim post-process | ✅ router | 0 | never triggered |
| Mail poll runs (sales) / sales mail intake log | ✅ collections | 0 / 0 | sales-side polling never executed |

---

## 4. What's missing entirely (no code path exists)

These are the actual feature holes you'd need to build to replace Square9+Zetadocs end-to-end:

### Square9 holes
1. **Universal document search** — full-text + indexed-field search across **all** doc types (not just AP). Today the inbox lists current queue; there's no "find me Coloplast packing slip from June 2025" UX. `DocumentsHubPage` is queue-oriented, not retrieval-oriented.
2. **Folder/drawer browse for non-AP docs** — Square9 users navigate by drawer→folder→doc. Hub's only browse axis is by-status or by-vendor on AP. Sales Invoice / Receipt / Shipping Document / OTHER classes have no organized retrieval UX.
3. **Multi-page PDF splitting w/ per-page filing** — code path exists for `auto_split` (5 docs done) but no operator UX to manually split a 50-page batch by page-range and file each piece against a different BC entity.
4. **Scanner / MFP capture** — no TWAIN, no scan-to-folder watcher. If a paper doc enters Gamer today, someone has to email it in.
5. **Custom indexing fields per doc type** — Square9 lets you define "this doc type has these searchable fields." Hub has fixed extraction fields per doc type, no tenant-customizable schema.

### Zetadocs holes (entire feature class missing)
1. **Outbound delivery / "Send"** — when BC posts a sales invoice, packing slip, or order confirmation, **nothing in the hub auto-emails the branded PDF to the customer**. This is Zetadocs's headline feature. Closest hub capability: `template_value_injector.py` (used for AP, not outbound delivery).
2. **Branded outbound PDF templates** — `TemplatesPage.js` exists but `operational_templates` collection holds 236 rows of *pattern templates* (used for extraction learning), not document layout templates. No PDF rendering pipeline for outbound docs.
3. **Outbound email archival into BC** — Zetadocs captures outbound emails sent from BC and files them. Hub has `email_logs` (mostly mock daily summaries) but no inbound-OR-outbound BC-tied archival.
4. **Approval routing inside BC pages** — Zetadocs surfaces approve/reject buttons inside BC's invoice page. Hub has its own approval UI; no BC page integration.

### Sales Order automation holes
1. **Customer PO → BC SO end-to-end** — code exists (`AUTO_CREATE_SALES_ORDER_ENABLED` flag, `inside_sales_pilot.py`, `services/sales_intake_learning_service.py`, the Giovanni patterns) but the flag is off and the pipeline has never produced a single live BC SO. The wiring from "extracted customer PO" → "matched items" → "BC SO POST" is built but unflipped.
2. **Inventory availability check at SO creation** — `sales_inventory_positions` is empty; no service queries BC inventory at draft time.
3. **Inventory reservation/allocation** — no allocation service exists. `inv_movements` (3,629 rows) tracks BC inventory movements pulled in, but there's no reservation-on-draft logic.
4. **Drop-ship vs warehouse routing decision automation** — gates exist (Lane C Step 6 + 7), but nothing triggers them on real customer POs because no real customer POs are flowing.

### General gaps
- **Auto-post for production AP** — flipping `BC_BLOCK_PRODUCTION_WRITES=false` + leaving `shadow_mode` is a deliberate decision that hasn't been made.
- **34 docs (16%) classified as `doc_type: None`** — classifier failure rate visible but no escalation path beyond the queue.

---

## 5. The honest score

Translating the user's question "where are we vs Square9 + Zetadocs + SO automation?":

| Dimension | Score | Note |
|---|---|---|
| **Document capture (Square9 core)** | 8/10 | AP email + manual upload works; missing scanner + better non-AP types |
| **Document classification + extraction** | 8/10 | AI working; 16% unclassified rate is the gap |
| **Document storage + retrieval** | 4/10 | Storage works; **search UX is queue-oriented, not Square9-style retrieval-oriented** |
| **Folder/drawer browse** | 2/10 | Effectively missing for non-AP types |
| **AP-to-BC posting (Zetadocs core)** | 2/10 | Pipeline built but stuck in shadow mode; **0 real posts** |
| **Outbound delivery (Zetadocs Send)** | 0/10 | No code path exists |
| **Outbound branded templates** | 0/10 | No PDF generation pipeline |
| **Sales order auto-creation** | 3/10 | Code scaffolding present; **0 real SOs created**; mailbox unwired |
| **Inventory tied to SO** | 1/10 | Inventory reads work; no reservation/allocation; empty positions table |
| **Drop-ship / COW / consignment routing** | 5/10 | Gates implemented; registries empty; no live traffic to test |
| **Approval workflow** | 7/10 | UI works for AP review; no BC-page-embedded approval |
| **Reporting / dashboards** | 8/10 | Many dashboards working with real data |
| **Audit trail** | 7/10 | 60K workflow events; missing structured `governance_audit_log` (P1.A) |

---

## 6. Where to spend the next sprint (my recommendation)

You can't fix all 30+ gaps in parallel. Highest leverage, lowest risk, **functionality-first**, ranked:

### Tier 1 — Make the AP pipeline actually do its job (1-2 days)
**Goal: real AP invoices posting to BC sandbox first, then production.**
1. **Decide on shadow mode.** Either flip `BC_BLOCK_PRODUCTION_WRITES=false` for a controlled batch, or define an exit criterion. Today's posture means the app cannot replace Zetadocs no matter what we build.
2. **Run a controlled posting batch in sandbox** — pick 10 ready-for-post AP docs, post to `Sandbox_11_3_2025`, walk the result with the operators, capture failure modes.
3. **Triage `doc_type: None` (34 docs)** — quick classifier pass to bring the unclassified rate down.

### Tier 2 — Get sales POs actually flowing (3-5 days)
**Goal: a real customer PO email turns into a real BC SO draft, end-to-end.**
1. **Diagnose why `hub-sales-intake@` isn't polling.** Mailbox is configured; either Graph creds are missing for it, or the poller isn't enabled, or the mailbox has zero inbound. Check + fix.
2. **Walk one real Coloplast/Giovanni PO through the pipeline manually** — drop the PDF into the sales mailbox, watch what happens, find every place it stops.
3. **Wire the auto-create-SO path to actually create a BC SO draft (not posted)** for high-confidence matches.
4. **Add inventory availability stamp on the draft** — single read against BC; cheap.

### Tier 3 — The Zetadocs-replacement piece nobody has tackled (5-10 days)
**Goal: outbound delivery. When BC posts a sales invoice, hub emails a branded PDF to the customer.**
1. Pull the BC posted invoice via existing reference cache.
2. Render to PDF with a branded template (one template to start: Gamer Packaging sales invoice).
3. Email via Graph API on the existing `hub-ap-intake` or new `hub-billing-out` mailbox.
4. Log to `email_logs` with a `bc_document_id` link.

### Tier 4 — Square9-style retrieval (3-5 days)
**Goal: a real "find me any document by filter" UX, not just queue browsing.**
1. New page `SearchPage.js` — filter by doc_type, vendor, customer, date range, BC document number, free-text on extracted fields.
2. Backend already has the data; this is mostly a search-API + UX shell.

### Defer until functional baseline is real
- Auth/RBAC/Entra cutover (P1.C / P1.J / P1.A / P1.F) — security comes after the app actually does its job.
- Scope-typo cleanup.
- Phase 3 monolith refactoring (still paused).
- MFA tier.
- Per-role denied-attempt counter.

---

## 7. Suggested next move

Pick **Tier 1**. It's the smallest effort with the largest payoff — flipping the hub from "observing" to "actually replacing Zetadocs for AP posting" is mostly a configuration + verification exercise, not a build. Once one batch posts cleanly, every subsequent sprint operates against a functioning baseline instead of scaffolding.

Reply with one of:
- **"Tier 1, sandbox batch"** — I prep a controlled batch of 10 ready-for-post AP docs, write the runbook, you click execute. No code change required for the batch itself; we'd add the unclassified triage pass alongside.
- **"Tier 2, sales pipeline diagnosis"** — I dig into why `hub-sales-intake@` isn't producing intake rows and walk one real customer PO end-to-end.
- **"Tier 3, outbound delivery POC"** — I build the smallest possible branded-PDF-on-BC-post-event POC.
- **"Tier 4, search UX"** — I build the unified document search page.
- **"All of Tier 1, then sequence"** — sequenced execution starting from the safest.

No more drift. Pick a tier and I move.
