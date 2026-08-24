[CmdletBinding()]
param(
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Step {
    param([Parameter(Mandatory)][string]$Text)
    Write-Host "`n== $Text ==" -ForegroundColor Cyan
}

function Replace-Once {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$Old,
        [Parameter(Mandatory)][string]$New,
        [Parameter(Mandatory)][string]$Label
    )

    $first = $Text.IndexOf($Old, [System.StringComparison]::Ordinal)
    if ($first -lt 0) {
        throw "0.20 patch anchor not found: $Label"
    }

    $second = $Text.IndexOf($Old, $first + $Old.Length, [System.StringComparison]::Ordinal)
    if ($second -ge 0) {
        throw "0.20 patch anchor is not unique: $Label"
    }

    return $Text.Substring(0, $first) + $New + $Text.Substring($first + $Old.Length)
}

function Save-PatchedFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )

    $backup = "$Path.pre-0.20.bak"
    if (-not (Test-Path -LiteralPath $backup)) {
        Copy-Item -LiteralPath $Path -Destination $backup -Force
    }

    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Patched: $Path" -ForegroundColor DarkGreen
}

$appJson = Join-Path $ProjectPath 'app.json'
$linkMgt = Join-Path $ProjectPath 'src\Codeunits\GPISpiroLinkMgt.Codeunit.al'
$quoteCard = Join-Path $ProjectPath 'src\PageExtensions\GPISpiroQuoteCard.PageExt.al'
$quoteApi = Join-Path $ProjectPath 'src\Pages\GPISpiroQuoteAPI.Page.al'

foreach ($file in @($appJson, $linkMgt, $quoteCard, $quoteApi)) {
    if (-not (Test-Path -LiteralPath $file)) {
        throw "Required file not found: $file"
    }
}

Write-Step 'PRECHECK 0.19'
$app = Get-Content -LiteralPath $appJson -Raw | ConvertFrom-Json
if ([string]$app.version -ne '0.19.0.0') {
    throw "Expected local app version 0.19.0.0 before the 0.20 upgrade. Found $($app.version)."
}

$linkRaw = Get-Content -LiteralPath $linkMgt -Raw
$cardRaw = Get-Content -LiteralPath $quoteCard -Raw
$apiRaw = Get-Content -LiteralPath $quoteApi -Raw

foreach ($marker in @(
    'GPI Spiro Assigned ISR',
    'GPI Spiro Est. Annual Volume',
    'GPI Spiro Close Date',
    'GPI Spiro Rating'
)) {
    if (-not $linkRaw.Contains($marker) -or -not $cardRaw.Contains($marker)) {
        throw "Expected 0.19 marker not found in local source: $marker"
    }
}

if ($linkRaw -match 'procedure RefreshLinkedOpportunity' -or $cardRaw -match 'Refresh Spiro Context') {
    throw '0.20 Spiro link lifecycle changes already appear to be present.'
}

Write-Host '0.19 source precheck passed.' -ForegroundColor Green

Write-Step 'BUMP APP VERSION TO 0.20.0.0'
$appText = Get-Content -LiteralPath $appJson -Raw
$appText = Replace-Once -Text $appText -Old '"version": "0.19.0.0"' -New '"version": "0.20.0.0"' -Label 'app version'
Save-PatchedFile -Path $appJson -Content $appText

Write-Step 'ADD REFRESH AND UNLINK LIFECYCLE TO SPIRO LINK MANAGEMENT'
$text = Get-Content -LiteralPath $linkMgt -Raw
$anchor = @'
    procedure LinkOpportunity(var Quote: Record "GPI Pack Quote"; Opportunity: Record "GPI Spiro Opp Cache")
'@
$replacement = @'
    procedure RefreshLinkedOpportunity(var Quote: Record "GPI Pack Quote")
    var
        Opportunity: Record "GPI Spiro Opp Cache";
    begin
        Quote.TestField("Customer No.");
        Quote.TestField("GPI Spiro Opportunity ID");
        Quote.CalcFields("GPI Spiro Company ID", "GPI Spiro Company Name");

        if Quote."GPI Spiro Company ID" = '' then
            Error('The quote customer is not mapped to a Spiro company.');

        if not Opportunity.Get(Quote."GPI Spiro Opportunity ID") then
            Error(
                'Linked Spiro opportunity %1 is not present in the local opportunity cache. Refresh the Spiro opportunity cache first.',
                Quote."GPI Spiro Opportunity ID");

        if Opportunity."Spiro Company ID" <> Quote."GPI Spiro Company ID" then
            Error(
                'Linked Spiro opportunity %1 belongs to company %2, but this quote customer is currently mapped to company %3. Re-select or unlink the opportunity before continuing.',
                Opportunity."Spiro Opportunity ID",
                Opportunity."Spiro Company ID",
                Quote."GPI Spiro Company ID");

        ApplyOpportunitySnapshot(Quote, Opportunity, false);
    end;

    procedure UnlinkOpportunity(var Quote: Record "GPI Pack Quote")
    var
        ExistingName: Text[100];
        ExistingId: Text[100];
    begin
        Quote.TestField("GPI Spiro Opportunity ID");

        ExistingName := Quote."GPI Spiro Opp. Name";
        ExistingId := Quote."GPI Spiro Opportunity ID";

        if not Confirm(
            'Remove the Spiro opportunity link from this packaging quote? Current link: %1 [%2].',
            false,
            ExistingName,
            ExistingId)
        then
            exit;

        Clear(Quote."GPI Spiro Opportunity ID");
        Clear(Quote."GPI Spiro Opp. Name");
        Clear(Quote."GPI Spiro Contact ID");
        Clear(Quote."GPI Spiro Contact Name");
        Clear(Quote."GPI Spiro Stage");
        Clear(Quote."GPI Spiro Owner");
        Clear(Quote."GPI Spiro Assigned ISR");
        Clear(Quote."GPI Spiro Probability");
        Clear(Quote."GPI Spiro Est. Annual Volume");
        Clear(Quote."GPI Spiro Close Date");
        Clear(Quote."GPI Spiro Rating");
        Clear(Quote."GPI Spiro Opp. URL");
        Clear(Quote."GPI Spiro Synced At");
        Clear(Quote."GPI Spiro Synced By");
        Quote.Modify(true);
    end;

    procedure LinkOpportunity(var Quote: Record "GPI Pack Quote"; Opportunity: Record "GPI Spiro Opp Cache")
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'LinkOpportunity procedure anchor'

$oldAssignments = @'
        Quote."GPI Spiro Opportunity ID" := Opportunity."Spiro Opportunity ID";
        Quote."GPI Spiro Opp. Name" := Opportunity."Opportunity Name";
        Quote."GPI Spiro Stage" := Opportunity.Stage;
        Quote."GPI Spiro Owner" := Opportunity.Owner;
        Quote."GPI Spiro Assigned ISR" := Opportunity."Assigned ISR";
        Quote."GPI Spiro Probability" := Opportunity.Probability;
        Quote."GPI Spiro Est. Annual Volume" := Opportunity."Estimated Annual Volume";
        Quote."GPI Spiro Close Date" := Opportunity."Close Date";
        Quote."GPI Spiro Rating" := Opportunity.Rating;
        Quote."GPI Spiro Opp. URL" := Opportunity."Browser URL";

        if ChangingOpportunity then begin
            Clear(Quote."GPI Spiro Contact ID");
            Clear(Quote."GPI Spiro Contact Name");
        end;

        Quote."GPI Spiro Synced At" := CurrentDateTime();
        Quote."GPI Spiro Synced By" := CopyStr(UserId(), 1, MaxStrLen(Quote."GPI Spiro Synced By"));
        Quote.Modify(true);
    end;
}
'@
$newAssignments = @'
        ApplyOpportunitySnapshot(Quote, Opportunity, ChangingOpportunity);
    end;

    local procedure ApplyOpportunitySnapshot(var Quote: Record "GPI Pack Quote"; Opportunity: Record "GPI Spiro Opp Cache"; ClearContact: Boolean)
    begin
        Quote."GPI Spiro Opportunity ID" := Opportunity."Spiro Opportunity ID";
        Quote."GPI Spiro Opp. Name" := Opportunity."Opportunity Name";
        Quote."GPI Spiro Stage" := Opportunity.Stage;
        Quote."GPI Spiro Owner" := Opportunity.Owner;
        Quote."GPI Spiro Assigned ISR" := Opportunity."Assigned ISR";
        Quote."GPI Spiro Probability" := Opportunity.Probability;
        Quote."GPI Spiro Est. Annual Volume" := Opportunity."Estimated Annual Volume";
        Quote."GPI Spiro Close Date" := Opportunity."Close Date";
        Quote."GPI Spiro Rating" := Opportunity.Rating;
        Quote."GPI Spiro Opp. URL" := Opportunity."Browser URL";

        if ClearContact then begin
            Clear(Quote."GPI Spiro Contact ID");
            Clear(Quote."GPI Spiro Contact Name");
        end;

        Quote."GPI Spiro Synced At" := CurrentDateTime();
        Quote."GPI Spiro Synced By" := CopyStr(UserId(), 1, MaxStrLen(Quote."GPI Spiro Synced By"));
        Quote.Modify(true);
    end;
}
'@
$text = Replace-Once -Text $text -Old $oldAssignments -New $newAssignments -Label 'link snapshot assignment block'
Save-PatchedFile -Path $linkMgt -Content $text

Write-Step 'ADD QUOTE CARD LIFECYCLE ACTIONS'
$text = Get-Content -LiteralPath $quoteCard -Raw
$anchor = @'
            action(OpenSpiroOpportunity)
'@
$replacement = @'
            action(RefreshSpiroContext)
            {
                ApplicationArea = All;
                Caption = 'Refresh Spiro Context';
                Image = Refresh;
                Enabled = Rec."GPI Spiro Opportunity ID" <> '';
                Promoted = true;
                PromotedCategory = Process;
                ToolTip = 'Refreshes the linked Spiro opportunity snapshot on this quote from the latest Business Central Spiro opportunity cache. No Spiro write is performed.';

                trigger OnAction()
                var
                    SpiroLinkMgt: Codeunit "GPI Spiro Link Mgt";
                begin
                    SpiroLinkMgt.RefreshLinkedOpportunity(Rec);
                    CurrPage.Update(false);
                    Message('Spiro context refreshed from the local opportunity cache.');
                end;
            }
            action(UnlinkSpiroOpportunity)
            {
                ApplicationArea = All;
                Caption = 'Unlink Spiro Opportunity';
                Image = RemoveLine;
                Enabled = Rec."GPI Spiro Opportunity ID" <> '';
                Promoted = true;
                PromotedCategory = Process;
                ToolTip = 'Removes the Spiro opportunity link and its cached CRM snapshot from this packaging quote. It does not delete or modify the Spiro opportunity.';

                trigger OnAction()
                var
                    SpiroLinkMgt: Codeunit "GPI Spiro Link Mgt";
                begin
                    SpiroLinkMgt.UnlinkOpportunity(Rec);
                    CurrPage.Update(false);
                end;
            }
            action(OpenSpiroOpportunity)
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'Open Spiro Opportunity action'
Save-PatchedFile -Path $quoteCard -Content $text

Write-Step 'EXPOSE FULL 0.19 SPIRO SNAPSHOT THROUGH QUOTE LINK API'
$text = Get-Content -LiteralPath $quoteApi -Raw
$anchor = @'
                field(spiroOwner; Rec."GPI Spiro Owner")
                {
                    Caption = 'Spiro Owner';
                }
'@
$replacement = $anchor + @'
                field(spiroAssignedIsr; Rec."GPI Spiro Assigned ISR")
                {
                    Caption = 'Spiro Assigned ISR';
                    Editable = false;
                }
                field(spiroProbability; Rec."GPI Spiro Probability")
                {
                    Caption = 'Spiro Probability';
                    Editable = false;
                }
                field(spiroEstimatedAnnualVolume; Rec."GPI Spiro Est. Annual Volume")
                {
                    Caption = 'Spiro Estimated Annual Volume';
                    Editable = false;
                }
                field(spiroCloseDate; Rec."GPI Spiro Close Date")
                {
                    Caption = 'Spiro Close Date';
                    Editable = false;
                }
                field(spiroRating; Rec."GPI Spiro Rating")
                {
                    Caption = 'Spiro Rating';
                    Editable = false;
                }
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'quote API Spiro owner field'
Save-PatchedFile -Path $quoteApi -Content $text

Write-Step 'VALIDATE 0.20 PATCH'
$checks = @(
    @{ Path = $appJson; Pattern = '"version": "0.20.0.0"'; Label = '0.20 app version' },
    @{ Path = $linkMgt; Pattern = 'procedure RefreshLinkedOpportunity'; Label = 'refresh linked opportunity procedure' },
    @{ Path = $linkMgt; Pattern = 'procedure UnlinkOpportunity'; Label = 'unlink opportunity procedure' },
    @{ Path = $linkMgt; Pattern = 'local procedure ApplyOpportunitySnapshot'; Label = 'shared snapshot procedure' },
    @{ Path = $quoteCard; Pattern = "Caption = 'Refresh Spiro Context'"; Label = 'refresh quote action' },
    @{ Path = $quoteCard; Pattern = "Caption = 'Unlink Spiro Opportunity'"; Label = 'unlink quote action' },
    @{ Path = $quoteApi; Pattern = 'field\(spiroAssignedIsr;'; Label = 'quote API Assigned ISR' },
    @{ Path = $quoteApi; Pattern = 'field\(spiroCloseDate;'; Label = 'quote API Close Date' }
)

foreach ($check in $checks) {
    $raw = Get-Content -LiteralPath $check.Path -Raw
    if ($raw -notmatch $check.Pattern) {
        throw "Validation failed: $($check.Label)"
    }
    Write-Host "PASS: $($check.Label)" -ForegroundColor Green
}

Write-Host "`n0.20 Spiro quote link lifecycle patch applied successfully." -ForegroundColor Green
Write-Host 'No publish or deployment was performed.' -ForegroundColor Yellow
Write-Host 'Scope: refresh linked context from cache, unlink safely, and expose the full CRM snapshot through the quote-link API.' -ForegroundColor Cyan
Write-Host 'No outbound Spiro write is introduced in this slice.' -ForegroundColor Cyan
Write-Host 'Next: run the normal GPI Packaging Catalog build.' -ForegroundColor Cyan
