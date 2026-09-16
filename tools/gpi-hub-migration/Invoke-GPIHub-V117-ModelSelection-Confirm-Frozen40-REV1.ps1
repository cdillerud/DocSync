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
$BaseControllerCommit = '7598ed3229fef8be216db445d02b3b4d55c5bf3d'
$BaseControllerRepoPath = 'tools/gpi-hub-migration/Invoke-GPIHub-V117-ModelBakeoff-REV3-Detached.ps1'
$ExpectedBaseControllerBlob = 'c60e18803f2936511fe1ffc0e6ab5f76e405e2f4'
$ExpectedSnapshotSha256 = 'ADCC312CDB639A364F84FF6CCA5AE9BC19D4DA1EB6451D80167CA9750D569A9E'
$ExpectedFrozenHoldoutDigest = '1D3B9B8E116ADFCFDE03B5B775A6CB9584A171CDDBDE5FF24339F302809F3D88'
$ExpectedFrozenBaseCount = 177
$ExpectedFrozenHoldoutCount = 40

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

Require (Test-Path -LiteralPath $StatePath -PathType Leaf) "Frozen-40 confirmation state missing: $StatePath"
Require ($null -ne (Get-Command git.exe -ErrorAction SilentlyContinue)) 'git.exe unavailable.'
Require ($null -ne (Get-Command pwsh.exe -ErrorAction SilentlyContinue)) 'pwsh.exe unavailable.'

$State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 80
$OperationalRoot = [string]$State.local.operational_root
Require (Test-Path -LiteralPath $OperationalRoot -PathType Container) "Operational repo missing: $OperationalRoot"

$baseSpec = "{0}:{1}" -f $BaseControllerCommit,$BaseControllerRepoPath
$baseBlob = (& git.exe -C $OperationalRoot rev-parse $baseSpec).Trim()
Require ($LASTEXITCODE -eq 0) 'Could not resolve detached bakeoff controller blob.'
Require ($baseBlob -ceq $ExpectedBaseControllerBlob) "Detached bakeoff controller blob drift: $baseBlob"

$Raw = Get-GitText -Repo $OperationalRoot -Ref $BaseControllerCommit -RepoPath $BaseControllerRepoPath

$InvokeOld = @'
& pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $GeneratedWrapper `
    -PilotSize $PilotSize `
    -ValidationSize $ValidationSize `
    -ConcurrencyPerModel $ConcurrencyPerModel
exit $LASTEXITCODE
'@

$InvokeNew = @'
$ConfirmWrapperRaw = Get-Content -LiteralPath $GeneratedWrapper -Raw

$InnerInvokeOld = @'
& pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $GeneratedController `
    -PilotSize $PilotSize `
    -ValidationSize $ValidationSize `
    -ConcurrencyPerModel $ConcurrencyPerModel
exit $LASTEXITCODE
'@

$InnerInvokeNew = @'
$ConfirmControllerRaw = Get-Content -LiteralPath $GeneratedController -Raw

$ImportOld = @'
import asyncio
import csv
import json
import os
import sys
from pathlib import Path
'@
$ImportNew = @'
import asyncio
import csv
import hashlib
import json
import os
import sys
from pathlib import Path
'@
Require ($ConfirmControllerRaw.Contains($ImportOld)) 'Frozen-40 confirmation Python import anchor missing.'
$ConfirmControllerRaw = $ConfirmControllerRaw.Replace($ImportOld,$ImportNew)

$BakeoffImportOld = 'from services.ap_routing_model_bakeoff_rev2_service import run_two_stage_bakeoff_rev2'
$BakeoffImportNew = @'
from services.ap_routing_model_bakeoff_rev2_service import run_two_stage_bakeoff_rev2
from services.ap_routing_model_bakeoff_service import _row_id
'@
Require ($ConfirmControllerRaw.Contains($BakeoffImportOld)) 'Frozen-40 confirmation bakeoff import anchor missing.'
$ConfirmControllerRaw = $ConfirmControllerRaw.Replace($BakeoffImportOld,$BakeoffImportNew)

$SplitOld = @'
    examples=list(corpus.get('examples') or [])
    if len(examples)<40:
        raise RuntimeError('bakeoff base corpus too small')
    train,holdout=split_train_holdout(examples)
    train=[{**row,'split':'train'} for row in train]
    print('V117_BAKEOFF_BASE_CORPUS_COUNT='+str(len(examples)),flush=True)
    print('V117_BAKEOFF_TRAIN_COUNT='+str(len(train)),flush=True)
    print('V117_BAKEOFF_FROZEN_HOLDOUT_EXCLUDED_COUNT='+str(len(holdout)),flush=True)
    print('V117_BAKEOFF_HOLDOUT_IDENTITIES_EMITTED=NO',flush=True)
    print('V117_BAKEOFF_HOLDOUT_USED_FOR_SELECTION=NO',flush=True)
'@
$SplitNew = @'
    examples=list(corpus.get('examples') or [])
    if len(examples)<124:
        raise RuntimeError('confirmation live corpus too small')

    snapshot_path=Path('/tmp/gpi-ap-routing-v117-evidence-snapshot.json')
    if not snapshot_path.is_file():
        raise RuntimeError('frozen base-corpus snapshot missing')
    snapshot_bytes=snapshot_path.read_bytes()
    snapshot_sha=hashlib.sha256(snapshot_bytes).hexdigest().upper()
    if snapshot_sha!='ADCC312CDB639A364F84FF6CCA5AE9BC19D4DA1EB6451D80167CA9750D569A9E':
        raise RuntimeError('frozen snapshot SHA256 drift:'+snapshot_sha)
    snapshot=json.loads(snapshot_bytes.decode('utf-8'))
    if str(snapshot.get('snapshot_role') or '')!='base_corpus_only':
        raise RuntimeError('frozen snapshot role mismatch')
    frozen_base=list(snapshot.get('examples') or [])
    if len(frozen_base)!=177:
        raise RuntimeError('frozen base count mismatch:'+str(len(frozen_base)))
    _,frozen_holdout=split_train_holdout(frozen_base)
    frozen_row_ids={_row_id(row) for row in frozen_holdout if _row_id(row)}
    frozen_source_ids={str(row.get('source_item_id')) for row in frozen_holdout if row.get('source_item_id')}
    if len(frozen_row_ids)!=40 or len(frozen_source_ids)!=40:
        raise RuntimeError('frozen holdout identity count mismatch')
    frozen_digest=hashlib.sha256(('\n'.join(sorted(frozen_row_ids))).encode('utf-8')).hexdigest().upper()
    if frozen_digest!='1D3B9B8E116ADFCFDE03B5B775A6CB9584A171CDDBDE5FF24339F302809F3D88':
        raise RuntimeError('frozen holdout identity digest drift:'+frozen_digest)

    excluded=[]
    train=[]
    for row in examples:
        rid=_row_id(row)
        sid=str(row.get('source_item_id') or '')
        if (rid and rid in frozen_row_ids) or (sid and sid in frozen_source_ids):
            excluded.append(row)
            continue
        train.append({**row,'split':'train'})
    residual_overlap=sum(
        1 for row in train
        if (_row_id(row) in frozen_row_ids)
        or (str(row.get('source_item_id') or '') in frozen_source_ids)
    )
    if residual_overlap!=0:
        raise RuntimeError('frozen holdout residual overlap:'+str(residual_overlap))
    if len(train)<124:
        raise RuntimeError('frozen40-excluded confirmation pool too small:'+str(len(train)))

    train_row_ids={_row_id(row) for row in train if _row_id(row)}
    train_source_ids={str(row.get('source_item_id')) for row in train if row.get('source_item_id')}
    train_row_digest=hashlib.sha256(('\n'.join(sorted(train_row_ids))).encode('utf-8')).hexdigest().upper()
    train_source_digest=hashlib.sha256(('\n'.join(sorted(train_source_ids))).encode('utf-8')).hexdigest().upper()

    print('V117_CONFIRM_LIVE_CORPUS_COUNT='+str(len(examples)),flush=True)
    print('V117_CONFIRM_FROZEN_BASE_COUNT='+str(len(frozen_base)),flush=True)
    print('V117_CONFIRM_FROZEN_HOLDOUT_COUNT='+str(len(frozen_holdout)),flush=True)
    print('V117_CONFIRM_FROZEN_HOLDOUT_DIGEST='+frozen_digest,flush=True)
    print('V117_CONFIRM_MATCHING_FROZEN_ROWS_REMOVED='+str(len(excluded)),flush=True)
    print('V117_CONFIRM_SELECTION_POOL_COUNT='+str(len(train)),flush=True)
    print('V117_CONFIRM_SELECTION_POOL_ROW_ID_DIGEST='+train_row_digest,flush=True)
    print('V117_CONFIRM_SELECTION_POOL_SOURCE_ID_DIGEST='+train_source_digest,flush=True)
    print('V117_CONFIRM_FROZEN40_RESIDUAL_OVERLAP_COUNT='+str(residual_overlap),flush=True)
    print('V117_CONFIRM_HOLDOUT_IDENTITIES_EMITTED=NO',flush=True)
    print('V117_CONFIRM_FROZEN_HOLDOUT_USED_FOR_SELECTION=NO',flush=True)
'@
Require ($ConfirmControllerRaw.Contains($SplitOld)) 'Frozen-40 confirmation corpus/split anchor missing.'
$ConfirmControllerRaw = $ConfirmControllerRaw.Replace($SplitOld,$SplitNew)

$CallOld = @'
    result=await run_two_stage_bakeoff_rev2(
        train_examples=train,
        contract=contract,
        pilot_size=PILOT_SIZE,
        validation_size=VALIDATION_SIZE,
        finalists=2,
        concurrency_per_model=CONCURRENCY,
    )
'@
$CallNew = @'
    confirm_specs=[
        {'provider':'openai','model':'gpt-5.6-sol','name':'gpt-5.6-sol'},
        {'provider':'anthropic','model':'claude-sonnet-4-6','name':'claude-sonnet-4-6'},
    ]
    result=await run_two_stage_bakeoff_rev2(
        train_examples=train,
        contract=contract,
        model_specs=confirm_specs,
        pilot_size=PILOT_SIZE,
        validation_size=VALIDATION_SIZE,
        finalists=2,
        concurrency_per_model=CONCURRENCY,
    )
    result['schema_version']='v117-model-selection-confirm-frozen40-rev1'
    result['frozen40_selection_isolation']={
        'pass': True,
        'snapshot_sha256': snapshot_sha,
        'frozen_base_count': len(frozen_base),
        'frozen_holdout_count': len(frozen_holdout),
        'frozen_holdout_identity_digest': frozen_digest,
        'live_corpus_count': len(examples),
        'matching_frozen_rows_removed': len(excluded),
        'selection_pool_count': len(train),
        'selection_pool_row_id_digest': train_row_digest,
        'selection_pool_source_id_digest': train_source_digest,
        'residual_overlap_count': residual_overlap,
        'holdout_identities_emitted': False,
        'holdout_used_for_selection': False,
    }
'@
Require ($ConfirmControllerRaw.Contains($CallOld)) 'Frozen-40 confirmation model-call anchor missing.'
$ConfirmControllerRaw = $ConfirmControllerRaw.Replace($CallOld,$CallNew)

$PrintOld = @'
    print('V117_BAKEOFF_PREFLIGHT='+json.dumps(result.get('preflight') or [],sort_keys=True,default=str),flush=True)
'@
$PrintNew = @'
    print('V117_CONFIRM_FROZEN40_SELECTION_ISOLATION='+json.dumps(result.get('frozen40_selection_isolation') or {},sort_keys=True,default=str),flush=True)
    print('V117_BAKEOFF_PREFLIGHT='+json.dumps(result.get('preflight') or [],sort_keys=True,default=str),flush=True)
'@
Require ($ConfirmControllerRaw.Contains($PrintOld)) 'Frozen-40 confirmation result-print anchor missing.'
$ConfirmControllerRaw = $ConfirmControllerRaw.Replace($PrintOld,$PrintNew)

$GateOld = @'
    if result.get('error'):
        print('V117_BAKEOFF_GATE=FAIL_'+str(result.get('error')).upper(),flush=True)
        raise SystemExit(96)
'@
$GateNew = @'
    isolation=result.get('frozen40_selection_isolation') or {}
    if not isolation.get('pass') or int(isolation.get('residual_overlap_count') or 0)!=0:
        print('V117_BAKEOFF_GATE=FAIL_FROZEN40_SELECTION_ISOLATION',flush=True)
        raise SystemExit(98)
    if result.get('error'):
        print('V117_BAKEOFF_GATE=FAIL_'+str(result.get('error')).upper(),flush=True)
        raise SystemExit(96)
'@
Require ($ConfirmControllerRaw.Contains($GateOld)) 'Frozen-40 confirmation gate anchor missing.'
$ConfirmControllerRaw = $ConfirmControllerRaw.Replace($GateOld,$GateNew)

$PassOld = "    print('V117_BAKEOFF_GATE=PASS_TRAIN_ONLY_IDENTICAL_PROMPTS_RESPONSE_SUFFICIENCY',flush=True)"
$PassNew = "    print('V117_BAKEOFF_GATE=PASS_EXACT_FROZEN40_EXCLUDED_IDENTICAL_PROMPTS_RESPONSE_SUFFICIENCY',flush=True)"
Require ($ConfirmControllerRaw.Contains($PassOld)) 'Frozen-40 confirmation pass marker anchor missing.'
$ConfirmControllerRaw = $ConfirmControllerRaw.Replace($PassOld,$PassNew)

Set-Content -LiteralPath $GeneratedController -Value $ConfirmControllerRaw -Encoding utf8 -NoNewline
$ct = $null
$ce = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($GeneratedController,[ref]$ct,[ref]$ce)
if (@($ce).Count -gt 0) {
    throw ('Frozen-40 confirmation generated controller parse failed: ' + ((@($ce) | ForEach-Object { $_.Message }) -join '; '))
}

Write-Host 'V117_CONFIRM_EXACT_FROZEN40_EXCLUSION_PATCH=PASS' -ForegroundColor Green
Write-Host 'V117_CONFIRM_MODELS=GPT-5.6-SOL|CLAUDE-SONNET-4-6' -ForegroundColor Green
Write-Host 'V117_CONFIRM_SNAPSHOT_SHA256=ADCC312CDB639A364F84FF6CCA5AE9BC19D4DA1EB6451D80167CA9750D569A9E' -ForegroundColor Green
Write-Host 'V117_CONFIRM_FROZEN_HOLDOUT_DIGEST=1D3B9B8E116ADFCFDE03B5B775A6CB9584A171CDDBDE5FF24339F302809F3D88' -ForegroundColor Green
Write-Host 'V117_CONFIRM_PRODUCTION_MUTATION=NONE' -ForegroundColor Green

& pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $GeneratedController `
    -PilotSize $PilotSize `
    -ValidationSize $ValidationSize `
    -ConcurrencyPerModel $ConcurrencyPerModel
exit $LASTEXITCODE
'@

Require ($ConfirmWrapperRaw.Contains($InnerInvokeOld)) 'Frozen-40 confirmation REV2 invocation anchor missing.'
$ConfirmWrapperRaw = $ConfirmWrapperRaw.Replace($InnerInvokeOld,$InnerInvokeNew)
Set-Content -LiteralPath $GeneratedWrapper -Value $ConfirmWrapperRaw -Encoding utf8 -NoNewline
$wt = $null
$we = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($GeneratedWrapper,[ref]$wt,[ref]$we)
if (@($we).Count -gt 0) {
    throw ('Frozen-40 confirmation generated wrapper parse failed: ' + ((@($we) | ForEach-Object { $_.Message }) -join '; '))
}

Write-Host 'V117_CONFIRM_WRAPPER_PATCH=PASS' -ForegroundColor Green
Write-Host 'V117_CONFIRM_EXECUTION_MODE=DETACHED_REMOTE_WITH_SHORT_POLLING' -ForegroundColor Green
Write-Host 'V117_CONFIRM_SELECTION_LOGIC=REV2_RELIABILITY_AWARE_UNCHANGED' -ForegroundColor Green
Write-Host 'V117_CONFIRM_AUTHORITY_THRESHOLDS=UNCHANGED' -ForegroundColor Green
Write-Host 'V117_CONFIRM_FROZEN_HOLDOUT_EVALUATION=NONE' -ForegroundColor Green
Write-Host 'V117_CONFIRM_PRODUCTION_MUTATION=NONE' -ForegroundColor Green

& pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $GeneratedWrapper `
    -PilotSize $PilotSize `
    -ValidationSize $ValidationSize `
    -ConcurrencyPerModel $ConcurrencyPerModel
exit $LASTEXITCODE
'@

Require ($Raw.Contains($InvokeOld)) 'Frozen-40 confirmation detached-controller invocation anchor missing.'
$Raw = $Raw.Replace($InvokeOld,$InvokeNew)

$GeneratedConfirm = Join-Path $ToolRoot 'Invoke-GPIHub-V117-ModelSelection-Confirm-Frozen40-REV1-Generated.ps1'
Set-Content -LiteralPath $GeneratedConfirm -Value $Raw -Encoding utf8 -NoNewline
$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($GeneratedConfirm,[ref]$tokens,[ref]$errors)
if (@($errors).Count -gt 0) {
    throw ('Frozen-40 confirmation generated entry parse failed: ' + ((@($errors) | ForEach-Object { $_.Message }) -join '; '))
}

Write-Host 'V117_CONFIRM_CONTROLLER_PATCH=PASS' -ForegroundColor Green
Write-Host "V117_CONFIRM_BASE_DETACHED_CONTROLLER=$BaseControllerCommit"
Write-Host "V117_CONFIRM_BASE_DETACHED_CONTROLLER_BLOB=$ExpectedBaseControllerBlob"
Write-Host "V117_CONFIRM_EXPECTED_SNAPSHOT_SHA256=$ExpectedSnapshotSha256"
Write-Host "V117_CONFIRM_EXPECTED_FROZEN_HOLDOUT_DIGEST=$ExpectedFrozenHoldoutDigest"
Write-Host "V117_CONFIRM_EXPECTED_FROZEN_BASE_COUNT=$ExpectedFrozenBaseCount"
Write-Host "V117_CONFIRM_EXPECTED_FROZEN_HOLDOUT_COUNT=$ExpectedFrozenHoldoutCount"
Write-Host 'V117_CONFIRM_MODEL_CALL_SCOPE=GPT-5.6-SOL|CLAUDE-SONNET-4-6' -ForegroundColor Green
Write-Host 'V117_CONFIRM_HOLDOUT_SELECTION_INPUT=NONE' -ForegroundColor Green
Write-Host 'V117_CONFIRM_PRODUCTION_MUTATION=NONE' -ForegroundColor Green
Write-Host "V117_CONFIRM_GENERATED_ENTRY=$GeneratedConfirm"

& pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $GeneratedConfirm `
    -PilotSize $PilotSize `
    -ValidationSize $ValidationSize `
    -ConcurrencyPerModel $ConcurrencyPerModel
exit $LASTEXITCODE
