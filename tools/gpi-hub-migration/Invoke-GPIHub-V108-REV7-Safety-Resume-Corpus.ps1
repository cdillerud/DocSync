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
$CorpusPath = Join-Path $env:USERPROFILE 'Downloads\W117105_Strategic Warehousing_122625_.pdf'
$CorpusSha = '48410cadceaa411d65e51bd266be5c5942b4431cdede9e7a05b871e75a3a2c25'
$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\migration-v108-rev7-safety-resume\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
Start-Transcript -LiteralPath (Join-Path $DiagDir 'Invoke-GPIHub-V108-REV7-Safety-Resume-Corpus.txt') -Force | Out-Null

function Require([bool]$Condition,[string]$Message) { if (-not $Condition) { throw $Message } }

function Invoke-NativeText {
    param([Parameter(Mandatory)][string]$FilePath,[Parameter(Mandatory)][string[]]$Arguments,[switch]$AllowFailure)
    $token=[guid]::NewGuid().ToString('N')
    $stderrFile=Join-Path $env:TEMP "gpi-v108-rev7-$token.err.txt"
    $oldEap=$ErrorActionPreference
    $nativeVar=Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $oldNative=if($null-ne$nativeVar){$nativeVar.Value}else{$null}
    try {
        $ErrorActionPreference='Continue'
        if($null-ne$nativeVar){$PSNativeCommandUseErrorActionPreference=$false}
        $output=& $FilePath @Arguments 2> $stderrFile
        $code=$LASTEXITCODE
        $stdout=(@($output)|ForEach-Object{[string]$_}) -join "`n"
        $stderr=if(Test-Path -LiteralPath $stderrFile){Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue}else{''}
        $r=[pscustomobject]@{ExitCode=[int]$code;StdOut=[string]$stdout;StdErr=[string]$stderr}
        if(-not$AllowFailure -and $r.ExitCode-ne0){throw "$FilePath failed ($($r.ExitCode)).`n$stdout`n$stderr"}
        return $r
    }
    finally {
        $ErrorActionPreference=$oldEap
        if($null-ne$nativeVar){$PSNativeCommandUseErrorActionPreference=$oldNative}
        Remove-Item -LiteralPath $stderrFile -Force -ErrorAction SilentlyContinue
    }
}

function Get-KnownHostsForIp([string]$Ip) {
    $diagRoot=Join-Path $OperationalRoot '.gpi-diagnostics'
    foreach($file in @(Get-ChildItem -LiteralPath $diagRoot -Filter '*known_hosts*' -File -Recurse -ErrorAction SilentlyContinue|Sort-Object LastWriteTime -Descending)){
        $p=Invoke-NativeText -FilePath 'ssh-keygen.exe' -Arguments @('-F',$Ip,'-f',$file.FullName) -AllowFailure
        if($p.ExitCode-eq0 -and -not[string]::IsNullOrWhiteSpace($p.StdOut)){return $file.FullName}
    }
    throw "No Azure-verified known_hosts file found for $Ip."
}

function Invoke-SshScript {
    param([string]$Ip,[string]$KnownHosts,[string]$ScriptText)
    $token=[guid]::NewGuid().ToString('N')
    $stderrFile=Join-Path $env:TEMP "gpi-v108-rev7-ssh-$token.err.txt"
    $args=@('-i',$KeyPath,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',"UserKnownHostsFile=$KnownHosts",'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=20',"azureuser@$Ip",'bash -s')
    $oldEap=$ErrorActionPreference
    $nativeVar=Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $oldNative=if($null-ne$nativeVar){$nativeVar.Value}else{$null}
    try {
        $ErrorActionPreference='Continue'
        if($null-ne$nativeVar){$PSNativeCommandUseErrorActionPreference=$false}
        $output=(($ScriptText-replace"`r`n","`n")|& ssh.exe @args 2> $stderrFile)
        $code=$LASTEXITCODE
        $stdout=(@($output)|ForEach-Object{[string]$_}) -join "`n"
        $stderr=if(Test-Path -LiteralPath $stderrFile){Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue}else{''}
        return [pscustomobject]@{ExitCode=[int]$code;StdOut=[string]$stdout;StdErr=[string]$stderr}
    }
    finally {
        $ErrorActionPreference=$oldEap
        if($null-ne$nativeVar){$PSNativeCommandUseErrorActionPreference=$oldNative}
        Remove-Item -LiteralPath $stderrFile -Force -ErrorAction SilentlyContinue
    }
}

function Stage-Corpus([string]$Ip,[string]$KnownHosts) {
    $r=Invoke-NativeText -FilePath 'scp.exe' -Arguments @('-i',$KeyPath,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',"UserKnownHostsFile=$KnownHosts",'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=20',$CorpusPath,"azureuser@${Ip}:/tmp/v108-w117105.pdf")
    Require ($r.ExitCode-eq0) "Failed to stage corpus to $Ip."
}

function Section([string]$Title){Write-Host '';Write-Host('='*120)-ForegroundColor Cyan;Write-Host $Title -ForegroundColor Cyan;Write-Host('='*120)-ForegroundColor Cyan}

try {
    Section 'V108 REV7 - SAFETY RESUME + STRATEGIC INBOUND AI CORPUS'
    Write-Host 'Action              : VERIFY RECREATED TARGET IN PLACE; NO BLIND RECREATE'
    Write-Host 'Target app/data     : NO APP TREE CHANGE / NO MONGO MUTATION'
    Write-Host 'Source              : AI-ONLY STANDALONE CLASSIFIER PROBE / NO INTAKE'
    Write-Host 'BC / SharePoint     : NO WRITES'
    Write-Host 'Production          : NOT TOUCHED'

    Require (Test-Path -LiteralPath $CorpusPath -PathType Leaf) "W117105 corpus missing: $CorpusPath"
    $sha=(Get-FileHash -LiteralPath $CorpusPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Require ($sha-eq$CorpusSha) "W117105 corpus SHA mismatch: $sha"
    Write-Host 'V108_REV7_CORPUS_SHA=PASS' -ForegroundColor Green

    Require (Test-Path -LiteralPath $KeyPath -PathType Leaf) "SSH key missing: $KeyPath"
    foreach($cmd in 'ssh.exe','scp.exe','ssh-keygen.exe'){Require ($null-ne(Get-Command $cmd -ErrorAction SilentlyContinue)) "$cmd unavailable."}
    $TargetKnown=Get-KnownHostsForIp $TargetIp
    $SourceKnown=Get-KnownHostsForIp $SourceIp
    Stage-Corpus $TargetIp $TargetKnown
    Stage-Corpus $SourceIp $SourceKnown
    Write-Host 'V108_REV7_CORPUS_STAGED=PASS' -ForegroundColor Green

    $TargetRemote=@'
set -euo pipefail
PROJECT='gpi-hub-v100'
STATIC_NET='gpi-hub-v100-static-net'
APP='/gpi-hub-data/apps/gpi-hub'
MIG='/gpi-hub-data/migration'
STATIC_SERVER="$MIG/v100-static-overlay/server.py"
DURABLE_WORKFLOW="$MIG/v108-warehouse-durable-overlay/workflow_status.py"
V108_OVERRIDE="$MIG/v108-warehouse-durable-overlay.yml"
CORPUS_DIR="$MIG/v108-strategic-inbound-corpus"
EXPECTED_IMAGE='sha256:646051f6b0434b20ad429dec18c5f7b2a7d017c0fdec94f4bd77eaa7375fabb3'
EXPECTED_BASELINE='7c763c99a7fa765d9e168e3df18baecbe71007b9737ee839d3b3418ce6395020'
EXPECTED_PATCH='0041452a8c0c6749f88e02990014141c327720abff8d157afcbe21969f6f0a4a'
EXPECTED_CORPUS='48410cadceaa411d65e51bd266be5c5942b4431cdede9e7a05b871e75a3a2c25'
REL='workflows/document_capture/rules/workflow_status.py'
TARGET_REL='/app/workflows/document_capture/rules/workflow_status.py'

backend=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
mongo=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=mongodb' --format '{{.Names}}' | head -n 1)
[ -n "$backend" ] && [ -n "$mongo" ] || { echo 'Required target service missing.' >&2; exit 41; }
[ "$(docker inspect "$backend" -f '{{.Image}}')" = "$EXPECTED_IMAGE" ] || { echo 'Backend image drift.' >&2; exit 42; }
[ "$(sha256sum "$APP/backend/$REL" | awk '{print $1}')" = "$EXPECTED_BASELINE" ] || { echo 'Original host tree drift.' >&2; exit 43; }
[ -f "$STATIC_SERVER" ] && [ -f "$DURABLE_WORKFLOW" ] && [ -f "$V108_OVERRIDE" ] || { echo 'Required durable/static overlay artifact missing.' >&2; exit 44; }
[ "$(sha256sum "$DURABLE_WORKFLOW" | awk '{print $1}')" = "$EXPECTED_PATCH" ] || { echo 'Durable workflow overlay SHA drift.' >&2; exit 45; }
[ "$(docker exec "$backend" sha256sum "$TARGET_REL" | awk '{print $1}')" = "$EXPECTED_PATCH" ] || { echo 'Running workflow overlay SHA drift.' >&2; exit 46; }

echo V108_REV7_DURABLE_WORKFLOW_OVERLAY=PASS

# Prove the actual running server.py is the static early-return overlay, independently of log timing.
server_src=$(docker inspect "$backend" -f '{{range .Mounts}}{{if eq .Destination "/app/server.py"}}{{println .Source}}{{end}}{{end}}' | head -n 1)
server_rw=$(docker inspect "$backend" -f '{{range .Mounts}}{{if eq .Destination "/app/server.py"}}{{println .RW}}{{end}}{{end}}' | head -n 1)
workflow_src=$(docker inspect "$backend" -f '{{range .Mounts}}{{if eq .Destination "/app/workflows/document_capture/rules/workflow_status.py"}}{{println .Source}}{{end}}{{end}}' | head -n 1)
workflow_rw=$(docker inspect "$backend" -f '{{range .Mounts}}{{if eq .Destination "/app/workflows/document_capture/rules/workflow_status.py"}}{{println .RW}}{{end}}{{end}}' | head -n 1)
[ "$server_src" = "$STATIC_SERVER" ] || { echo "Unexpected server overlay source: $server_src" >&2; exit 47; }
[ "$server_rw" = 'false' ] || { echo 'Static server overlay is not read-only.' >&2; exit 48; }
[ "$workflow_src" = "$DURABLE_WORKFLOW" ] || { echo "Unexpected workflow overlay source: $workflow_src" >&2; exit 49; }
[ "$workflow_rw" = 'false' ] || { echo 'Durable workflow overlay is not read-only.' >&2; exit 50; }
server_host_sha=$(sha256sum "$STATIC_SERVER" | awk '{print $1}')
server_container_sha=$(docker exec "$backend" sha256sum /app/server.py | awk '{print $1}')
[ "$server_host_sha" = "$server_container_sha" ] || { echo 'Static server host/container SHA mismatch.' >&2; exit 51; }
grep -Fq 'GPI_MIGRATION_STATIC_RUNTIME=ACTIVE - background workers and schedulers suppressed' "$STATIC_SERVER" || { echo 'Static suppression marker missing from overlay source.' >&2; exit 52; }
grep -Fq 'os.environ.get("GPI_MIGRATION_STATIC_RUNTIME", "false").lower() == "true"' "$STATIC_SERVER" || { echo 'Static early-return env guard missing.' >&2; exit 53; }
docker exec "$backend" grep -Fq 'GPI_MIGRATION_STATIC_RUNTIME=ACTIVE - background workers and schedulers suppressed' /app/server.py || { echo 'Static marker missing from running server.py.' >&2; exit 54; }
echo "V108_REV7_STATIC_SERVER_SHA=$server_container_sha"
echo V108_REV7_STATIC_SERVER_STRUCTURAL_GUARD=PASS

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
  docker inspect "$backend" -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fxq "$expected" || { echo "Safety env missing: $expected" >&2; exit 55; }
done
[ "$(docker network inspect "$STATIC_NET" -f '{{.Internal}}')" = 'true' ] || { echo 'Static network is not internal.' >&2; exit 56; }
nets=$(docker inspect "$backend" -f '{{range $k,$v := .NetworkSettings.Networks}}{{println $k}}{{end}}' | sed '/^$/d')
[ "$nets" = "$STATIC_NET" ] || { echo "Unexpected backend networks: $nets" >&2; exit 57; }
health=$(docker exec "$backend" python - <<'PY'
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8001/api/health', timeout=4) as r: print(r.status)
PY
)
[ "$health" -ge 200 ] && [ "$health" -lt 400 ] || { echo "Backend health failed: $health" >&2; exit 58; }
if docker exec "$backend" python -c 'import socket; s=socket.create_connection(("graph.microsoft.com",443),3); s.close()' >/dev/null 2>&1; then
  echo 'Target backend unexpectedly has Graph egress.' >&2; exit 59
fi
sleep 5
logs=$(docker logs "$backend" 2>&1 || true)
for forbidden in 'Dynamic mailbox polling worker started' 'AP email polling worker started' 'Sales email polling worker started'; do
  if printf '%s\n' "$logs" | grep -Fq "$forbidden"; then echo "Forbidden worker started: $forbidden" >&2; exit 60; fi
done
if printf '%s\n' "$logs" | grep -Fq 'GPI_MIGRATION_STATIC_RUNTIME=ACTIVE - background workers and schedulers suppressed'; then
  echo V108_REV7_LOG_MARKER=PRESENT
else
  echo V108_REV7_LOG_MARKER=ABSENT_BUT_STRUCTURAL_STATIC_GUARD_PROVEN
fi
echo "V108_REV7_BACKEND_INTERNAL_HTTP=$health"
echo V108_REV7_EXTERNAL_EGRESS_BLOCKED=PASS
echo V108_REV7_FORBIDDEN_WORKERS_ABSENT=PASS
echo V108_REV7_TARGET_STATIC_SAFETY=PASS

# Re-prove V107 canonical data truth after the durable backend recreate.
cat > /tmp/v108-rev7-truth.js <<'JS'
const C=db.getSiblingDB('gpi_document_hub').getCollection('hub_documents');
const j=C.findOne({id:'04a47c5e-9180-4b41-bbd2-fcbfb62d336b'},{_id:0,shipment_number:1,bol_number:1});
const s=C.findOne({id:'f35038a9-6d26-49c5-8461-67cef2083171'},{_id:0,shipment_number:1,bol_number:1});
if(!j || String(j.shipment_number)!=='5975975') throw new Error('JBS canonical shipment missing');
if(!s || String(s.shipment_number)!=='57745') throw new Error('Strategic outbound canonical shipment missing');
print('V108_REV7_CANONICAL_TRUTH='+JSON.stringify({jbs:j,strategic:s}));
print('V108_REV7_CANONICAL_TRUTH=PASS');
JS
docker cp /tmp/v108-rev7-truth.js "$mongo:/tmp/v108-rev7-truth.js" >/dev/null
rm -f /tmp/v108-rev7-truth.js
if docker inspect "$mongo" -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -q '^MONGO_INITDB_ROOT_USERNAME='; then
  docker exec "$mongo" sh -lc 'mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin /tmp/v108-rev7-truth.js'
else
  docker exec "$mongo" mongosh --quiet /tmp/v108-rev7-truth.js
fi
docker exec "$mongo" rm -f /tmp/v108-rev7-truth.js >/dev/null 2>&1 || true

[ "$(sha256sum /tmp/v108-w117105.pdf | awk '{print $1}')" = "$EXPECTED_CORPUS" ] || { echo 'Target staged corpus SHA mismatch.' >&2; exit 61; }
mkdir -p "$CORPUS_DIR"
cp -f /tmp/v108-w117105.pdf "$CORPUS_DIR/W117105_Strategic_Warehousing_122625_.pdf"
chmod 0444 "$CORPUS_DIR/W117105_Strategic_Warehousing_122625_.pdf"
[ "$(sha256sum "$CORPUS_DIR/W117105_Strategic_Warehousing_122625_.pdf" | awk '{print $1}')" = "$EXPECTED_CORPUS" ] || { echo 'Preserved corpus SHA mismatch.' >&2; exit 62; }
rm -f /tmp/v108-w117105.pdf
echo V108_REV7_TARGET_CORPUS_PRESERVED=PASS
echo V108_REV7_TARGET_DURABILITY_RESUME=PASS
'@

    $tr=Invoke-SshScript $TargetIp $TargetKnown $TargetRemote
    Set-Content -LiteralPath (Join-Path $DiagDir 'target-v108-rev7.txt') -Value $tr.StdOut -Encoding utf8
    if($tr.StdOut){Write-Host $tr.StdOut}
    if($tr.StdErr){Write-Host $tr.StdErr -ForegroundColor DarkYellow}
    Require ($tr.ExitCode-eq0) "V108 REV7 target safety resume failed with exit code $($tr.ExitCode)."
    foreach($m in 'V108_REV7_DURABLE_WORKFLOW_OVERLAY=PASS','V108_REV7_STATIC_SERVER_STRUCTURAL_GUARD=PASS','V108_REV7_TARGET_STATIC_SAFETY=PASS','V108_REV7_CANONICAL_TRUTH=PASS','V108_REV7_TARGET_CORPUS_PRESERVED=PASS','V108_REV7_TARGET_DURABILITY_RESUME=PASS'){
        Require ($tr.StdOut-match[regex]::Escape($m)) "Missing target marker: $m"
    }

    $SourceRemote=@'
set -euo pipefail
EXPECTED_IMAGE='sha256:646051f6b0434b20ad429dec18c5f7b2a7d017c0fdec94f4bd77eaa7375fabb3'
EXPECTED_HELPER='2d2298b9c7e6315745d814e5437687caf463a44dec24d73d710b6d9e4e772117'
EXPECTED_CORPUS='48410cadceaa411d65e51bd266be5c5942b4431cdede9e7a05b871e75a3a2c25'
backend=$(docker ps --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
[ -n "$backend" ] || { echo 'Source backend missing.' >&2; exit 71; }
[ "$(docker inspect "$backend" -f '{{.Image}}')" = "$EXPECTED_IMAGE" ] || { echo 'Source backend image drift.' >&2; exit 72; }
[ "$(docker exec "$backend" sha256sum /app/services/document_intel_helpers.py | awk '{print $1}')" = "$EXPECTED_HELPER" ] || { echo 'Source AI helper drift.' >&2; exit 73; }
[ "$(sha256sum /tmp/v108-w117105.pdf | awk '{print $1}')" = "$EXPECTED_CORPUS" ] || { echo 'Source corpus SHA mismatch.' >&2; exit 74; }
health_before=$(docker exec "$backend" python - <<'PY'
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8001/api/health', timeout=4) as r: print(r.status)
PY
)
[ "$health_before" -ge 200 ] && [ "$health_before" -lt 400 ] || { echo 'Source backend unhealthy before AI probe.' >&2; exit 75; }
echo "V108_REV7_SOURCE_HEALTH_BEFORE=$health_before"
echo V108_REV7_SOURCE_AI_AUTHORITY=PASS

docker cp /tmp/v108-w117105.pdf "$backend:/tmp/v108-w117105.pdf" >/dev/null
rm -f /tmp/v108-w117105.pdf
cat > /tmp/v108-rev7-probe.py <<'PY'
import asyncio, json, sys, types

async def empty(*args, **kwargs): return ''
fb=types.ModuleType('services.classification_feedback_service')
fb.build_few_shot_prompt_section=empty
fb.build_vendor_hints_prompt_section=empty
sys.modules['services.classification_feedback_service']=fb
loop=types.ModuleType('services.feedback_loop_service')
loop.build_feedback_context_for_prompt=empty
sys.modules['services.feedback_loop_service']=loop
vendor=types.ModuleType('services.vendor_inference_service')
def no_vendor(*args, **kwargs): return (None,None)
vendor.infer_vendor=no_vendor
sys.modules['services.vendor_inference_service']=vendor

from services.document_intel_helpers import classify_document_with_ai

def has(obj, token):
    t=token.lower()
    if isinstance(obj,dict): return any(has(k,t) or has(v,t) for k,v in obj.items())
    if isinstance(obj,(list,tuple)): return any(has(v,t) for v in obj)
    return t in str(obj).lower()

async def classify(path,name,label):
    r=await classify_document_with_ai(path,name)
    print(f'V108_REV7_AI_{label}='+json.dumps(r,sort_keys=True,default=str))
    return r

async def main():
    import fitz
    packet='/tmp/v108-w117105.pdf'
    full=await classify(packet,'W117105_Strategic Warehousing_122625_.pdf','FULL_PACKET')
    doc=fitz.open(packet)
    if doc.page_count != 4: raise SystemExit(f'Expected 4-page packet, got {doc.page_count}')
    out=fitz.open(); out.insert_pdf(doc,from_page=3,to_page=3)
    p4='/tmp/v108-w117105-page4.pdf'; out.save(p4); out.close(); doc.close()
    page4=await classify(p4,'W117105_Strategic_supporting_shipping_page.pdf','SUPPORTING_PAGE4')
    checks={
      'full_W117105':has(full,'W117105'),
      'full_962222-1':has(full,'962222-1'),
      'full_815734':has(full,'815734'),
      'full_ER25-1560':has(full,'ER25-1560'),
      'page4_ER25-1560':has(page4,'ER25-1560')
    }
    print('V108_REV7_AI_CHECKS='+json.dumps(checks,sort_keys=True))
    for k,v in checks.items(): print(f'V108_REV7_CHECK_{k}=' + ('PASS' if v else 'MISS'))
    if checks['page4_ER25-1560'] and not checks['full_ER25-1560']:
        gap='PROVEN_SUPPORTING_SHIPMENT_LOST_BY_CURRENT_FIRST_PAGE_SEAM'
    elif checks['full_ER25-1560']:
        gap='NOT_OBSERVED_FULL_PACKET_PRESERVED_SHIPMENT'
    else:
        gap='UNRESOLVED_SUPPORTING_SHIPMENT_NOT_EXTRACTED'
    print('V108_MULTIPAGE_REFERENCE_GAP='+gap)
    print('V108_STRATEGIC_PRIMARY_IDENTITY=' + ('PASS' if checks['full_W117105'] else 'MISS'))
    print('V108_REV7_AI_CORPUS_EXECUTION=PASS')

asyncio.run(main())
PY
docker cp /tmp/v108-rev7-probe.py "$backend:/tmp/v108-rev7-probe.py" >/dev/null
rm -f /tmp/v108-rev7-probe.py
set +e
probe_out=$(docker exec -e PYTHONPATH=/app -w /app "$backend" python /tmp/v108-rev7-probe.py 2>&1)
probe_code=$?
set -e
printf '%s\n' "$probe_out"
docker exec "$backend" rm -f /tmp/v108-rev7-probe.py /tmp/v108-w117105.pdf /tmp/v108-w117105-page4.pdf >/dev/null 2>&1 || true
[ "$probe_code" -eq 0 ] || { echo "AI corpus probe failed with exit code $probe_code" >&2; exit 76; }
printf '%s\n' "$probe_out" | grep -Fq 'V108_REV7_AI_CORPUS_EXECUTION=PASS' || { echo 'AI execution marker missing.' >&2; exit 77; }
health_after=$(docker exec "$backend" python - <<'PY'
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8001/api/health', timeout=4) as r: print(r.status)
PY
)
[ "$health_after" -ge 200 ] && [ "$health_after" -lt 400 ] || { echo 'Source backend unhealthy after AI probe.' >&2; exit 78; }
echo "V108_REV7_SOURCE_HEALTH_AFTER=$health_after"
echo V108_REV7_SOURCE_AI_CORPUS_PROBE=PASS
'@

    $sr=Invoke-SshScript $SourceIp $SourceKnown $SourceRemote
    Set-Content -LiteralPath (Join-Path $DiagDir 'source-v108-rev7-ai-corpus.txt') -Value $sr.StdOut -Encoding utf8
    if($sr.StdOut){Write-Host $sr.StdOut}
    if($sr.StdErr){Write-Host $sr.StdErr -ForegroundColor DarkYellow}
    Require ($sr.ExitCode-eq0) "V108 REV7 source AI corpus probe failed with exit code $($sr.ExitCode)."
    foreach($m in 'V108_REV7_SOURCE_AI_AUTHORITY=PASS','V108_REV7_AI_CORPUS_EXECUTION=PASS','V108_REV7_SOURCE_AI_CORPUS_PROBE=PASS'){
        Require ($sr.StdOut-match[regex]::Escape($m)) "Missing source marker: $m"
    }
    $gap=@($sr.StdOut-split"`n"|Where-Object{$_-like'V108_MULTIPAGE_REFERENCE_GAP=*'}|Select-Object -Last 1)
    Require ($gap.Count-eq1) 'Missing multi-page reference disposition.'
    $primary=@($sr.StdOut-split"`n"|Where-Object{$_-like'V108_STRATEGIC_PRIMARY_IDENTITY=*'}|Select-Object -Last 1)
    Require ($primary.Count-eq1) 'Missing Strategic primary identity disposition.'

    Section 'V108 REV7 FINAL RESULT'
    Write-Host 'Durable shipment fix  : VERIFIED ACTIVE READ-ONLY OVERLAY'
    Write-Host 'Target static safety  : STRUCTURALLY PROVEN / EGRESS BLOCKED / FORBIDDEN WORKERS ABSENT'
    Write-Host 'JBS outbound          : shipment_number=5975975 preserved'
    Write-Host 'Strategic outbound    : shipment_number=57745 preserved'
    Write-Host "Strategic inbound ID  : $($primary[0])"
    Write-Host "Multi-page finding    : $($gap[0])"
    Write-Host 'Source AI probe       : STANDALONE CLASSIFIER ONLY / NO INTAKE'
    Write-Host 'BC / SharePoint       : NO WRITES'
    Write-Host 'Production            : NOT TOUCHED'
    Write-Host "Diagnostics           : $DiagDir"
    Write-Host 'V108_DURABLE_WAREHOUSE_STRATEGIC_CORPUS=PASS' -ForegroundColor Green
    Write-Host 'NEXT: resolve multi-page reference gap if proven; otherwise move immediately to AP TOP-10 PAYABLE COHORT (#19).' -ForegroundColor Yellow
}
finally { try{Stop-Transcript|Out-Null}catch{} }
