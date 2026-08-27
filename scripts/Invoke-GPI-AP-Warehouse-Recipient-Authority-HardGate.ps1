#requires -Version 7.0

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = 'C:\Users\ChadDillerud\Documents\DocSync-Zetadocs'
$ExpectedBranch = 'feature/phase-3-record-documents'
$AuditScriptCandidates = @(
    (Join-Path $RepoRoot 'scripts\Audit-GPI-All-Document-Recipient-Authority.ps1'),
    (Join-Path $RepoRoot 'Audit-GPI-All-Document-Recipient-Authority.ps1')
)

$InScope = @(
    'Purchase Order - Warehouse',
    'Purchase Order - Drop Ship',
    'Warehouse Receiving Notice',
    'Purchase Credit Memo',
    'Purchase Return Order',
    'Purchase Return Pick Ticket',
    'Transfer Pick List',
    'Transfer Receipt Notice',
    'Transfer Shipment'
)

function Section([string]$Text) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

Section '1. PRECHECK'

if (-not (Test-Path -LiteralPath $RepoRoot)) {
    throw "Repo not found: $RepoRoot"
}

$Branch = (& git -C $RepoRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) {
    throw 'Could not determine Git branch.'
}
if ($Branch -ne $ExpectedBranch) {
    throw "Expected branch '$ExpectedBranch', found '$Branch'."
}

$AuditScript = $AuditScriptCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $AuditScript) {
    $AuditScript = Get-ChildItem -LiteralPath $RepoRoot -Recurse -File -Filter 'Audit-GPI-All-Document-Recipient-Authority.ps1' -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty FullName -First 1
}
if (-not $AuditScript) {
    throw 'Could not locate Audit-GPI-All-Document-Recipient-Authority.ps1.'
}

Write-Host "Repo   : $RepoRoot"
Write-Host "Branch : $Branch"
Write-Host "Audit  : $AuditScript"
Write-Host 'Mode   : READ ONLY'

Section '2. RUN FULL RECIPIENT AUTHORITY AUDIT'

& $AuditScript
if ($LASTEXITCODE -ne 0) {
    throw "Recipient authority audit exited $LASTEXITCODE."
}

Section '3. LOCATE NEWEST COVERAGE OUTPUT'

$Coverage = Get-ChildItem -LiteralPath $RepoRoot -Recurse -File -Filter 'Recipient_Authority_Document_Coverage.csv' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $Coverage) {
    throw 'Recipient_Authority_Document_Coverage.csv was not found after audit.'
}

$Rows = @(Import-Csv -LiteralPath $Coverage.FullName)
if ($Rows.Count -eq 0) {
    throw 'Recipient authority coverage CSV is empty.'
}

Write-Host "Coverage: $($Coverage.FullName)"

Section '4. AP / WAREHOUSE HARD GATE'

$Scoped = @(
    foreach ($DocType in $InScope) {
        $Match = @($Rows | Where-Object { [string]$_.DocumentType -eq $DocType })
        if ($Match.Count -eq 0) {
            [pscustomobject]@{
                DocumentType = $DocType
                Classification = 'NO SEND PATH FOUND'
                SendPathCount = 0
                Procedures = ''
            }
        }
        else {
            $Match
        }
    }
)

$Scoped |
    Select-Object DocumentType,Classification,SendPathCount,Procedures |
    Format-Table -AutoSize -Wrap

$Blockers = @(
    $Scoped | Where-Object {
        [string]$_.Classification -in @('PARITY BLOCKER','NO SEND PATH FOUND')
    }
)

$Risks = @(
    $Scoped | Where-Object {
        [string]$_.Classification -eq 'PARITY RISK'
    }
)

$Validated = @(
    $Scoped | Where-Object {
        [string]$_.Classification -eq 'VALIDATED PARITY'
    }
)

Write-Host ''
Write-Host "Validated parity : $($Validated.Count)"
Write-Host "Parity risks     : $($Risks.Count)"
Write-Host "Parity blockers  : $($Blockers.Count)"

if ($Blockers.Count -gt 0) {
    Write-Host ''
    foreach ($B in $Blockers) {
        Write-Host ("BLOCKER: {0} :: {1}" -f $B.DocumentType,$B.Classification) -ForegroundColor Red
    }
    throw "AP/Warehouse recipient authority hard gate FAILED with $($Blockers.Count) blocker(s)."
}

if ($Risks.Count -gt 0) {
    Write-Host ''
    foreach ($R in $Risks) {
        Write-Host ("RISK: {0} :: {1}" -f $R.DocumentType,$R.Classification) -ForegroundColor Yellow
    }
    Write-Host 'AP/Warehouse recipient authority has no blockers, but risks remain.' -ForegroundColor Yellow
    exit 2
}

Section '5. RESULT'
Write-Host 'AP / WAREHOUSE RECIPIENT AUTHORITY HARD GATE PASS' -ForegroundColor Green
Write-Host 'No in-scope recipient-authority blockers or risks remain.'
exit 0
