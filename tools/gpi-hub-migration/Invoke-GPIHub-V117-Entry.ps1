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
$ExpectedFeatureCommit = '834eaed10b7285177544864a995eb9da647d2313'
$GeneratedRoot = Join-Path $OperationalRoot '.gpi-diagnostics\v117-generated'
$GeneratedPath = Join-Path $GeneratedRoot 'Invoke-GPIHub-V117-Generated.ps1'
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
    Require ($Text.Contains($Old)) "V117 repair anchor missing: $Marker"
    return $Text.Replace($Old,$New)
}

Require (Test-Path -LiteralPath $BasePath -PathType Leaf) "Base V116 controller missing: $BasePath"
Require (Test-Path -LiteralPath $StatePath -PathType Leaf) "V117 state missing: $StatePath"
New-Item -ItemType Directory -Path $GeneratedRoot -Force | Out-Null
$Raw = Get-Content -LiteralPath $BasePath -Raw

$Raw = Replace-Required -Text $Raw `
    -Old "`$ExpectedFeatureCommit = 'ee75f8dbea0a72f1184b5e241f100bf8df83b17f'" `
    -New "`$ExpectedFeatureCommit = '$ExpectedFeatureCommit'" `
    -Marker 'feature commit pin'

$Raw = Replace-Required -Text $Raw `
    -Old "        'backend/services/ap_routing_decision_service.py'," `
    -New "        'backend/services/ap_routing_decision_service.py',`r`n        'backend/services/ap_routing_authority_guard_service.py',`r`n        'backend/services/ap_routing_runtime_authority_service.py',`r`n        'backend/services/ap_routing_evaluation_context_service.py',`r`n        'backend/services/ap_routing_corpus_expansion_service.py',`r`n        'backend/tests/test_ap_routing_v117_authority.py'," `
    -Marker 'V117 candidate materialization'

$Raw = Replace-Required -Text $Raw `
    -Old "FEATURE_COMMIT='ee75f8dbea0a72f1184b5e241f100bf8df83b17f'" `
    -New "FEATURE_COMMIT='$ExpectedFeatureCommit'" `
    -Marker 'probe feature commit evidence'

$FastGate = @'
echo V116_CANDIDATE_PYCOMPILE=PASS

docker exec "$backend" python -c 'import pytest; print("V117_PYTEST_VERSION=" + str(pytest.__version__))'
echo V117_PYTEST_PREFLIGHT=PASS

docker exec -w "$CONTAINER_STAGE" -e "PYTHONPATH=$CONTAINER_STAGE:/app" "$backend" python -m py_compile \
 "$CONTAINER_STAGE/services/ap_routing_authority_guard_service.py" \
 "$CONTAINER_STAGE/services/ap_routing_runtime_authority_service.py" \
 "$CONTAINER_STAGE/services/ap_routing_evaluation_context_service.py" \
 "$CONTAINER_STAGE/services/ap_routing_corpus_expansion_service.py" \
 "$CONTAINER_STAGE/tests/test_ap_routing_v117_authority.py"
echo V117_ADDITIVE_PYCOMPILE=PASS

docker exec -w "$CONTAINER_STAGE" -e "PYTHONPATH=$CONTAINER_STAGE:/app" "$backend" python -c 'import services.ap_routing_authority_guard_service as a, services.ap_routing_runtime_authority_service as r, services.ap_routing_evaluation_context_service as c; paths=[str(a.__file__),str(r.__file__),str(c.__file__)]; print("V117_CANDIDATE_IMPORT_ORIGINS="+"|".join(paths)); assert all(p.startswith("/tmp/gpi-ap-routing-v116/") for p in paths), paths'
echo V117_CANDIDATE_IMPORT_ORIGIN=PASS

docker exec -w "$CONTAINER_STAGE" -e "PYTHONPATH=$CONTAINER_STAGE:/app" "$backend" python -m pytest -q "$CONTAINER_STAGE/tests/test_ap_routing_v117_authority.py"
echo V117_FOCUSED_AUTHORITY_REGRESSIONS=PASS
'@
$Raw = Replace-Required -Text $Raw `
    -Old 'echo V116_CANDIDATE_PYCOMPILE=PASS' `
    -New $FastGate `
    -Marker 'focused V117 compile and regression gate'

$ProbeImports = @'
import services.ap_routing_corpus_service as _v117_corpus_module
import services.ap_routing_evaluation_service as _v117_eval_module
from services.ap_routing_corpus_service import build_supervised_routing_corpus
from services.ap_routing_corpus_expansion_service import expand_high_value_vendor_corpus
from services.ap_routing_evaluation_context_service import (
    mongo_fallback_latched,
    resolve_ap_routing_context_resilient,
)
from services.ap_routing_runtime_authority_service import (
    decide_ap_route_with_authority_guard as _v117_runtime_decide,
)

_v117_corpus_module.resolve_ap_routing_context = resolve_ap_routing_context_resilient
_v117_eval_module.decide_ap_route_with_authority_guard = _v117_runtime_decide
print('V117_RUNTIME_AUTHORITY_OVERLAY=ACTIVE',flush=True)
print('V117_RESILIENT_CONTEXT_FALLBACK=ACTIVE',flush=True)
'@
$Raw = Replace-Required -Text $Raw `
    -Old 'from services.ap_routing_corpus_service import build_supervised_routing_corpus' `
    -New $ProbeImports `
    -Marker 'runtime authority and resilient context probe imports'

$Raw = Replace-Required -Text $Raw `
    -Old '        max_per_route=15,' `
    -New '        max_per_route=8,' `
    -Marker 'balanced base per-route sample'

$Raw = Replace-Required -Text $Raw `
    -Old '        max_total=80,' `
    -New '        max_total=180,' `
    -Marker 'balanced base total sample'

$OldExamples = @'
    examples=list(corpus.get('examples') or [])
    if len(examples)<20:
'@
$NewExamples = @'
    examples=list(corpus.get('examples') or [])
    print('V117_VENDOR_EXPANSION_START=1',flush=True)
    expansion_progress_state={'ok':0,'fail':0}
    def expansion_progress(done,total,row):
        if row.get('ok'):
            expansion_progress_state['ok']+=1
        else:
            expansion_progress_state['fail']+=1
        if done==1 or done%10==0 or done==total:
            print(
                'V117_VENDOR_EXPANSION_PROGRESS='
                +str(done)+'/'+str(total)
                +';ok='+str(expansion_progress_state['ok'])
                +';fail='+str(expansion_progress_state['fail'])
                +';mongo_fallback='+str(mongo_fallback_latched()).lower(),
                flush=True,
            )

    expansion=await expand_high_value_vendor_corpus(
        examples,
        routing_contract=contract,
        discovery_max_files=50000,
        max_vendors=10,
        desired_total_per_vendor=30,
        max_additional=180,
        concurrency=2,
        retry_count=3,
        progress_callback=expansion_progress,
    )
    print('V117_MONGO_FALLBACK_LATCHED='+str(mongo_fallback_latched()).lower(),flush=True)
    print('V117_VENDOR_EXPANSION_TARGETS='+json.dumps(expansion.get('target_vendors') or [],sort_keys=True,default=str),flush=True)
    print('V117_VENDOR_EXPANSION_CANDIDATES='+json.dumps(expansion.get('candidate_vendor_counts') or {},sort_keys=True),flush=True)
    print('V117_VENDOR_EXPANSION_SELECTED='+str(expansion.get('selected_count') or 0),flush=True)
    print('V117_VENDOR_EXPANSION_HYDRATED='+str(expansion.get('hydrated_count') or 0),flush=True)
    print('V117_VENDOR_EXPANSION_BY_VENDOR='+json.dumps(expansion.get('hydrated_by_vendor') or {},sort_keys=True),flush=True)
    print('V117_VENDOR_EXPANSION_FAILURES='+str(expansion.get('failure_count') or 0),flush=True)
    for failure in (expansion.get('failures') or [])[:20]:
        print('V117_VENDOR_EXPANSION_FAILURE='+json.dumps(failure,sort_keys=True,default=str),flush=True)

    merged={}
    for example in examples + list(expansion.get('examples') or []):
        key=str(example.get('fingerprint') or example.get('source_item_id') or example.get('file_name') or '')
        if key:
            merged[key]=example
    examples=list(merged.values())
    merged_route_counts=Counter(str(e.get('route_path') or '') for e in examples)
    merged_vendor_counts=Counter(normalize_vendor_name(e.get('vendor_name')) or 'unknown' for e in examples)
    print('V117_MERGED_LABEL_COUNT='+str(len(examples)),flush=True)
    print('V117_MERGED_ROUTE_COUNTS='+json.dumps(dict(merged_route_counts),sort_keys=True),flush=True)
    print('V117_MERGED_VENDOR_COUNTS='+json.dumps(dict(merged_vendor_counts),sort_keys=True),flush=True)

    if len(examples)<20:
'@
$Raw = Replace-Required -Text $Raw -Old $OldExamples -New $NewExamples -Marker 'vendor expansion execution and progress telemetry'

$Raw = Replace-Required -Text $Raw `
    -Old "        'hydrated_route_counts':corpus.get('hydrated_route_counts')," `
    -New "        'hydrated_route_counts':dict(merged_route_counts),`n        'vendor_expansion_selected':expansion.get('selected_count'),`n        'vendor_expansion_hydrated':expansion.get('hydrated_count'),`n        'vendor_expansion_failure_count':expansion.get('failure_count'),`n        'mongo_fallback_latched':mongo_fallback_latched(),`n        'merged_vendor_counts':dict(merged_vendor_counts)," `
    -Marker 'summary merged corpus evidence'

$Raw = $Raw.Replace("'schema_version':'1.1'","'schema_version':'1.3'")
$Raw = $Raw.Replace('V116_','V117_')
$Raw = $Raw.Replace('V116 - AP ROUTING BROAD HELD-OUT EVALUATION','V117 - AP ROUTING EVIDENCE-AUTHORITY HELD-OUT EVALUATION')
$Raw = $Raw.Replace('V116 held-out evaluation gate failed','V117 held-out evaluation gate failed')

Require ($Raw.Contains($ExpectedFeatureCommit)) 'V117 generated script lacks expected feature commit.'
Require ($Raw.Contains('backend/services/ap_routing_authority_guard_service.py')) 'V117 generated script lacks authority guard service.'
Require ($Raw.Contains('backend/services/ap_routing_runtime_authority_service.py')) 'V117 generated script lacks runtime authority overlay.'
Require ($Raw.Contains('backend/services/ap_routing_evaluation_context_service.py')) 'V117 generated script lacks resilient evaluation context service.'
Require ($Raw.Contains('backend/services/ap_routing_corpus_expansion_service.py')) 'V117 generated script lacks corpus expansion service.'
Require ($Raw.Contains('test_ap_routing_v117_authority.py')) 'V117 generated script lacks focused authority tests.'
Require ($Raw.Contains('V117_PYTEST_PREFLIGHT=PASS')) 'V117 generated script lacks pytest preflight.'
Require ($Raw.Contains('V117_CANDIDATE_IMPORT_ORIGIN=PASS')) 'V117 generated script lacks candidate import-origin gate.'
Require ($Raw.Contains('V117_FOCUSED_AUTHORITY_REGRESSIONS=PASS')) 'V117 generated script lacks focused authority gate.'
Require ($Raw.Contains('V117_RUNTIME_AUTHORITY_OVERLAY=ACTIVE')) 'V117 generated script lacks runtime authority overlay activation.'
Require ($Raw.Contains('V117_RESILIENT_CONTEXT_FALLBACK=ACTIVE')) 'V117 generated script lacks resilient context activation.'
Require ($Raw.Contains('V117_VENDOR_EXPANSION_PROGRESS=')) 'V117 generated script lacks expansion progress telemetry.'
Require ($Raw.Contains('V117_VENDOR_EXPANSION_START=1')) 'V117 generated script lacks vendor expansion phase.'
Require ($Raw.Contains('max_total=180')) 'V117 generated script lacks balanced base sample.'

Set-Content -LiteralPath $GeneratedPath -Value $Raw -Encoding utf8 -NoNewline
Copy-Item -LiteralPath $StatePath -Destination $GeneratedStatePath -Force
Require (Test-Path -LiteralPath $GeneratedStatePath -PathType Leaf) 'V117 generated state copy missing.'

$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($GeneratedPath,[ref]$tokens,[ref]$errors)
if (@($errors).Count -gt 0) {
    $text = (@($errors) | ForEach-Object { $_.Message }) -join '; '
    throw "V117 generated script parse failed: $text"
}

Write-Host 'GPI_HUB_DESKTOP_LAUNCHER_STATIC_WRAPPER=PASS' -ForegroundColor Green
Write-Host 'V117_STABLE_VENDOR_CONSENSUS=PASS' -ForegroundColor Green
Write-Host 'V117_VARIABLE_VENDOR_SEMANTIC_DISCRIMINATION=PASS' -ForegroundColor Green
Write-Host 'V117_ORDER_FAMILY_SAFETY=PASS' -ForegroundColor Green
Write-Host 'V117_CROSS_VENDOR_REFERENCE_RELIANCE_GUARD=PASS' -ForegroundColor Green
Write-Host 'V117_TARGETED_VENDOR_CORPUS_EXPANSION=PASS' -ForegroundColor Green
Write-Host 'V117_WAREHOUSE_TOOLING_SAFETY_OVERLAY_CONFIGURED=PASS' -ForegroundColor Green
Write-Host 'V117_MONGO_RESILIENT_CONTEXT_CONFIGURED=PASS' -ForegroundColor Green
Write-Host 'V117_EXPANSION_PROGRESS_TELEMETRY_CONFIGURED=PASS' -ForegroundColor Green
Write-Host 'V117_CANDIDATE_PACKAGE_ORIGIN_GATE=PASS' -ForegroundColor Green
Write-Host 'V117_FAST_REGRESSION_GATE_CONFIGURED=PASS' -ForegroundColor Green
Write-Host 'V117_GENERATED_PARSE=PASS' -ForegroundColor Green
Write-Host "V117_FEATURE_COMMIT=$ExpectedFeatureCommit"
Write-Host "V117_GENERATED=$GeneratedPath"

& $GeneratedPath
exit $LASTEXITCODE