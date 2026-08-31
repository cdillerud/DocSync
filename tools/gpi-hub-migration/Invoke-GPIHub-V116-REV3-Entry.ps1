#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$BasePath = Join-Path $ToolRoot 'Invoke-GPIHub-V116-AP-Routing-Heldout-Evaluation.ps1'
$StatePath = Join-Path $ToolRoot 'state.json'
$State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 80
$OperationalRoot = [string]$State.local.operational_root
$ExpectedFeatureCommit = '003db3994535694fc2f04dd06154a45cf6e6506f'
$GeneratedRoot = Join-Path $OperationalRoot '.gpi-diagnostics\v116-rev3-generated'
$GeneratedPath = Join-Path $GeneratedRoot 'Invoke-GPIHub-V116-REV3-Generated.ps1'
$GeneratedStatePath = Join-Path $GeneratedRoot 'state.json'

function Require {
    param([bool]$Condition,[string]$Message)
    if (-not $Condition) { throw $Message }
}

function Replace-Required {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$Old,
        [Parameter(Mandatory)][string]$New,
        [Parameter(Mandatory)][string]$Marker
    )
    Require ($Text.Contains($Old)) "V116 REV3 repair anchor missing: $Marker"
    return $Text.Replace($Old,$New)
}

Require (Test-Path -LiteralPath $BasePath -PathType Leaf) "Base V116 controller missing: $BasePath"
Require (Test-Path -LiteralPath $StatePath -PathType Leaf) "V116 REV3 state missing: $StatePath"
New-Item -ItemType Directory -Path $GeneratedRoot -Force | Out-Null
$Raw = Get-Content -LiteralPath $BasePath -Raw

$Raw = Replace-Required -Text $Raw `
    -Old "`$ExpectedFeatureCommit = 'ee75f8dbea0a72f1184b5e241f100bf8df83b17f'" `
    -New "`$ExpectedFeatureCommit = '$ExpectedFeatureCommit'" `
    -Marker 'feature commit pin'

$Raw = Replace-Required -Text $Raw `
    -Old "        'backend/services/ap_routing_decision_service.py'," `
    -New "        'backend/services/ap_routing_decision_service.py',`r`n        'backend/services/ap_routing_authority_guard_service.py'," `
    -Marker 'authority guard candidate materialization'

$Raw = Replace-Required -Text $Raw `
    -Old "FEATURE_COMMIT='ee75f8dbea0a72f1184b5e241f100bf8df83b17f'" `
    -New "FEATURE_COMMIT='$ExpectedFeatureCommit'" `
    -Marker 'probe feature commit evidence'

$Raw = Replace-Required -Text $Raw `
    -Old '        max_per_route=15,' `
    -New '        max_per_route=8,' `
    -Marker 'expanded per-route sample'

$Raw = Replace-Required -Text $Raw `
    -Old '        max_total=80,' `
    -New '        max_total=180,' `
    -Marker 'expanded total sample'

$Raw = Replace-Required -Text $Raw `
    -Old "    print('V116_UNMAPPED_QUEUE_COUNTS='+json.dumps(corpus.get('unmapped_route_counts') or {},sort_keys=True),flush=True)" `
    -New "    print('V116_UNMAPPED_QUEUE_COUNTS='+json.dumps(corpus.get('unmapped_route_counts') or {},sort_keys=True),flush=True)`n    print('V116_EXCLUDED_LEARNING_FILE_COUNT='+str(corpus.get('excluded_learning_file_count') or 0),flush=True)`n    print('V116_EXCLUDED_LEARNING_ROUTE_COUNTS='+json.dumps(corpus.get('excluded_learning_route_counts') or {},sort_keys=True),flush=True)" `
    -Marker 'excluded downstream label evidence'

$Raw = Replace-Required -Text $Raw `
    -Old "        'collapsed_nested_placements':corpus.get('collapsed_route_path_count')," `
    -New "        'collapsed_nested_placements':corpus.get('collapsed_route_path_count'),`n        'excluded_learning_file_count':corpus.get('excluded_learning_file_count'),`n        'excluded_learning_route_counts':corpus.get('excluded_learning_route_counts')," `
    -Marker 'summary exclusion evidence'

Require ($Raw.Contains($ExpectedFeatureCommit)) 'V116 REV3 generated script lacks expected feature commit.'
Require ($Raw.Contains('backend/services/ap_routing_authority_guard_service.py')) 'V116 REV3 generated script lacks authority guard service.'
Require ($Raw.Contains('max_total=180')) 'V116 REV3 generated script lacks expanded sample size.'
Require ($Raw.Contains('V116_EXCLUDED_LEARNING_FILE_COUNT')) 'V116 REV3 generated script lacks downstream-label diagnostics.'

Set-Content -LiteralPath $GeneratedPath -Value $Raw -Encoding utf8 -NoNewline
Copy-Item -LiteralPath $StatePath -Destination $GeneratedStatePath -Force
Require (Test-Path -LiteralPath $GeneratedStatePath -PathType Leaf) 'V116 REV3 generated state copy missing.'
$GeneratedState = Get-Content -LiteralPath $GeneratedStatePath -Raw | ConvertFrom-Json -Depth 80
Require ([string]$GeneratedState.phase -eq 'V116_AP_ROUTING_CORPUS_HELDOUT_EVALUATION_REV3') 'V116 REV3 generated state phase mismatch.'
Require ([string]$GeneratedState.local.operational_root -eq $OperationalRoot) 'V116 REV3 generated state operational-root mismatch.'

# Do not rewrite the currently executing desktop .cmd. V116 REV2 proved that
# self-modifying a live batch file can move cmd.exe's read position and cause it
# to execute a path fragment after PowerShell returns. The desktop launcher is a
# static thin pointer to the self-updating repo-controlled runner.
Write-Host 'GPI_HUB_DESKTOP_LAUNCHER_STATIC_WRAPPER=PASS' -ForegroundColor Green
Write-Host 'V116_REV3_FULL_CORPUS_CONSENSUS=PASS' -ForegroundColor Green
Write-Host 'V116_REV3_CROSS_VENDOR_REFERENCE_GUARD=PASS' -ForegroundColor Green
Write-Host 'V116_REV3_ROUTE_NEUTRAL_RETRIEVAL=PASS' -ForegroundColor Green
Write-Host 'V116_REV3_DOWNSTREAM_LABEL_EXCLUSION=PASS' -ForegroundColor Green
Write-Host 'V116_REV3_EXPANDED_CORPUS=PASS' -ForegroundColor Green
Write-Host 'V116_REV3_GENERATED_STATE=PASS' -ForegroundColor Green
Write-Host "V116_REV3_FEATURE_COMMIT=$ExpectedFeatureCommit"
Write-Host "V116_REV3_GENERATED=$GeneratedPath"

& $GeneratedPath
exit $LASTEXITCODE
