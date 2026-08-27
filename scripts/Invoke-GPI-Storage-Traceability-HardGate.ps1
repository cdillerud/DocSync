#requires -Version 7.0

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = 'C:\Users\ChadDillerud\Documents\DocSync-Zetadocs'
$ExpectedBranch = 'feature/phase-3-record-documents'
$MainRoot = Join-Path $RepoRoot 'bc-extension\zetadocs-replacement'
$TestsRoot = Join-Path $RepoRoot 'bc-extension\zetadocs-replacement-tests'
$MgtPath = Join-Path $MainRoot 'src\codeunit\GPIRecordDocumentMgt.Codeunit.al'
$ReportRoot = Join-Path $RepoRoot '.gpi-diagnostics\storage-traceability-hard-gate'

function Section([string]$Name) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Name -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

function Assert-Markers([string]$Name,[string]$Text,[string[]]$Markers) {
    $Missing = @($Markers | Where-Object { -not $Text.Contains($_) })
    if ($Missing.Count -gt 0) { throw "$Name failed. Missing: $($Missing -join ' | ')" }
    Write-Host "PASS  $Name" -ForegroundColor Green
}

Section '1. HARD SAFETY'
if (-not (Test-Path -LiteralPath $RepoRoot)) { throw "Repo not found: $RepoRoot" }
$Branch = (& git -C $RepoRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Could not determine Git branch.' }
if ($Branch -ne $ExpectedBranch) { throw "Expected branch '$ExpectedBranch', found '$Branch'." }
if (-not (Test-Path -LiteralPath $MgtPath -PathType Leaf)) { throw "Record-document manager missing: $MgtPath" }

Write-Host "Repo       : $RepoRoot"
Write-Host "Branch     : $Branch"
Write-Host 'Mode       : READ ONLY'
Write-Host 'Production : NOT TOUCHED' -ForegroundColor Green

$Mgt = Get-Content -LiteralPath $MgtPath -Raw

Section '2. SENT-DOCUMENT EXPOSURE'
Assert-Markers 'Delivery-log source binding' $Mgt @(
    'procedure AddSentDocumentsToBuffer(',
    'Record "GPI Document Delivery Log"',
    'DeliveryLog.SetRange("Source Table ID", SourceTableId);',
    'DeliveryLog.SetRange("Source SystemId", SourceSystemId);',
    'DeliveryLog.Status::Sent',
    'DeliveryLog.Status::Archived'
)

Assert-Markers 'Stable sent-document buffer identity' $Mgt @(
    'EntryReference := -DeliveryLog."Entry No.";',
    'TempDocuments."Source Table ID" := SourceTableId;',
    'TempDocuments."Source SystemId" := SourceSystemId;',
    'TempDocuments."Original File Name" := GetDeliveryFileName(DeliveryLog);',
    'TempDocuments."Uploaded By" := DeliveryLog."Completed By";'
)

Section '3. OPEN / DELETE SAFETY'
Assert-Markers 'Sent-document open path' $Mgt @(
    'procedure OpenDocumentReference(EntryReference: Integer)',
    'if EntryReference = 0 then',
    'if EntryReference > 0 then begin',
    'OpenSentDocument(-EntryReference);'
)

Assert-Markers 'Sent history delete protection' $Mgt @(
    'procedure DeleteDocumentReference(EntryReference: Integer)',
    'if EntryReference < 0 then',
    'Sent document history cannot be deleted from the Gamer Documents FactBox'
)

Section '4. REGRESSION TEST EVIDENCE IN SOURCE'
$TestFiles = @(Get-ChildItem -LiteralPath $TestsRoot -Recurse -File -Filter '*.al' -ErrorAction SilentlyContinue)
if ($TestFiles.Count -eq 0) { throw "No AL test files found under $TestsRoot" }
$Tests = ($TestFiles | ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw }) -join "`n"

Assert-Markers 'Sent/draft buffer regression tests' $Tests @(
    'procedure SentDeliveryAppearsInGamerDocumentsBuffer()',
    'procedure DraftDeliveryDoesNotAppearInGamerDocumentsBuffer()',
    'The sent Delivery Log document was not added to the Gamer Documents buffer.',
    'A saved draft was incorrectly added to the Gamer Documents buffer.'
)

Section '5. WRITE EVIDENCE'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$OutDir = Join-Path $ReportRoot $Stamp
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
$OutFile = Join-Path $OutDir 'Storage_Traceability_HardGate.txt'
@(
    'GPI Storage / Traceability Hard Gate',
    "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
    "Branch: $Branch",
    'Classification: VALIDATED PARITY',
    'Sent/Archived delivery-log exposure: PASS',
    'Source Table ID + SystemId binding: PASS',
    'Stable negative delivery-log reference: PASS',
    'Sent-document open path: PASS',
    'Sent-history delete protection: PASS',
    'Sent/draft regression tests present: PASS',
    'Production: NOT TOUCHED'
) | Set-Content -LiteralPath $OutFile -Encoding UTF8

Write-Host ''
Write-Host 'STORAGE / TRACEABILITY HARD GATE: PASS' -ForegroundColor Green
Write-Host "Evidence : $OutFile"
Write-Host 'Classification: VALIDATED PARITY' -ForegroundColor Green
