#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$StatePath = Join-Path $ToolRoot 'state.json'
$State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 50
$OperationalRoot = [string]$State.local.operational_root

function Require([bool]$Condition,[string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Write-Section([string]$Title) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

Write-Section 'V102 REV2 - WAREHOUSE REFERENCE-MATRIX DISCOVERY CLOSEOUT'
Write-Host 'Action              : REUSE COMPLETED V102 DISCOVERY JSON; NO REMOTE RESCAN'
Write-Host 'Mode                : LOCAL / READ ONLY'
Write-Host 'Target changes      : NONE'
Write-Host 'Source changes      : NONE'
Write-Host 'Production          : NOT TOUCHED'

$DiagRoot = Join-Path $OperationalRoot '.gpi-diagnostics\migration-v102-warehouse-reference-matrix'
Require (Test-Path -LiteralPath $DiagRoot -PathType Container) "V102 diagnostics root not found: $DiagRoot"

$jsonFiles = @(Get-ChildItem -LiteralPath $DiagRoot -Filter 'warehouse-reference-matrix-discovery.json' -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
Require ($jsonFiles.Count -gt 0) 'No prior V102 discovery JSON was found. REV2 refuses to invent or rescan evidence.'

$SourceJson = $jsonFiles[0].FullName
$matrix = Get-Content -LiteralPath $SourceJson -Raw | ConvertFrom-Json -Depth 50

Require ($null -ne $matrix.total_documents) 'V102 discovery JSON is missing total_documents.'
Require ($null -ne $matrix.scanned_documents) 'V102 discovery JSON is missing scanned_documents.'
Require ($null -ne $matrix.scan_complete) 'V102 discovery JSON is missing scan_complete.'
Require ([bool]$matrix.scan_complete) 'V102 prior scan was not a full collection scan.'
Require ([int64]$matrix.scanned_documents -eq [int64]$matrix.total_documents) "V102 scan count mismatch: scanned=$($matrix.scanned_documents) total=$($matrix.total_documents)"

Write-Host "Discovery JSON      : $SourceJson"
Write-Host "Hub documents       : $($matrix.total_documents)"
Write-Host "Scanned             : $($matrix.scanned_documents)"
Write-Host "Full collection scan: $($matrix.scan_complete)"
Write-Host 'V102_REV2_REUSE_DISCOVERY_JSON=PASS' -ForegroundColor Green
Write-Host 'V102_REV2_FULL_COLLECTION_SCAN=PASS' -ForegroundColor Green

$Required = @(
    'JBS_INBOUND_R',
    'JBS_OUTBOUND_SHIPMENT',
    'STRATEGIC_INBOUND_BOL',
    'STRATEGIC_OUTBOUND_BL'
)

Write-Section 'V102 DISCOVERY MATRIX - RECONCILED'
foreach ($name in $Required) {
    $count = [int]$matrix.counts.$name
    $status = if ($count -gt 0) { 'CANDIDATE_FOUND' } else { 'NO_CANDIDATE_IN_SCAN' }
    Write-Host ("{0,-32}: {1,6}  {2}" -f $name,$count,$status)
}

$Missing = @($Required | Where-Object { [int]$matrix.counts.$_ -le 0 })
if ($Missing.Count -eq 0) {
    Write-Host 'V102_REQUIRED_PATTERN_CANDIDATES=ALL_FOUR_PRESENT' -ForegroundColor Green
} else {
    Write-Host ('V102_REQUIRED_PATTERN_CANDIDATES=INCOMPLETE|{0}' -f ($Missing -join ',')) -ForegroundColor Yellow
}

function Get-CandidateScore {
    param($Candidate)
    $score = 0
    if ($null -ne $Candidate.sharepoint_path -and -not [string]::IsNullOrWhiteSpace([string]$Candidate.sharepoint_path)) { $score += 4 }
    if ($null -ne $Candidate.reference_candidates -and @($Candidate.reference_candidates).Count -gt 0) { $score += 4 }
    if ($null -ne $Candidate.document_type -and [string]$Candidate.document_type -match '(?i)warehouse|shipping|receipt') { $score += 2 }
    if ($null -ne $Candidate.status -and [string]$Candidate.status -match '(?i)complete|processed|routed|linked') { $score += 1 }
    if ($null -ne $Candidate.filename -and -not [string]::IsNullOrWhiteSpace([string]$Candidate.filename)) { $score += 1 }
    return $score
}

$Shortlist = [ordered]@{
    generated_utc = (Get-Date).ToUniversalTime().ToString('o')
    source_discovery_json = $SourceJson
    scan_complete = [bool]$matrix.scan_complete
    total_documents = [int64]$matrix.total_documents
    scanned_documents = [int64]$matrix.scanned_documents
    groups = [ordered]@{}
}

Write-Section 'V102 TARGETED VALIDATION SHORTLIST'
foreach ($name in $Required) {
    $Candidates = @($matrix.candidates.$name)
    $Ranked = @($Candidates | ForEach-Object {
        $c = $_
        [pscustomobject]@{
            score = Get-CandidateScore -Candidate $c
            candidate = $c
        }
    } | Sort-Object score -Descending)

    $Top = @($Ranked | Select-Object -First 5)
    $Shortlist.groups[$name] = @($Top | ForEach-Object {
        $c = $_.candidate
        [ordered]@{
            score = [int]$_.score
            id = [string]$c.id
            filename = if ($null -ne $c.filename) { [string]$c.filename } else { $null }
            document_type = if ($null -ne $c.document_type) { [string]$c.document_type } else { $null }
            status = if ($null -ne $c.status) { [string]$c.status } else { $null }
            sharepoint_path = if ($null -ne $c.sharepoint_path) { [string]$c.sharepoint_path } else { $null }
            reference_candidates = @($c.reference_candidates)
        }
    })

    Write-Host ''
    Write-Host "[$name] total candidates=$($Candidates.Count) shortlist=$($Top.Count)" -ForegroundColor Cyan
    $rank = 0
    foreach ($entry in @($Shortlist.groups[$name])) {
        $rank++
        Write-Host ("  #{0} score={1} id={2}" -f $rank,$entry.score,$entry.id)
        Write-Host ("     file={0}" -f $entry.filename)
        Write-Host ("     type={0} status={1}" -f $entry.document_type,$entry.status)
        Write-Host ("     sharepoint={0}" -f $entry.sharepoint_path)
        $refs = @($entry.reference_candidates)
        if ($refs.Count -gt 0) {
            foreach ($r in ($refs | Select-Object -First 8)) {
                Write-Host ("     ref={0} => {1}" -f $r.path,$r.value)
            }
        } else {
            Write-Host '     ref=<none captured>'
        }
    }
}

$ShortlistPath = Join-Path (Split-Path -Parent $SourceJson) 'warehouse-reference-matrix-shortlist.json'
$Shortlist | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $ShortlistPath -Encoding utf8
Write-Host ''
Write-Host "Shortlist JSON      : $ShortlistPath"
Write-Host 'V102_REV2_SHORTLIST_CREATED=PASS' -ForegroundColor Green

if ($Missing.Count -gt 0) {
    Write-Host ''
    Write-Host 'V102 DISCOVERY RESULT: INCOMPLETE - authoritative historical evidence must be sourced for missing groups.' -ForegroundColor Yellow
    Write-Host 'V102_REV2_DISCOVERY_CLOSEOUT=PASS_WITH_MISSING_GROUPS' -ForegroundColor Yellow
    exit 0
}

Write-Host ''
Write-Host 'Important: ALL FOUR groups have candidates, but candidate presence is NOT parity validation.' -ForegroundColor Yellow
Write-Host 'NEXT: choose representative candidates and prove reference semantics + BC resolution where applicable + actual routing/delivery.' -ForegroundColor Cyan
Write-Host 'V102_REV2_DISCOVERY_CLOSEOUT=PASS' -ForegroundColor Green
