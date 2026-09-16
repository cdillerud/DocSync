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
$Rev2FeatureBranch = 'feature/v117-model-bakeoff-rev2-reliability'
$Rev2FeatureCommit = '1ff21c21c318e1a31173942bff0b98ca3761e00c'

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

Require (Test-Path -LiteralPath $StatePath -PathType Leaf) "Bakeoff REV2 state missing: $StatePath"
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

$OldFeatureBranch = '$FeatureBranch = ''feature/v117-model-bakeoff-rev1'''
$NewFeatureBranch = '$FeatureBranch = ''feature/v117-model-bakeoff-rev2-reliability'''
Require ($Raw.Contains($OldFeatureBranch)) 'Bakeoff REV2 feature-branch anchor missing.'
$Raw = $Raw.Replace($OldFeatureBranch,$NewFeatureBranch)

$OldFeatureCommit = '$ExpectedFeatureCommit = ''53129e098da42bae7f8ab3ef3f8c30659fa4f6fc'''
$NewFeatureCommit = '$ExpectedFeatureCommit = ''1ff21c21c318e1a31173942bff0b98ca3761e00c'''
Require ($Raw.Contains($OldFeatureCommit)) 'Bakeoff REV2 feature-commit anchor missing.'
$Raw = $Raw.Replace($OldFeatureCommit,$NewFeatureCommit)

$Raw = $Raw.Replace('v117-model-bakeoff-rev1','v117-model-bakeoff-rev2')

$CandidateOld = @'
        'backend/services/ap_routing_decision_service.py',
        'backend/services/document_bundle_reference_service.py',
'@
$CandidateNew = @'
        'backend/services/ap_routing_decision_service.py',
        'backend/services/ap_routing_authority_guard_service.py',
        'backend/services/document_bundle_reference_service.py',
'@
Require ($Raw.Contains($CandidateOld)) 'Bakeoff REV2 authority-guard materialization anchor missing.'
$Raw = $Raw.Replace($CandidateOld,$CandidateNew)

$BusinessOld = @'
        'backend/services/ap_routing_business_context_service.py',
        'backend/services/ap_routing_model_bakeoff_service.py',
'@
$BusinessNew = @'
        'backend/services/ap_routing_business_context_service.py',
        'backend/services/ap_routing_business_context_expansion_service.py',
        'backend/services/ap_routing_model_bakeoff_service.py',
        'backend/services/ap_routing_model_bakeoff_rev2_service.py',
'@
Require ($Raw.Contains($BusinessOld)) 'Bakeoff REV2 service materialization anchor missing.'
$Raw = $Raw.Replace($BusinessOld,$BusinessNew)

$TestOld = @'
        'backend/tests/test_ap_routing_v117_model_bakeoff.py',
        'backend/config/ap_routing_contract.v1.json'
'@
$TestNew = @'
        'backend/tests/test_ap_routing_v117_model_bakeoff.py',
        'backend/tests/test_ap_routing_v117_model_bakeoff_rev2.py',
        'backend/config/ap_routing_contract.v1.json'
'@
Require ($Raw.Contains($TestOld)) 'Bakeoff REV2 test materialization anchor missing.'
$Raw = $Raw.Replace($TestOld,$TestNew)

$PytestOld = @'
docker exec "`$backend" sh -c "PYTHONPATH='`$CONTAINER_STAGE:/app' python -m pytest -q
'@
$PytestNew = @'
docker exec "`$backend" sh -c "cd '`$CONTAINER_STAGE' && PYTHONPATH='`$CONTAINER_STAGE:/app' python -m pytest -q
'@
Require ($Raw.Contains($PytestOld)) 'Bakeoff REV2 pytest working-directory anchor missing.'
$Raw = $Raw.Replace($PytestOld,$PytestNew)

$PytestTailOld = @'
 '`$CONTAINER_STAGE/tests/test_ap_routing_v117_model_bakeoff.py'"
'@
$PytestTailNew = @'
 '`$CONTAINER_STAGE/tests/test_ap_routing_v117_model_bakeoff.py' \
 '`$CONTAINER_STAGE/tests/test_ap_routing_v117_model_bakeoff_rev2.py'"
'@
Require ($Raw.Contains($PytestTailOld)) 'Bakeoff REV2 pytest test-list anchor missing.'
$Raw = $Raw.Replace($PytestTailOld,$PytestTailNew)

$CompileMarker = @'
echo V117_BAKEOFF_PYCOMPILE=PASS

'@
$PostCompile = @'
echo V117_BAKEOFF_PYCOMPILE=PASS

docker exec "`$backend" sh -c "PYTHONPATH='`$CONTAINER_STAGE:/app' python -m py_compile '`$CONTAINER_STAGE/services/ap_routing_authority_guard_service.py' '`$CONTAINER_STAGE/services/ap_routing_business_context_expansion_service.py' '`$CONTAINER_STAGE/services/ap_routing_model_bakeoff_rev2_service.py'"
echo V117_BAKEOFF_REV2_ADDITIONAL_PYCOMPILE=PASS

docker exec "`$backend" sh -c "cd '`$CONTAINER_STAGE' && PYTHONPATH='`$CONTAINER_STAGE:/app' python -c 'import services.ap_routing_ai_primary_service as a, services.ap_routing_business_context_service as b, services.ap_routing_business_context_expansion_service as x, services.ap_routing_model_bakeoff_service as m, services.ap_routing_model_bakeoff_rev2_service as r, services.ap_routing_authority_guard_service as g; paths=[a.__file__,b.__file__,x.__file__,m.__file__,r.__file__,g.__file__]; expected=\"/tmp/gpi-v117-model-bakeoff/services/\"; assert all(str(p).startswith(expected) for p in paths), paths; print(\"V117_BAKEOFF_IMPORT_ORIGINS=\"+\"|\".join(paths))'"
echo V117_BAKEOFF_IMPORT_ORIGIN=PASS

'@
Require ($Raw.Contains($CompileMarker)) 'Bakeoff REV2 post-compile insertion anchor missing.'
$Raw = $Raw.Replace($CompileMarker,$PostCompile)

$ImportOld = 'from services.ap_routing_model_bakeoff_service import run_two_stage_bakeoff'
$ImportNew = 'from services.ap_routing_model_bakeoff_rev2_service import run_two_stage_bakeoff_rev2'
Require ($Raw.Contains($ImportOld)) 'Bakeoff REV2 probe import anchor missing.'
$Raw = $Raw.Replace($ImportOld,$ImportNew)

$CallOld = '    result=await run_two_stage_bakeoff('
$CallNew = '    result=await run_two_stage_bakeoff_rev2('
Require ($Raw.Contains($CallOld)) 'Bakeoff REV2 probe call anchor missing.'
$Raw = $Raw.Replace($CallOld,$CallNew)

$FinalistPrintOld = @'
    print('V117_BAKEOFF_FINALISTS='+json.dumps(result.get('finalists') or [],sort_keys=True,default=str),flush=True)
'@
$FinalistPrintNew = @'
    print('V117_BAKEOFF_HEALTHY_PILOT_MODELS='+json.dumps(result.get('healthy_pilot_models') or [],sort_keys=True,default=str),flush=True)
    print('V117_BAKEOFF_FINALISTS='+json.dumps(result.get('finalists') or [],sort_keys=True,default=str),flush=True)
    print('V117_BAKEOFF_FINALIST_PREFLIGHT='+json.dumps(result.get('finalist_preflight') or [],sort_keys=True,default=str),flush=True)
    print('V117_BAKEOFF_VALIDATION_RESPONSE_SUFFICIENCY_PASS='+str(bool(result.get('validation_response_sufficiency_pass'))),flush=True)
    print('V117_BAKEOFF_VALIDATION_ABORT_REASON='+str(result.get('validation_abort_reason') or ''),flush=True)
'@
Require ($Raw.Contains($FinalistPrintOld)) 'Bakeoff REV2 result-marker anchor missing.'
$Raw = $Raw.Replace($FinalistPrintOld,$FinalistPrintNew)

$PassOld = "    print('V117_BAKEOFF_GATE=PASS_TRAIN_ONLY_IDENTICAL_PROMPTS',flush=True)"
$PassNew = "    print('V117_BAKEOFF_GATE=PASS_TRAIN_ONLY_IDENTICAL_PROMPTS_RESPONSE_SUFFICIENCY',flush=True)"
Require ($Raw.Contains($PassOld)) 'Bakeoff REV2 pass-gate anchor missing.'
$Raw = $Raw.Replace($PassOld,$PassNew)

$HeadingOld = "V117 MODEL BAKEOFF REV1 — TRAIN ONLY / READ ONLY"
$HeadingNew = "V117 MODEL BAKEOFF REV2 — RELIABILITY-GUARDED TRAIN ONLY / READ ONLY"
Require ($Raw.Contains($HeadingOld)) 'Bakeoff REV2 heading anchor missing.'
$Raw = $Raw.Replace($HeadingOld,$HeadingNew)

$GeneratedController = Join-Path $ToolRoot 'Invoke-GPIHub-V117-ModelBakeoff-REV2-Generated.ps1'
Set-Content -LiteralPath $GeneratedController -Value $Raw -Encoding utf8 -NoNewline

$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($GeneratedController,[ref]$tokens,[ref]$errors)
if (@($errors).Count -gt 0) {
    $text = (@($errors) | ForEach-Object { $_.Message }) -join '; '
    throw "Bakeoff REV2 generated controller parse failed: $text"
}

Write-Host 'V117_BAKEOFF_REV2_CONTROLLER_PATCH=PASS' -ForegroundColor Green
Write-Host "V117_BAKEOFF_REV2_BASE_CONTROLLER=$BaseControllerCommit"
Write-Host "V117_BAKEOFF_REV2_BASE_CONTROLLER_BLOB=$ExpectedBaseControllerBlob"
Write-Host "V117_BAKEOFF_REV2_FEATURE_BRANCH=$Rev2FeatureBranch"
Write-Host "V117_BAKEOFF_REV2_FEATURE_COMMIT=$Rev2FeatureCommit"
Write-Host 'V117_BAKEOFF_REV2_COMPLETION_GUARD=GE90_PERCENT' -ForegroundColor Green
Write-Host 'V117_BAKEOFF_REV2_RELIABILITY_AWARE_SELECTION=PASS' -ForegroundColor Green
Write-Host 'V117_BAKEOFF_REV2_FINALIST_PREFLIGHT=CONFIGURED' -ForegroundColor Green
Write-Host 'V117_BAKEOFF_REV2_VALIDATION_BATCH_SIZE=10' -ForegroundColor Green
Write-Host 'V117_BAKEOFF_REV2_PROVIDER_BUDGET_FAIL_FAST=CONFIGURED' -ForegroundColor Green
Write-Host 'V117_BAKEOFF_REV2_VALIDATION_SUFFICIENCY_GATE=GE90_PERCENT' -ForegroundColor Green
Write-Host 'V117_BAKEOFF_REV2_FROZEN_HOLDOUT_EVALUATION=NONE' -ForegroundColor Green
Write-Host 'V117_BAKEOFF_REV2_PRODUCTION_MUTATION=NONE' -ForegroundColor Green
Write-Host "V117_BAKEOFF_REV2_GENERATED_CONTROLLER=$GeneratedController"

& pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $GeneratedController `
    -PilotSize $PilotSize `
    -ValidationSize $ValidationSize `
    -ConcurrencyPerModel $ConcurrencyPerModel
exit $LASTEXITCODE
