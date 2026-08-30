#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$StatePath = Join-Path $ToolRoot 'state.json'
$State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 80
$OperationalRoot = [string]$State.local.operational_root
$KeyPath = [string]$State.local.ssh_key
$SourceIp = [string]$State.source.public_ip
$FeatureBranch = 'feature/ap-ai-routing-learning'
$FeatureRef = 'refs/remotes/origin/feature/ap-ai-routing-learning'
$ExpectedFeatureCommit = 'be1b3ad44e1aa7f97fd0ff6102d0638acc04a7a8'
$ExpectedBackendImage = 'sha256:646051f6b0434b20ad429dec18c5f7b2a7d017c0fdec94f4bd77eaa7375fabb3'
$ExpectedHelperSha = '2d2298b9c7e6315745d814e5437687caf463a44dec24d73d710b6d9e4e772117'
$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\v116-ap-routing-heldout-evaluation\$Stamp"
$CandidateRoot = Join-Path $DiagDir 'candidate'
New-Item -ItemType Directory -Path $CandidateRoot -Force | Out-Null
Start-Transcript -LiteralPath (Join-Path $DiagDir 'Invoke-GPIHub-V116-AP-Routing-Heldout-Evaluation.txt') -Force | Out-Null

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
    $stderrFile = Join-Path $env:TEMP "gpi-v116-$token.err.txt"
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
        $stderr = if (Test-Path -LiteralPath $stderrFile) {
            Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue
        }
        else { '' }
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
    param([Parameter(Mandatory)][string]$Ip)
    $diagRoot = Join-Path $OperationalRoot '.gpi-diagnostics'
    foreach ($file in @(Get-ChildItem -LiteralPath $diagRoot -Filter '*known_hosts*' -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)) {
        $probe = Invoke-NativeText -FilePath 'ssh-keygen.exe' -Arguments @('-F',$Ip,'-f',$file.FullName) -AllowFailure
        if ($probe.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($probe.StdOut)) { return $file.FullName }
    }
    throw "No Azure-verified known_hosts file found for $Ip."
}

function Invoke-SshScript {
    param(
        [Parameter(Mandatory)][string]$KnownHosts,
        [Parameter(Mandatory)][string]$ScriptText
    )
    $token = [guid]::NewGuid().ToString('N')
    $stderrFile = Join-Path $env:TEMP "gpi-v116-ssh-$token.err.txt"
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
        $normalized = $ScriptText -replace "`r",""
        $payload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($normalized))
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
        [Parameter(Mandatory)][string]$Ref,
        [Parameter(Mandatory)][string]$RepoPath,
        [Parameter(Mandatory)][string]$Destination
    )
    $parent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $show = Invoke-NativeText -FilePath 'git.exe' -Arguments @('-C',$OperationalRoot,'show',"$Ref`:$RepoPath")
    Set-Content -LiteralPath $Destination -Value $show.StdOut -Encoding utf8 -NoNewline
}

try {
    Section 'V116 - AP ROUTING BROAD HELD-OUT EVALUATION'
    Write-Host 'Classification       : PARITY BLOCKER / MEASURED AUTOMATION'
    Write-Host 'Routing label truth  : LIVE GamerAccounting AP Temp placement (READ ONLY)'
    Write-Host 'Evaluation design    : BALANCED LIVE CORPUS + STABLE 80/20 HOLDOUT'
    Write-Host 'Few-shot design      : MAX 8 / SIMILAR + ROUTE-DIVERSE / TRAIN SPLIT ONLY'
    Write-Host 'Promotion targets    : ZERO WRONG AUTO-ROUTES / 100% AUTO ACCURACY / >=90% COVERAGE'
    Write-Host 'Feature code         : TEMP-STAGED ONLY; /app NOT MODIFIED'
    Write-Host 'Mongo                : NO WRITES / CORPUS persist=False'
    Write-Host 'SharePoint           : PRODUCTION ACCOUNTING READS ONLY / NO MOVES / NO UPLOADS'
    Write-Host 'Business Central     : READ ONLY / PRODUCTION WRITES HARD-BLOCKED'
    Write-Host 'Source runtime       : NO RESTART'
    Write-Host 'Production mutation  : NONE'

    foreach ($cmd in 'git.exe','ssh.exe','scp.exe','ssh-keygen.exe') {
        Require ($null -ne (Get-Command $cmd -ErrorAction SilentlyContinue)) "$cmd unavailable."
    }
    Require (Test-Path -LiteralPath $OperationalRoot -PathType Container) "Operational repo missing: $OperationalRoot"
    Require (Test-Path -LiteralPath $KeyPath -PathType Leaf) "SSH key missing: $KeyPath"

    Section '1. PIN FEATURE BRANCH + MATERIALIZE CANDIDATE FILES'
    [void](Invoke-NativeText -FilePath 'git.exe' -Arguments @(
        '-C',$OperationalRoot,'fetch','origin',"+$FeatureBranch`:$FeatureRef"
    ))
    $resolved = (Invoke-NativeText -FilePath 'git.exe' -Arguments @('-C',$OperationalRoot,'rev-parse',$FeatureRef)).StdOut.Trim()
    Write-Host "V116_FEATURE_COMMIT=$resolved"
    Require ($resolved -eq $ExpectedFeatureCommit) "Feature branch drift: expected $ExpectedFeatureCommit, got $resolved"
    Write-Host 'V116_FEATURE_COMMIT=PASS' -ForegroundColor Green

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
        'backend/config/ap_routing_contract.v1.json'
    )
    foreach ($repoPath in $CandidateFiles) {
        $relative = $repoPath -replace '^backend/',''
        $dest = Join-Path $CandidateRoot ($relative -replace '/', [IO.Path]::DirectorySeparatorChar)
        Materialize-GitTextFile -Ref $FeatureRef -RepoPath $repoPath -Destination $dest
    }
    $ServiceInit = Join-Path $CandidateRoot 'services\__init__.py'
    @'
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)
'@ | Set-Content -LiteralPath $ServiceInit -Encoding utf8 -NoNewline
    Write-Host "V116_CANDIDATE_LOCAL=$CandidateRoot"
    Write-Host 'V116_CANDIDATE_MATERIALIZATION=PASS' -ForegroundColor Green

    $Known = Get-KnownHostsForIp -Ip $SourceIp

    Section '2. STAGE CANDIDATE TO SOURCE HOST TEMP ONLY'
    $prepRemote = Invoke-SshScript -KnownHosts $Known -ScriptText @'
set -euo pipefail
rm -rf /tmp/gpi-ap-routing-v116-stage
mkdir -p /tmp/gpi-ap-routing-v116-stage
chmod 700 /tmp/gpi-ap-routing-v116-stage
'@
    Require ($prepRemote.ExitCode -eq 0) "Source temp prep failed: $($prepRemote.StdErr)"

    $scpArgs = @(
        '-r',
        '-i',$KeyPath,
        '-o','BatchMode=yes',
        '-o','StrictHostKeyChecking=yes',
        '-o',"UserKnownHostsFile=$Known",
        '-o','GlobalKnownHostsFile=NUL',
        '-o','ConnectTimeout=20',
        $CandidateRoot,
        "azureuser@$SourceIp`:/tmp/gpi-ap-routing-v116-stage/"
    )
    [void](Invoke-NativeText -FilePath 'scp.exe' -Arguments $scpArgs)
    Write-Host 'V116_CANDIDATE_SOURCE_TEMP_STAGED=PASS' -ForegroundColor Green

    Section '3. LIVE ACCOUNTING CORPUS + HELD-OUT EVALUATION (READ ONLY)'
    $Remote = @'
set -euo pipefail
EXPECTED_IMAGE='sha256:646051f6b0434b20ad429dec18c5f7b2a7d017c0fdec94f4bd77eaa7375fabb3'
EXPECTED_HELPER='2d2298b9c7e6315745d814e5437687caf463a44dec24d73d710b6d9e4e772117'
HOST_STAGE='/tmp/gpi-ap-routing-v116-stage/candidate'
CONTAINER_STAGE='/tmp/gpi-ap-routing-v116'
PROBE='/tmp/gpi-ap-routing-v116-probe.py'
backend=$(docker ps --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
[ -n "$backend" ] || { echo 'Source backend missing.' >&2; exit 71; }
[ "$(docker inspect "$backend" -f '{{.Image}}')" = "$EXPECTED_IMAGE" ] || { echo 'Source backend image drift.' >&2; exit 72; }
[ "$(docker exec "$backend" sha256sum /app/services/document_intel_helpers.py | awk '{print $1}')" = "$EXPECTED_HELPER" ] || { echo 'Source document helper drift.' >&2; exit 73; }

sp_target=$(docker exec "$backend" sh -c 'printf %s "${SHAREPOINT_TARGET:-}"')
bc_write=$(docker exec "$backend" sh -c 'printf %s "${BC_WRITE_ENABLED:-false}"')
bc_block=$(docker exec "$backend" sh -c 'printf %s "${BC_BLOCK_PRODUCTION_WRITES:-true}"')
[ "$sp_target" = 'test' ] || { echo "Unsafe SHAREPOINT_TARGET=$sp_target" >&2; exit 74; }
case "${bc_write,,}" in false|0|no|'') ;; *) echo "Unsafe BC_WRITE_ENABLED=$bc_write" >&2; exit 75;; esac
case "${bc_block,,}" in true|1|yes) ;; *) echo "Unsafe BC_BLOCK_PRODUCTION_WRITES=$bc_block" >&2; exit 76;; esac
health=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=4); print(r.status)')
case "$health" in 2??|3??) ;; *) echo "Source backend unhealthy: $health" >&2; exit 77;; esac
echo "V116_SOURCE_HEALTH_BEFORE=$health"
echo V116_SOURCE_SAFETY=PASS

rm -f "$PROBE"
docker exec "$backend" rm -rf "$CONTAINER_STAGE"
docker cp "$HOST_STAGE/." "$backend:$CONTAINER_STAGE"

docker exec "$backend" python -c 'import pypdf; print("V116_PYPDF_VERSION=" + str(getattr(pypdf,"__version__","unknown")))'
docker exec "$backend" sh -c "PYTHONPATH='$CONTAINER_STAGE:/app' python -m py_compile \
 '$CONTAINER_STAGE/services/ap_routing_learning_service.py' \
 '$CONTAINER_STAGE/services/ap_routing_decision_service.py' \
 '$CONTAINER_STAGE/services/document_bundle_reference_service.py' \
 '$CONTAINER_STAGE/services/ap_bc_routing_context_service.py' \
 '$CONTAINER_STAGE/services/ap_routing_corpus_service.py' \
 '$CONTAINER_STAGE/services/ap_routing_evaluation_service.py' \
 '$CONTAINER_STAGE/services/ap_routing_feedback_bridge_service.py' \
 '$CONTAINER_STAGE/services/ap_primary_document_service.py' \
 '$CONTAINER_STAGE/services/ap_routing_intelligence_service.py'"
echo V116_CANDIDATE_PYCOMPILE=PASS

cat > "$PROBE" <<'PY'
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

CANDIDATE='/tmp/gpi-ap-routing-v116'
sys.path.insert(0,CANDIDATE)
sys.path.insert(1,'/app')

from database import db as _v116_source_db
from deps import get_db as _v116_get_db, set_db as _v116_set_db
_v116_set_db(_v116_source_db)
if _v116_get_db() is not _v116_source_db:
    raise RuntimeError('V116 read-only DB dependency bootstrap verification failed')
print('V116_READONLY_DB_BOOTSTRAP=PASS',flush=True)

from services.ap_routing_corpus_service import build_supervised_routing_corpus
from services.ap_routing_evaluation_service import (
    evaluate_holdout,
    promotion_gate,
    summarize_evaluation,
)
from services.ap_routing_learning_service import normalize_vendor_name

EXPECTED_AUTHORITY='gamerpackaging1.sharepoint.com/sites/GamerAccounting/General/Accounting/Accounts Payable/Temp Folder'
FEATURE_COMMIT='be1b3ad44e1aa7f97fd0ff6102d0638acc04a7a8'


def load_contract():
    return json.loads(Path(CANDIDATE+'/config/ap_routing_contract.v1.json').read_text(encoding='utf-8'))


def contract_route_known(route, contract):
    route=str(route or '').strip('/')
    if route in set(contract.get('static_routes') or []):
        return True
    for rule in contract.get('dynamic_routes') or []:
        prefix=str(rule.get('prefix') or '').strip('/')
        if prefix and route.startswith(prefix+'/'):
            return True
    return False


async def main():
    contract=load_contract()
    print('V116_CORPUS_BUILD_START=1',flush=True)
    corpus=await build_supervised_routing_corpus(
        None,
        discovery_max_files=50000,
        max_per_route=15,
        max_total=80,
        concurrency=2,
        persist=False,
    )
    authority=str(corpus.get('authority') or '')
    if authority != EXPECTED_AUTHORITY:
        raise RuntimeError(f'Unexpected routing-label authority: {authority}')
    if corpus.get('persisted'):
        raise RuntimeError('V116 corpus unexpectedly persisted data')

    print('V116_ACCOUNTING_AUTHORITY='+authority,flush=True)
    print('V116_DISCOVERED_FILE_COUNT='+str(corpus.get('discovered_file_count')),flush=True)
    print('V116_DISCOVERED_ROUTE_COUNTS='+json.dumps(corpus.get('discovered_route_counts') or {},sort_keys=True),flush=True)
    print('V116_SELECTED_COUNT='+str(corpus.get('selected_count')),flush=True)
    print('V116_HYDRATED_COUNT='+str(corpus.get('hydrated_count')),flush=True)
    print('V116_HYDRATION_FAILURE_COUNT='+str(corpus.get('failure_count')),flush=True)
    for failure in (corpus.get('failures') or [])[:20]:
        print('V116_HYDRATION_FAILURE='+json.dumps(failure,sort_keys=True,default=str),flush=True)

    discovered_routes=list((corpus.get('discovered_route_counts') or {}).keys())
    drift=sorted(route for route in discovered_routes if not contract_route_known(route,contract))
    print('V116_CONTRACT_DRIFT_ROUTES='+json.dumps(drift),flush=True)
    if drift:
        print('V116_CONTRACT_DRIFT=FAIL',flush=True)
        raise SystemExit(94)
    print('V116_CONTRACT_DRIFT=PASS',flush=True)

    examples=list(corpus.get('examples') or [])
    if len(examples)<20:
        print('V116_CORPUS_SUFFICIENCY=FAIL_LT_20_HYDRATED',flush=True)
        raise SystemExit(93)
    if len({str(e.get('route_path') or '') for e in examples})<2:
        print('V116_CORPUS_SUFFICIENCY=FAIL_LT_2_ROUTES',flush=True)
        raise SystemExit(93)
    print('V116_CORPUS_SUFFICIENCY=PASS',flush=True)

    print('V116_HELDOUT_EVALUATION_START=1',flush=True)
    evaluation=await evaluate_holdout(
        examples=examples,
        contract=contract,
        model='gemini-2.5-pro',
        few_shot_limit=8,
    )
    for row in evaluation.get('rows') or []:
        print('V116_HOLDOUT_ROW='+json.dumps(row,sort_keys=True,default=str),flush=True)

    screen_gate=promotion_gate(
        evaluation,
        labeled_example_count=len(examples),
        minimum_examples=20,
        target_coverage=0.90,
        minimum_auto_route_accuracy=1.00,
    )

    label_counts=Counter(
        normalize_vendor_name(e.get('vendor_name')) or 'unknown'
        for e in examples
    )
    rows=evaluation.get('rows') or []
    vendor_gates=[]
    for vendor,label_count in sorted(label_counts.items(),key=lambda kv:(-kv[1],kv[0])):
        vendor_rows=[r for r in rows if (r.get('normalized_vendor') or 'unknown')==vendor]
        if not vendor_rows:
            continue
        vendor_eval=summarize_evaluation(vendor_rows,train_count=0,holdout_count=len(vendor_rows))
        gate=promotion_gate(
            vendor_eval,
            labeled_example_count=label_count,
            minimum_examples=20,
            target_coverage=0.90,
            minimum_auto_route_accuracy=1.00,
        )
        vendor_gates.append({
            'normalized_vendor':vendor,
            'labeled_example_count':label_count,
            'holdout_count':vendor_eval.get('holdout_count'),
            'coverage':vendor_eval.get('coverage'),
            'auto_route_accuracy':vendor_eval.get('auto_route_accuracy'),
            'wrong_auto_routes':vendor_eval.get('wrong_auto_routes'),
            'ready_for_runtime_authority':gate.get('ready_for_runtime_authority'),
            'reasons':gate.get('reasons'),
        })

    summary={
        'schema_version':'1.0',
        'feature_commit':FEATURE_COMMIT,
        'authority':authority,
        'selected_count':corpus.get('selected_count'),
        'hydrated_count':len(examples),
        'hydration_failure_count':corpus.get('failure_count'),
        'train_count':evaluation.get('train_count'),
        'holdout_count':evaluation.get('holdout_count'),
        'auto_routed':evaluation.get('auto_routed'),
        'reviewed':evaluation.get('reviewed'),
        'coverage':evaluation.get('coverage'),
        'auto_route_accuracy':evaluation.get('auto_route_accuracy'),
        'wrong_auto_routes':evaluation.get('wrong_auto_routes'),
        'by_route':evaluation.get('by_route'),
        'by_vendor':evaluation.get('by_vendor'),
        'screen_gate':screen_gate,
        'vendor_gates':vendor_gates,
    }
    print('V116_EVALUATION_SUMMARY='+json.dumps(summary,sort_keys=True,default=str),flush=True)

    holdout=int(evaluation.get('holdout_count') or 0)
    wrong=int(evaluation.get('wrong_auto_routes') or 0)
    coverage=float(evaluation.get('coverage') or 0.0)
    accuracy=evaluation.get('auto_route_accuracy')
    if holdout<8:
        print('V116_MEASURED_AUTOMATION_GATE=FAIL_HOLDOUT_TOO_SMALL',flush=True)
        raise SystemExit(93)
    if wrong>0:
        print('V116_MEASURED_AUTOMATION_GATE=FAIL_WRONG_AUTO_ROUTE',flush=True)
        raise SystemExit(91)
    if accuracy is None or float(accuracy)<1.0:
        print('V116_MEASURED_AUTOMATION_GATE=FAIL_AUTO_ROUTE_ACCURACY',flush=True)
        raise SystemExit(91)
    if coverage<0.90:
        print('V116_MEASURED_AUTOMATION_GATE=FAIL_COVERAGE',flush=True)
        raise SystemExit(92)

    print('V116_MEASURED_AUTOMATION_GATE=PASS_ZERO_WRONG_100PCT_AUTO_ACCURACY_GE90PCT_COVERAGE',flush=True)

asyncio.run(main())
PY

docker cp "$PROBE" "$backend:$PROBE"
set +e
docker exec "$backend" sh -c "PYTHONPATH='$CONTAINER_STAGE:/app' python '$PROBE'"
probe_exit=$?
set -e
echo "V116_HELDOUT_PROBE_EXIT=$probe_exit"

after=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=4); print(r.status)')
echo "V116_SOURCE_HEALTH_AFTER=$after"
[ "$after" = "$health" ] || { echo 'Source health changed during V116.' >&2; exit 78; }
[ "$(docker inspect "$backend" -f '{{.Image}}')" = "$EXPECTED_IMAGE" ] || { echo 'Source backend image changed during V116.' >&2; exit 79; }

docker exec "$backend" rm -rf "$CONTAINER_STAGE" "$PROBE"
rm -rf /tmp/gpi-ap-routing-v116-stage "$PROBE"
echo V116_TEMP_CLEANUP=PASS
echo V116_SOURCE_RUNTIME_UNCHANGED=PASS
exit "$probe_exit"
'@

    $probe = Invoke-SshScript -KnownHosts $Known -ScriptText $Remote
    if (-not [string]::IsNullOrWhiteSpace($probe.StdOut)) { Write-Host $probe.StdOut }
    if (-not [string]::IsNullOrWhiteSpace($probe.StdErr)) { Write-Host $probe.StdErr -ForegroundColor DarkYellow }
    Write-Host "V116_REMOTE_EXIT=$($probe.ExitCode)"
    Require ($probe.ExitCode -eq 0) "V116 held-out evaluation gate failed with exit code $($probe.ExitCode)."

    Section 'V116 RESULT'
    Write-Host 'V116_AP_ROUTING_HELDOUT_EVALUATION=PASS' -ForegroundColor Green
    Write-Host "Diagnostics: $DiagDir"
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
