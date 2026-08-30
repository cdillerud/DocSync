#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$StatePath = Join-Path $ToolRoot 'state.json'
$ManifestPath = Join-Path $ToolRoot 'v104-warehouse-historical-authority.json'
$State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 50

$OperationalRoot = [string]$State.local.operational_root
$DiagRoot = Join-Path $OperationalRoot '.gpi-diagnostics\migration-v104-warehouse-historical-authority'
$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$CloseoutDir = Join-Path $OperationalRoot ".gpi-diagnostics\migration-v104-rev2-closeout\$Stamp"
New-Item -ItemType Directory -Path $CloseoutDir -Force | Out-Null
$TranscriptPath = Join-Path $CloseoutDir 'Invoke-GPIHub-V104-REV2-Historical-Authority-Closeout.txt'
Start-Transcript -LiteralPath $TranscriptPath -Force | Out-Null

function Require([bool]$Condition,[string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Write-Section([string]$Title) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

function Has-Property {
    param([Parameter(Mandatory)]$Object,[Parameter(Mandatory)][string]$Name)
    return $null -ne $Object.PSObject.Properties[$Name]
}

try {
    Write-Section 'V104 REV2 - HISTORICAL AUTHORITY LOCAL CLOSEOUT'
    Write-Host 'Action              : REUSE COMPLETED V104 RECONCILIATION JSON; NO REMOTE CALLS'
    Write-Host 'Mode                : LOCAL / READ ONLY'
    Write-Host 'Target changes      : NONE'
    Write-Host 'Source changes      : NONE'
    Write-Host 'Mongo               : NOT TOUCHED'
    Write-Host 'Production          : NOT TOUCHED'

    Require (Test-Path -LiteralPath $ManifestPath -PathType Leaf) "Historical authority manifest missing: $ManifestPath"
    Require (Test-Path -LiteralPath $DiagRoot -PathType Container) "V104 diagnostics root missing: $DiagRoot"

    $jsonFiles = @(Get-ChildItem -LiteralPath $DiagRoot -Filter 'warehouse-historical-authority-reconciliation.json' -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
    Require ($jsonFiles.Count -gt 0) 'No completed V104 reconciliation JSON was found.'
    $jsonPath = $jsonFiles[0].FullName
    $r = Get-Content -LiteralPath $jsonPath -Raw | ConvertFrom-Json -Depth 50

    $required = @('JBS_INBOUND_R','JBS_OUTBOUND_SHIPMENT','STRATEGIC_INBOUND_BOL','STRATEGIC_OUTBOUND_BL')
    foreach ($name in $required) {
        Require ($null -ne $r.cases.PSObject.Properties[$name]) "V104 result missing case $name"
    }

    Write-Host "Reconciliation JSON : $jsonPath"
    Write-Host 'V104_REV2_REUSE_RECONCILIATION_JSON=PASS' -ForegroundColor Green
    Write-Host 'V104_HISTORICAL_AUTHORITY_MANIFEST=PASS' -ForegroundColor Green

    Write-Section 'V104 DEFECT LEDGER - AUTHORITATIVE'
    foreach ($name in $required) {
        $c = $r.cases.$name
        $status = if (Has-Property -Object $c -Name 'status') { [string]$c.status } else { 'STATUS_MISSING' }
        Write-Host ("{0,-32}: {1}" -f $name,$status)

        if (Has-Property -Object $c -Name 'target') {
            $t = $c.target
            if ($null -ne $t) {
                if (Has-Property -Object $t -Name 'id') { Write-Host "  target id   : $($t.id)" }
                if (Has-Property -Object $t -Name 'filename') { Write-Host "  target file : $($t.filename)" }
                if (Has-Property -Object $t -Name 'document_type') { Write-Host "  target type : $($t.document_type)" }
            }
        }

        if ($name -eq 'STRATEGIC_INBOUND_BOL') {
            $targetCandidates = @()
            $bolCandidates = @()
            if (Has-Property -Object $c -Name 'target_candidates') { $targetCandidates = @($c.target_candidates) }
            if (Has-Property -Object $c -Name 'explicit_bol_candidates') { $bolCandidates = @($c.explicit_bol_candidates) }
            Write-Host "  W117105/Strategic target candidates: $($targetCandidates.Count)"
            Write-Host "  Explicit BOL candidates             : $($bolCandidates.Count)"
        }
    }

    $expected = [ordered]@{
        JBS_INBOUND_R = 'REFERENCE_MATCH_ROUTE_CONFLICT'
        JBS_OUTBOUND_SHIPMENT = 'SHIPMENT_REFERENCE_NOT_NORMALIZED'
        STRATEGIC_INBOUND_BOL = 'AUTHENTIC_PACKET_NOT_FOUND_IN_TARGET'
        STRATEGIC_OUTBOUND_BL = 'BL_REFERENCE_MATCH'
    }

    foreach ($name in $expected.Keys) {
        $actual = [string]$r.cases.$name.status
        Require ($actual -eq $expected[$name]) "Unexpected V104 result for $name. Expected '$($expected[$name])', got '$actual'."
    }
    Write-Host 'V104_REV2_EXPECTED_DEFECT_SET=PASS' -ForegroundColor Green

    Require ([int]$r.open_blockers -eq 3) "Expected 3 open Warehouse matrix blockers, found $($r.open_blockers)."
    Require (-not [bool]$r.matrix_closed) 'Warehouse matrix unexpectedly reported closed.'

    Write-Section 'V104 FINAL CLOSEOUT'
    Write-Host 'JBS inbound       : reference extraction proven; routing conflict remains'
    Write-Host 'JBS outbound      : shipping document found; shipment reference normalization gap remains'
    Write-Host 'Strategic inbound : authentic historical packet not represented in restored target'
    Write-Host 'Strategic outbound: exact B/L 57745 extraction proven'
    Write-Host ''
    Write-Host 'Open Warehouse matrix blockers : 3'
    Write-Host 'V104_WAREHOUSE_REFERENCE_MATRIX=OPEN' -ForegroundColor Yellow
    Write-Host 'V104_REV2_DEFECT_LEDGER=PASS' -ForegroundColor Green
    Write-Host 'V104_HISTORICAL_AUTHORITY_RECONCILIATION=PASS' -ForegroundColor Green
    Write-Host 'NEXT: V105 TARGETED WAREHOUSE GAP CODE-PATH AUDIT / FIX DESIGN.' -ForegroundColor Cyan
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
