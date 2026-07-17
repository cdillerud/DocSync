[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedProductionVersion = "0.27.0.4"
$ExpectedTestVersion = "0.8.0.4"
$NewProductionVersion = "0.27.0.5"
$NewTestVersion = "0.8.0.5"

$ProductionRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests"

$ProductionAppJson = Join-Path $ProductionRoot "app.json"
$TestAppJson = Join-Path $TestRoot "app.json"
$ChangeLog = Join-Path $ProductionRoot "CHANGELOG.md"
$BuildScript = Join-Path $RepoRoot "scripts\Prepare-GPIALTests.ps1"
$PostedSalesInvoicesPageExt = Join-Path $ProductionRoot "src\pageextension\GPIPostedSalesInvoices.PageExt.al"
$NewOptionsPagePath = Join-Path $ProductionRoot "src\page\GPIEODInvoiceBatchOptions.Page.al"

$RequiredPaths = @(
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLog,
    $BuildScript,
    $PostedSalesInvoicesPageExt
)

foreach ($RequiredPath in $RequiredPaths) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required path was not found: $RequiredPath"
    }
}

if (Test-Path -LiteralPath $NewOptionsPagePath) {
    throw "The EOD invoice batch options page already exists: $NewOptionsPagePath. No files were changed."
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )

    $Encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $Encoding)
}

function Write-JsonNoBom {
    param(
        [Parameter(Mandatory)][object]$Value,
        [Parameter(Mandatory)][string]$Path
    )

    $Json = $Value | ConvertTo-Json -Depth 100
    Write-Utf8NoBom -Path $Path -Content ($Json + [Environment]::NewLine)
}

function Get-LineEnding {
    param([Parameter(Mandatory)][string]$Content)

    if ($Content.Contains("`r`n")) {
        return "`r`n"
    }

    return "`n"
}

function Replace-ActionByName {
    param(
        [Parameter(Mandatory)][string]$Content,
        [Parameter(Mandatory)][string]$ActionName,
        [Parameter(Mandatory)][string]$ReplacementAction
    )

    $LineEnding = Get-LineEnding -Content $Content
    $Lines = [System.Collections.Generic.List[string]]::new()

    foreach ($Line in [regex]::Split($Content, "`r?`n")) {
        $Lines.Add($Line)
    }

    $StartIndexes = @()
    for ($Index = 0; $Index -lt $Lines.Count; $Index++) {
        if ($Lines[$Index] -match "^\s*action\($([regex]::Escape($ActionName))\)\s*$") {
            $StartIndexes += $Index
        }
    }

    if ($StartIndexes.Count -ne 1) {
        throw "Expected exactly one action named $ActionName, but found $($StartIndexes.Count). No files were changed."
    }

    $StartIndex = $StartIndexes[0]
    $Depth = 0
    $Started = $false
    $EndIndex = -1

    for ($Index = $StartIndex; $Index -lt $Lines.Count; $Index++) {
        $Line = $Lines[$Index]

        for ($CharIndex = 0; $CharIndex -lt $Line.Length; $CharIndex++) {
            $Char = $Line[$CharIndex]
            if ($Char -eq '{') {
                $Depth++
                $Started = $true
            }
            elseif ($Char -eq '}') {
                if ($Started) {
                    $Depth--
                    if ($Depth -eq 0) {
                        $EndIndex = $Index
                        break
                    }
                }
            }
        }

        if ($EndIndex -ge 0) {
            break
        }
    }

    if ($EndIndex -lt $StartIndex) {
        throw "Could not find the end of action $ActionName. No files were changed."
    }

    $ReplacementLines = [regex]::Split($ReplacementAction.Trim("`r", "`n"), "`r?`n")
    $Output = [System.Collections.Generic.List[string]]::new()

    for ($Index = 0; $Index -lt $StartIndex; $Index++) {
        $Output.Add($Lines[$Index])
    }

    foreach ($Line in $ReplacementLines) {
        $Output.Add($Line)
    }

    for ($Index = $EndIndex + 1; $Index -lt $Lines.Count; $Index++) {
        $Output.Add($Lines[$Index])
    }

    return ($Output -join $LineEnding)
}

function Pick-AvailableObjectId {
    param(
        [Parameter(Mandatory)][string]$RootPath,
        [Parameter(Mandatory)][int[]]$Candidates
    )

    $UsedIds = New-Object "System.Collections.Generic.HashSet[int]"

    Get-ChildItem -LiteralPath $RootPath -Recurse -File -Filter "*.al" |
        ForEach-Object {
            $Text = Get-Content -LiteralPath $_.FullName -Raw
            foreach ($Match in [regex]::Matches($Text, '(?im)^\s*(page|pageextension|table|tableextension|codeunit|report|reportextension|xmlport|query|enum|enumextension|permissionset|permissionsetextension|controladdin)\s+(\d+)\b')) {
                [void]$UsedIds.Add([int]$Match.Groups[2].Value)
            }
        }

    foreach ($Candidate in $Candidates) {
        if (-not $UsedIds.Contains($Candidate)) {
            return $Candidate
        }
    }

    throw "No available object ID was found in candidate list: $($Candidates -join ', '). No files were changed."
}

function Find-BasePermissionSetFile {
    param([Parameter(Mandatory)][string]$RootPath)

    $Matches = @(
        Get-ChildItem -LiteralPath (Join-Path $RootPath "src") -Recurse -File -Filter "*.al" |
            Where-Object {
                $Text = Get-Content -LiteralPath $_.FullName -Raw
                $Text -match 'permissionset\s+70510\s+"GPI DOC EMAIL"'
            }
    )

    if ($Matches.Count -ne 1) {
        throw "Expected exactly one GPI DOC EMAIL permission set file, but found $($Matches.Count). No files were changed."
    }

    return $Matches[0].FullName
}

$ProductionApp = Get-Content -LiteralPath $ProductionAppJson -Raw | ConvertFrom-Json
$TestApp = Get-Content -LiteralPath $TestAppJson -Raw | ConvertFrom-Json

if ([string]$ProductionApp.version -ne $ExpectedProductionVersion) {
    throw "Expected production version $ExpectedProductionVersion, but found $($ProductionApp.version). No files were changed."
}

if ([string]$TestApp.version -ne $ExpectedTestVersion) {
    throw "Expected test version $ExpectedTestVersion, but found $($TestApp.version). No files were changed."
}

$MainDependency = @(
    $TestApp.dependencies |
        Where-Object { [string]$_.id -eq [string]$ProductionApp.id }
)

if ($MainDependency.Count -ne 1) {
    throw "Expected exactly one test dependency on production app $($ProductionApp.id), but found $($MainDependency.Count). No files were changed."
}

$OptionsPageObjectId = Pick-AvailableObjectId -RootPath $ProductionRoot -Candidates @(70649, 70648, 70647, 70646, 70645, 70644, 70643, 70642, 70641, 70640)
$PermissionSetPath = Find-BasePermissionSetFile -RootPath $ProductionRoot

$OriginalProductionAppJson = Get-Content -LiteralPath $ProductionAppJson -Raw
$OriginalTestAppJson = Get-Content -LiteralPath $TestAppJson -Raw
$OriginalChangeLog = Get-Content -LiteralPath $ChangeLog -Raw
$OriginalPostedSalesInvoices = Get-Content -LiteralPath $PostedSalesInvoicesPageExt -Raw
$OriginalPermissionSet = Get-Content -LiteralPath $PermissionSetPath -Raw

if ($OriginalPostedSalesInvoices -notmatch 'action\(GPIOpenEndOfDayInvoiceBatch\)') {
    throw "The Gamer EOD Invoice Batch action was not found. Publish/build 0.27.0.4 first, then rerun this script. No files were changed."
}

if ($OriginalPostedSalesInvoices -notmatch 'SalesInvoiceHeader\.SetRange\("Posting Date", Today\);') {
    throw "The existing EOD invoice action no longer appears to be the hard-coded Today version. No files were changed."
}

$NewEodAction = @'
            action(GPIOpenEndOfDayInvoiceBatch)
            {
                ApplicationArea = All;
                Caption = 'Gamer EOD Invoice Batch';
                Image = SendMail;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;
                ToolTip = 'Opens the Gamer posted invoice queue filtered by selected Posting Date range and Amount not equal to zero.';

                trigger OnAction()
                var
                    SalesInvoiceHeader: Record "Sales Invoice Header";
                    EODOptions: Page "GPI EOD Invoice Batch Options";
                    PostingDateFrom: Date;
                    PostingDateTo: Date;
                begin
                    EODOptions.SetDefaultPostingDate(WorkDate());
                    if EODOptions.RunModal() <> Action::OK then
                        exit;

                    EODOptions.GetPostingDateFilter(PostingDateFrom, PostingDateTo);
                    if (PostingDateFrom = 0D) and (PostingDateTo = 0D) then
                        Error('Enter at least one Posting Date filter value.');

                    if (PostingDateFrom <> 0D) and (PostingDateTo <> 0D) and (PostingDateTo < PostingDateFrom) then
                        Error('Posting Date To cannot be before Posting Date From.');

                    if (PostingDateFrom <> 0D) and (PostingDateTo <> 0D) then
                        SalesInvoiceHeader.SetRange("Posting Date", PostingDateFrom, PostingDateTo)
                    else
                        if PostingDateFrom <> 0D then
                            SalesInvoiceHeader.SetFilter("Posting Date", '%1..', PostingDateFrom)
                        else
                            SalesInvoiceHeader.SetFilter("Posting Date", '..%1', PostingDateTo);

                    SalesInvoiceHeader.SetFilter(Amount, '<>0');
                    Page.Run(Page::"GPI Posted Invoice Queue", SalesInvoiceHeader);
                end;
            }
'@

$UpdatedPostedSalesInvoices = Replace-ActionByName `
    -Content $OriginalPostedSalesInvoices `
    -ActionName "GPIOpenEndOfDayInvoiceBatch" `
    -ReplacementAction $NewEodAction

$OptionsPageSource = @"
page $OptionsPageObjectId "GPI EOD Invoice Batch Options"
{
    Caption = 'Gamer EOD Invoice Batch Options';
    PageType = StandardDialog;
    ApplicationArea = All;

    layout
    {
        area(Content)
        {
            group(Options)
            {
                Caption = 'Invoice Filters';

                field(PostingDateFrom; PostingDateFrom)
                {
                    ApplicationArea = All;
                    Caption = 'Posting Date From';
                    ToolTip = 'Specifies the first posted sales invoice Posting Date to include. Leave blank to include everything through Posting Date To.';
                }

                field(PostingDateTo; PostingDateTo)
                {
                    ApplicationArea = All;
                    Caption = 'Posting Date To';
                    ToolTip = 'Specifies the last posted sales invoice Posting Date to include. Leave blank to include everything from Posting Date From forward.';
                }

                field(AmountFilterDescription; AmountFilterDescription)
                {
                    ApplicationArea = All;
                    Caption = 'Amount Filter';
                    Editable = false;
                    ToolTip = 'The end-of-day invoice batch always filters Amount not equal to zero.';
                }
            }
        }
    }

    trigger OnOpenPage()
    begin
        if PostingDateFrom = 0D then
            PostingDateFrom := WorkDate();

        if PostingDateTo = 0D then
            PostingDateTo := PostingDateFrom;

        AmountFilterDescription := 'Amount <> 0';
    end;

    procedure SetDefaultPostingDate(DefaultPostingDate: Date)
    begin
        PostingDateFrom := DefaultPostingDate;
        PostingDateTo := DefaultPostingDate;
    end;

    procedure GetPostingDateFilter(var DateFrom: Date; var DateTo: Date)
    begin
        DateFrom := PostingDateFrom;
        DateTo := PostingDateTo;
    end;

    var
        PostingDateFrom: Date;
        PostingDateTo: Date;
        AmountFilterDescription: Text[30];
}
"@

if ($OriginalPermissionSet -match 'page\s+"GPI EOD Invoice Batch Options"\s*=\s*X') {
    throw "The GPI EOD Invoice Batch Options page is already present in the permission set. No files were changed."
}

if ($OriginalPermissionSet -notmatch 'page\s+"GPI Posted Invoice Queue"\s*=\s*X,') {
    throw "Could not find the GPI Posted Invoice Queue permission line. No files were changed."
}

$UpdatedPermissionSet = [regex]::Replace(
    $OriginalPermissionSet,
    '(page\s+"GPI Posted Invoice Queue"\s*=\s*X,\s*)',
    "`${1}        page ""GPI EOD Invoice Batch Options"" = X,`r`n",
    1)

$ProductionApp.version = $NewProductionVersion
$TestApp.version = $NewTestVersion
$MainDependency[0].version = $NewProductionVersion

$ChangeLogEntry = @"
## $NewProductionVersion

### Changed
- Gamer EOD Invoice Batch now prompts for a Posting Date range instead of always filtering to today.
- The default date range is still Work Date to Work Date to match normal end-of-day usage.
- Amount <> 0 remains enforced automatically.

### Safety
- No invoice recipient resolution, sender account, PDF generation, Delivery Log, archive, routing-rule, or send logic was changed.
- No package is published automatically.
- Publish only to Sandbox_5_5_2026 unless Chad explicitly approves another environment.

"@

if ($OriginalChangeLog -match '(?m)^# Changelog\s*$') {
    $UpdatedChangeLog = [regex]::Replace(
        $OriginalChangeLog,
        '(?m)^# Changelog\s*$',
        "# Changelog`r`n`r`n$ChangeLogEntry",
        1
    )
}
else {
    throw "The changelog header was not found. No files were changed."
}

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $RepoRoot ".gpi-backups\eod-invoice-date-filter-027005-$Timestamp"
New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

$FilesToBackup = @(
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLog,
    $PostedSalesInvoicesPageExt,
    $PermissionSetPath
)

foreach ($Path in $FilesToBackup) {
    $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
    $BackupPath = Join-Path $BackupRoot $RelativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $BackupPath) -Force | Out-Null
    Copy-Item -LiteralPath $Path -Destination $BackupPath -Force
}

$ProductionPackage = Join-Path $ProductionRoot "Gamer Packaging_GPI Sales Document Email_$NewProductionVersion.app"
$TestPackage = Join-Path $TestRoot "Gamer Packaging_GPI Sales Document Email Tests_$NewTestVersion.app"

try {
    Write-Utf8NoBom -Path $PostedSalesInvoicesPageExt -Content $UpdatedPostedSalesInvoices
    Write-Utf8NoBom -Path $NewOptionsPagePath -Content $OptionsPageSource
    Write-Utf8NoBom -Path $PermissionSetPath -Content $UpdatedPermissionSet
    Write-JsonNoBom -Value $ProductionApp -Path $ProductionAppJson
    Write-JsonNoBom -Value $TestApp -Path $TestAppJson
    Write-Utf8NoBom -Path $ChangeLog -Content $UpdatedChangeLog

    if (Test-Path -LiteralPath $ProductionPackage) {
        Remove-Item -LiteralPath $ProductionPackage -Force
    }

    if (Test-Path -LiteralPath $TestPackage) {
        Remove-Item -LiteralPath $TestPackage -Force
    }

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host " GPI EOD invoice date filter 0.27.0.5" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Production version: $NewProductionVersion"
    Write-Host "Test version:       $NewTestVersion"
    Write-Host "Options page ID:    $OptionsPageObjectId"
    Write-Host "Backup:             $BackupRoot"
    Write-Host ""
    Write-Host "Running production and test builds..." -ForegroundColor Cyan

    & $BuildScript

    if (-not (Test-Path -LiteralPath $ProductionPackage)) {
        throw "The expected production package was not created: $ProductionPackage"
    }

    if (-not (Test-Path -LiteralPath $TestPackage)) {
        throw "The expected test package was not created: $TestPackage"
    }
}
catch {
    Write-Host ""
    Write-Host "The EOD invoice date-filter build failed. Restoring all modified files." -ForegroundColor Red

    foreach ($Path in $FilesToBackup) {
        $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
        $BackupPath = Join-Path $BackupRoot $RelativePath
        Copy-Item -LiteralPath $BackupPath -Destination $Path -Force
    }

    if (Test-Path -LiteralPath $NewOptionsPagePath) {
        Remove-Item -LiteralPath $NewOptionsPagePath -Force
    }

    if (Test-Path -LiteralPath $ProductionPackage) {
        Remove-Item -LiteralPath $ProductionPackage -Force
    }

    if (Test-Path -LiteralPath $TestPackage) {
        Remove-Item -LiteralPath $TestPackage -Force
    }

    throw
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " GPI 0.27.0.5 build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Backup:             $BackupRoot"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish both packages only to Sandbox_5_5_2026, refresh the Testing panel, and run the complete test suite." -ForegroundColor Yellow
