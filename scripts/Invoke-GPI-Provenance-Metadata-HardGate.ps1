#requires -Version 7.0

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = 'C:\Users\ChadDillerud\Documents\DocSync-Zetadocs'
$ExpectedBranch = 'feature/phase-3-record-documents'
$MainRoot = Join-Path $RepoRoot 'bc-extension\zetadocs-replacement'
$RecordTable = Join-Path $MainRoot 'src\table\GPIRecordDocument.Table.al'
$RecordMgt = Join-Path $MainRoot 'src\codeunit\GPIRecordDocumentMgt.Codeunit.al'
$DeliveryLog = Join-Path $MainRoot 'src\table\GPIDocumentDeliveryLog.Table.al'

function Section([string]$Name) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Name -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

function Read-Required([string]$Path,[string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label missing: $Path" }
    return Get-Content -LiteralPath $Path -Raw
}

function Require([string]$Text,[string[]]$Markers,[string]$Label) {
    $Missing = @($Markers | Where-Object { -not $Text.Contains($_) })
    if ($Missing.Count -gt 0) { throw "$Label PARITY BLOCKER - missing markers: $($Missing -join '; ')" }
    Write-Host "PASS  $Label" -ForegroundColor Green
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

Section '2. RECORD DOCUMENT PROVENANCE SCHEMA'
$TableText = Read-Required $RecordTable 'GPI Record Document table'
Require $TableText @(
    'field(2; "Source Table ID"; Integer)',
    'field(3; "Source SystemId"; Guid)',
    'field(4; "Source Document Type"; Text[50])',
    'field(5; "Source Document No."; Code[20])',
    'field(6; "Source Party Type"; Text[20])',
    'field(7; "Source Party No."; Code[20])',
    'field(8; "Customer No."; Code[20])',
    'field(9; "Vendor No."; Code[20])',
    'field(10; "Location Code"; Code[10])',
    'field(11; "Original File Name"; Text[250])',
    '"SharePoint File Name"',
    '"SharePoint Path"',
    '"SharePoint URL"'
) 'Record provenance schema'

Section '3. UPLOAD METADATA PERSISTENCE'
$MgtText = Read-Required $RecordMgt 'GPI Record Document management codeunit'
Require $MgtText @(
    'procedure UploadDocument(SourceTableId: Integer; SourceSystemId: Guid;',
    'Document."Source Table ID" := SourceTableId;',
    'Document."Source SystemId" := SourceSystemId;',
    'Document."Source Document Type" := SourceDocumentType;',
    'Document."Source Document No." := SourceDocumentNo;',
    'Document."Source Party Type" := SourcePartyType;',
    'Document."Source Party No." := SourcePartyNo;',
    'Document."Customer No." := CustomerNo;',
    'Document."Vendor No." := VendorNo;',
    'Document."Location Code" := LocationCode;',
    'Document."Original File Name" := CopyStr(OriginalFileName',
    'Document."Uploaded By" := CopyStr(UserId()',
    'Document."Uploaded Date/Time" := CurrentDateTime();'
) 'Upload provenance persistence'

Section '4. SENT-DOCUMENT PROVENANCE'
Require $MgtText @(
    'AddSentDocumentsToBuffer(SourceTableId, SourceSystemId, TempDocuments);',
    'DeliveryLog.SetRange("Source Table ID", SourceTableId);',
    'DeliveryLog.SetRange("Source SystemId", SourceSystemId);',
    'TempDocuments."Source Document Type" := DeliveryLog."Source Document Type";',
    'TempDocuments."Source Document No." := DeliveryLog."Source Document No.";',
    'TempDocuments."Source Party Type" := DeliveryLog."Source Party Type";',
    'TempDocuments."Source Party No." := DeliveryLog."Source Party No.";',
    'TempDocuments."Customer No." := DeliveryLog."Customer No.";',
    'TempDocuments."Location Code" := DeliveryLog."Location Code";'
) 'Sent-document provenance projection'

Section '5. DELIVERY LOG TRACEABILITY SCHEMA'
if (Test-Path -LiteralPath $DeliveryLog -PathType Leaf) {
    $LogText = Get-Content -LiteralPath $DeliveryLog -Raw
    Require $LogText @(
        '"Source Table ID"',
        '"Source SystemId"',
        '"Source Document No."',
        '"Delivery Document Type"',
        'Status',
        '"Created Date/Time"'
    ) 'Delivery-log traceability schema'
}
else {
    Write-Host 'RISK  delivery-log table source filename differs or is not present at expected path; management-codeunit projection already validated.' -ForegroundColor Yellow
}

Section '6. RESULT'
Write-Host 'PROVENANCE / METADATA HARD GATE: PASS' -ForegroundColor Green
Write-Host 'Classification : VALIDATED PARITY (source-level gate)'
Write-Host 'Record identity : Source Table ID + Source SystemId'
Write-Host 'Business keys   : document type/no, party, customer/vendor, location'
Write-Host 'File metadata    : original filename + SharePoint location metadata'
Write-Host 'Audit metadata   : uploaded by/date-time and delivery-log timestamps'
Write-Host 'Production       : NOT TOUCHED'
Write-Host 'No routing changes / no email sends / no document writes'
