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
$FeatureBranch = 'feature/v117-model-bakeoff-rev1'
$FeatureRef = "refs/remotes/origin/$FeatureBranch"
$ExpectedFeatureCommit = '53129e098da42bae7f8ab3ef3f8c30659fa4f6fc'
$ExpectedBackendImage = 'sha256:646051f6b0434b20ad429dec18c5f7b2a7d017c0fdec94f4bd77eaa7375fabb3'
$ExpectedHelperSha = '2d2298b9c7e6315745d814e5437687caf463a44dec24d73d710b6d9e4e772117'
$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')

function Require {
    param([bool]$Condition,[string]$Message)
    if (-not $Condition) { throw $Message }
}

function Section([string]$Title) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

function Invoke-NativeText {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$AllowFailure,
        [string]$WorkingDirectory
    )
    $token = [guid]::NewGuid().ToString('N')
    $stderrFile = Join-Path $env:TEMP "gpi-v117-bakeoff-$token.err.txt"
    $oldEap = $ErrorActionPreference
    $nativeVar = Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $oldNative = if ($null -ne $nativeVar) { $nativeVar.Value } else { $null }
    $oldLocation = Get-Location
    try {
        if ($WorkingDirectory) { Set-Location -LiteralPath $WorkingDirectory }
        $ErrorActionPreference = 'Continue'
        if ($null -ne $nativeVar) { $PSNativeCommandUseErrorActionPreference = $false }
        $output = & $FilePath @Arguments 2> $stderrFile
        $code = $LASTEXITCODE
        $stdout = (@($output) | ForEach-Object { [string]$_ }) -join "`n"
        $stderr = if (Test-Path -LiteralPath $stderrFile) { Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue } else { '' }
        $result = [pscustomobject]@{ ExitCode=[int]$code; StdOut=[string]$stdout; StdErr=[string]$stderr }
        if (-not $AllowFailure -and $result.ExitCode -ne 0) {
            throw "$FilePath failed ($($result.ExitCode)).`n$stdout`n$stderr"
        }
        return $result
    }
    finally {
        Set-Location -LiteralPath $oldLocation
        $ErrorActionPreference = $oldEap
        if ($null -ne $nativeVar) { $PSNativeCommandUseErrorActionPreference = $oldNative }
        Remove-Item -LiteralPath $stderrFile -Force -ErrorAction SilentlyContinue
    }
}

function Get-KnownHostsForIp {
    param([Parameter(Mandatory)][string]$Ip,[Parameter(Mandatory)][string]$OperationalRoot)
    $diagRoot = Join-Path $OperationalRoot '.gpi-diagnostics'
    foreach ($file in @(Get-ChildItem -LiteralPath $diagRoot -Filter '*known_hosts*' -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)) {
        $probe = Invoke-NativeText -FilePath 'ssh-keygen.exe' -Arguments @('-F',$Ip,'-f',$file.FullName) -AllowFailure
        if ($probe.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($probe.StdOut)) { return $file.FullName }
    }
    throw "No verified known_hosts file found for $Ip."
}

function Invoke-SshScript {
    param(
        [Parameter(Mandatory)][string]$KnownHosts,
        [Parameter(Mandatory)][string]$KeyPath,
        [Parameter(Mandatory)][string]$SourceIp,
        [Parameter(Mandatory)][string]$ScriptText
    )
    $token = [guid]::NewGuid().ToString('N')
    $stderrFile = Join-Path $env:TEMP "gpi-v117-bakeoff-ssh-$token.err.txt"
    $args = @(
        '-i',$KeyPath,
        '-o','BatchMode=yes',
        '-o','StrictHostKeyChecking=yes',
        '-o',"UserKnownHostsFile=$KnownHosts",
        '-o','GlobalKnownHostsFile=NUL',
        '-o','ConnectTimeout=20',
        "azureuser@$SourceIp",
        'base64 -di | bash'
    )
    $oldEap = $ErrorActionPreference
    $nativeVar = Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $oldNative = if ($null -ne $nativeVar) { $nativeVar.Value } else { $null }
    try {
        $ErrorActionPreference = 'Continue'
        if ($null -ne $nativeVar) { $PSNativeCommandUseErrorActionPreference = $false }
        $payload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($ScriptText -replace "`r",'')))
        $output = $payload | & ssh.exe @args 2> $stderrFile
        $code = $LASTEXITCODE
        $stdout = (@($output) | ForEach-Object { [string]$_ }) -join "`n"
        $stderr = if (Test-Path -LiteralPath $stderrFile) { Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue } else { '' }
        return [pscustomobject]@{ ExitCode=[int]$code; StdOut=[string]$stdout; StdErr=[string]$stderr }
    }
    finally {
        $ErrorActionPreference = $oldEap
        if ($null -ne $nativeVar) { $PSNativeCommandUseErrorActionPreference = $oldNative }
        Remove-Item -LiteralPath $stderrFile -Force -ErrorAction SilentlyContinue
    }
}

function Materialize-GitTextFile {
    param(
        [Parameter(Mandatory)][string]$OperationalRoot,
        [Parameter(Mandatory)][string]$Ref,
        [Parameter(Mandatory)][string]$RepoPath,
        [Parameter(Mandatory)][string]$Destination
    )
    $parent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $show = Invoke-NativeText -FilePath 'git.exe' -Arguments @('-C',$OperationalRoot,'show',"$Ref`:$RepoPath")
    Set-Content -LiteralPath $Destination -Value $show.StdOut -Encoding utf8 -NoNewline
}

Require (Test-Path -LiteralPath $StatePath -PathType Leaf) "State missing: $StatePath"
$State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 80
$OperationalRoot = [string]$State.local.operational_root
$KeyPath = [string]$State.local.ssh_key
$SourceIp = [string]$State.source.public_ip
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\v117-model-bakeoff-rev1\$Stamp"
$CandidateRoot = Join-Path $DiagDir 'candidate'
New-Item -ItemType Directory -Path $CandidateRoot -Force | Out-Null
Start-Transcript -LiteralPath (Join-Path $DiagDir 'Invoke-GPIHub-V117-ModelBakeoff-REV1.txt') -Force | Out-Null

try {
    Section 'V117 MODEL BAKEOFF REV1 — TRAIN ONLY / READ ONLY'
    Write-Host 'Purpose              : compare LLM proposal quality under identical REV7 prompts'
    Write-Host 'Frozen holdout       : EXCLUDED FROM MODEL SELECTION / IDENTITIES NOT EMITTED'
    Write-Host 'Pilot                : all available configured models'
    Write-Host 'Validation           : top two pilot models / disjoint TRAIN targets'
    Write-Host "Pilot target         : $PilotSize"
    Write-Host "Validation target    : $ValidationSize"
    Write-Host "Concurrency/model    : $ConcurrencyPerModel"
    Write-Host 'Prompt equality      : SHA256 asserted before authority replay'
    Write-Host 'SharePoint           : READ ONLY / NO MOVES / NO UPLOADS'
    Write-Host 'Business Central     : READ ONLY / PRODUCTION WRITES HARD-BLOCKED'
    Write-Host 'Mongo                : NO WRITES / corpus persist=False'
    Write-Host 'Runtime              : NO RESTART / NO DEPLOYMENT'
    Write-Host 'Production mutation  : NONE'

    foreach ($cmd in 'git.exe','ssh.exe','scp.exe','ssh-keygen.exe') {
        Require ($null -ne (Get-Command $cmd -ErrorAction SilentlyContinue)) "$cmd unavailable."
    }
    Require (Test-Path -LiteralPath $OperationalRoot -PathType Container) "Operational repo missing: $OperationalRoot"
    Require (Test-Path -LiteralPath $KeyPath -PathType Leaf) "SSH key missing: $KeyPath"

    Section '1. PIN BAKEOFF FEATURE + MATERIALIZE TEMP CANDIDATE'
    [void](Invoke-NativeText -FilePath 'git.exe' -Arguments @('-C',$OperationalRoot,'fetch','origin',"+$FeatureBranch`:$FeatureRef"))
    $resolved = (Invoke-NativeText -FilePath 'git.exe' -Arguments @('-C',$OperationalRoot,'rev-parse',$FeatureRef)).StdOut.Trim()
    Write-Host "V117_BAKEOFF_FEATURE_COMMIT=$resolved"
    Require ($resolved -eq $ExpectedFeatureCommit) "Bakeoff feature drift: expected $ExpectedFeatureCommit, got $resolved"
    Write-Host 'V117_BAKEOFF_FEATURE_COMMIT=PASS' -ForegroundColor Green

    $CandidateFiles = @(
        'backend/services/ap_routing_learning_service.py',
        'backend/services/ap_routing_decision_service.py',
        'backend/services/document_bundle_reference_service.py',
        'backend/services/ap_bc_routing_context_service.py',
        'backend/services/ap_routing_corpus_service.py',
        'backend/services/ap_routing_evaluation_service.py',
        'backend/services/ap_routing_feedback_bridge_service.py',
        'backend/services/ap_primary_document_service.py',
        'backend/services/ap_routing_intelligence_service.py',
        'backend/services/ap_routing_ai_primary_service.py',
        'backend/services/ap_routing_autonomy_performance_service.py',
        'backend/services/ap_routing_learned_features_service.py',
        'backend/services/ap_routing_relevant_learning_service.py',
        'backend/services/ap_routing_train_context_service.py',
        'backend/services/ap_routing_anchor_authority_service.py',
        'backend/services/ap_routing_corroboration_authority_service.py',
        'backend/services/ap_routing_learned_neighborhood_service.py',
        'backend/services/ap_routing_learned_autonomy_service.py',
        'backend/services/ap_routing_learned_safety_service.py',
        'backend/services/ap_routing_learned_pipeline_service.py',
        'backend/services/ap_routing_learned_v117_adapter.py',
        'backend/services/ap_routing_learned_evaluation_service.py',
        'backend/services/ap_routing_semantic_hydration_service.py',
        'backend/services/ap_routing_business_context_service.py',
        'backend/services/ap_routing_model_bakeoff_service.py',
        'backend/tests/test_ap_routing_v117_semantic_authority_guard.py',
        'backend/tests/test_ap_routing_v117_documented_business_context.py',
        'backend/tests/test_ap_routing_v117_model_bakeoff.py',
        'backend/config/ap_routing_contract.v1.json'
    )
    foreach ($repoPath in $CandidateFiles) {
        $relative = $repoPath -replace '^backend/',''
        $dest = Join-Path $CandidateRoot ($relative -replace '/', [IO.Path]::DirectorySeparatorChar)
        Materialize-GitTextFile -OperationalRoot $OperationalRoot -Ref $FeatureRef -RepoPath $repoPath -Destination $dest
    }
    $ServiceInit = Join-Path $CandidateRoot 'services\__init__.py'
    @'
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)
'@ | Set-Content -LiteralPath $ServiceInit -Encoding utf8 -NoNewline
    Write-Host "V117_BAKEOFF_CANDIDATE_LOCAL=$CandidateRoot"
    Write-Host 'V117_BAKEOFF_CANDIDATE_MATERIALIZATION=PASS' -ForegroundColor Green

    $Known = Get-KnownHostsForIp -Ip $SourceIp -OperationalRoot $OperationalRoot

    Section '2. STAGE TO SOURCE HOST TEMP ONLY'
    $prep = Invoke-SshScript -KnownHosts $Known -KeyPath $KeyPath -SourceIp $SourceIp -ScriptText @'
set -euo pipefail
rm -rf /tmp/gpi-v117-model-bakeoff-stage
mkdir -p /tmp/gpi-v117-model-bakeoff-stage
chmod 700 /tmp/gpi-v117-model-bakeoff-stage
rm -f /tmp/gpi-v117-model-bakeoff-result.json /tmp/gpi-v117-model-bakeoff-rows.csv
'@
    Require ($prep.ExitCode -eq 0) "Remote temp prep failed: $($prep.StdErr)"

    $scpArgs = @(
        '-r','-i',$KeyPath,
        '-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
        '-o',"UserKnownHostsFile=$Known",'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=20',
        $CandidateRoot,"azureuser@$SourceIp`:/tmp/gpi-v117-model-bakeoff-stage/"
    )
    [void](Invoke-NativeText -FilePath 'scp.exe' -Arguments $scpArgs)
    Write-Host 'V117_BAKEOFF_SOURCE_TEMP_STAGED=PASS' -ForegroundColor Green

    Section '3. TARGETED REGRESSION + TRAIN-ONLY MODEL BAKEOFF'
    $Remote = @"
set -euo pipefail
EXPECTED_IMAGE='$ExpectedBackendImage'
EXPECTED_HELPER='$ExpectedHelperSha'
HOST_STAGE='/tmp/gpi-v117-model-bakeoff-stage/candidate'
CONTAINER_STAGE='/tmp/gpi-v117-model-bakeoff'
PROBE='/tmp/gpi-v117-model-bakeoff-probe.py'
RESULT_JSON='/tmp/gpi-v117-model-bakeoff-result.json'
RESULT_CSV='/tmp/gpi-v117-model-bakeoff-rows.csv'

backend=''
while IFS= read -r candidate; do
  [ -n "`$candidate" ] || continue
  image="`$(docker inspect "`$candidate" -f '{{.Image}}' 2>/dev/null || true)"
  [ "`$image" = "`$EXPECTED_IMAGE" ] || continue
  helper="`$(docker exec "`$candidate" sha256sum /app/services/document_intel_helpers.py 2>/dev/null | awk '{print `$1}' || true)"
  [ "`$helper" = "`$EXPECTED_HELPER" ] || continue
  backend="`$candidate"
  break
done < <(docker ps --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}')
[ -n "`$backend" ] || { echo 'Certified source backend not found.' >&2; exit 71; }
echo "V117_BAKEOFF_SOURCE_BACKEND=`$backend"

sp_target="`$(docker exec "`$backend" sh -c 'printf %s "`${SHAREPOINT_TARGET:-}"')"
bc_write="`$(docker exec "`$backend" sh -c 'printf %s "`${BC_WRITE_ENABLED:-false}"')"
bc_block="`$(docker exec "`$backend" sh -c 'printf %s "`${BC_BLOCK_PRODUCTION_WRITES:-true}"')"
[ "`$sp_target" = 'test' ] || { echo "Unsafe SHAREPOINT_TARGET=`$sp_target" >&2; exit 74; }
case "`${bc_write,,}" in false|0|no|'') ;; *) echo "Unsafe BC_WRITE_ENABLED=`$bc_write" >&2; exit 75;; esac
case "`${bc_block,,}" in true|1|yes) ;; *) echo "Unsafe BC_BLOCK_PRODUCTION_WRITES=`$bc_block" >&2; exit 76;; esac
health="`$(docker exec "`$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=4); print(r.status)')"
case "`$health" in 2??|3??) ;; *) echo "Source backend unhealthy: `$health" >&2; exit 77;; esac
echo "V117_BAKEOFF_SOURCE_HEALTH_BEFORE=`$health"
echo V117_BAKEOFF_SOURCE_SAFETY=PASS

docker exec "`$backend" rm -rf "`$CONTAINER_STAGE" "`$PROBE" /tmp/v117-model-bakeoff-result.json /tmp/v117-model-bakeoff-rows.csv
docker cp "`$HOST_STAGE/." "`$backend:`$CONTAINER_STAGE"

docker exec "`$backend" sh -c "PYTHONPATH='`$CONTAINER_STAGE:/app' python -m py_compile \\
 '`$CONTAINER_STAGE/services/ap_routing_model_bakeoff_service.py' \\
 '`$CONTAINER_STAGE/services/ap_routing_business_context_service.py' \\
 '`$CONTAINER_STAGE/services/ap_routing_learned_features_service.py' \\
 '`$CONTAINER_STAGE/services/ap_routing_corroboration_authority_service.py'"
echo V117_BAKEOFF_PYCOMPILE=PASS

docker exec "`$backend" sh -c "PYTHONPATH='`$CONTAINER_STAGE:/app' python -m pytest -q \\
 '`$CONTAINER_STAGE/tests/test_ap_routing_v117_semantic_authority_guard.py' \\
 '`$CONTAINER_STAGE/tests/test_ap_routing_v117_documented_business_context.py' \\
 '`$CONTAINER_STAGE/tests/test_ap_routing_v117_model_bakeoff.py'"
echo V117_BAKEOFF_TARGETED_REGRESSIONS=PASS

cat > "`$PROBE" <<'PY'
import asyncio
import csv
import json
import os
import sys
from pathlib import Path

CANDIDATE='/tmp/gpi-v117-model-bakeoff'
sys.path.insert(0,CANDIDATE)
sys.path.insert(1,'/app')

from database import db as _source_db
from deps import get_db as _get_db, set_db as _set_db
_set_db(_source_db)
if _get_db() is not _source_db:
    raise RuntimeError('V117 bakeoff read-only DB bootstrap failed')
print('V117_BAKEOFF_READONLY_DB_BOOTSTRAP=PASS',flush=True)

import services.ap_routing_corpus_service as _corpus_service
from services.ap_routing_corpus_service import build_supervised_routing_corpus
from services.ap_routing_evaluation_service import split_train_holdout
from services.ap_routing_semantic_hydration_service import hydrate_accounting_label_with_semantics
from services.ap_routing_model_bakeoff_service import run_two_stage_bakeoff

_corpus_service.hydrate_accounting_label=hydrate_accounting_label_with_semantics

EXPECTED_AUTHORITY='gamerpackaging1.sharepoint.com/sites/GamerAccounting/General/Accounting/Accounts Payable/Temp Folder'
RESULT_JSON=Path('/tmp/v117-model-bakeoff-result.json')
RESULT_CSV=Path('/tmp/v117-model-bakeoff-rows.csv')
PILOT_SIZE=int(os.environ.get('V117_BAKEOFF_PILOT_SIZE','24'))
VALIDATION_SIZE=int(os.environ.get('V117_BAKEOFF_VALIDATION_SIZE','100'))
CONCURRENCY=int(os.environ.get('V117_BAKEOFF_CONCURRENCY','2'))


def load_contract():
    return json.loads(Path(CANDIDATE+'/config/ap_routing_contract.v1.json').read_text(encoding='utf-8'))


def write_csv(result):
    fields=[
        'stage','model_name','provider','model','target_id','file_name','expected_route',
        'proposed_route','proposal_correct','family_correct','confidence','contract_route_allowed',
        'overconfident_wrong','dnp_false_positive','dynamic_child_unseen_in_train','safe_decision',
        'safe_route','safe_auto','safe_auto_correct','safe_wrong_auto','earned_by','latency_seconds',
        'prompt_sha256','model_error'
    ]
    with RESULT_CSV.open('w',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields)
        writer.writeheader()
        for stage in ('pilot','validation'):
            for model_result in result.get(stage) or []:
                spec=model_result.get('spec') or {}
                for row in model_result.get('rows') or []:
                    writer.writerow({
                        'stage':stage,
                        'model_name':spec.get('name'),
                        'provider':spec.get('provider'),
                        'model':spec.get('model'),
                        **{key:row.get(key) for key in fields if key not in {'stage','model_name','provider','model'}},
                    })


async def main():
    contract=load_contract()
    print('V117_BAKEOFF_CORPUS_BUILD_START=1',flush=True)
    corpus=await build_supervised_routing_corpus(
        None,
        discovery_max_files=50000,
        max_per_route=8,
        max_total=180,
        concurrency=4,
        persist=False,
        routing_contract=contract,
    )
    authority=str(corpus.get('authority') or '')
    if authority != EXPECTED_AUTHORITY:
        raise RuntimeError('unexpected routing label authority')
    if corpus.get('persisted'):
        raise RuntimeError('bakeoff corpus unexpectedly persisted data')
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

    result=await run_two_stage_bakeoff(
        train_examples=train,
        contract=contract,
        pilot_size=PILOT_SIZE,
        validation_size=VALIDATION_SIZE,
        finalists=2,
        concurrency_per_model=CONCURRENCY,
    )
    RESULT_JSON.write_text(json.dumps(result,indent=2,sort_keys=True,default=str),encoding='utf-8')
    write_csv(result)

    print('V117_BAKEOFF_PREFLIGHT='+json.dumps(result.get('preflight') or [],sort_keys=True,default=str),flush=True)
    print('V117_BAKEOFF_AVAILABLE_MODELS='+json.dumps(result.get('available_models') or [],sort_keys=True,default=str),flush=True)
    print('V117_BAKEOFF_PILOT_TARGET_COUNT='+str(result.get('pilot_target_count') or 0),flush=True)
    print('V117_BAKEOFF_VALIDATION_TARGET_COUNT='+str(result.get('validation_target_count') or 0),flush=True)
    print('V117_BAKEOFF_PILOT_VALIDATION_OVERLAP_COUNT='+str(result.get('pilot_validation_overlap_count') or 0),flush=True)
    print('V117_BAKEOFF_PROMPT_HASH_MISMATCH_COUNT='+str(result.get('prompt_hash_mismatch_count') or 0),flush=True)
    for row in result.get('pilot') or []:
        print('V117_BAKEOFF_PILOT_MODEL='+json.dumps({'spec':row.get('spec'),'summary':row.get('summary')},sort_keys=True,default=str),flush=True)
    print('V117_BAKEOFF_FINALISTS='+json.dumps(result.get('finalists') or [],sort_keys=True,default=str),flush=True)
    for row in result.get('validation') or []:
        print('V117_BAKEOFF_VALIDATION_MODEL='+json.dumps({'spec':row.get('spec'),'summary':row.get('summary')},sort_keys=True,default=str),flush=True)

    if result.get('error'):
        print('V117_BAKEOFF_GATE=FAIL_'+str(result.get('error')).upper(),flush=True)
        raise SystemExit(96)
    if int(result.get('pilot_validation_overlap_count') or 0)!=0:
        print('V117_BAKEOFF_GATE=FAIL_PILOT_VALIDATION_OVERLAP',flush=True)
        raise SystemExit(97)
    if int(result.get('prompt_hash_mismatch_count') or 0)!=0:
        print('V117_BAKEOFF_GATE=FAIL_PROMPT_HASH_MISMATCH',flush=True)
        raise SystemExit(97)
    if len(result.get('validation') or [])<2:
        print('V117_BAKEOFF_GATE=FAIL_LT2_VALIDATION_MODELS',flush=True)
        raise SystemExit(96)
    print('V117_BAKEOFF_GATE=PASS_TRAIN_ONLY_IDENTICAL_PROMPTS',flush=True)

asyncio.run(main())
PY

docker cp "`$PROBE" "`$backend:`$PROBE"
set +e
docker exec "`$backend" sh -c "V117_BAKEOFF_PILOT_SIZE='$PilotSize' V117_BAKEOFF_VALIDATION_SIZE='$ValidationSize' V117_BAKEOFF_CONCURRENCY='$ConcurrencyPerModel' PYTHONPATH='`$CONTAINER_STAGE:/app' python '`$PROBE'"
probe_exit=`$?
set -e
echo "V117_BAKEOFF_PROBE_EXIT=`$probe_exit"

if docker exec "`$backend" test -f /tmp/v117-model-bakeoff-result.json; then
  docker cp "`$backend:/tmp/v117-model-bakeoff-result.json" "`$RESULT_JSON"
fi
if docker exec "`$backend" test -f /tmp/v117-model-bakeoff-rows.csv; then
  docker cp "`$backend:/tmp/v117-model-bakeoff-rows.csv" "`$RESULT_CSV"
fi

after="`$(docker exec "`$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=4); print(r.status)')"
echo "V117_BAKEOFF_SOURCE_HEALTH_AFTER=`$after"
[ "`$after" = "`$health" ] || { echo 'Source health changed during bakeoff.' >&2; exit 78; }
[ "`$(docker inspect "`$backend" -f '{{.Image}}')" = "`$EXPECTED_IMAGE" ] || { echo 'Source image changed during bakeoff.' >&2; exit 79; }
docker exec "`$backend" rm -rf "`$CONTAINER_STAGE" "`$PROBE" /tmp/v117-model-bakeoff-result.json /tmp/v117-model-bakeoff-rows.csv
echo V117_BAKEOFF_CONTAINER_TEMP_CLEANUP=PASS
echo V117_BAKEOFF_SOURCE_RUNTIME_UNCHANGED=PASS
exit "`$probe_exit"
"@

    $probe = Invoke-SshScript -KnownHosts $Known -KeyPath $KeyPath -SourceIp $SourceIp -ScriptText $Remote
    if (-not [string]::IsNullOrWhiteSpace($probe.StdOut)) { Write-Host $probe.StdOut }
    if (-not [string]::IsNullOrWhiteSpace($probe.StdErr)) { Write-Host $probe.StdErr -ForegroundColor DarkYellow }
    Write-Host "V117_BAKEOFF_REMOTE_EXIT=$($probe.ExitCode)"

    Section '4. RETRIEVE BAKEOFF ARTIFACTS'
    foreach ($name in 'gpi-v117-model-bakeoff-result.json','gpi-v117-model-bakeoff-rows.csv') {
        $remotePath = "/tmp/$name"
        $dest = Join-Path $DiagDir $name
        $get = Invoke-NativeText -FilePath 'scp.exe' -Arguments @(
            '-i',$KeyPath,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
            '-o',"UserKnownHostsFile=$Known",'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=20',
            "azureuser@$SourceIp`:$remotePath",$dest
        ) -AllowFailure
        if ($get.ExitCode -eq 0 -and (Test-Path -LiteralPath $dest -PathType Leaf)) {
            Write-Host "V117_BAKEOFF_ARTIFACT=$dest" -ForegroundColor Green
        } else {
            Write-Host "V117_BAKEOFF_ARTIFACT_MISSING=$name" -ForegroundColor Yellow
        }
    }

    [void](Invoke-SshScript -KnownHosts $Known -KeyPath $KeyPath -SourceIp $SourceIp -ScriptText @'
set -euo pipefail
rm -rf /tmp/gpi-v117-model-bakeoff-stage
rm -f /tmp/gpi-v117-model-bakeoff-result.json /tmp/gpi-v117-model-bakeoff-rows.csv
'@)
    Write-Host 'V117_BAKEOFF_HOST_TEMP_CLEANUP=PASS' -ForegroundColor Green

    Require ($probe.ExitCode -eq 0) "V117 model bakeoff failed with exit code $($probe.ExitCode)."

    Section 'V117 MODEL BAKEOFF REV1 RESULT'
    Write-Host 'V117_MODEL_BAKEOFF_REV1=PASS' -ForegroundColor Green
    Write-Host "Diagnostics: $DiagDir"
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
