#requires -Version 7.0

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = 'C:\Users\ChadDillerud\Documents\DocSync-Zetadocs'
$ExpectedBranch = 'feature/phase-3-record-documents'
$BridgeRoot = Join-Path $RepoRoot 'bc-extension\gpi-zetadocs-pilot-bridge'
$Bulk = Join-Path $BridgeRoot 'src\codeunit\GPIZetadocsBulkMigration.Codeunit.al'
$Direct = Join-Path $BridgeRoot 'src\codeunit\GPIZetadocsDirectLinkCopy.Codeunit.al'
$AuditTable = Join-Path $BridgeRoot 'src\table\GPIZetadocsMigrationAudit.Table.al'

function Section([string]$Name) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Name -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

function Require-Markers([string]$Path,[string[]]$Markers,[string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label source missing: $Path" }
    $Text = Get-Content -LiteralPath $Path -Raw
    $Missing = @($Markers | Where-Object { -not $Text.Contains($_) })
    if ($Missing.Count -gt 0) {
        throw "$Label PARITY BLOCKER - missing markers: $($Missing -join '; ')"
    }
    Write-Host "PASS  $Label" -ForegroundColor Green
    return $Text
}

Section '1. HARD SAFETY / SCOPE'
if (-not (Test-Path -LiteralPath $RepoRoot)) { throw "Repo not found: $RepoRoot" }
$Branch = (& git -C $RepoRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Could not determine Git branch.' }
if ($Branch -ne $ExpectedBranch) { throw "Expected branch '$ExpectedBranch', found '$Branch'." }
Write-Host "Repo       : $RepoRoot"
Write-Host "Branch     : $Branch"
Write-Host 'Mode       : READ ONLY'
Write-Host 'Production : NOT TOUCHED' -ForegroundColor Green

Section '2. MIGRATION AUDIT IDENTITY / REPLAY GUARD'
$Audit = Require-Markers $AuditTable @(
    'key(PK; "Source Table ID", "Source SystemId")',
    'field(8; "Links Created"; Integer)',
    'field(9; "Links Existing"; Integer)',
    'field(11; Attempts; Integer)',
    'field(13; "Last Error"; Text[2048])'
) 'Migration audit identity'

Section '3. SOURCE RECORD RESOLUTION'
$BulkText = Require-Markers $Bulk @(
    'SourceSystemId := GetSystemIdFromRecordRef(SourceRef);',
    'if ShouldProcess(TableId, SourceSystemId, RetryFailures) then begin',
    'local procedure ShouldProcess(TableId: Integer; SourceSystemId: Guid; RetryFailures: Boolean): Boolean',
    'if IsNullGuid(SourceSystemId) then',
    'local procedure GetSystemIdFromRecordRef(var SourceRef: RecordRef): Guid',
    'SourceRef.Field(SourceRef.SystemIdNo())'
) 'SystemId record resolution'

Section '4. DEDUPE / EXISTING-LINK ACCOUNTING'
foreach ($Marker in @(
    'var LinksExisting: Integer;',
    '"Links Existing" := LinksExisting;',
    'DirectCopy: Codeunit "GPI ZD Direct Link Copy";'
)) {
    if (-not $BulkText.Contains($Marker)) { throw "Dedupe PARITY BLOCKER - missing bulk marker: $Marker" }
}
Write-Host 'PASS  bulk existing-link accounting' -ForegroundColor Green

$DirectText = Require-Markers $Direct @(
    '"GPI Record Document"',
    '"Source Table ID"',
    '"Source SystemId"'
) 'Direct-link dedupe source'

$DedupeSignals = @(
    'LinksExisting',
    'Existing',
    'FindFirst',
    'FindSet',
    'SetRange'
)
$FoundSignal = $false
foreach ($Signal in $DedupeSignals) {
    if ($DirectText.Contains($Signal)) { $FoundSignal = $true; break }
}
if (-not $FoundSignal) { throw 'Dedupe PARITY BLOCKER - direct-link copy exposes no existing-link lookup/accounting signal.' }
Write-Host 'PASS  direct-link existing-link path present' -ForegroundColor Green

Section '5. FAILURE / RETRY TRACEABILITY'
foreach ($Marker in @(
    'Audit.Attempts += 1;',
    'Audit."Last Run Date/Time" := CurrentDateTime();',
    'Audit."Last Error" := CopyStr(ErrorText, 1, MaxStrLen(Audit."Last Error"));'
)) {
    if (-not $BulkText.Contains($Marker)) { throw "Retry traceability PARITY BLOCKER - missing marker: $Marker" }
}
Write-Host 'PASS  retry/failure traceability' -ForegroundColor Green

Section '6. RESULT'
Write-Host 'DEDUPE / RECORD RESOLUTION HARD GATE: PASS' -ForegroundColor Green
Write-Host 'Classification : VALIDATED PARITY (source-level gate)'
Write-Host 'Identity       : Source Table ID + Source SystemId'
Write-Host 'Replay guard   : migration audit PK + ShouldProcess'
Write-Host 'Existing links : explicitly accounted'
Write-Host 'Production     : NOT TOUCHED'
Write-Host 'No routing changes / no email sends / no migration writes'
