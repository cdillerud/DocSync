#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$State = Get-Content -LiteralPath (Join-Path $ToolRoot 'state.json') -Raw | ConvertFrom-Json -Depth 50
$OperationalRoot = [string]$State.local.operational_root
$KeyPath = [string]$State.local.ssh_key
$TargetIp = [string]$State.target.public_ip
$SourceIp = [string]$State.source.public_ip

$CorpusName = 'W117105_Strategic Warehousing_122625_.pdf'
$CorpusSha = '48410cadceaa411d65e51bd266be5c5942b4431cdede9e7a05b871e75a3a2c25'
$CorpusCandidates = @(
    (Join-Path $env:USERPROFILE "Downloads\$CorpusName"),
    (Join-Path $ToolRoot "corpus\$CorpusName"),
    (Join-Path $OperationalRoot ".gpi-corpus\$CorpusName")
)
$CorpusPath = @($CorpusCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1)

$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\migration-v108-durable-warehouse-strategic-corpus\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
Start-Transcript -LiteralPath (Join-Path $DiagDir 'Invoke-GPIHub-V108-Durable-Warehouse-Strategic-Corpus.txt') -Force | Out-Null

function Require([bool]$Condition,[string]$Message) { if (-not $Condition) { throw $Message } }

function Invoke-NativeText {
    param([Parameter(Mandatory)][string]$FilePath,[Parameter(Mandatory)][string[]]$Arguments,[switch]$AllowFailure)
    $token = [guid]::NewGuid().ToString('N')
    $stderrFile = Join-Path $env:TEMP "gpi-v108-$token.err.txt"
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
        if (-not $AllowFailure -and $result.ExitCode -ne 0) { throw "$FilePath failed ($($result.ExitCode)).`n$stdout`n$stderr" }
        return $result
    }
    finally {
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
    throw "No Azure-verified known_hosts file was found for $Ip."
}

function Invoke-SshScript {
    param([Parameter(Mandatory)][string]$Ip,[Parameter(Mandatory)][string]$KnownHosts,[Parameter(Mandatory)][string]$ScriptText)
    $token = [guid]::NewGuid().ToString('N')
    $stderrFile = Join-Path $env:TEMP "gpi-v108-ssh-$token.err.txt"
    $oldEap = $ErrorActionPreference
    $nativeVar = Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $oldNative = if ($null -ne $nativeVar) { $nativeVar.Value } else { $null }
    $args = @('-i',$KeyPath,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',"UserKnownHostsFile=$KnownHosts",'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=20',"azureuser@$Ip",'bash -s')
    try {
        $ErrorActionPreference = 'Continue'
        if ($null -ne $nativeVar) { $PSNativeCommandUseErrorActionPreference = $false }
        $output = (($ScriptText -replace "`r`n","`n") | & ssh.exe @args 2> $stderrFile)
        return [pscustomobject]@{
            ExitCode=[int]$LASTEXITCODE
            StdOut=((@($output) | ForEach-Object { [string]$_ }) -join "`n")
            StdErr=(if (Test-Path -LiteralPath $stderrFile) { Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue } else { '' })
        }
    }
    finally {
        $ErrorActionPreference = $oldEap
        if ($null -ne $nativeVar) { $PSNativeCommandUseErrorActionPreference = $oldNative }
        Remove-Item -LiteralPath $stderrFile -Force -ErrorAction SilentlyContinue
    }
}

function Stage-Corpus {
    param([string]$Ip,[string]$KnownHosts,[string]$RemotePath,[string]$LocalPath)
    $r = Invoke-NativeText -FilePath 'scp.exe' -Arguments @('-i',$KeyPath,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',"UserKnownHostsFile=$KnownHosts",'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=20',$LocalPath,"azureuser@${Ip}:$RemotePath")
    Require ($r.ExitCode -eq 0) "Failed to stage corpus to $Ip."
}

function Write-Section([string]$Title) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

try {
    Write-Section 'V108 - DURABLE WAREHOUSE OVERLAY + AUTHENTIC STRATEGIC INBOUND AI CORPUS'
    Write-Host 'Classification     : PARITY BLOCKER VALIDATION'
    Write-Host 'Target             : make proven V107 shipment_number line durable as read-only overlay'
    Write-Host 'AI corpus          : W117105 Strategic Warehousing legacy packet'
    Write-Host 'AI execution       : source backend standalone classify_document_with_ai ONLY; no intake call'
    Write-Host 'Source app/data    : no app change, no Mongo write, no SharePoint/BC call, no restart'
    Write-Host 'Target main runtime: remains static/internal-only/no external egress'
    Write-Host 'Production         : NOT TOUCHED'

    Require ($CorpusPath.Count -eq 1) "Authentic corpus file missing. Download '$CorpusName' to your Downloads folder, then rerun the launcher."
    $LocalCorpus = [string]$CorpusPath[0]
    $actualSha = (Get-FileHash -LiteralPath $LocalCorpus -Algorithm SHA256).Hash.ToLowerInvariant()
    Require ($actualSha -eq $CorpusSha) "W117105 corpus SHA mismatch. Expected $CorpusSha, found $actualSha."
    Write-Host "V108_LOCAL_CORPUS=$LocalCorpus"
    Write-Host "V108_LOCAL_CORPUS_SHA256=$actualSha"
    Write-Host 'V108_AUTHENTIC_CORPUS_LOCAL=PASS' -ForegroundColor Green

    Require (Test-Path -LiteralPath $KeyPath -PathType Leaf) "SSH key missing: $KeyPath"
    Require ($null -ne (Get-Command ssh.exe -ErrorAction SilentlyContinue)) 'ssh.exe unavailable.'
    Require ($null -ne (Get-Command scp.exe -ErrorAction SilentlyContinue)) 'scp.exe unavailable.'
    Require ($null -ne (Get-Command ssh-keygen.exe -ErrorAction SilentlyContinue)) 'ssh-keygen.exe unavailable.'
    $TargetKnownHosts = Get-KnownHostsForIp -Ip $TargetIp
    $SourceKnownHosts = Get-KnownHostsForIp -Ip $SourceIp

    Stage-Corpus -Ip $TargetIp -KnownHosts $TargetKnownHosts -RemotePath '/tmp/v108-w117105.pdf' -LocalPath $LocalCorpus
    Stage-Corpus -Ip $SourceIp -KnownHosts $SourceKnownHosts -RemotePath '/tmp/v108-w117105.pdf' -LocalPath $LocalCorpus
    Write-Host 'V108_AUTHENTIC_CORPUS_STAGED=PASS' -ForegroundColor Green

    $TargetRemote = @'
set -euo pipefail
PROJECT='gpi-hub-v100'
STATIC_NET='gpi-hub-v100-static-net'
APP='/gpi-hub-data/apps/gpi-hub'
MIG='/gpi-hub-data/migration'
BASE="$APP/docker-compose.yml"
V100_OVERRIDE="$MIG/v100-target-override.yml"
STATIC_OVERRIDE="$MIG/v100-static-isolation.yml"
V108_OVERRIDE="$MIG/v108-warehouse-durable-overlay.yml"
OVERLAY_DIR="$MIG/v108-warehouse-durable-overlay"
CORPUS_DIR="$MIG/v108-strategic-inbound-corpus"
REL='workflows/document_capture/rules/workflow_status.py'
TARGET_REL='/app/workflows/document_capture/rules/workflow_status.py'
EXPECTED_BASELINE='7c763c99a7fa765d9e168e3df18baecbe71007b9737ee839d3b3418ce6395020'
EXPECTED_PATCH='0041452a8c0c6749f88e02990014141c327720abff8d157afcbe21969f6f0a4a'
EXPECTED_BACKEND='sha256:646051f6b0434b20ad429dec18c5f7b2a7d017c0fdec94f4bd77eaa7375fabb3'
EXPECTED_CORPUS='48410cadceaa411d65e51bd266be5c5942b4431cdede9e7a05b871e75a3a2c25'

backend=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
mongo=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=mongodb' --format '{{.Names}}' | head -n 1)
[ -n "$backend" ] && [ -n "$mongo" ] || { echo 'Required target service missing.' >&2; exit 41; }
[ "$(docker inspect "$backend" -f '{{.Image}}')" = "$EXPECTED_BACKEND" ] || { echo 'Backend image drift.' >&2; exit 42; }
[ "$(sha256sum "$APP/backend/$REL" | awk '{print $1}')" = "$EXPECTED_BASELINE" ] || { echo 'Original host tree drift.' >&2; exit 43; }
[ "$(docker exec "$backend" sha256sum "$TARGET_REL" | awk '{print $1}')" = "$EXPECTED_PATCH" ] || { echo 'V107 patched runtime not active.' >&2; exit 44; }
for expected in 'GPI_MIGRATION_STATIC_RUNTIME=true' 'SHAREPOINT_TARGET=test' 'BC_WRITE_ENABLED=false' 'BC_BLOCK_PRODUCTION_WRITES=true' 'EMAIL_POLLING_ENABLED=false' 'SALES_EMAIL_POLLING_ENABLED=false' 'AUTO_POST_ENABLED=false' 'AUTO_CREATE_SALES_ORDER_ENABLED=false'; do
  docker inspect "$backend" -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fxq "$expected" || { echo "Safety env missing: $expected" >&2; exit 45; }
done
[ "$(docker network inspect "$STATIC_NET" -f '{{.Internal}}')" = 'true' ] || { echo 'Static network not internal.' >&2; exit 46; }
[ "$(sha256sum /tmp/v108-w117105.pdf | awk '{print $1}')" = "$EXPECTED_CORPUS" ] || { echo 'Target staged corpus SHA mismatch.' >&2; exit 47; }
echo V108_TARGET_DURABILITY_PRECHECK=PASS

# Canonical data truth created by V107 REV2 must already exist.
cat > /tmp/v108-truth.js <<'JS'
const C=db.getSiblingDB('gpi_document_hub').getCollection('hub_documents');
const j=C.findOne({id:'04a47c5e-9180-4b41-bbd2-fcbfb62d336b'},{_id:0,shipment_number:1});
const s=C.findOne({id:'f35038a9-6d26-49c5-8461-67cef2083171'},{_id:0,shipment_number:1});
if(!j || String(j.shipment_number)!=='5975975') throw new Error('JBS canonical shipment missing');
if(!s || String(s.shipment_number)!=='57745') throw new Error('Strategic outbound canonical shipment missing');
print('V108_CANONICAL_TRUTH_PRE_RECREATE=PASS');
JS
docker cp /tmp/v108-truth.js "$mongo:/tmp/v108-truth.js" >/dev/null
rm -f /tmp/v108-truth.js
if docker inspect "$mongo" -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -q '^MONGO_INITDB_ROOT_USERNAME='; then
  docker exec "$mongo" sh -lc 'mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin /tmp/v108-truth.js'
else
  docker exec "$mongo" mongosh --quiet /tmp/v108-truth.js
fi
docker exec "$mongo" rm -f /tmp/v108-truth.js >/dev/null 2>&1 || true

mkdir -p "$OVERLAY_DIR" "$CORPUS_DIR"
docker cp "$backend:$TARGET_REL" "$OVERLAY_DIR/workflow_status.py"
[ "$(sha256sum "$OVERLAY_DIR/workflow_status.py" | awk '{print $1}')" = "$EXPECTED_PATCH" ] || { echo 'Durable overlay SHA mismatch.' >&2; exit 48; }
python3 -m py_compile "$OVERLAY_DIR/workflow_status.py"
chmod 0444 "$OVERLAY_DIR/workflow_status.py"
cat > "$V108_OVERRIDE" <<YAML
services:
  backend:
    volumes:
      - type: bind
        source: $OVERLAY_DIR/workflow_status.py
        target: $TARGET_REL
        read_only: true
YAML
COMPOSE=(docker compose -p "$PROJECT" -f "$BASE" -f "$V100_OVERRIDE" -f "$STATIC_OVERRIDE" -f "$V108_OVERRIDE")
"${COMPOSE[@]}" config --quiet
config_text=$("${COMPOSE[@]}" config)
printf '%s\n' "$config_text" | grep -Fq '/app/server.py' || { echo 'Static server overlay disappeared from compose.' >&2; exit 49; }
printf '%s\n' "$config_text" | grep -Fq "$TARGET_REL" || { echo 'V108 workflow overlay missing from compose.' >&2; exit 50; }
echo V108_DURABLE_OVERLAY_CONFIG=PASS

"${COMPOSE[@]}" up -d --no-build --no-deps --force-recreate backend >/dev/null
backend=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
[ -n "$backend" ] || { echo 'Backend missing after durable recreate.' >&2; exit 51; }
[ "$(docker inspect "$backend" -f '{{.Image}}')" = "$EXPECTED_BACKEND" ] || { echo 'Image drift after recreate.' >&2; exit 52; }
[ "$(docker exec "$backend" sha256sum "$TARGET_REL" | awk '{print $1}')" = "$EXPECTED_PATCH" ] || { echo 'Durable workflow overlay not active.' >&2; exit 53; }
[ "$(sha256sum "$APP/backend/$REL" | awk '{print $1}')" = "$EXPECTED_BASELINE" ] || { echo 'Original host app tree changed.' >&2; exit 54; }
for expected in 'GPI_MIGRATION_STATIC_RUNTIME=true' 'SHAREPOINT_TARGET=test' 'BC_WRITE_ENABLED=false' 'BC_BLOCK_PRODUCTION_WRITES=true' 'EMAIL_POLLING_ENABLED=false' 'SALES_EMAIL_POLLING_ENABLED=false' 'AUTO_POST_ENABLED=false' 'AUTO_CREATE_SALES_ORDER_ENABLED=false'; do
  docker inspect "$backend" -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fxq "$expected" || { echo "Safety env changed: $expected" >&2; exit 55; }
done
nets=$(docker inspect "$backend" -f '{{range $k,$v := .NetworkSettings.Networks}}{{println $k}}{{end}}' | sed '/^$/d')
[ "$nets" = "$STATIC_NET" ] || { echo "Unexpected backend networks: $nets" >&2; exit 56; }
server_ro=$(docker inspect "$backend" -f '{{range .Mounts}}{{if eq .Destination "/app/server.py"}}{{println .RW}}{{end}}{{end}}' | head -n 1)
workflow_ro=$(docker inspect "$backend" -f '{{range .Mounts}}{{if eq .Destination "/app/workflows/document_capture/rules/workflow_status.py"}}{{println .RW}}{{end}}{{end}}' | head -n 1)
[ "$server_ro" = 'false' ] && [ "$workflow_ro" = 'false' ] || { echo 'Required overlays are not read-only.' >&2; exit 57; }
healthy=0
for i in $(seq 1 120); do
  if docker exec "$backend" python - <<'PY' >/dev/null 2>&1
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8001/api/health', timeout=3) as r:
    raise SystemExit(0 if 200 <= r.status < 400 else 1)
PY
  then healthy=1; break; fi
  sleep 2
done
[ "$healthy" -eq 1 ] || { docker logs --tail 160 "$backend" >&2 || true; echo 'Backend unhealthy after durable recreate.' >&2; exit 58; }
if docker exec "$backend" python -c 'import socket; s=socket.create_connection(("graph.microsoft.com",443),3); s.close()' >/dev/null 2>&1; then
  echo 'Target backend unexpectedly has egress.' >&2; exit 59
fi
logs=$(docker logs "$backend" 2>&1 || true)
printf '%s\n' "$logs" | grep -Fq 'GPI_MIGRATION_STATIC_RUNTIME=ACTIVE - background workers and schedulers suppressed' || { echo 'Worker suppression marker missing.' >&2; exit 60; }
for forbidden in 'Dynamic mailbox polling worker started' 'AP email polling worker started' 'Sales email polling worker started'; do
  printf '%s\n' "$logs" | grep -Fq "$forbidden" && { echo "Forbidden worker started: $forbidden" >&2; exit 61; } || true
done
echo V108_DURABLE_TARGET_OVERLAY=PASS

# Re-prove canonical data after backend recreate.
cat > /tmp/v108-post.js <<'JS'
const C=db.getSiblingDB('gpi_document_hub').getCollection('hub_documents');
const j=C.findOne({id:'04a47c5e-9180-4b41-bbd2-fcbfb62d336b'},{_id:0,shipment_number:1});
const s=C.findOne({id:'f35038a9-6d26-49c5-8461-67cef2083171'},{_id:0,shipment_number:1});
if(!j || String(j.shipment_number)!=='5975975') throw new Error('JBS canonical shipment lost');
if(!s || String(s.shipment_number)!=='57745') throw new Error('Strategic outbound canonical shipment lost');
print('V108_CANONICAL_TRUTH_POST_RECREATE=PASS');
JS
docker cp /tmp/v108-post.js "$mongo:/tmp/v108-post.js" >/dev/null
rm -f /tmp/v108-post.js
if docker inspect "$mongo" -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -q '^MONGO_INITDB_ROOT_USERNAME='; then
  docker exec "$mongo" sh -lc 'mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin /tmp/v108-post.js'
else
  docker exec "$mongo" mongosh --quiet /tmp/v108-post.js
fi
docker exec "$mongo" rm -f /tmp/v108-post.js >/dev/null 2>&1 || true

mv /tmp/v108-w117105.pdf "$CORPUS_DIR/W117105_Strategic_Warehousing_122625_.pdf"
[ "$(sha256sum "$CORPUS_DIR/W117105_Strategic_Warehousing_122625_.pdf" | awk '{print $1}')" = "$EXPECTED_CORPUS" ] || { echo 'Stored target corpus SHA mismatch.' >&2; exit 62; }
chmod 0444 "$CORPUS_DIR/W117105_Strategic_Warehousing_122625_.pdf"
echo V108_TARGET_CORPUS_PRESERVED=PASS
echo V108_TARGET_DURABILITY=PASS
'@

    $targetResult = Invoke-SshScript -Ip $TargetIp -KnownHosts $TargetKnownHosts -ScriptText $TargetRemote
    Set-Content -LiteralPath (Join-Path $DiagDir 'target-v108-durable-overlay.txt') -Value $targetResult.StdOut -Encoding utf8
    if ($targetResult.StdOut) { Write-Host $targetResult.StdOut }
    if ($targetResult.StdErr) { Write-Host $targetResult.StdErr -ForegroundColor DarkYellow }
    Require ($targetResult.ExitCode -eq 0) "V108 target durability phase failed with exit code $($targetResult.ExitCode)."
    foreach ($m in @('V108_TARGET_DURABILITY_PRECHECK=PASS','V108_CANONICAL_TRUTH_PRE_RECREATE=PASS','V108_DURABLE_OVERLAY_CONFIG=PASS','V108_DURABLE_TARGET_OVERLAY=PASS','V108_CANONICAL_TRUTH_POST_RECREATE=PASS','V108_TARGET_CORPUS_PRESERVED=PASS','V108_TARGET_DURABILITY=PASS')) {
        Require ($targetResult.StdOut -match [regex]::Escape($m)) "Missing target marker: $m"
    }

    $SourceRemote = @'
set -euo pipefail
EXPECTED_IMAGE='sha256:646051f6b0434b20ad429dec18c5f7b2a7d017c0fdec94f4bd77eaa7375fabb3'
EXPECTED_HELPER='2d2298b9c7e6315745d814e5437687caf463a44dec24d73d710b6d9e4e772117'
EXPECTED_CORPUS='48410cadceaa411d65e51bd266be5c5942b4431cdede9e7a05b871e75a3a2c25'
APP='/data/apps/gpi-hub'
cd "$APP"
backend=$(docker ps --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
[ -n "$backend" ] || { echo 'Source backend not running.' >&2; exit 71; }
[ "$(docker inspect "$backend" -f '{{.Image}}')" = "$EXPECTED_IMAGE" ] || { echo 'Source backend image differs from audited exact image.' >&2; exit 72; }
[ "$(docker exec "$backend" sha256sum /app/services/document_intel_helpers.py | awk '{print $1}')" = "$EXPECTED_HELPER" ] || { echo 'Source document_intel_helpers.py differs from V106 audited helper.' >&2; exit 73; }
[ "$(sha256sum /tmp/v108-w117105.pdf | awk '{print $1}')" = "$EXPECTED_CORPUS" ] || { echo 'Source staged corpus SHA mismatch.' >&2; exit 74; }
health_before=$(docker exec "$backend" python - <<'PY'
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8001/api/health', timeout=3) as r: print(r.status)
PY
)
[ "$health_before" -ge 200 ] && [ "$health_before" -lt 400 ] || { echo 'Source backend unhealthy before corpus probe.' >&2; exit 75; }
echo "V108_SOURCE_HEALTH_BEFORE=$health_before"
echo V108_SOURCE_AI_AUTHORITY=PASS

docker cp /tmp/v108-w117105.pdf "$backend:/tmp/v108-w117105.pdf"
rm -f /tmp/v108-w117105.pdf
cat > /tmp/v108-probe.py <<'PY'
import asyncio, json, sys, types

# Keep this probe AI-only: suppress prompt-learning DB reads so no source Mongo access is required.
fb = types.ModuleType('services.classification_feedback_service')
async def empty(*args, **kwargs): return ''
fb.build_few_shot_prompt_section = empty
fb.build_vendor_hints_prompt_section = empty
sys.modules['services.classification_feedback_service'] = fb
loop = types.ModuleType('services.feedback_loop_service')
loop.build_feedback_context_for_prompt = empty
sys.modules['services.feedback_loop_service'] = loop
vendor = types.ModuleType('services.vendor_inference_service')
def no_vendor(*args, **kwargs): return (None, None)
vendor.infer_vendor = no_vendor
sys.modules['services.vendor_inference_service'] = vendor

from services.document_intel_helpers import classify_document_with_ai

async def run(path, name, label):
    r = await classify_document_with_ai(path, name)
    print(f'V108_AI_{label}=' + json.dumps(r, sort_keys=True, default=str))
    return r

def has(obj, token):
    token = token.lower()
    if isinstance(obj, dict): return any(has(k, token) or has(v, token) for k,v in obj.items())
    if isinstance(obj, (list,tuple)): return any(has(v, token) for v in obj)
    return token in str(obj).lower()

async def main():
    from pypdf import PdfReader, PdfWriter
    packet='/tmp/v108-w117105.pdf'
    full=await run(packet,'W117105_Strategic Warehousing_122625_.pdf','FULL_PACKET')
    rd=PdfReader(packet)
    if len(rd.pages) != 4: raise SystemExit(f'Expected 4-page packet, got {len(rd.pages)}')
    wr=PdfWriter(); wr.add_page(rd.pages[3])
    p4='/tmp/v108-w117105-page4.pdf'
    with open(p4,'wb') as f: wr.write(f)
    support=await run(p4,'W117105_Strategic_supporting_shipping_page.pdf','SUPPORTING_PAGE4')
    checks={
      'full_W117105':has(full,'W117105'),
      'full_962222-1':has(full,'962222-1'),
      'full_815734':has(full,'815734'),
      'full_ER25-1560':has(full,'ER25-1560'),
      'page4_ER25-1560':has(support,'ER25-1560'),
    }
    print('V108_AI_CHECKS='+json.dumps(checks,sort_keys=True))
    for k,v in checks.items(): print(f'V108_CHECK_{k}=' + ('PASS' if v else 'MISS'))
    if checks['page4_ER25-1560'] and not checks['full_ER25-1560']:
        print('V108_MULTIPAGE_REFERENCE_GAP=PROVEN_SUPPORTING_SHIPMENT_LOST_BY_CURRENT_FIRST_PAGE_SEAM')
    elif checks['full_ER25-1560']:
        print('V108_MULTIPAGE_REFERENCE_GAP=NOT_OBSERVED_FULL_PACKET_PRESERVED_SHIPMENT')
    else:
        print('V108_MULTIPAGE_REFERENCE_GAP=UNRESOLVED_SUPPORTING_SHIPMENT_NOT_EXTRACTED')
    if not checks['full_W117105']:
        raise SystemExit('Full-packet AI result failed to retain W117105 primary identity')
    print('V108_STRATEGIC_PRIMARY_IDENTITY=PASS')

asyncio.run(main())
PY
docker cp /tmp/v108-probe.py "$backend:/tmp/v108-probe.py"
rm -f /tmp/v108-probe.py
set +e
probe_out=$(docker exec "$backend" python /tmp/v108-probe.py 2>&1)
probe_code=$?
set -e
printf '%s\n' "$probe_out"
docker exec "$backend" rm -f /tmp/v108-probe.py /tmp/v108-w117105.pdf /tmp/v108-w117105-page4.pdf >/dev/null 2>&1 || true
[ "$probe_code" -eq 0 ] || { echo "Source AI-only corpus probe failed with exit code $probe_code" >&2; exit 76; }
printf '%s\n' "$probe_out" | grep -Fq 'V108_STRATEGIC_PRIMARY_IDENTITY=PASS' || { echo 'Strategic primary identity marker missing.' >&2; exit 77; }
health_after=$(docker exec "$backend" python - <<'PY'
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8001/api/health', timeout=3) as r: print(r.status)
PY
)
[ "$health_after" -ge 200 ] && [ "$health_after" -lt 400 ] || { echo 'Source backend unhealthy after corpus probe.' >&2; exit 78; }
echo "V108_SOURCE_HEALTH_AFTER=$health_after"
echo V108_SOURCE_AI_CORPUS_PROBE=PASS
'@

    $sourceResult = Invoke-SshScript -Ip $SourceIp -KnownHosts $SourceKnownHosts -ScriptText $SourceRemote
    Set-Content -LiteralPath (Join-Path $DiagDir 'source-v108-strategic-ai-corpus.txt') -Value $sourceResult.StdOut -Encoding utf8
    if ($sourceResult.StdOut) { Write-Host $sourceResult.StdOut }
    if ($sourceResult.StdErr) { Write-Host $sourceResult.StdErr -ForegroundColor DarkYellow }
    Require ($sourceResult.ExitCode -eq 0) "V108 source AI-only corpus probe failed with exit code $($sourceResult.ExitCode)."
    foreach ($m in @('V108_SOURCE_AI_AUTHORITY=PASS','V108_STRATEGIC_PRIMARY_IDENTITY=PASS','V108_SOURCE_AI_CORPUS_PROBE=PASS')) {
        Require ($sourceResult.StdOut -match [regex]::Escape($m)) "Missing source marker: $m"
    }
    $gap = @($sourceResult.StdOut -split "`n" | Where-Object { $_ -like 'V108_MULTIPAGE_REFERENCE_GAP=*' } | Select-Object -Last 1)
    Require ($gap.Count -eq 1) 'Missing V108 multi-page reference disposition.'

    Write-Section 'V108 FINAL RESULT'
    Write-Host 'Durable target patch : PASS / READ-ONLY OVERLAY / PINNED IMAGE PRESERVED'
    Write-Host 'JBS outbound         : shipment_number=5975975 preserved'
    Write-Host 'Strategic outbound   : shipment_number=57745 preserved'
    Write-Host 'Strategic inbound    : authentic W117105 AI-only corpus probe complete'
    Write-Host "Multi-page finding   : $($gap[0])"
    Write-Host 'Source runtime       : no restart / no intake / no SharePoint or BC call'
    Write-Host 'Target runtime       : internal-only / workers suppressed / no egress'
    Write-Host 'Production           : NOT TOUCHED'
    Write-Host "Diagnostics          : $DiagDir"
    Write-Host 'V108_DURABLE_WAREHOUSE_STRATEGIC_CORPUS=PASS' -ForegroundColor Green
    Write-Host 'NEXT: resolve any proven multi-page Warehouse extraction gap, then AP TOP-10 PAYABLE COHORT (ISSUE #19).' -ForegroundColor Yellow
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
