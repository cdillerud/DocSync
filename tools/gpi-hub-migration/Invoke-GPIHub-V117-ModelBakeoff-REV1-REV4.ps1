#requires -Version 7.0
[CmdletBinding()]
param(
    [int]$PilotSize = 24,
    [int]$ValidationSize = 100,
    [int]$ConcurrencyPerModel = 2
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$StatePath = Join-Path $ToolRoot 'state.json'
$BaseControllerCommit = '0c945c0a491a083a0545fac58f2a6409f75c05e8'
$BaseControllerRepoPath = 'tools/gpi-hub-migration/Invoke-GPIHub-V117-ModelBakeoff-REV1.ps1'
$ExpectedBaseControllerBlob = '58151913d0dd99d3537c97d781f88257558719a5'

function Require {
    param([bool]$Condition,[string]$Message)
    if (-not $Condition) { throw $Message }
}

function Get-GitText {
    param([string]$Repo,[string]$Ref,[string]$RepoPath)
    $spec = "{0}:{1}" -f $Ref,$RepoPath
    $lines = & git.exe -C $Repo show $spec
    $code = $LASTEXITCODE
    Require ($code -eq 0) "Could not read $RepoPath from $Ref."
    return ((@($lines) | ForEach-Object { [string]$_ }) -join "`n") -replace "`r",''
}

Require (Test-Path -LiteralPath $StatePath -PathType Leaf) "Bakeoff REV4 state missing: $StatePath"
Require ($null -ne (Get-Command git.exe -ErrorAction SilentlyContinue)) 'git.exe unavailable.'
Require ($null -ne (Get-Command pwsh.exe -ErrorAction SilentlyContinue)) 'pwsh.exe unavailable.'

$State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 80
$OperationalRoot = [string]$State.local.operational_root
Require (Test-Path -LiteralPath $OperationalRoot -PathType Container) "Operational repo missing: $OperationalRoot"

$baseSpec = "{0}:{1}" -f $BaseControllerCommit,$BaseControllerRepoPath
$baseBlob = (& git.exe -C $OperationalRoot rev-parse $baseSpec).Trim()
Require ($LASTEXITCODE -eq 0) 'Could not resolve bakeoff REV1 controller blob.'
Require ($baseBlob -ceq $ExpectedBaseControllerBlob) "Bakeoff REV1 controller blob drift: $baseBlob"

$Raw = Get-GitText -Repo $OperationalRoot -Ref $BaseControllerCommit -RepoPath $BaseControllerRepoPath

$CandidateOld = @'
        'backend/services/ap_routing_decision_service.py',
        'backend/services/document_bundle_reference_service.py',
'@
$CandidateNew = @'
        'backend/services/ap_routing_decision_service.py',
        'backend/services/ap_routing_authority_guard_service.py',
        'backend/services/document_bundle_reference_service.py',
'@
Require ($Raw.Contains($CandidateOld)) 'Bakeoff REV4 authority-guard materialization anchor missing.'
$Raw = $Raw.Replace($CandidateOld,$CandidateNew)

$BusinessOld = @'
        'backend/services/ap_routing_business_context_service.py',
        'backend/services/ap_routing_model_bakeoff_service.py',
'@
$BusinessNew = @'
        'backend/services/ap_routing_business_context_service.py',
        'backend/services/ap_routing_business_context_expansion_service.py',
        'backend/services/ap_routing_model_bakeoff_service.py',
'@
Require ($Raw.Contains($BusinessOld)) 'Bakeoff REV4 business-context expansion materialization anchor missing.'
$Raw = $Raw.Replace($BusinessOld,$BusinessNew)

$CompileOld = @'
 '$CONTAINER_STAGE/services/ap_routing_business_context_service.py' \
 '$CONTAINER_STAGE/services/ap_routing_learned_features_service.py' \
'@
$CompileNew = @'
 '$CONTAINER_STAGE/services/ap_routing_business_context_service.py' \
 '$CONTAINER_STAGE/services/ap_routing_business_context_expansion_service.py' \
 '$CONTAINER_STAGE/services/ap_routing_learned_features_service.py' \
'@
Require ($Raw.Contains($CompileOld)) 'Bakeoff REV4 business-context expansion pycompile anchor missing.'
$Raw = $Raw.Replace($CompileOld,$CompileNew)

$PytestOld = @'
docker exec "`$backend" sh -c "PYTHONPATH='`$CONTAINER_STAGE:/app' python -m pytest -q
'@
$PytestNew = @'
docker exec "`$backend" sh -c "cd '`$CONTAINER_STAGE' && PYTHONPATH='`$CONTAINER_STAGE:/app' python -m pytest -q
'@
Require ($Raw.Contains($PytestOld)) 'Bakeoff REV4 pytest working-directory anchor missing.'
$Raw = $Raw.Replace($PytestOld,$PytestNew)

$CompileMarker = @'
echo V117_BAKEOFF_PYCOMPILE=PASS

'@
$OriginProof = @'
echo V117_BAKEOFF_PYCOMPILE=PASS

docker exec "`$backend" sh -c "cd '`$CONTAINER_STAGE' && PYTHONPATH='`$CONTAINER_STAGE:/app' python -c 'import services.ap_routing_ai_primary_service as a, services.ap_routing_business_context_service as b, services.ap_routing_business_context_expansion_service as x, services.ap_routing_model_bakeoff_service as m, services.ap_routing_authority_guard_service as g; paths=[a.__file__,b.__file__,x.__file__,m.__file__,g.__file__]; expected=\"/tmp/gpi-v117-model-bakeoff/services/\"; assert all(str(p).startswith(expected) for p in paths), paths; print(\"V117_BAKEOFF_IMPORT_ORIGINS=\"+\"|\".join(paths))'"
echo V117_BAKEOFF_IMPORT_ORIGIN=PASS

'@
Require ($Raw.Contains($CompileMarker)) 'Bakeoff REV4 import-origin insertion anchor missing.'
$Raw = $Raw.Replace($CompileMarker,$OriginProof)

$HeadingOld = "V117 MODEL BAKEOFF REV1 — TRAIN ONLY / READ ONLY"
$HeadingNew = "V117 MODEL BAKEOFF REV1 REV4 — TRAIN ONLY / READ ONLY"
Require ($Raw.Contains($HeadingOld)) 'Bakeoff REV4 heading anchor missing.'
$Raw = $Raw.Replace($HeadingOld,$HeadingNew)

$GeneratedController = Join-Path $ToolRoot 'Invoke-GPIHub-V117-ModelBakeoff-REV1-REV4-Generated.ps1'
Set-Content -LiteralPath $GeneratedController -Value $Raw -Encoding utf8 -NoNewline

$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($GeneratedController,[ref]$tokens,[ref]$errors)
if (@($errors).Count -gt 0) {
    $text = (@($errors) | ForEach-Object { $_.Message }) -join '; '
    throw "Bakeoff REV4 generated controller parse failed: $text"
}

Write-Host 'V117_BAKEOFF_REV4_CONTROLLER_PATCH=PASS' -ForegroundColor Green
Write-Host "V117_BAKEOFF_REV4_BASE_CONTROLLER=$BaseControllerCommit"
Write-Host "V117_BAKEOFF_REV4_BASE_CONTROLLER_BLOB=$ExpectedBaseControllerBlob"
Write-Host 'V117_BAKEOFF_REV4_AUTHORITY_GUARD_STAGED=PASS' -ForegroundColor Green
Write-Host 'V117_BAKEOFF_REV4_BUSINESS_CONTEXT_EXPANSION_STAGED=PASS' -ForegroundColor Green
Write-Host 'V117_BAKEOFF_REV4_PYTEST_CWD=CANDIDATE_ROOT' -ForegroundColor Green
Write-Host 'V117_BAKEOFF_REV4_IMPORT_ORIGIN_ASSERTION=CONFIGURED' -ForegroundColor Green
Write-Host 'V117_BAKEOFF_REV4_PRODUCTION_MUTATION=NONE' -ForegroundColor Green
Write-Host "V117_BAKEOFF_REV4_GENERATED_CONTROLLER=$GeneratedController"

& pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $GeneratedController `
    -PilotSize $PilotSize `
    -ValidationSize $ValidationSize `
    -ConcurrencyPerModel $ConcurrencyPerModel
exit $LASTEXITCODE
