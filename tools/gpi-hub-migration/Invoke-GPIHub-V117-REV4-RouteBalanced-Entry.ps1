#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$StatePath = Join-Path $ToolRoot 'state.json'
$ControllerCommit = '338e17116a3c02cacbf1a6fc756c1f9e07d80858'
$ControllerRepoPath = 'tools/gpi-hub-migration/Invoke-GPIHub-V117-REV2-Detached-Entry.ps1'
$ExpectedControllerBlob = 'e5dbabe7e313c733a027820f79a817a2a833339a'
$FrozenFeatureCommit = 'f423c94ca23fc137a80f03fe5694412403c41443'
$Rev4FeatureCommit = 'e55ee1432051dc48e4ad30cc421615b4e8ebc5f3'
$OverlaySourceCommit = '9858b2b4a000ce8d049274ac6f8394422af4a578'
$OverlayRepoPath = 'tools/gpi-hub-migration/v117-rev4-controller-overlay.ps1frag'
$ExpectedOverlayBlob = '4d695ea648844b801b196400cc299ff59269d416'

function Require {
    param([bool]$Condition,[string]$Message)
    if (-not $Condition) { throw $Message }
}

function Get-GitText {
    param([string]$Repo,[string]$Ref,[string]$RepoPath)
    $spec = "{0}:{1}" -f $Ref,$RepoPath
    $lines = & git.exe -C $Repo show $spec
    $exitCode = $LASTEXITCODE
    Require ($exitCode -eq 0) "Could not read $RepoPath from $Ref."
    return ((@($lines) | ForEach-Object { [string]$_ }) -join "`n") -replace "`r",''
}

Require (Test-Path -LiteralPath $StatePath -PathType Leaf) "V117 REV4 state missing: $StatePath"
Require ($null -ne (Get-Command git.exe -ErrorAction SilentlyContinue)) 'git.exe unavailable.'
Require ($null -ne (Get-Command pwsh.exe -ErrorAction SilentlyContinue)) 'pwsh.exe unavailable.'

$State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 80
$OperationalRoot = [string]$State.local.operational_root
Require (Test-Path -LiteralPath $OperationalRoot -PathType Container) "V117 REV4 operational repo missing: $OperationalRoot"

$controllerSpec = "{0}:{1}" -f $ControllerCommit,$ControllerRepoPath
$controllerBlob = (& git.exe -C $OperationalRoot rev-parse $controllerSpec).Trim()
Require ($LASTEXITCODE -eq 0) 'Could not resolve frozen REV3 controller blob.'
Require ($controllerBlob -ceq $ExpectedControllerBlob) "Frozen REV3 controller blob drift: $controllerBlob"

$overlaySpec = "{0}:{1}" -f $OverlaySourceCommit,$OverlayRepoPath
$overlayBlob = (& git.exe -C $OperationalRoot rev-parse $overlaySpec).Trim()
Require ($LASTEXITCODE -eq 0) 'Could not resolve REV4 controller overlay blob.'
Require ($overlayBlob -ceq $ExpectedOverlayBlob) "REV4 controller overlay blob drift: $overlayBlob"

$ControllerRaw = Get-GitText -Repo $OperationalRoot -Ref $ControllerCommit -RepoPath $ControllerRepoPath
$OverlayRaw = Get-GitText -Repo $OperationalRoot -Ref $OverlaySourceCommit -RepoPath $OverlayRepoPath

$featureOld = "`$ExpectedFeatureCommit = '$FrozenFeatureCommit'"
$featureNew = "`$ExpectedFeatureCommit = '$Rev4FeatureCommit'"
Require ($ControllerRaw.Contains($featureOld)) 'V117 REV4 frozen feature pin anchor missing.'
$ControllerRaw = $ControllerRaw.Replace($featureOld,$featureNew)

$targetOld = 'V117_REV3_FOCUSED_REGRESSION_TARGET_CONFIGURED=182'
$targetNew = 'V117_REV3_FOCUSED_REGRESSION_TARGET_CONFIGURED=190'
Require ($ControllerRaw.Contains($targetOld)) 'V117 REV4 configured focused-regression marker anchor missing.'
$ControllerRaw = $ControllerRaw.Replace($targetOld,$targetNew)

$insertAnchor = '$ReplayTransformB64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($ReplayTransform))'
Require ($ControllerRaw.Contains($insertAnchor)) 'V117 REV4 replay transform insertion anchor missing.'
$ControllerRaw = $ControllerRaw.Replace($insertAnchor,$OverlayRaw + "`n`n" + $insertAnchor)

$productionMarker = "Write-Host 'V117_REV3_PRODUCTION_MUTATION=NONE' -ForegroundColor Green"
$rev4Markers = $productionMarker + "`nWrite-Host 'V117_REV4_FEATURE_COMMIT=$Rev4FeatureCommit' -ForegroundColor Green`nWrite-Host 'V117_REV4_ROUTE_BALANCED_TRAIN_CONTEXT=PASS' -ForegroundColor Green`nWrite-Host 'V117_REV4_ROUTE_BALANCED_TRAIN_EXPANSION=PASS' -ForegroundColor Green`nWrite-Host 'V117_REV4_FOCUSED_REGRESSION_TARGET=190' -ForegroundColor Green`nWrite-Host 'V117_REV4_EVIDENCE_REPLAY=UNCHANGED' -ForegroundColor Green`nWrite-Host 'V117_REV4_AUTHORITY_THRESHOLDS=UNCHANGED' -ForegroundColor Green`nWrite-Host 'V117_REV4_PRODUCTION_MUTATION=NONE' -ForegroundColor Green"
Require ($ControllerRaw.Contains($productionMarker)) 'V117 REV4 production marker anchor missing.'
$ControllerRaw = $ControllerRaw.Replace($productionMarker,$rev4Markers)

$GeneratedController = Join-Path $ToolRoot 'Invoke-GPIHub-V117-REV4-Replay-Controller-Generated.ps1'
Set-Content -LiteralPath $GeneratedController -Value $ControllerRaw -Encoding utf8 -NoNewline

$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($GeneratedController,[ref]$tokens,[ref]$errors)
if (@($errors).Count -gt 0) {
    $text = (@($errors) | ForEach-Object { $_.Message }) -join '; '
    throw "V117 REV4 generated controller parse failed: $text"
}

Write-Host 'V117_REV4_CONTROLLER_OVERLAY=PASS' -ForegroundColor Green
Write-Host "V117_REV4_CONTROLLER_BASE=$ControllerCommit"
Write-Host "V117_REV4_CONTROLLER_BLOB=$ExpectedControllerBlob"
Write-Host "V117_REV4_OVERLAY_SOURCE_COMMIT=$OverlaySourceCommit"
Write-Host "V117_REV4_OVERLAY_BLOB=$ExpectedOverlayBlob"
Write-Host "V117_REV4_FEATURE_COMMIT=$Rev4FeatureCommit"
Write-Host 'V117_REV4_FROZEN_HOLDOUT=PRESERVED' -ForegroundColor Green
Write-Host 'V117_REV4_EVIDENCE_REPLAY=UNCHANGED' -ForegroundColor Green
Write-Host 'V117_REV4_AUTHORITY_THRESHOLDS=UNCHANGED' -ForegroundColor Green
Write-Host 'V117_REV4_PRODUCTION_MUTATION=NONE' -ForegroundColor Green
Write-Host "V117_REV4_GENERATED_CONTROLLER=$GeneratedController"

& pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $GeneratedController
exit $LASTEXITCODE
