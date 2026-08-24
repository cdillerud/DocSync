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
    if ($first -lt 0) { throw "0.22 patch anchor not found: $Label" }
    $second = $Text.IndexOf($Old, $first + $Old.Length, [System.StringComparison]::Ordinal)
    if ($second -ge 0) { throw "0.22 patch anchor is not unique: $Label" }
    return $Text.Substring(0, $first) + $New + $Text.Substring($first + $Old.Length)
}

function Save-PatchedFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )

    $backup = "$Path.pre-0.22.bak"
    if (-not (Test-Path -LiteralPath $backup)) {
        Copy-Item -LiteralPath $Path -Destination $backup -Force
    }
    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Patched: $Path" -ForegroundColor DarkGreen
}

$appJson = Join-Path $ProjectPath 'app.json'
$quoteTable = Join-Path $ProjectPath 'src\TableExtensions\GPISpiroQuote.TableExt.al'
$quoteCard = Join-Path $ProjectPath 'src\PageExtensions\GPISpiroQuoteCard.PageExt.al'
$permissionSet = Join-Path $ProjectPath 'src\PermissionSets\GPIPackagingCatalog.PermissionSet.al'
$queueTable = Join-Path $ProjectPath 'src\Tables\GPISpiroPushQueue.Table.al'
$queueMgt = Join-Path $ProjectPath 'src\Codeunits\GPISpiroPushMgt.Codeunit.al'
$queueApi = Join-Path $ProjectPath 'src\Pages\GPISpiroPushQueueAPI.Page.al'

foreach ($file in @($appJson, $quoteTable, $quoteCard, $permissionSet)) {
    if (-not (Test-Path -LiteralPath $file)) { throw "Required file not found: $file" }
}

Write-Step 'PRECHECK 0.21'
$app = Get-Content -LiteralPath $appJson -Raw | ConvertFrom-Json
if ([string]$app.version -ne '0.21.0.0') {
    throw "Expected local app version 0.21.0.0 before the 0.22 upgrade. Found $($app.version)."
}

$tableRaw = Get-Content -LiteralPath $quoteTable -Raw
$cardRaw = Get-Content -LiteralPath $quoteCard -Raw
if (-not $tableRaw.Contains('GPI Spiro Push Status')) { throw 'Expected 0.21 push-status field not found.' }
if (-not $cardRaw.Contains('GPI Spiro Last Pushed At')) { throw 'Expected 0.21 quote-card push fields not found.' }
if ((Test-Path -LiteralPath $queueTable) -or (Test-Path -LiteralPath $queueMgt) -or (Test-Path -LiteralPath $queueApi)) {
    throw '0.22 queued writeback objects already appear to exist.'
}

Write-Host '0.21 source precheck passed.' -ForegroundColor Green

Write-Step 'BUMP APP VERSION TO 0.22.0.0'
$appText = Get-Content -LiteralPath $appJson -Raw
$appText = Replace-Once -Text $appText -Old '"version": "0.21.0.0"' -New '"version": "0.22.0.0"' -Label 'app version'
Save-PatchedFile -Path $appJson -Content $appText

Write-Step 'CREATE SPIRO PUSH QUEUE TABLE'
$queueTableText = @'
table 71106 "GPI Spiro Push Queue"
{
    Caption = 'GPI Spiro Push Queue';
    DataClassification = CustomerContent;

    fields
    {
        field(1; "Entry No."; Integer)
        {
            Caption = 'Entry No.';
            AutoIncrement = true;
        }
        field(2; "Quote No."; Integer)
        {
            Caption = 'Quote No.';
        }
        field(3; "Spiro Opportunity ID"; Text[100])
        {
            Caption = 'Spiro Opportunity ID';
        }
        field(4; Status; Text[30])
        {
            Caption = 'Status';
        }
        field(5; "Requested At"; DateTime)
        {
            Caption = 'Requested At';
        }
        field(6; "Requested By"; Text[100])
        {
            Caption = 'Requested By';
        }
        field(7; "Processed At"; DateTime)
        {
            Caption = 'Processed At';
        }
        field(8; Message; Text[250])
        {
            Caption = 'Message';
        }
    }

    keys
    {
        key(PK; "Entry No.")
        {
            Clustered = true;
        }
        key(QuoteStatus; "Quote No.", Status)
        {
        }
    }
}
'@
[System.IO.File]::WriteAllText($queueTable, $queueTableText, [System.Text.UTF8Encoding]::new($false))
Write-Host "Created: $queueTable" -ForegroundColor DarkGreen

Write-Step 'CREATE QUEUE MANAGEMENT CODEUNIT'
$queueMgtText = @'
codeunit 71106 "GPI Spiro Push Mgt"
{
    procedure QueueQuoteLink(var Quote: Record "GPI Pack Quote")
    var
        PushQueue: Record "GPI Spiro Push Queue";
        ExistingQueue: Record "GPI Spiro Push Queue";
    begin
        Quote.TestField("GPI Spiro Opportunity ID");

        ExistingQueue.SetRange("Quote No.", Quote."Entry No.");
        ExistingQueue.SetRange(Status, 'Queued');
        if ExistingQueue.FindFirst() then
            Error('Packaging Quote %1 already has a queued Spiro writeback request.', Quote."Entry No.");

        if not Confirm(
            'Queue the Business Central link for Packaging Quote %1 to Spiro opportunity %2? The external Spiro integration worker will perform the write.',
            false,
            Quote."Entry No.",
            Quote."GPI Spiro Opportunity ID")
        then
            exit;

        PushQueue.Init();
        PushQueue."Quote No." := Quote."Entry No.";
        PushQueue."Spiro Opportunity ID" := Quote."GPI Spiro Opportunity ID";
        PushQueue.Status := 'Queued';
        PushQueue."Requested At" := CurrentDateTime();
        PushQueue."Requested By" := CopyStr(UserId(), 1, MaxStrLen(PushQueue."Requested By"));
        PushQueue.Message := 'Queued from Business Central for external Spiro writeback.';
        PushQueue.Insert(true);

        Quote."GPI Spiro Push Status" := 'Queued';
        Quote."GPI Spiro Push Message" := CopyStr(
            StrSubstNo('Queued request %1 for external Spiro writeback.', PushQueue."Entry No."),
            1,
            MaxStrLen(Quote."GPI Spiro Push Message"));
        Quote.Modify(true);
    end;
}
'@
[System.IO.File]::WriteAllText($queueMgt, $queueMgtText, [System.Text.UTF8Encoding]::new($false))
Write-Host "Created: $queueMgt" -ForegroundColor DarkGreen

Write-Step 'CREATE PUSH QUEUE API'
$queueApiText = @'
page 71109 "GPI Spiro Push Q API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'spiroIntegration';
    APIVersion = 'v1.0';
    Caption = 'spiroPushRequests';
    EntityName = 'spiroPushRequest';
    EntitySetName = 'spiroPushRequests';
    SourceTable = "GPI Spiro Push Queue";
    ODataKeyFields = SystemId;
    InsertAllowed = false;
    ModifyAllowed = true;
    DeleteAllowed = false;
    Extensible = false;

    layout
    {
        area(Content)
        {
            repeater(General)
            {
                field(id; Rec.SystemId)
                {
                    Caption = 'Id';
                    Editable = false;
                }
                field(entryNo; Rec."Entry No.")
                {
                    Caption = 'Entry No.';
                    Editable = false;
                }
                field(quoteNo; Rec."Quote No.")
                {
                    Caption = 'Quote No.';
                    Editable = false;
                }
                field(spiroOpportunityId; Rec."Spiro Opportunity ID")
                {
                    Caption = 'Spiro Opportunity ID';
                    Editable = false;
                }
                field(status; Rec.Status)
                {
                    Caption = 'Status';
                }
                field(requestedAt; Rec."Requested At")
                {
                    Caption = 'Requested At';
                    Editable = false;
                }
                field(requestedBy; Rec."Requested By")
                {
                    Caption = 'Requested By';
                    Editable = false;
                }
                field(processedAt; Rec."Processed At")
                {
                    Caption = 'Processed At';
                }
                field(message; Rec.Message)
                {
                    Caption = 'Message';
                }
            }
        }
    }
}
'@
[System.IO.File]::WriteAllText($queueApi, $queueApiText, [System.Text.UTF8Encoding]::new($false))
Write-Host "Created: $queueApi" -ForegroundColor DarkGreen

Write-Step 'ADD PUSH ACTION TO QUOTE CARD'
$text = Get-Content -LiteralPath $quoteCard -Raw
$anchor = @'
            action(RefreshSpiroContext)
'@
$replacement = @'
            action(PushQuoteLinkToSpiro)
            {
                ApplicationArea = All;
                Caption = 'Push Quote Link to Spiro';
                Image = SendTo;
                Enabled = Rec."GPI Spiro Opportunity ID" <> '';
                Promoted = true;
                PromotedCategory = Process;
                ToolTip = 'Queues this Business Central packaging quote link for the external Spiro integration worker. Spiro credentials remain outside Business Central.';

                trigger OnAction()
                var
                    SpiroPushMgt: Codeunit "GPI Spiro Push Mgt";
                begin
                    SpiroPushMgt.QueueQuoteLink(Rec);
                    CurrPage.Update(false);
                    Message('Spiro quote-link writeback request queued.');
                end;
            }
            action(RefreshSpiroContext)
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'Refresh Spiro Context action'
Save-PatchedFile -Path $quoteCard -Content $text

Write-Step 'ADD 0.22 PERMISSIONS'
$text = Get-Content -LiteralPath $permissionSet -Raw
$text = Replace-Once -Text $text -Old '        tabledata "GPI Spiro Opp Cache" = RIMD,' -New "        tabledata \"GPI Spiro Opp Cache\" = RIMD,`r`n        tabledata \"GPI Spiro Push Queue\" = RIMD," -Label 'Spiro queue tabledata permission'
$text = Replace-Once -Text $text -Old '        table "GPI Spiro Opp Cache" = X,' -New "        table \"GPI Spiro Opp Cache\" = X,`r`n        table \"GPI Spiro Push Queue\" = X," -Label 'Spiro queue table permission'
$text = Replace-Once -Text $text -Old '        page "GPI Spiro Opp API" = X,' -New "        page \"GPI Spiro Opp API\" = X,`r`n        page \"GPI Spiro Push Q API\" = X," -Label 'Spiro queue API permission'
$text = Replace-Once -Text $text -Old '        codeunit "GPI Spiro Link Mgt" = X;' -New "        codeunit \"GPI Spiro Link Mgt\" = X,`r`n        codeunit \"GPI Spiro Push Mgt\" = X;" -Label 'Spiro queue codeunit permission'
Save-PatchedFile -Path $permissionSet -Content $text

Write-Step 'VALIDATE 0.22 PATCH'
$checks = @(
    @{ Path = $appJson; Pattern = '"version": "0.22.0.0"'; Label = '0.22 app version' },
    @{ Path = $queueTable; Pattern = 'table 71106 "GPI Spiro Push Queue"'; Label = 'push queue table' },
    @{ Path = $queueMgt; Pattern = 'procedure QueueQuoteLink'; Label = 'queue management procedure' },
    @{ Path = $queueApi; Pattern = 'EntitySetName = ''spiroPushRequests'''; Label = 'push queue API' },
    @{ Path = $quoteCard; Pattern = "Caption = 'Push Quote Link to Spiro'"; Label = 'quote card push action' },
    @{ Path = $permissionSet; Pattern = 'tabledata "GPI Spiro Push Queue" = RIMD'; Label = 'queue tabledata permission' },
    @{ Path = $permissionSet; Pattern = 'codeunit "GPI Spiro Push Mgt" = X'; Label = 'queue codeunit permission' }
)

foreach ($check in $checks) {
    $raw = Get-Content -LiteralPath $check.Path -Raw
    if ($raw -notmatch $check.Pattern) { throw "Validation failed: $($check.Label)" }
    Write-Host "PASS: $($check.Label)" -ForegroundColor Green
}

Write-Host "`n0.22 queued Spiro writeback workflow patch applied successfully." -ForegroundColor Green
Write-Host 'No publish or deployment was performed.' -ForegroundColor Yellow
Write-Host 'BC now queues writeback requests; outbound Spiro credentials and API writes remain outside AL.' -ForegroundColor Cyan
Write-Host 'Next: run the normal GPI Packaging Catalog build.' -ForegroundColor Cyan
