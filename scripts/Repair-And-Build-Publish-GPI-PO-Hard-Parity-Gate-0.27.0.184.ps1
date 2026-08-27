#requires -Version 7.0
<#
.SYNOPSIS
Repairs the local .184 PO recipient hard-gate page state if a prior guarded build
left app.json at .184 without the RunHardParityGate action, then runs the existing
guarded .184 builder/publisher.

.DESCRIPTION
Safety:
- Local delivery worktree only.
- Expected branch feature/phase-3-record-documents.
- Sandbox_08142026_GamerDocs only through the downstream guarded publisher.
- No Git reset / clean / checkout.
- Targeted backup + automatic restore on any failure before successful downstream completion.
#>

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot       = 'C:\Users\ChadDillerud\Documents\DocSync-Zetadocs'
$ExpectedBranch = 'feature/phase-3-record-documents'
$AppRoot        = Join-Path $RepoRoot 'bc-extension\zetadocs-replacement'
$SrcRoot        = Join-Path $AppRoot 'src'
$AppJson        = Join-Path $AppRoot 'app.json'
$AuditPage      = Join-Path $SrcRoot 'page\GPIPOBucketEvidenceAudit.Page.al'
$SourceVersion  = '0.27.0.183'
$TargetVersion  = '0.27.0.184'
$ToolingCommit  = 'b929f7f57299400d9e54a808f9ebfc49ade18ff8'
$BuilderUrl     = "https://raw.githubusercontent.com/cdillerud/DocSync/$ToolingCommit/scripts/Build-Publish-GPI-PO-Recipient-Hard-Parity-Gate-0.27.0.184.ps1"
$TempBuilder    = Join-Path $env:TEMP ('Build-Publish-GPI-PO-Recipient-Hard-Parity-Gate-0.27.0.184-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.ps1')
$BackupRoot     = Join-Path $RepoRoot ('.gpi-backups\repair-po-hard-gate-state-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))

function Section([string]$Title) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

function Read-Text([string]$Path) { [System.IO.File]::ReadAllText($Path) }
function Write-Text([string]$Path,[string]$Text) { [System.IO.File]::WriteAllText($Path,$Text,[System.Text.UTF8Encoding]::new($false)) }
function Find-MatchingBrace {
    param([Parameter(Mandatory)][string]$Text,[Parameter(Mandatory)][int]$OpenBraceIndex)
    $depth = 0
    for ($i = $OpenBraceIndex; $i -lt $Text.Length; $i++) {
        switch ($Text[$i]) {
            '{' { $depth++ }
            '}' { $depth--; if ($depth -eq 0) { return $i } }
        }
    }
    return -1
}

$ActionInsert = @'
        action(RunHardParityGate)
        {
            ApplicationArea = All;
            Caption = 'Run Hard Parity Gate';
            Image = TestReport;
            ToolTip = 'Rebuilds exact retained Production PO recipient evidence and fails if any available sandbox Purchase Header resolves to different To/CC/BCC buckets. Missing sandbox source records are reported separately as fixture risks.';

            trigger OnAction()
            var
                AuditMgt: Codeunit "GPI PO Bucket Audit Mgt";
                MatchCount: Integer;
                FixtureRiskCount: Integer;
                BlockerCount: Integer;
                BlockerDetail: Text;
            begin
                AuditMgt.BuildAudit(Rec);
                MatchCount := 0;
                FixtureRiskCount := 0;
                BlockerCount := 0;
                Clear(BlockerDetail);
                Rec.Reset();
                if Rec.FindSet() then
                    repeat
                        case Rec.Result of
                            'MATCH': MatchCount += 1;
                            'SOURCE NOT FOUND': FixtureRiskCount += 1;
                            else begin
                                BlockerCount += 1;
                                if BlockerDetail = '' then
                                    BlockerDetail := CopyStr(StrSubstNo('%1 %2: %3',Rec."PO No.",Rec."Vendor No.",Rec.Result),1,MaxStrLen(BlockerDetail));
                            end;
                        end;
                    until Rec.Next() = 0;
                CurrPage.Update(false);
                if BlockerCount > 0 then
                    Error('PO RECIPIENT PARITY BLOCKER: %1 source-found audit row(s) failed exact Production To/CC/BCC comparison. First failure: %2. Exact matches: %3. Missing sandbox fixtures: %4.',BlockerCount,BlockerDetail,MatchCount,FixtureRiskCount);
                Message('PO RECIPIENT PARITY GATE PASS. Exact source-found resolver matches: %1. Missing sandbox fixtures (risk only): %2. No source-found To/CC/BCC mismatches.',MatchCount,FixtureRiskCount);
            end;
        }

'@

Section '1. HARD SAFETY / LOCAL STATE'
foreach ($Path in @($RepoRoot,$AppRoot,$AppJson,$AuditPage)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Required path missing: $Path" }
}
$Branch = (& git -C $RepoRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Could not determine current Git branch.' }
if ($Branch -ne $ExpectedBranch) { throw "Expected branch '$ExpectedBranch', found '$Branch'." }
$App = Get-Content -LiteralPath $AppJson -Raw | ConvertFrom-Json
if ([string]$App.version -notin @($SourceVersion,$TargetVersion)) { throw "Expected local version $SourceVersion or $TargetVersion, found $($App.version)." }
Write-Host "Repo       : $RepoRoot"
Write-Host "Branch     : $Branch"
Write-Host "Version    : $($App.version)"
Write-Host 'Production : NOT TOUCHED' -ForegroundColor Green
Write-Host 'Git        : no reset / clean / checkout'

Section '2. TARGETED BACKUP'
New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null
Copy-Item -LiteralPath $AppJson -Destination (Join-Path $BackupRoot 'app.json') -Force
Copy-Item -LiteralPath $AuditPage -Destination (Join-Path $BackupRoot 'GPIPOBucketEvidenceAudit.Page.al') -Force
Write-Host "Backup : $BackupRoot"

try {
    Section '3. NORMALIZE LOCAL .184 HARD-GATE SOURCE STATE'
    $Page = Read-Text $AuditPage
    if (-not $Page.Contains('action(RunHardParityGate)')) {
        $actionsMatch = [regex]::Match($Page,'(?m)^\s*actions\s*$')
        if (-not $actionsMatch.Success) { throw 'Could not locate actions block in GPI PO Bucket Evidence Audit page.' }
        $openBrace = $Page.IndexOf('{',$actionsMatch.Index + $actionsMatch.Length)
        if ($openBrace -lt 0) { throw 'Could not locate actions block opening brace.' }
        $closeBrace = Find-MatchingBrace -Text $Page -OpenBraceIndex $openBrace
        if ($closeBrace -lt 0) { throw 'Could not locate actions block closing brace.' }
        $Page = $Page.Substring(0,$closeBrace) + $ActionInsert + $Page.Substring($closeBrace)
        Write-Text $AuditPage $Page
        Write-Host 'PATCHED  RunHardParityGate action into actions block' -ForegroundColor Green
    } else { Write-Host 'PASS     RunHardParityGate action already present' -ForegroundColor Green }

    $RawApp = Read-Text $AppJson
    $CurrentApp = $RawApp | ConvertFrom-Json
    if ([string]$CurrentApp.version -eq $SourceVersion) {
        $Pattern = '("version"\s*:\s*")' + [regex]::Escape($SourceVersion) + '(")'
        if (([regex]::Matches($RawApp,$Pattern)).Count -ne 1) { throw 'Expected exactly one manifest version field.' }
        $RawApp = [regex]::Replace($RawApp,$Pattern,'${1}' + $TargetVersion + '${2}',1)
        Write-Text $AppJson $RawApp
        Write-Host "PATCHED  manifest $SourceVersion -> $TargetVersion" -ForegroundColor Green
    } elseif ([string]$CurrentApp.version -eq $TargetVersion) {
        Write-Host "PASS     manifest already $TargetVersion" -ForegroundColor Green
    } else { throw "Unexpected manifest version after normalization: $($CurrentApp.version)" }

    $PageCheck = Read-Text $AuditPage
    foreach ($Marker in @('action(RunHardParityGate)','case Rec.Result of',"'MATCH':","'SOURCE NOT FOUND':",'BlockerCount += 1;','PO RECIPIENT PARITY BLOCKER:','PO RECIPIENT PARITY GATE PASS.')) {
        if (-not $PageCheck.Contains($Marker)) { throw "Local normalization validation failed. Missing: $Marker" }
    }
    $ManifestCheck = Get-Content -LiteralPath $AppJson -Raw | ConvertFrom-Json
    if ([string]$ManifestCheck.version -ne $TargetVersion) { throw "Manifest normalization failed. Found $($ManifestCheck.version)." }
    Write-Host 'LOCAL .184 HARD-GATE SOURCE STATE: PASS' -ForegroundColor Green

    Section '4. ACQUIRE PINNED GUARDED BUILDER'
    Invoke-WebRequest -Uri ($BuilderUrl + '?cb=' + (Get-Date -Format 'yyyyMMddHHmmssfff')) -OutFile $TempBuilder -UseBasicParsing
    $tokens = $null; $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path -LiteralPath $TempBuilder),[ref]$tokens,[ref]$errors) | Out-Null
    if ($errors.Count -gt 0) { throw "Downloaded builder parser failure: $((@($errors | ForEach-Object Message)) -join '; ')" }
    Write-Host "PASS  pinned builder $ToolingCommit" -ForegroundColor Green

    Section '5. COMPILE / PUBLISH / VERIFY .184'
    & $TempBuilder
    if ($LASTEXITCODE -ne 0) { throw "Guarded .184 builder exited $LASTEXITCODE." }

    Section '6. RESULT'
    Write-Host 'PO RECIPIENT HARD PARITY GATE .184 SOURCE/PACKAGE/PUBLISH: PASS' -ForegroundColor Green
    Write-Host 'Production: NOT TOUCHED' -ForegroundColor Green
    Write-Host "Backup retained: $BackupRoot"
}
catch {
    Write-Host ''
    Write-Host 'FAILURE DETECTED - RESTORING TARGETED LOCAL BACKUP' -ForegroundColor Red
    Copy-Item -LiteralPath (Join-Path $BackupRoot 'app.json') -Destination $AppJson -Force
    Copy-Item -LiteralPath (Join-Path $BackupRoot 'GPIPOBucketEvidenceAudit.Page.al') -Destination $AuditPage -Force
    throw
}
finally {
    Remove-Item -LiteralPath $TempBuilder -Force -ErrorAction SilentlyContinue
}
