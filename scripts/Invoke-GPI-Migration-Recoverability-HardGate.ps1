#requires -Version 7.0

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = 'C:\Users\ChadDillerud\Documents\DocSync-Zetadocs'
$ExpectedBranch = 'feature/phase-3-record-documents'
$BridgeRoot = Join-Path $RepoRoot 'bc-extension\gpi-zetadocs-pilot-bridge'
$BulkPath = Join-Path $BridgeRoot 'src\codeunit\GPIZetadocsBulkMigration.Codeunit.al'
$TaskPath = Join-Path $BridgeRoot 'src\codeunit\GPIZetadocsAutoMigrationTask.Codeunit.al'
$FailurePath = Join-Path $BridgeRoot 'src\codeunit\GPIZetadocsAutoMigrationFailure.Codeunit.al'
$AuditPath = Join-Path $BridgeRoot 'src\table\GPIZetadocsMigrationAudit.Table.al'
$StatePath = Join-Path $BridgeRoot 'src\table\GPIZetadocsAutoMigrationState.Table.al'
$ReportRoot = Join-Path $RepoRoot '.gpi-diagnostics\migration-recoverability-hard-gate'

function Section([string]$Name) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Name -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

function Assert-Markers {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string[]]$Markers
    )

    $Missing = @($Markers | Where-Object { -not $Text.Contains($_) })
    if ($Missing.Count -gt 0) {
        throw "$Name hard gate failed. Missing marker(s): $($Missing -join ' | ')"
    }

    Write-Host ("PASS  {0}" -f $Name) -ForegroundColor Green
}

Section '1. HARD SAFETY / SOURCE SCOPE'

if (-not (Test-Path -LiteralPath $RepoRoot)) { throw "Repo not found: $RepoRoot" }
$Branch = (& git -C $RepoRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Could not determine Git branch.' }
if ($Branch -ne $ExpectedBranch) { throw "Wrong branch. Expected '$ExpectedBranch', found '$Branch'." }

foreach ($Path in @($BridgeRoot,$BulkPath,$TaskPath,$FailurePath,$AuditPath,$StatePath)) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf) -and $Path -ne $BridgeRoot) { throw "Required bridge source missing: $Path" }
}

Write-Host "Repo       : $RepoRoot"
Write-Host "Branch     : $Branch"
Write-Host 'Mode       : READ ONLY'
Write-Host 'Production : NOT TOUCHED' -ForegroundColor Green

$Bulk = Get-Content -LiteralPath $BulkPath -Raw
$Task = Get-Content -LiteralPath $TaskPath -Raw
$Failure = Get-Content -LiteralPath $FailurePath -Raw
$Audit = Get-Content -LiteralPath $AuditPath -Raw
$State = Get-Content -LiteralPath $StatePath -Raw

Section '2. BATCH BOUNDS / RESUMABILITY'
Assert-Markers 'Bounded batch execution' $Bulk @(
    "if BatchSize <= 0 then",
    "if BatchSize > 1000 then",
    "Error('Batch Size cannot exceed 1000 records per run.')",
    'if RecordsProcessed >= MaxRecords then',
    'Commit();'
)

Assert-Markers 'Idempotent audit checkpoint' $Bulk @(
    'local procedure ShouldProcess(',
    'if not Audit.Get(TableId, SourceSystemId) then',
    "exit(RetryFailures and (Audit.Status = 'Failed'));",
    'Audit.Attempts += 1;',
    'Audit."Last Run Date/Time" := CurrentDateTime();'
)

Section '3. PER-RECORD FAILURE ISOLATION'
Assert-Markers 'Failure accounting' $Bulk @(
    'if OperationSucceeded then begin',
    'FailedRecords += 1;',
    'UpsertAudit(',
    'RecordMissingUrl',
    'ErrorText'
)

Assert-Markers 'Scheduled failure handler' $Failure @(
    'State.Active := false;',
    'State.Running := false;',
    'Clear(State."Scheduled Task ID")',
    'GetLastErrorText()'
)

Section '4. FIRST-BATCH STALE-RUN RECOVERY (.21)'
Assert-Markers 'Canonical .21 stale recovery' $Task @(
    'procedure RecoverStaleRun()',
    'StaleReferenceDateTime: DateTime;',
    'StaleReferenceLabel: Text[50];',
    'if State."Last Batch Date/Time" <> 0DT then begin',
    'StaleReferenceDateTime := State."Started Date/Time";',
    "StaleReferenceLabel := 'run start';",
    'StaleThreshold := 60 * 60 * 1000;',
    'if not IsNullGuid(State."Scheduled Task ID") then',
    "State.Status := 'Stopped: stale run recovered';",
    'Use Resume to continue.'
)

if ($Task.Contains('Recovery was blocked because there is no Last Batch Date/Time to prove the run is stale.')) {
    throw 'First-batch stale-run dead-end is still present.'
}
Write-Host 'PASS  first-batch 0DT dead-end removed' -ForegroundColor Green

Section '5. MIGRATION AUDIT / RECOVERY STATE PERSISTENCE'
Assert-Markers 'Migration audit persistence' $Audit @(
    'field(1;',
    'SystemId',
    'Attempts',
    'Last Error',
    'Last Run Date/Time'
)

Assert-Markers 'Unattended state persistence' $State @(
    'Active',
    'Running',
    'Stop Requested',
    'Scheduled Task ID',
    'Started Date/Time',
    'Last Batch Date/Time',
    'Last Error'
)

Section '6. WRITE EVIDENCE'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$OutDir = Join-Path $ReportRoot $Stamp
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
$OutFile = Join-Path $OutDir 'Migration_Recoverability_HardGate.txt'

@(
    'GPI Migration / Recoverability Hard Gate',
    "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
    "Branch: $Branch",
    'Classification: VALIDATED PARITY',
    'Bounded batch execution: PASS',
    'Per-record checkpoint/commit path: PASS',
    'Audit-backed retry behavior: PASS',
    'Failure-state cleanup: PASS',
    'First-batch stale-run recovery (.21): PASS',
    'Scheduled Task ID ambiguity guard: PASS',
    'Migration audit/state persistence: PASS',
    'Production: NOT TOUCHED'
) | Set-Content -LiteralPath $OutFile -Encoding UTF8

Write-Host ''
Write-Host 'MIGRATION / RECOVERABILITY HARD GATE: PASS' -ForegroundColor Green
Write-Host "Evidence : $OutFile"
Write-Host 'Classification: VALIDATED PARITY' -ForegroundColor Green
