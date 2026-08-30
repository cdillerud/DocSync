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

function Section([string]$Title){Write-Host '';Write-Host('='*120)-ForegroundColor Cyan;Write-Host $Title -ForegroundColor Cyan;Write-Host('='*120)-ForegroundColor Cyan}
function Run-Phase {
    param([string]$Name,[string]$Script,[switch]$ContinueOnFailure)
    $Path=Join-Path $ToolRoot $Script
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){throw "Autopilot phase missing: $Path"}
    Section "AUTOPILOT PHASE: $Name"
    $Log=Join-Path $DiagDir ($Name -replace '[^A-Za-z0-9_.-]','_')+'.txt'
    $Ok=$true;$Err=$null
    try {
        & $Path *>&1 | Tee-Object -FilePath $Log | ForEach-Object { Write-Host $_ }
    }
    catch {
        $Ok=$false;$Err=$_.Exception.Message
        Write-Host "AUTOPILOT_PHASE_FAILURE=$Name|$Err" -ForegroundColor Red
        Add-Content -LiteralPath $Log -Value "AUTOPILOT_PHASE_FAILURE=$Name|$Err"
        if(-not$ContinueOnFailure){throw}
    }
    $Text=if(Test-Path $Log){Get-Content -LiteralPath $Log -Raw}else{''}
    [pscustomobject]@{Name=$Name;Ok=$Ok;Error=$Err;Log=$Log;Text=$Text}
}

Section 'GPI HUB PARITY AUTOPILOT'
Write-Host 'Policy              : KEEP MOVING WITHOUT INTERIM USER HANDOFFS'
Write-Host 'Production          : NOT TOUCHED'
Write-Host 'BC writes           : NONE'
Write-Host 'SharePoint writes   : NONE'
Write-Host 'Target recreate     : NONE IN THIS DRIVER'
Write-Host 'Failure behavior    : INDEPENDENT READ-ONLY PHASES CONTINUE; FINAL SUMMARY FAILS CLOSED'

$Results=New-Object System.Collections.Generic.List[object]
$Warehouse=Run-Phase -Name 'V108_REV10_SOURCE_CORPUS' -Script 'Invoke-GPIHub-V108-REV10-Source-Corpus-Only.ps1' -ContinueOnFailure
$Results.Add($Warehouse)

$Gap='UNKNOWN'
$m=[regex]::Matches($Warehouse.Text,'V108_MULTIPAGE_REFERENCE_GAP=([^\r\n]+)')
if($m.Count-gt0){$Gap=$m[$m.Count-1].Groups[1].Value.Trim()}
Write-Host "AUTOPILOT_WAREHOUSE_GAP=$Gap" -ForegroundColor Yellow

if($Gap -eq 'PROVEN_SUPPORTING_SHIPMENT_LOST_BY_CURRENT_FIRST_PAGE_SEAM' -or $Gap -eq 'UNRESOLVED_SUPPORTING_SHIPMENT_NOT_EXTRACTED'){
    $V109=Run-Phase -Name 'V109_SUPPORTING_REFERENCE_CANDIDATE' -Script 'Invoke-GPIHub-V109-Supporting-Reference-Candidate-Test.ps1' -ContinueOnFailure
    $Results.Add($V109)
}else{
    Write-Host "AUTOPILOT_V109=SKIPPED_GAP_DISPOSITION_$Gap"
}

$AP=Run-Phase -Name 'AP_TOP10_LEGACY_INVENTORY_AI' -Script 'Invoke-GPIHub-AP-Top10-Legacy-Inventory-AI.ps1' -ContinueOnFailure
$Results.Add($AP)

$GUI=Run-Phase -Name 'GUI_TRUTH_AUDIT' -Script 'Invoke-GPIHub-GUI-Truth-Audit.ps1' -ContinueOnFailure
$Results.Add($GUI)

Section 'AUTOPILOT FINAL SUMMARY'
$failed=@($Results|Where-Object{-not$_.Ok})
foreach($r in $Results){
    Write-Host ("{0,-42}: {1}" -f $r.Name,($(if($r.Ok){'PASS'}else{'FAILED'})))
    if(-not$r.Ok){Write-Host "  $($r.Error)" -ForegroundColor Red}
}
Write-Host "Warehouse gap       : $Gap"
Write-Host "Diagnostics         : $DiagDir"
$summary=@()
$summary+='GPI HUB PARITY AUTOPILOT SUMMARY'
$summary+="Generated: $((Get-Date).ToUniversalTime().ToString('o'))"
$summary+="Warehouse gap: $Gap"
foreach($r in $Results){$summary+=("{0}: {1}{2}" -f $r.Name,($(if($r.Ok){'PASS'}else{'FAILED'})),($(if($r.Error){" | $($r.Error)"}else{''})))}
Set-Content -LiteralPath $SummaryPath -Value $summary -Encoding utf8

if($failed.Count-gt0){
    Write-Host "AUTOPILOT_COMPLETED_WITH_OPEN_FAILURES=$($failed.Count)" -ForegroundColor Yellow
    throw "Autopilot completed all independent phases, but $($failed.Count) phase(s) remain failed. Evidence preserved at $DiagDir"
}
Write-Host 'GPI_HUB_PARITY_AUTOPILOT=PASS' -ForegroundColor Green
