# Charlie Demo Runbook

## Purpose

Demonstrate the current Business Central packaging workflow using a clean, real-data-backed scenario in `Sandbox_NoZetadocs_UAT`.

The prepared demo quote is intentionally left in Draft and Not Evaluated status so the guardrail decision can be shown live.

## Prepared demo quote

- Quote No.: 66
- Customer: WAT / Watkins Inc.
- Product: FG10900B
- Description: Watkins 4oz Spice Bottle Commercial Review
- Quantity: 10
- UOM: M
- Landed Cost per Unit: 91.92
- Proposed Sell Price per Unit: 131.94
- Target Gross Margin %: 13
- Calculated Gross Margin %: 30.33197
- Guardrail Status before demo: Not Evaluated
- Audit Entries before demo: 0

## Historical pricing context

The setup script verified exact posted sales history for WAT + FG10900B + M through 2026-08-19.

- Exact history lines: 74
- Recent-5 median sell price: 146.60
- Proposed sell price: 131.94
- Variance from recent median: -10.00%

Expected guardrail after evaluation: `Below Customer History`

Expected approval requirement: Yes

## Live demo sequence

1. Open `GPI Packaging Quotes` and open Quote 66.
2. Point out that the quote is Draft and that the line is Not Evaluated.
3. Review the commercial inputs: customer, item, quantity, M UOM, landed cost, proposed sell, target margin, and calculated GP.
4. Click `Run Guardrail Evaluation`.
5. Confirm the completion message reports 1 of 1 line requiring approval.
6. Show that the line now reads `Below Customer History` and `Needs Approval` is selected.
7. Open `Show/Hide Review Details` and show the historical pricing evidence: 74 exact lines, 146.60 recent-5 median, and -10.00% variance.
8. Show the Commercial Review status as `Approval required`.
9. Click `Ready for Review` and show that the quote becomes `Ready, approval required`.
10. Enter an approval note that describes the business reason for accepting the exception.
11. Click `Approve Quote`.
12. Show the final Approved status, Decision By, Decision At, and the Approval and Audit History entries.

## Talking points

- Business Central is applying deterministic pricing and margin rules. AI is not setting the customer price.
- The user chooses the proposed sell price. BC evaluates it against landed cost, target margin, protected pricing rules, and customer-specific posted sales history.
- Historical pricing is review evidence only. It never replaces the user-entered sell price.
- The exact customer/item/UOM history is used so unlike pack sizes or units are not mixed into the comparison.
- The M UOM is normalized from the BC item UOM setup while preserving extended landed cost and proposed sell economics.
- A pricing exception remains visible through Ready for Review and requires an explicit approval decision.
- The final decision and the pricing evidence are preserved in the audit trail.

## Expected live results

After `Run Guardrail Evaluation`:

- Guardrail Status: Below Customer History
- Needs Approval: Yes
- Review Status: Approval required
- Customer History Lines: 74
- Customer History Median: 146.60
- Customer History Variance: -10.00%
- Calculated Gross Margin: approximately 30.33%
- Total Landed Cost: 919.20
- Total Proposed Sell: 1,319.40
- Gross Profit Total: 400.20

After `Ready for Review`:

- Status: Ready
- Review Status: Ready, approval required
- Approve Quote: enabled
- Reject Quote: enabled

After approval:

- Status: Approved
- Review Status: Approved
- Decision By: populated
- Decision At: populated
- Approval note: preserved
- Reopen Draft: enabled
- Guardrail evaluation actions: disabled

## Reset for another demo

Do not reuse an already evaluated or approved demo quote if a clean live evaluation is desired.

Run:

```powershell
$Worktree = "$env:USERPROFILE\Documents\DocSync-PackagingCatalog"
$AppPath  = "$Worktree\packaging-catalog-bc"

& "$AppPath\scripts\New-GPICharlieDemoQuote.ps1"
```

The script verifies current protected-pricing rules and historical pricing before creating another clean Draft quote. If setup fails partway through, it removes the partial quote.

## Safety

- UAT only: `Sandbox_NoZetadocs_UAT`
- Do not publish or run this demo setup against Production.
- Do not merge this packaging branch into `main` as part of the demo.
- Do not modify the Zetadocs replacement extension for this demo.
