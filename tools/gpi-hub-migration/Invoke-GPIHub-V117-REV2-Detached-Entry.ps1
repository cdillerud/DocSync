#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$StatePath = Join-Path $ToolRoot 'state.json'
$ControlBranch = 'migration/gpi-hub-dedicated-vm'
$RemoteTrackingRef = "refs/remotes/origin/$ControlBranch"
$LegacyControlCommit = 'b45ae78800b8f6666a6a105318cf0b7bf6fe6648'
$LegacyRepoPath = 'tools/gpi-hub-migration/Invoke-GPIHub-V117-REV2-Detached-Entry.ps1'
$EntryPatchRepoPath = 'tools/gpi-hub-migration/v117-rev3-entry-patch.ps1frag'
$ReplayTransformRepoPath = 'tools/gpi-hub-migration/v117-rev3-replay-transform.ps1frag'
$ExpectedEntryPatchSha256 = '67D0F30B1A4D547C186BC15C8450C3777BF7CDA76CF49B6DCD8E01607B831537'
$ExpectedReplayTransformSha256 = 'EDAF2B455F7F903E82E418DE38642C39E9AF79094042EDD1185797049064A7C6'
$ExpectedFeatureCommit = '2c766d8caf6c64be830949eeddb6ee28a85ef9e6'
$EntryPatchFeatureCommit = 'dc7d1a5716b81b2a2d49d04af1e0f7d22a4e4fa1'

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

function Get-TextSha256 {
    param([string]$Text)
    $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','')
    }
    finally {
        $sha.Dispose()
    }
}

Require (Test-Path -LiteralPath $StatePath -PathType Leaf) "V117 REV3 state missing: $StatePath"
$State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 80
$OperationalRoot = [string]$State.local.operational_root
Require (Test-Path -LiteralPath $OperationalRoot -PathType Container) "V117 REV3 operational repo missing: $OperationalRoot"
Require ($null -ne (Get-Command git.exe -ErrorAction SilentlyContinue)) 'git.exe unavailable.'
Require ($null -ne (Get-Command pwsh.exe -ErrorAction SilentlyContinue)) 'pwsh.exe unavailable.'

$LegacyRaw = Get-GitText -Repo $OperationalRoot -Ref $LegacyControlCommit -RepoPath $LegacyRepoPath
$EntryPatchTemplate = Get-GitText -Repo $OperationalRoot -Ref $RemoteTrackingRef -RepoPath $EntryPatchRepoPath
$ReplayTransform = Get-GitText -Repo $OperationalRoot -Ref $RemoteTrackingRef -RepoPath $ReplayTransformRepoPath

Require ((Get-TextSha256 $EntryPatchTemplate) -eq $ExpectedEntryPatchSha256) 'V117 REV3 entry patch SHA256 drift.'
Require ((Get-TextSha256 $ReplayTransform) -eq $ExpectedReplayTransformSha256) 'V117 REV3 replay transform SHA256 drift.'
Require ($EntryPatchTemplate.Contains('__REPLAY_TRANSFORM_B64__')) 'V117 REV3 replay transform placeholder missing.'
Require ($EntryPatchTemplate.Contains($EntryPatchFeatureCommit)) 'V117 REV3 feature pin anchor missing from validated entry patch.'
$EntryPatchTemplate = $EntryPatchTemplate.Replace($EntryPatchFeatureCommit,$ExpectedFeatureCommit)
Require ($EntryPatchTemplate.Contains($ExpectedFeatureCommit)) 'V117 REV3 dynamic feature repin failed.'

$SemanticGuardMaterializationOld = @'
        'backend/tests/test_ap_routing_v117_corroboration_and_safety_scope.py',
'@
$SemanticGuardMaterializationNew = @'
        'backend/tests/test_ap_routing_v117_corroboration_and_safety_scope.py',
        'backend/tests/test_ap_routing_v117_semantic_authority_guard.py',
        'backend/tests/test_ap_routing_v117_corpus_expansion_holdout_isolation.py',
'@
Require ($EntryPatchTemplate.Contains($SemanticGuardMaterializationOld)) 'V117 REV3 semantic guard materialization anchor missing.'
$EntryPatchTemplate = $EntryPatchTemplate.Replace($SemanticGuardMaterializationOld,$SemanticGuardMaterializationNew)

$SemanticGuardPytestOld = @'
 "$CONTAINER_STAGE/tests/test_ap_routing_v117_corroboration_and_safety_scope.py"
'@
$SemanticGuardPytestNew = @'
 "$CONTAINER_STAGE/tests/test_ap_routing_v117_corroboration_and_safety_scope.py" \
 "$CONTAINER_STAGE/tests/test_ap_routing_v117_semantic_authority_guard.py" \
 "$CONTAINER_STAGE/tests/test_ap_routing_v117_corpus_expansion_holdout_isolation.py"
'@
Require ($EntryPatchTemplate.Contains($SemanticGuardPytestOld)) 'V117 REV3 semantic guard focused-test anchor missing.'
$EntryPatchTemplate = $EntryPatchTemplate.Replace($SemanticGuardPytestOld,$SemanticGuardPytestNew)
Require ($EntryPatchTemplate.Contains('V117_FOCUSED_REGRESSION_TARGET=161')) 'V117 REV3 focused regression target anchor missing.'
$EntryPatchTemplate = $EntryPatchTemplate.Replace('V117_FOCUSED_REGRESSION_TARGET=161','V117_FOCUSED_REGRESSION_TARGET=166')

$EvalModuleImportOld = @'
from services.ap_routing_learned_features_service import SEMANTIC_FEATURE_SCHEMA
from services.ap_routing_semantic_hydration_service import hydrate_accounting_label_with_semantics
import services.ap_routing_corpus_service as _v117_corpus_service
'@
$EvalModuleImportNew = @'
from services.ap_routing_learned_features_service import SEMANTIC_FEATURE_SCHEMA
from services.ap_routing_semantic_hydration_service import hydrate_accounting_label_with_semantics
from services.ap_routing_evaluation_service import split_train_holdout as _v117_native_split_train_holdout
import services.ap_routing_learned_evaluation_service as _v117_learned_eval_module
import services.ap_routing_corpus_service as _v117_corpus_service
'@
Require ($EntryPatchTemplate.Contains($EvalModuleImportOld)) 'V117 REV3 learned evaluator split import anchor missing.'
$EntryPatchTemplate = $EntryPatchTemplate.Replace($EvalModuleImportOld,$EvalModuleImportNew)

$StableSplitOld = @'
_v117_live_expand_high_value_vendor_corpus=expand_high_value_vendor_corpus
_v117_snapshot_replay_active=False
async def _v117_expand_high_value_vendor_corpus_guarded(*args,**kwargs):
'@
$StableSplitNew = @'
_v117_live_expand_high_value_vendor_corpus=expand_high_value_vendor_corpus
_v117_snapshot_replay_active=False
_v117_expected_holdout_source_item_ids=set()

def _v117_split_train_holdout_with_expansion_train_only(examples,*,holdout_bucket=0,buckets=5):
    base=[row for row in examples if not bool(row.get('_v117_expansion_train_only'))]
    expansion=[row for row in examples if bool(row.get('_v117_expansion_train_only'))]
    train,holdout=_v117_native_split_train_holdout(base,holdout_bucket=holdout_bucket,buckets=buckets)
    holdout_source_item_ids={str(row.get('source_item_id')) for row in holdout if row.get('source_item_id')}
    if holdout_source_item_ids!=_v117_expected_holdout_source_item_ids:
        raise RuntimeError(
            'V117 stable holdout identity changed: expected='
            +str(len(_v117_expected_holdout_source_item_ids))
            +';actual='+str(len(holdout_source_item_ids))
        )
    print('V117_STABLE_BASE_HOLDOUT_IDENTITY=PASS',flush=True)
    print('V117_STABLE_BASE_HOLDOUT_COUNT='+str(len(holdout)),flush=True)
    print('V117_EXPANSION_TRAIN_ONLY_COUNT='+str(len(expansion)),flush=True)
    print('V117_EVALUATION_TRAIN_COUNT='+str(len(train)+len(expansion)),flush=True)
    return train+expansion,holdout

_v117_learned_eval_module.split_train_holdout=_v117_split_train_holdout_with_expansion_train_only

async def _v117_expand_high_value_vendor_corpus_guarded(*args,**kwargs):
'@
Require ($EntryPatchTemplate.Contains($StableSplitOld)) 'V117 REV3 stable holdout split anchor missing.'
$EntryPatchTemplate = $EntryPatchTemplate.Replace($StableSplitOld,$StableSplitNew)

$SnapshotExpansionOld = @'
async def _v117_expand_high_value_vendor_corpus_guarded(*args,**kwargs):
    if _v117_snapshot_replay_active:
        print('V117_VENDOR_EXPANSION=SKIPPED_VALIDATED_SNAPSHOT',flush=True)
        return {
'@
$SnapshotExpansionNew = @'
async def _v117_expand_high_value_vendor_corpus_guarded(*args,**kwargs):
    if _v117_snapshot_replay_active:
        print('V117_VENDOR_EXPANSION=LIVE_READONLY_AFTER_VALIDATED_SNAPSHOT',flush=True)
    if False:
        return {
'@
Require ($EntryPatchTemplate.Contains($SnapshotExpansionOld)) 'V117 REV3 snapshot expansion guard anchor missing.'
$EntryPatchTemplate = $EntryPatchTemplate.Replace($SnapshotExpansionOld,$SnapshotExpansionNew)
Require ($EntryPatchTemplate.Contains('V117_VENDOR_EXPANSION=LIVE_READONLY_AFTER_VALIDATED_SNAPSHOT')) 'V117 REV3 snapshot targeted expansion enablement failed.'

$ExpansionReturnOld = @'
    return await _v117_live_expand_high_value_vendor_corpus(*args,**kwargs)
expand_high_value_vendor_corpus=_v117_expand_high_value_vendor_corpus_guarded
'@
$ExpansionReturnNew = @'
    result=await _v117_live_expand_high_value_vendor_corpus(*args,**kwargs)
    for row in list(result.get('examples') or []):
        row['_v117_expansion_train_only']=True
    return result
expand_high_value_vendor_corpus=_v117_expand_high_value_vendor_corpus_guarded
'@
Require ($EntryPatchTemplate.Contains($ExpansionReturnOld)) 'V117 REV3 expansion train-only marker anchor missing.'
$EntryPatchTemplate = $EntryPatchTemplate.Replace($ExpansionReturnOld,$ExpansionReturnNew)

$ReplayRoleOld = @'
    snapshot_replay=bool(replay.get('valid'))
    _v117_snapshot_replay_active=snapshot_replay
'@
$ReplayRoleNew = @'
    if replay.get('valid'):
        try:
            snapshot_payload=json.loads(snapshot_path.read_text(encoding='utf-8'))
            snapshot_role=str(snapshot_payload.get('snapshot_role') or '')
        except Exception:
            snapshot_role=''
        if snapshot_role!='base_corpus_only':
            replay=dict(replay)
            replay['valid']=False
            replay['reason']='snapshot_role_mismatch:'+(snapshot_role or 'missing')
    snapshot_replay=bool(replay.get('valid'))
    _v117_snapshot_replay_active=snapshot_replay
'@
Require ($ReplayTransform.Contains($ReplayRoleOld)) 'V117 REV3 replay snapshot-role anchor missing.'
$ReplayTransform = $ReplayTransform.Replace($ReplayRoleOld,$ReplayRoleNew)

$ReplayMainGlobalTransform = @'
$Raw = Replace-Required -Text $Raw `
    -Old "    global _v117_snapshot_replay_active" `
    -New "    global _v117_snapshot_replay_active,_v117_expected_holdout_source_item_ids" `
    -Marker 'REV3 stable holdout identity global'
'@
$ReplayTransform = $ReplayTransform + "`n" + $ReplayMainGlobalTransform

$ReplayBaseCaptureTransform = @'
$Raw = Replace-Required -Text $Raw `
    -Old "    examples=list(corpus.get('examples') or [])`n    print('V117_VENDOR_EXPANSION_START=1',flush=True)" `
    -New "    examples=list(corpus.get('examples') or [])`n    base_examples=list(examples)`n    base_train_examples,_v117_expansion_holdout=_v117_native_split_train_holdout(base_examples)`n    base_source_item_ids={str(row.get('source_item_id')) for row in base_examples if row.get('source_item_id')}`n    _v117_expected_holdout_source_item_ids={str(row.get('source_item_id')) for row in _v117_expansion_holdout if row.get('source_item_id')}`n    if len(base_source_item_ids)!=len(base_examples):`n        raise RuntimeError('V117 base source-item identity incomplete')`n    if len(_v117_expected_holdout_source_item_ids)!=len(_v117_expansion_holdout):`n        raise RuntimeError('V117 holdout source-item identity incomplete')`n    print('V117_EVALUATION_BASE_COUNT='+str(len(base_examples)),flush=True)`n    print('V117_EXPANSION_TARGET_BASE_TRAIN_COUNT='+str(len(base_train_examples)),flush=True)`n    print('V117_EXPANSION_TARGET_HOLDOUT_EXCLUDED='+str(len(_v117_expansion_holdout)),flush=True)`n    print('V117_EXPANSION_EXCLUDED_BASE_ID_COUNT='+str(len(base_source_item_ids)),flush=True)`n    print('V117_VENDOR_EXPANSION_START=1',flush=True)" `
    -Marker 'REV3 base TRAIN capture plus immutable base identity exclusion'
'@
$ReplayTransform = $ReplayTransform + "`n" + $ReplayBaseCaptureTransform

$ReplayExpansionTargetTransform = @'
$Raw = Replace-Required -Text $Raw `
    -Old "    expansion=await expand_high_value_vendor_corpus(`n        examples," `
    -New "    expansion=await expand_high_value_vendor_corpus(`n        base_train_examples,`n        excluded_source_item_ids=base_source_item_ids," `
    -Marker 'REV3 expansion target selection excludes heldout labels and all base identities'
'@
$ReplayTransform = $ReplayTransform + "`n" + $ReplayExpansionTargetTransform

$ReplayExpansionOverlapTransform = @'
$Raw = Replace-Required -Text $Raw `
    -Old "    merged={}`n    for example in examples + list(expansion.get('examples') or []):" `
    -New "    expansion_examples=list(expansion.get('examples') or [])`n    expansion_source_item_ids={str(row.get('source_item_id')) for row in expansion_examples if row.get('source_item_id')}`n    expansion_base_overlap=sorted(base_source_item_ids & expansion_source_item_ids)`n    print('V117_EXPANSION_SERVICE_EXCLUDED_ID_COUNT='+str(expansion.get('excluded_source_item_id_count') or 0),flush=True)`n    print('V117_EXPANSION_BASE_ID_OVERLAP_COUNT='+str(len(expansion_base_overlap)),flush=True)`n    if expansion_base_overlap:`n        raise RuntimeError('V117 expansion/base source-item overlap detected')`n    merged={}`n    for example in examples + expansion_examples:" `
    -Marker 'REV3 fail closed on expansion/base source identity overlap'
'@
$ReplayTransform = $ReplayTransform + "`n" + $ReplayExpansionOverlapTransform

$ReplayMergedCountTransform = @'
$Raw = Replace-Required -Text $Raw `
    -Old "    examples=list(merged.values())`n    snapshot_path=Path('/tmp/gpi-ap-routing-v117-evidence-snapshot.json')" `
    -New "    examples=list(merged.values())`n    expected_merged_count=len(base_examples)+len(expansion_examples)`n    if len(examples)!=expected_merged_count:`n        raise RuntimeError('V117 merged corpus identity collision: expected='+str(expected_merged_count)+';actual='+str(len(examples)))`n    print('V117_EXPANSION_MERGE_IDENTITY=PASS',flush=True)`n    snapshot_path=Path('/tmp/gpi-ap-routing-v117-evidence-snapshot.json')" `
    -Marker 'REV3 fail closed on any merged identity collision'
'@
$ReplayTransform = $ReplayTransform + "`n" + $ReplayMergedCountTransform

$ReplayTransformB64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($ReplayTransform))
$EntryPatch = $EntryPatchTemplate.Replace('__REPLAY_TRANSFORM_B64__',$ReplayTransformB64)

$EntryReadAnchor = @'
$EntryRaw = (Get-Content -LiteralPath $EntrySourcePath -Raw) -replace "`r",''
'@
Require ($LegacyRaw.Contains($EntryReadAnchor)) 'V117 REV3 legacy entry-read anchor missing.'
$LegacyRaw = $LegacyRaw.Replace($EntryReadAnchor,$EntryReadAnchor + "`n" + $EntryPatch)

$LegacyScpPatchAnchor = @'
$BaseRaw = Replace-Required -Text $BaseRaw `
    -Old "        concurrency=2,`n        persist=False," `
    -New "        concurrency=4,`n        persist=False," `
    -Marker 'base corpus concurrency 4'
'@
$LegacyScpPatchReplacement = @'
$BaseRaw = Replace-Required -Text $BaseRaw `
    -Old "        concurrency=2,`n        persist=False," `
    -New "        concurrency=4,`n        persist=False," `
    -Marker 'base corpus concurrency 4'

$BaseRaw = Replace-Required -Text $BaseRaw `
    -Old "    `$scpArgs = @(`n        '-r'," `
    -New "    `$scpArgs = @(`n        '-O',`n        '-r'," `
    -Marker 'force legacy scp protocol for candidate staging'
'@
Require ($LegacyRaw.Contains($LegacyScpPatchAnchor)) 'V117 REV3 legacy SCP staging patch anchor missing.'
$LegacyRaw = $LegacyRaw.Replace($LegacyScpPatchAnchor,$LegacyScpPatchReplacement)

$SnapshotDigestOld = @'
                'example_count':len(examples),
                'examples':examples,
'@
$SnapshotDigestNew = @'
                'example_count':len(base_examples),
                'semantic_feature_schema':'v117-semantic-v1',
                'snapshot_role':'base_corpus_only',
                'examples_sha256':snapshot_examples_sha256(base_examples),
                'examples':base_examples,
'@
Require ($LegacyRaw.Contains($SnapshotDigestOld)) 'V117 REV3 snapshot digest anchor missing.'
$LegacyRaw = $LegacyRaw.Replace($SnapshotDigestOld,$SnapshotDigestNew)

$SnapshotCountOld = "print('V117_EVIDENCE_SNAPSHOT_COUNT='+str(len(examples)),flush=True)"
$SnapshotCountNew = "print('V117_EVIDENCE_SNAPSHOT_COUNT='+str(len(base_examples)),flush=True)`n    print('V117_EVIDENCE_SNAPSHOT_ROLE=base_corpus_only',flush=True)"
Require ($LegacyRaw.Contains($SnapshotCountOld)) 'V117 REV3 snapshot count anchor missing.'
$LegacyRaw = $LegacyRaw.Replace($SnapshotCountOld,$SnapshotCountNew)

$Rev3MarkerOld = "Write-Host 'V117_REV2_EVIDENCE_SNAPSHOT_CONFIGURED=PASS' -ForegroundColor Green"
$Rev3MarkerNew = $Rev3MarkerOld + "`nWrite-Host 'V117_REV3_VALIDATED_EVIDENCE_REPLAY_CONFIGURED=PASS' -ForegroundColor Green`nWrite-Host 'V117_REV3_INVALID_SNAPSHOT_LIVE_REBUILD_FALLBACK_CONFIGURED=PASS' -ForegroundColor Green`nWrite-Host 'V117_REV3_FOCUSED_REGRESSION_TARGET_CONFIGURED=166' -ForegroundColor Green`nWrite-Host 'V117_REV3_SEMANTIC_EVIDENCE_SCHEMA=v117-semantic-v1' -ForegroundColor Green`nWrite-Host 'V117_REV3_FULL_TRAIN_PROMPT_CONTEXT_CONFIGURED=PASS' -ForegroundColor Green`nWrite-Host 'V117_REV3_HIGH_SPECIFICITY_ANCHOR_AUTHORITY_CONFIGURED=PASS' -ForegroundColor Green`nWrite-Host 'V117_REV3_TRAIN_CORROBORATION_AUTHORITY_CONFIGURED=PASS' -ForegroundColor Green`nWrite-Host 'V117_REV3_SNAPSHOT_TARGETED_EXPANSION_CONFIGURED=PASS' -ForegroundColor Green`nWrite-Host 'V117_REV3_STABLE_BASE_HOLDOUT_CONFIGURED=PASS' -ForegroundColor Green`nWrite-Host 'V117_REV3_EXPANSION_TRAIN_ONLY_CONFIGURED=PASS' -ForegroundColor Green`nWrite-Host 'V117_REV3_BASE_ONLY_SNAPSHOT_CONFIGURED=PASS' -ForegroundColor Green`nWrite-Host 'V117_REV3_DISCRIMINATING_SEMANTIC_GUARD_CONFIGURED=PASS' -ForegroundColor Green`nWrite-Host 'V117_REV3_EXPANSION_TARGET_TRAIN_ONLY_CONFIGURED=PASS' -ForegroundColor Green`nWrite-Host 'V117_REV3_EXPANSION_BASE_ID_EXCLUSION_CONFIGURED=PASS' -ForegroundColor Green`nWrite-Host 'V117_REV3_STABLE_HOLDOUT_IDENTITY_CONFIGURED=PASS' -ForegroundColor Green`nWrite-Host 'V117_REV3_LEGACY_SCP_STAGING_CONFIGURED=PASS' -ForegroundColor Green"
Require ($LegacyRaw.Contains($Rev3MarkerOld)) 'V117 REV3 marker anchor missing.'
$LegacyRaw = $LegacyRaw.Replace($Rev3MarkerOld,$Rev3MarkerNew)

$OverlayPath = Join-Path $ToolRoot 'Invoke-GPIHub-V117-REV3-Replay-Generated.ps1'
Set-Content -LiteralPath $OverlayPath -Value $LegacyRaw -Encoding utf8 -NoNewline

$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($OverlayPath,[ref]$tokens,[ref]$errors)
if (@($errors).Count -gt 0) {
    $text = (@($errors) | ForEach-Object { $_.Message }) -join '; '
    throw "V117 REV3 overlay parse failed: $text"
}

Write-Host 'V117_REV3_RESTARTED_SPRINT=PASS' -ForegroundColor Green
Write-Host "V117_REV3_LEGACY_CONTROL_BASE=$LegacyControlCommit"
Write-Host "V117_REV3_FEATURE_COMMIT=$ExpectedFeatureCommit"
Write-Host 'V117_REV3_DYNAMIC_FEATURE_REPIN=PASS' -ForegroundColor Green
Write-Host "V117_REV3_ENTRY_PATCH_SHA256=$ExpectedEntryPatchSha256"
Write-Host "V117_REV3_REPLAY_TRANSFORM_SHA256=$ExpectedReplayTransformSha256"
Write-Host 'V117_REV3_SNAPSHOT_MAX_AGE_HOURS=24'
Write-Host 'V117_REV3_SNAPSHOT_FAILS_CLOSED_TO_LIVE_REBUILD=PASS' -ForegroundColor Green
Write-Host 'V117_REV3_SNAPSHOT_TARGETED_EXPANSION=LIVE_READONLY' -ForegroundColor Green
Write-Host 'V117_REV3_STABLE_BASE_HOLDOUT=PASS' -ForegroundColor Green
Write-Host 'V117_REV3_EXPANSION_TRAIN_ONLY=PASS' -ForegroundColor Green
Write-Host 'V117_REV3_BASE_ONLY_SNAPSHOT=PASS' -ForegroundColor Green
Write-Host 'V117_REV3_DISCRIMINATING_SEMANTIC_GUARD=PASS' -ForegroundColor Green
Write-Host 'V117_REV3_EXPANSION_TARGET_TRAIN_ONLY=PASS' -ForegroundColor Green
Write-Host 'V117_REV3_EXPANSION_BASE_ID_EXCLUSION=PASS' -ForegroundColor Green
Write-Host 'V117_REV3_STABLE_HOLDOUT_IDENTITY=PASS' -ForegroundColor Green
Write-Host 'V117_REV3_LEGACY_SCP_STAGING=PASS' -ForegroundColor Green
Write-Host 'V117_REV3_PRODUCTION_MUTATION=NONE' -ForegroundColor Green
Write-Host "V117_REV3_GENERATED_CONTROLLER=$OverlayPath"

& pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $OverlayPath
exit $LASTEXITCODE