#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$State = Get-Content -LiteralPath (Join-Path $ToolRoot 'state.json') -Raw | ConvertFrom-Json -Depth 50
$OperationalRoot = [string]$State.local.operational_root
$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\autopilot-parity-pipeline\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
$SummaryPath = Join-Path $DiagDir 'autopilot-summary.txt'

function Section([string]$Title) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

function Run-Phase {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Script,
        [switch]$ContinueOnFailure
    )

    $Path = Join-Path $ToolRoot $Script
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Autopilot phase missing: $Path"
    }

    Section "AUTOPILOT PHASE: $Name"
    $SafeName = $Name -replace '[^A-Za-z0-9_.-]', '_'
    $Log = Join-Path $DiagDir "$SafeName.txt"
    $Ok = $true
    $Err = $null

    try {
        $Tokens = $null
        $ParseErrors = $null
        [void][System.Management.Automation.Language.Parser]::ParseFile($Path,[ref]$Tokens,[ref]$ParseErrors)
        if (@($ParseErrors).Count -gt 0) {
            $ParseMessage = (@($ParseErrors) | ForEach-Object { $_.Message }) -join '; '
            throw "Phase parser failed before execution: $ParseMessage"
        }
        Write-Host "AUTOPILOT_PHASE_PARSE=PASS|$Name" -ForegroundColor Green

        & $Path *>&1 | Tee-Object -FilePath $Log | ForEach-Object { Write-Host $_ }
    }
    catch {
        $Ok = $false
        $Err = $_.Exception.Message
        Write-Host "AUTOPILOT_PHASE_FAILURE=$Name|$Err" -ForegroundColor Red
        Add-Content -LiteralPath $Log -Value "AUTOPILOT_PHASE_FAILURE=$Name|$Err"
        if (-not $ContinueOnFailure) {
            throw
        }
    }

    $Text = if (Test-Path -LiteralPath $Log) {
        Get-Content -LiteralPath $Log -Raw
    }
    else {
        ''
    }

    return [pscustomobject]@{
        Name = $Name
        Ok = $Ok
        Error = $Err
        Log = $Log
        Text = $Text
    }
}

Section 'GPI HUB PARITY AUTOPILOT'
Write-Host 'Policy              : KEEP MOVING WITHOUT INTERIM USER HANDOFFS'
Write-Host 'Production          : NOT TOUCHED'
Write-Host 'BC writes           : NONE'
Write-Host 'SharePoint writes   : NONE'
Write-Host 'Target recreate     : NONE IN THIS DRIVER'
Write-Host 'Failure behavior    : INDEPENDENT READ-ONLY PHASES CONTINUE; FINAL SUMMARY FAILS CLOSED'
Write-Host 'Parser policy       : EVERY CHILD PHASE PARSED BEFORE EXECUTION'

$Results = New-Object System.Collections.Generic.List[object]

$Warehouse = Run-Phase -Name 'V108_REV10_SOURCE_CORPUS' -Script 'Invoke-GPIHub-V108-REV10-Source-Corpus-Only.ps1' -ContinueOnFailure
$Results.Add($Warehouse)

$Gap = 'UNKNOWN'
$Matches = [regex]::Matches($Warehouse.Text, 'V108_MULTIPAGE_REFERENCE_GAP=([^\r\n]+)')
if ($Matches.Count -gt 0) {
    $Gap = $Matches[$Matches.Count - 1].Groups[1].Value.Trim()
}
Write-Host "AUTOPILOT_WAREHOUSE_GAP=$Gap" -ForegroundColor Yellow

if (
    $Gap -eq 'PROVEN_SUPPORTING_SHIPMENT_LOST_BY_CURRENT_FIRST_PAGE_SEAM' -or
    $Gap -eq 'UNRESOLVED_SUPPORTING_SHIPMENT_NOT_EXTRACTED'
) {
    $V109 = Run-Phase -Name 'V109_SUPPORTING_REFERENCE_CANDIDATE' -Script 'Invoke-GPIHub-V109-Supporting-Reference-Candidate-Test.ps1' -ContinueOnFailure
    $Results.Add($V109)
}
else {
    Write-Host "AUTOPILOT_V109=SKIPPED_GAP_DISPOSITION_$Gap"
}

$V110 = Run-Phase -Name 'V110_TUMALO_PYPDF_AP_GUARD' -Script 'Invoke-GPIHub-V110-Tumalo-Pypdf-AP-Guard-Candidate.ps1' -ContinueOnFailure
$Results.Add($V110)

$AP = Run-Phase -Name 'AP_TOP10_LEGACY_INVENTORY_AI_REV3_DELTA' -Script 'Invoke-GPIHub-AP-Top10-Legacy-Inventory-AI-REV3-Delta.ps1' -ContinueOnFailure
$Results.Add($AP)

$GUI = Run-Phase -Name 'GUI_TRUTH_AUDIT' -Script 'Invoke-GPIHub-GUI-Truth-Audit.ps1' -ContinueOnFailure
$Results.Add($GUI)

Section 'AUTOPILOT FINAL SUMMARY'
$Failed = @($Results | Where-Object { -not $_.Ok })
foreach ($Result in $Results) {
    $Status = if ($Result.Ok) { 'PASS' } else { 'FAILED' }
    Write-Host ("{0,-42}: {1}" -f $Result.Name, $Status)
    if (-not $Result.Ok) {
        Write-Host "  $($Result.Error)" -ForegroundColor Red
    }
}

Write-Host "Warehouse gap       : $Gap"
Write-Host "Diagnostics         : $DiagDir"

$Summary = New-Object System.Collections.Generic.List[string]
$Summary.Add('GPI HUB PARITY AUTOPILOT SUMMARY')
$Summary.Add("Generated: $((Get-Date).ToUniversalTime().ToString('o'))")
$Summary.Add("Warehouse gap: $Gap")
foreach ($Result in $Results) {
    $Status = if ($Result.Ok) { 'PASS' } else { 'FAILED' }
    $Suffix = if ($Result.Error) { " | $($Result.Error)" } else { '' }
    $Summary.Add("$($Result.Name): $Status$Suffix")
}
Set-Content -LiteralPath $SummaryPath -Value $Summary -Encoding utf8

if ($Failed.Count -gt 0) {
    Write-Host "AUTOPILOT_COMPLETED_WITH_OPEN_FAILURES=$($Failed.Count)" -ForegroundColor Yellow
    throw "Autopilot completed all independent phases, but $($Failed.Count) phase(s) remain failed. Evidence preserved at $DiagDir"
}

Write-Host 'GPI_HUB_PARITY_AUTOPILOT=PASS' -ForegroundColor Green
