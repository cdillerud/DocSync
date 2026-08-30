#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$StatePath = Join-Path $ToolRoot 'state.json'
if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) { throw "Migration state missing: $StatePath" }
$State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 50

$OperationalRoot = [string]$State.local.operational_root
$KeyPath = [string]$State.local.ssh_key
$TargetIp = [string]$State.target.public_ip
$SourceIp = [string]$State.source.public_ip
$CorpusPath = Join-Path $env:USERPROFILE 'Downloads\W117105_Strategic Warehousing_122625_.pdf'
$CorpusSha = '48410cadceaa411d65e51bd266be5c5942b4431cdede9e7a05b871e75a3a2c25'

$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\migration-v108-rev9-standalone\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
Start-Transcript -LiteralPath (Join-Path $DiagDir 'Invoke-GPIHub-V108-REV9-Standalone-Safety-Corpus.txt') -Force | Out-Null

function Require([bool]$Condition,[string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Invoke-NativeText {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$AllowFailure
    )
    $token = [guid]::NewGuid().ToString('N')
    $stderrFile = Join-Path $env:TEMP "gpi-v108-rev9-$token.err.txt"
    $oldEap = $ErrorActionPreference
    $nativeVar = Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $oldNative = if ($null -ne $nativeVar) { $nativeVar.Value } else { $null }
    try {
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
        $ErrorActionPreference = $oldEap
        if ($null -ne $nativeVar) { $PSNativeCommandUseErrorActionPreference = $oldNative }
        Remove-Item -LiteralPath $stderrFile -Force -ErrorAction SilentlyContinue
    }
}

function Get-KnownHostsForIp([string]$Ip) {
    $diagRoot = Join-Path $OperationalRoot '.gpi-diagnostics'
    foreach ($file in @(Get-ChildItem -LiteralPath $diagRoot -Filter '*known_hosts*' -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)) {
        $probe = Invoke-NativeText -FilePath 'ssh-keygen.exe' -Arguments @('-F',$Ip,'-f',$file.FullName) -AllowFailure
        if ($probe.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($probe.StdOut)) { return $file.FullName }
    }
    throw "No Azure-verified known_hosts file found for $Ip."
}

function Invoke-SshScript {
    param(
        [Parameter(Mandatory)][string]$Ip,
        [Parameter(Mandatory)][string]$KnownHosts,
        [Parameter(Mandatory)][string]$ScriptText
    )
    $token = [guid]::NewGuid().ToString('N')
    $stderrFile = Join-Path $env:TEMP "gpi-v108-rev9-ssh-$token.err.txt"
    $oldEap = $ErrorActionPreference
    $nativeVar = Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $oldNative = if ($null -ne $nativeVar) { $nativeVar.Value } else { $null }
    $args = @(
        '-i',$KeyPath,
        '-o','BatchMode=yes',
        '-o','StrictHostKeyChecking=yes',
        '-o',"UserKnownHostsFile=$KnownHosts",
        '-o','GlobalKnownHostsFile=NUL',
        '-o','ConnectTimeout=20',
        "azureuser@$Ip",
        'bash -s'
    )
    try {
        $ErrorActionPreference = 'Continue'
        if ($null -ne $nativeVar) { $PSNativeCommandUseErrorActionPreference = $false }
        $normalized = $ScriptText -replace "`r`n","`n"
        $output = $normalized | & ssh.exe @args 2> $stderrFile
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

function Stage-Corpus([string]$Ip,[string]$KnownHosts) {
    $r = Invoke-NativeText -FilePath 'scp.exe' -Arguments @(
        '-i',$KeyPath,
        '-o','BatchMode=yes',
        '-o','StrictHostKeyChecking=yes',
        '-o',"UserKnownHostsFile=$KnownHosts",
        '-o','GlobalKnownHostsFile=NUL',
        '-o','ConnectTimeout=20',
        $CorpusPath,
        "azureuser@${Ip}:/tmp/v108-w117105.pdf"
    )
    Require ($r.ExitCode -eq 0) "Failed to stage corpus to $Ip."
}

function Section([string]$Title) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

try {
    Section 'V108 REV9 - STANDALONE DURABILITY SAFETY + STRATEGIC INBOUND AI CORPUS'
    Write-Host 'Mode                : STANDALONE RESUME / NO GENERATED SCRIPT PATCHING'
    Write-Host 'Target backend      : VERIFY IN PLACE / NO RECREATE'
    Write-Host 'Target app tree     : NO CHANGE'
    Write-Host 'Target Mongo        : READ ONLY'
    Write-Host 'Source              : AI-ONLY classifier probe / NO intake / NO restart'
    Write-Host 'BC / SharePoint     : NO WRITES'
    Write-Host 'Production          : NOT TOUCHED'

    Require (Test-Path -LiteralPath $CorpusPath -PathType Leaf) "W117105 corpus missing: $CorpusPath"
    $sha = (Get-FileHash -LiteralPath $CorpusPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Require ($sha -eq $CorpusSha) "W117105 corpus SHA mismatch: $sha"
    Write-Host 'V108_REV9_CORPUS_SHA=PASS' -ForegroundColor Green

    Require (Test-Path -LiteralPath $KeyPath -PathType Leaf) "SSH key missing: $KeyPath"
    foreach ($cmd in @('ssh.exe','scp.exe','ssh-keygen.exe')) {
        Require ($null -ne (Get-Command $cmd -ErrorAction SilentlyContinue)) "$cmd unavailable."
    }

    $TargetKnown = Get-KnownHostsForIp $TargetIp
    $SourceKnown = Get-KnownHostsForIp $SourceIp
    Stage-Corpus $TargetIp $TargetKnown
    Stage-Corpus $SourceIp $SourceKnown
    Write-Host 'V108_REV9_CORPUS_STAGED=PASS' -ForegroundColor Green

    $TargetRemote = @'
set -euo pipefail
PROJECT='gpi-hub-v100'
STATIC_NET='gpi-hub-v100-static-net'
APP='/gpi-hub-data/apps/gpi-hub'
MIG='/gpi-hub-data/migration'
STATIC_SERVER="$MIG/v100-static-overlay/server.py"
DURABLE_WORKFLOW="$MIG/v108-warehouse-durable-overlay/workflow_status.py"
CORPUS_DIR="$MIG/v108-strategic-inbound-corpus"
EXPECTED_IMAGE='sha256:646051f6b0434b20ad429dec18c5f7b2a7d017c0fdec94f4bd77eaa7375fabb3'
EXPECTED_BASELINE='7c763c99a7fa765d9e168e3df18baecbe71007b9737ee839d3b3418ce6395020'
EXPECTED_PATCH='0041452a8c0c6749f88e02990014141c327720abff8d157afcbe21969f6f0a4a'
EXPECTED_CORPUS='48410cadceaa411d65e51bd266be5c5942b4431cdede9e7a05b871e75a3a2c25'
REL='workflows/document_capture/rules/workflow_status.py'
TARGET_REL='/app/workflows/document_capture/rules/workflow_status.py'

backend=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
mongo=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=mongodb' --format '{{.Names}}' | head -n 1)
[ -n "$backend" ] || { echo 'Target backend missing.' >&2; exit 41; }
[ -n "$mongo" ] || { echo 'Target Mongo missing.' >&2; exit 42; }

actual_image=$(docker inspect "$backend" -f '{{.Image}}')
[ "$actual_image" = "$EXPECTED_IMAGE" ] || { echo "Backend image drift: $actual_image" >&2; exit 43; }
[ "$(sha256sum "$APP/backend/$REL" | awk '{print $1}')" = "$EXPECTED_BASELINE" ] || { echo 'Original host workflow tree drift.' >&2; exit 44; }
[ -f "$STATIC_SERVER" ] || { echo "Static server overlay missing: $STATIC_SERVER" >&2; exit 45; }
[ -f "$DURABLE_WORKFLOW" ] || { echo "Durable workflow overlay missing: $DURABLE_WORKFLOW" >&2; exit 46; }
[ "$(sha256sum "$DURABLE_WORKFLOW" | awk '{print $1}')" = "$EXPECTED_PATCH" ] || { echo 'Durable workflow overlay SHA drift.' >&2; exit 47; }
[ "$(docker exec "$backend" sha256sum "$TARGET_REL" | awk '{print $1}')" = "$EXPECTED_PATCH" ] || { echo 'Running workflow SHA drift.' >&2; exit 48; }

echo V108_REV9_DURABLE_WORKFLOW_OVERLAY=PASS

server_src=$(docker inspect "$backend" -f '{{range .Mounts}}{{if eq .Destination "/app/server.py"}}{{println .Source}}{{end}}{{end}}' | head -n 1)
server_rw=$(docker inspect "$backend" -f '{{range .Mounts}}{{if eq .Destination "/app/server.py"}}{{println .RW}}{{end}}{{end}}' | head -n 1)
workflow_src=$(docker inspect "$backend" -f '{{range .Mounts}}{{if eq .Destination "/app/workflows/document_capture/rules/workflow_status.py"}}{{println .Source}}{{end}}{{end}}' | head -n 1)
workflow_rw=$(docker inspect "$backend" -f '{{range .Mounts}}{{if eq .Destination "/app/workflows/document_capture/rules/workflow_status.py"}}{{println .RW}}{{end}}{{end}}' | head -n 1)
[ "$server_src" = "$STATIC_SERVER" ] || { echo "Unexpected /app/server.py mount source: $server_src" >&2; exit 49; }
[ "$server_rw" = 'false' ] || { echo 'Static server overlay is writable.' >&2; exit 50; }
[ "$workflow_src" = "$DURABLE_WORKFLOW" ] || { echo "Unexpected workflow mount source: $workflow_src" >&2; exit 51; }
[ "$workflow_rw" = 'false' ] || { echo 'Durable workflow overlay is writable.' >&2; exit 52; }

server_host_sha=$(sha256sum "$STATIC_SERVER" | awk '{print $1}')
server_container_sha=$(docker exec "$backend" sha256sum /app/server.py | awk '{print $1}')
[ "$server_host_sha" = "$server_container_sha" ] || { echo 'Static server host/container SHA mismatch.' >&2; exit 53; }
grep -Fq 'os.environ.get("GPI_MIGRATION_STATIC_RUNTIME", "false").lower() == "true"' "$STATIC_SERVER" || { echo 'Static early-return env guard missing from overlay.' >&2; exit 54; }
grep -Fq 'GPI_MIGRATION_STATIC_RUNTIME=ACTIVE - background workers and schedulers suppressed' "$STATIC_SERVER" || { echo 'Static suppression marker missing from overlay.' >&2; exit 55; }
docker exec "$backend" grep -Fq 'GPI_MIGRATION_STATIC_RUNTIME=ACTIVE - background workers and schedulers suppressed' /app/server.py || { echo 'Static suppression marker missing from running /app/server.py.' >&2; exit 56; }

echo "V108_REV9_STATIC_SERVER_SHA=$server_container_sha"
echo V108_REV9_STATIC_SERVER_STRUCTURAL_GUARD=PASS

for expected in \
  'GPI_MIGRATION_STATIC_RUNTIME=true' \
  'SHAREPOINT_TARGET=test' \
  'BC_WRITE_ENABLED=false' \
  'BC_BLOCK_PRODUCTION_WRITES=true' \
  'EMAIL_POLLING_ENABLED=false' \
  'SALES_EMAIL_POLLING_ENABLED=false' \
  'INSIDE_SALES_PILOT_ENABLED=false' \
  'AUTO_POST_ENABLED=false' \
  'AUTO_CREATE_SALES_ORDER_ENABLED=false' \
  'PILOT_MODE_ENABLED=false'; do
    docker inspect "$backend" -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fxq "$expected" || { echo "Safety env missing: $expected" >&2; exit 57; }
done

echo V108_REV9_SAFETY_ENV=PASS

[ "$(docker network inspect "$STATIC_NET" -f '{{.Internal}}')" = 'true' ] || { echo 'Static network not internal.' >&2; exit 58; }
nets=$(docker inspect "$backend" -f '{{range $k,$v := .NetworkSettings.Networks}}{{println $k}}{{end}}' | sed '/^$/d')
[ "$nets" = "$STATIC_NET" ] || { echo "Unexpected backend networks: $nets" >&2; exit 59; }
echo V108_REV9_INTERNAL_ONLY_NETWORK=PASS

set +e
health=$(docker exec "$backend" python -c 'import urllib.request,sys; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health", timeout=4); print(r.status); sys.exit(0 if 200 <= r.status < 400 else 1)' 2>/tmp/v108-rev9-health.err)
health_code=$?
set -e
if [ "$health_code" -ne 0 ]; then
  echo "Backend health command failed with exit $health_code" >&2
  cat /tmp/v108-rev9-health.err >&2 || true
  rm -f /tmp/v108-rev9-health.err
  exit 60
fi
rm -f /tmp/v108-rev9-health.err
[[ "$health" =~ ^[23][0-9][0-9]$ ]] || { echo "Backend health returned non-HTTP status: '$health'" >&2; exit 61; }
echo "V108_REV9_BACKEND_INTERNAL_HTTP=$health"
echo V108_REV9_INTERNAL_HEALTH=PASS

if docker exec "$backend" python -c 'import socket; s=socket.create_connection(("graph.microsoft.com",443),3); s.close()' >/dev/null 2>&1; then
  echo 'Target backend unexpectedly has Graph egress.' >&2
  exit 62
fi
echo V108_REV9_EXTERNAL_EGRESS_BLOCKED=PASS

logs=$(docker logs "$backend" 2>&1 || true)
for forbidden in 'Dynamic mailbox polling worker started' 'AP email polling worker started' 'Sales email polling worker started'; do
  if printf '%s\n' "$logs" | grep -Fq "$forbidden"; then
    echo "Forbidden worker started: $forbidden" >&2
    exit 63
  fi
done
if printf '%s\n' "$logs" | grep -Fq 'GPI_MIGRATION_STATIC_RUNTIME=ACTIVE - background workers and schedulers suppressed'; then
  echo V108_REV9_LOG_MARKER=PRESENT
else
  echo V108_REV9_LOG_MARKER=ABSENT_BUT_STRUCTURAL_STATIC_GUARD_PROVEN
fi
echo V108_REV9_FORBIDDEN_WORKERS_ABSENT=PASS
echo V108_REV9_TARGET_STATIC_SAFETY=PASS

cat > /tmp/v108-rev9-truth.js <<'JS'
const C=db.getSiblingDB('gpi_document_hub').getCollection('hub_documents');
const j=C.findOne({id:'04a47c5e-9180-4b41-bbd2-fcbfb62d336b'},{_id:0,id:1,file_name:1,shipment_number:1,bol_number:1});
const s=C.findOne({id:'f35038a9-6d26-49c5-8461-67cef2083171'},{_id:0,id:1,file_name:1,shipment_number:1,bol_number:1});
if(!j || String(j.shipment_number)!=='5975975') throw new Error('JBS canonical shipment missing');
if(!s || String(s.shipment_number)!=='57745') throw new Error('Strategic outbound canonical shipment missing');
print('V108_REV9_CANONICAL_TRUTH_JSON='+JSON.stringify({jbs:j,strategic:s}));
print('V108_REV9_CANONICAL_TRUTH=PASS');
JS
docker cp /tmp/v108-rev9-truth.js "$mongo:/tmp/v108-rev9-truth.js" >/dev/null
rm -f /tmp/v108-rev9-truth.js
if docker inspect "$mongo" -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -q '^MONGO_INITDB_ROOT_USERNAME='; then
  docker exec "$mongo" sh -lc 'mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin /tmp/v108-rev9-truth.js'
else
  docker exec "$mongo" mongosh --quiet /tmp/v108-rev9-truth.js
fi
docker exec "$mongo" rm -f /tmp/v108-rev9-truth.js >/dev/null 2>&1 || true

echo V108_REV9_CANONICAL_DATA_PRESERVED=PASS

[ "$(sha256sum /tmp/v108-w117105.pdf | awk '{print $1}')" = "$EXPECTED_CORPUS" ] || { echo 'Target staged corpus SHA mismatch.' >&2; exit 64; }
mkdir -p "$CORPUS_DIR"
cp -f /tmp/v108-w117105.pdf "$CORPUS_DIR/W117105_Strategic_Warehousing_122625_.pdf"
chmod 0444 "$CORPUS_DIR/W117105_Strategic_Warehousing_122625_.pdf"
[ "$(sha256sum "$CORPUS_DIR/W117105_Strategic_Warehousing_122625_.pdf" | awk '{print $1}')" = "$EXPECTED_CORPUS" ] || { echo 'Preserved target corpus SHA mismatch.' >&2; exit 65; }
rm -f /tmp/v108-w117105.pdf

echo V108_REV9_TARGET_CORPUS_PRESERVED=PASS
echo V108_REV9_TARGET_DURABILITY_SAFETY=PASS
'@

    $tr = Invoke-SshScript -Ip $TargetIp -KnownHosts $TargetKnown -ScriptText $TargetRemote
    Set-Content -LiteralPath (Join-Path $DiagDir 'target-v108-rev9.txt') -Value $tr.StdOut -Encoding utf8
    if ($tr.StdOut) { Write-Host $tr.StdOut }
    if ($tr.StdErr) { Write-Host $tr.StdErr -ForegroundColor DarkYellow }
    Require ($tr.ExitCode -eq 0) "V108 REV9 target safety validation failed with exit code $($tr.ExitCode)."
    foreach ($m in @(
        'V108_REV9_DURABLE_WORKFLOW_OVERLAY=PASS',
        'V108_REV9_STATIC_SERVER_STRUCTURAL_GUARD=PASS',
        'V108_REV9_SAFETY_ENV=PASS',
        'V108_REV9_INTERNAL_ONLY_NETWORK=PASS',
        'V108_REV9_INTERNAL_HEALTH=PASS',
        'V108_REV9_EXTERNAL_EGRESS_BLOCKED=PASS',
        'V108_REV9_FORBIDDEN_WORKERS_ABSENT=PASS',
        'V108_REV9_TARGET_STATIC_SAFETY=PASS',
        'V108_REV9_CANONICAL_TRUTH=PASS',
        'V108_REV9_CANONICAL_DATA_PRESERVED=PASS',
        'V108_REV9_TARGET_CORPUS_PRESERVED=PASS',
        'V108_REV9_TARGET_DURABILITY_SAFETY=PASS'
    )) {
        Require ($tr.StdOut -match [regex]::Escape($m)) "Missing target marker: $m"
    }

    $SourceRemote = @'
set -euo pipefail
EXPECTED_IMAGE='sha256:646051f6b0434b20ad429dec18c5f7b2a7d017c0fdec94f4bd77eaa7375fabb3'
EXPECTED_HELPER='2d2298b9c7e6315745d814e5437687caf463a44dec24d73d710b6d9e4e772117'
EXPECTED_CORPUS='48410cadceaa411d65e51bd266be5c5942b4431cdede9e7a05b871e75a3a2c25'

backend=$(docker ps --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
[ -n "$backend" ] || { echo 'Source backend missing.' >&2; exit 71; }
[ "$(docker inspect "$backend" -f '{{.Image}}')" = "$EXPECTED_IMAGE" ] || { echo 'Source backend image drift.' >&2; exit 72; }
[ "$(docker exec "$backend" sha256sum /app/services/document_intel_helpers.py | awk '{print $1}')" = "$EXPECTED_HELPER" ] || { echo 'Source AI helper drift.' >&2; exit 73; }
[ "$(sha256sum /tmp/v108-w117105.pdf | awk '{print $1}')" = "$EXPECTED_CORPUS" ] || { echo 'Source corpus SHA mismatch.' >&2; exit 74; }

set +e
health_before=$(docker exec "$backend" python -c 'import urllib.request,sys; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health", timeout=4); print(r.status); sys.exit(0 if 200 <= r.status < 400 else 1)' 2>/tmp/v108-rev9-source-health-before.err)
health_before_code=$?
set -e
if [ "$health_before_code" -ne 0 ]; then
  echo "Source health-before command failed with exit $health_before_code" >&2
  cat /tmp/v108-rev9-source-health-before.err >&2 || true
  rm -f /tmp/v108-rev9-source-health-before.err
  exit 75
fi
rm -f /tmp/v108-rev9-source-health-before.err
[[ "$health_before" =~ ^[23][0-9][0-9]$ ]] || { echo "Source health-before returned non-HTTP status: '$health_before'" >&2; exit 76; }
echo "V108_REV9_SOURCE_HEALTH_BEFORE=$health_before"
echo V108_REV9_SOURCE_AI_AUTHORITY=PASS

docker cp /tmp/v108-w117105.pdf "$backend:/tmp/v108-w117105.pdf" >/dev/null
rm -f /tmp/v108-w117105.pdf
cat > /tmp/v108-rev9-probe.py <<'PY'
import asyncio, json, sys, types

async def empty(*args, **kwargs):
    return ''

fb = types.ModuleType('services.classification_feedback_service')
fb.build_few_shot_prompt_section = empty
fb.build_vendor_hints_prompt_section = empty
sys.modules['services.classification_feedback_service'] = fb

loop = types.ModuleType('services.feedback_loop_service')
loop.build_feedback_context_for_prompt = empty
sys.modules['services.feedback_loop_service'] = loop

vendor = types.ModuleType('services.vendor_inference_service')
def no_vendor(*args, **kwargs):
    return (None, None)
vendor.infer_vendor = no_vendor
sys.modules['services.vendor_inference_service'] = vendor

from services.document_intel_helpers import classify_document_with_ai


def has(obj, token):
    t = str(token).lower()
    if isinstance(obj, dict):
        return any(has(k, t) or has(v, t) for k, v in obj.items())
    if isinstance(obj, (list, tuple)):
        return any(has(v, t) for v in obj)
    return t in str(obj).lower()


async def classify(path, name, label):
    result = await classify_document_with_ai(path, name)
    print(f'V108_REV9_AI_{label}=' + json.dumps(result, sort_keys=True, default=str))
    return result


async def main():
    import fitz

    packet = '/tmp/v108-w117105.pdf'
    full = await classify(packet, 'W117105_Strategic Warehousing_122625_.pdf', 'FULL_PACKET')

    doc = fitz.open(packet)
    if doc.page_count != 4:
        raise SystemExit(f'Expected 4-page packet, got {doc.page_count}')
    out = fitz.open()
    out.insert_pdf(doc, from_page=3, to_page=3)
    page4_path = '/tmp/v108-w117105-page4.pdf'
    out.save(page4_path)
    out.close()
    doc.close()

    page4 = await classify(page4_path, 'W117105_Strategic_supporting_shipping_page.pdf', 'SUPPORTING_PAGE4')

    checks = {
        'full_W117105': has(full, 'W117105'),
        'full_962222-1': has(full, '962222-1'),
        'full_815734': has(full, '815734'),
        'full_ER25-1560': has(full, 'ER25-1560'),
        'page4_ER25-1560': has(page4, 'ER25-1560')
    }
    print('V108_REV9_AI_CHECKS=' + json.dumps(checks, sort_keys=True))
    for key, value in checks.items():
        print(f'V108_REV9_CHECK_{key}=' + ('PASS' if value else 'MISS'))

    if checks['page4_ER25-1560'] and not checks['full_ER25-1560']:
        gap = 'PROVEN_SUPPORTING_SHIPMENT_LOST_BY_CURRENT_FIRST_PAGE_SEAM'
    elif checks['full_ER25-1560']:
        gap = 'NOT_OBSERVED_FULL_PACKET_PRESERVED_SHIPMENT'
    else:
        gap = 'UNRESOLVED_SUPPORTING_SHIPMENT_NOT_EXTRACTED'

    primary = 'PASS' if checks['full_W117105'] else 'MISS'
    print('V108_MULTIPAGE_REFERENCE_GAP=' + gap)
    print('V108_STRATEGIC_PRIMARY_IDENTITY=' + primary)
    print('V108_REV9_AI_CORPUS_EXECUTION=PASS')


asyncio.run(main())
PY

docker cp /tmp/v108-rev9-probe.py "$backend:/tmp/v108-rev9-probe.py" >/dev/null
rm -f /tmp/v108-rev9-probe.py
set +e
probe_out=$(docker exec -e PYTHONPATH=/app -w /app "$backend" python /tmp/v108-rev9-probe.py 2>&1)
probe_code=$?
set -e
printf '%s\n' "$probe_out"
docker exec "$backend" rm -f /tmp/v108-rev9-probe.py /tmp/v108-w117105.pdf /tmp/v108-w117105-page4.pdf >/dev/null 2>&1 || true
[ "$probe_code" -eq 0 ] || { echo "AI corpus probe failed with exit code $probe_code" >&2; exit 77; }
printf '%s\n' "$probe_out" | grep -Fq 'V108_REV9_AI_CORPUS_EXECUTION=PASS' || { echo 'AI corpus execution marker missing.' >&2; exit 78; }

set +e
health_after=$(docker exec "$backend" python -c 'import urllib.request,sys; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health", timeout=4); print(r.status); sys.exit(0 if 200 <= r.status < 400 else 1)' 2>/tmp/v108-rev9-source-health-after.err)
health_after_code=$?
set -e
if [ "$health_after_code" -ne 0 ]; then
  echo "Source health-after command failed with exit $health_after_code" >&2
  cat /tmp/v108-rev9-source-health-after.err >&2 || true
  rm -f /tmp/v108-rev9-source-health-after.err
  exit 79
fi
rm -f /tmp/v108-rev9-source-health-after.err
[[ "$health_after" =~ ^[23][0-9][0-9]$ ]] || { echo "Source health-after returned non-HTTP status: '$health_after'" >&2; exit 80; }
echo "V108_REV9_SOURCE_HEALTH_AFTER=$health_after"
echo V108_REV9_SOURCE_AI_CORPUS_PROBE=PASS
'@

    $sr = Invoke-SshScript -Ip $SourceIp -KnownHosts $SourceKnown -ScriptText $SourceRemote
    Set-Content -LiteralPath (Join-Path $DiagDir 'source-v108-rev9-ai-corpus.txt') -Value $sr.StdOut -Encoding utf8
    if ($sr.StdOut) { Write-Host $sr.StdOut }
    if ($sr.StdErr) { Write-Host $sr.StdErr -ForegroundColor DarkYellow }
    Require ($sr.ExitCode -eq 0) "V108 REV9 source AI corpus probe failed with exit code $($sr.ExitCode)."
    foreach ($m in @(
        'V108_REV9_SOURCE_AI_AUTHORITY=PASS',
        'V108_REV9_AI_CORPUS_EXECUTION=PASS',
        'V108_REV9_SOURCE_AI_CORPUS_PROBE=PASS'
    )) {
        Require ($sr.StdOut -match [regex]::Escape($m)) "Missing source marker: $m"
    }

    $gap = @($sr.StdOut -split "`n" | Where-Object { $_ -like 'V108_MULTIPAGE_REFERENCE_GAP=*' } | Select-Object -Last 1)
    $primary = @($sr.StdOut -split "`n" | Where-Object { $_ -like 'V108_STRATEGIC_PRIMARY_IDENTITY=*' } | Select-Object -Last 1)
    Require ($gap.Count -eq 1) 'Missing multi-page reference disposition.'
    Require ($primary.Count -eq 1) 'Missing Strategic primary identity disposition.'

    Section 'V108 REV9 FINAL RESULT'
    Write-Host 'Durable shipment fix  : ACTIVE / READ-ONLY OVERLAY / NO RECREATE THIS RUN'
    Write-Host 'Target static safety  : STRUCTURALLY PROVEN / INTERNAL HEALTHY / NO EGRESS / NO FORBIDDEN WORKERS'
    Write-Host 'JBS outbound          : shipment_number=5975975 preserved'
    Write-Host 'Strategic outbound    : shipment_number=57745 preserved'
    Write-Host "Strategic inbound ID  : $($primary[0])"
    Write-Host "Multi-page finding    : $($gap[0])"
    Write-Host 'Source AI probe       : STANDALONE CLASSIFIER ONLY / NO INTAKE / NO RESTART'
    Write-Host 'BC / SharePoint       : NO WRITES'
    Write-Host 'Production            : NOT TOUCHED'
    Write-Host "Diagnostics           : $DiagDir"
    Write-Host 'V108_REV9_STANDALONE_SAFETY_CORPUS=PASS' -ForegroundColor Green
    Write-Host 'V108_DURABLE_WAREHOUSE_STRATEGIC_CORPUS=PASS' -ForegroundColor Green
    Write-Host 'NEXT: fix multi-page reference loss if proven; otherwise advance immediately to AP TOP-10 PAYABLE COHORT (#19).' -ForegroundColor Yellow
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
