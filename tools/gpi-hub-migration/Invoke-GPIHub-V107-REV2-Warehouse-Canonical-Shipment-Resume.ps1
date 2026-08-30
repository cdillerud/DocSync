#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$StatePath = Join-Path $ToolRoot 'state.json'
$State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 50

$OperationalRoot = [string]$State.local.operational_root
$KeyPath = [string]$State.local.ssh_key
$TargetIp = [string]$State.target.public_ip

$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\migration-v107-rev2-warehouse-canonical-shipment\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
$TranscriptPath = Join-Path $DiagDir 'Invoke-GPIHub-V107-REV2-Warehouse-Canonical-Shipment-Resume.txt'
Start-Transcript -LiteralPath $TranscriptPath -Force | Out-Null

function Require([bool]$Condition,[string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Invoke-NativeText {
    param([Parameter(Mandatory)][string]$FilePath,[Parameter(Mandatory)][string[]]$Arguments,[switch]$AllowFailure)
    $token = [guid]::NewGuid().ToString('N')
    $stderrFile = Join-Path $env:TEMP "gpi-v107r2-$token.err.txt"
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
    $files = @(Get-ChildItem -LiteralPath $diagRoot -Filter '*known_hosts*' -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
    foreach ($file in $files) {
        $probe = Invoke-NativeText -FilePath 'ssh-keygen.exe' -Arguments @('-F',$Ip,'-f',$file.FullName) -AllowFailure
        if ($probe.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($probe.StdOut)) { return $file.FullName }
    }
    throw "No Azure-verified known_hosts file was found for $Ip."
}

function Invoke-SshScript {
    param([Parameter(Mandatory)][string]$Ip,[Parameter(Mandatory)][string]$KnownHosts,[Parameter(Mandatory)][string]$ScriptText)
    $token = [guid]::NewGuid().ToString('N')
    $stderrFile = Join-Path $env:TEMP "gpi-v107r2-ssh-$token.err.txt"
    $oldEap = $ErrorActionPreference
    $nativeVar = Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $oldNative = if ($null -ne $nativeVar) { $nativeVar.Value } else { $null }
    $args = @('-i',$KeyPath,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',"UserKnownHostsFile=$KnownHosts",'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=20',"azureuser@$Ip",'bash -s')
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

function Write-Section([string]$Title) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

try {
    Write-Section 'V107 REV2 - RESUME / CLOSEOUT WAREHOUSE CANONICAL SHIPMENT TARGET TEST'
    Write-Host 'Action              : RESUME AFTER V107 HARNESS STDIN BUG; NO BLIND REPATCH / NO BLIND RESTART'
    Write-Host 'Target code         : VERIFY EXISTING ONE-LINE CONTAINER TEST PATCH'
    Write-Host 'Target data         : VERIFY BEFORE STATE, THEN TWO AUTHORITATIVE shipment_number BACKFILLS ONLY'
    Write-Host 'JBS inbound         : CURRENT ROUTING FUNCTION REPLAY VIA TEMP FILE; NO STORED ROUTE WRITE'
    Write-Host 'Strategic inbound   : NOT MUTATED / REMAINS OPEN CORPUS TEST'
    Write-Host 'Source VM           : NOT TOUCHED'
    Write-Host 'BC / SharePoint     : NO WRITES'
    Write-Host 'Traffic cutover     : NONE'
    Write-Host 'Production          : NOT TOUCHED'

    Require (Test-Path -LiteralPath $KeyPath -PathType Leaf) "SSH key missing: $KeyPath"
    Require ($null -ne (Get-Command ssh.exe -ErrorAction SilentlyContinue)) 'ssh.exe unavailable.'
    Require ($null -ne (Get-Command ssh-keygen.exe -ErrorAction SilentlyContinue)) 'ssh-keygen.exe unavailable.'
    $KnownHosts = Get-KnownHostsForIp -Ip $TargetIp

    $Remote = @'
set -euo pipefail
PROJECT='gpi-hub-v100'
STATIC_NET='gpi-hub-v100-static-net'
BASELINE_SHA='7c763c99a7fa765d9e168e3df18baecbe71007b9737ee839d3b3418ce6395020'
PATCHED_SHA='0041452a8c0c6749f88e02990014141c327720abff8d157afcbe21969f6f0a4a'
REL='workflows/document_capture/rules/workflow_status.py'
APP='/gpi-hub-data/apps/gpi-hub/backend'
RUN='/gpi-hub-data/migration/v107-rev2-warehouse-canonical-shipment/'$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$RUN"

backend=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
mongo=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=mongodb' --format '{{.Names}}' | head -n 1)
[ -n "$backend" ] && [ -n "$mongo" ] || { echo 'Required target service missing.' >&2; exit 41; }

for expected in 'GPI_MIGRATION_STATIC_RUNTIME=true' 'SHAREPOINT_TARGET=test' 'BC_WRITE_ENABLED=false' 'BC_BLOCK_PRODUCTION_WRITES=true' 'EMAIL_POLLING_ENABLED=false' 'SALES_EMAIL_POLLING_ENABLED=false' 'AUTO_POST_ENABLED=false' 'AUTO_CREATE_SALES_ORDER_ENABLED=false'; do
  docker inspect "$backend" -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fxq "$expected" || { echo "SAFETY_ENV_MISSING=$expected" >&2; exit 42; }
done
[ "$(docker network inspect "$STATIC_NET" -f '{{.Internal}}')" = 'true' ] || { echo 'Static network is not internal.' >&2; exit 43; }
[ "$(docker inspect "$backend" -f '{{range $k,$v := .NetworkSettings.Networks}}{{println $k}}{{end}}' | sed '/^$/d')" = "$STATIC_NET" ] || { echo 'Unexpected backend network set.' >&2; exit 44; }
if docker exec "$backend" python -c 'import socket; s=socket.create_connection(("graph.microsoft.com",443),3); s.close()' >/dev/null 2>&1; then
  echo 'Target unexpectedly has external egress.' >&2; exit 45
fi
server_mount=$(docker inspect "$backend" -f '{{range .Mounts}}{{if eq .Destination "/app/server.py"}}{{println .Source}}{{end}}{{end}}' | head -n 1)
[ -n "$server_mount" ] || { echo 'Static server suppression overlay missing.' >&2; exit 46; }
echo V107_REV2_TARGET_ISOLATION=PASS

host_sha=$(sha256sum "$APP/$REL" | awk '{print $1}')
container_sha=$(docker exec "$backend" sha256sum "/app/$REL" | awk '{print $1}')
echo "V107_REV2_CODE_STATE|HOST=$host_sha|CONTAINER=$container_sha|EXPECTED_PATCH=$PATCHED_SHA"
[ "$host_sha" = "$BASELINE_SHA" ] || { echo 'Original host tree changed unexpectedly.' >&2; exit 47; }
[ "$container_sha" = "$PATCHED_SHA" ] || { echo 'Expected V107 target container patch is not present; refusing resume.' >&2; exit 48; }
docker exec "$backend" grep -Fq 'GPI-SQUARE9-WAREHOUSE-SHIPMENT-CANONICAL-V107' "/app/$REL"
echo V107_REV2_EXISTING_PATCH_VERIFIED=PASS

# Confirm backend remains internally healthy after the already-completed V107 restart.
docker exec "$backend" python - <<'PY'
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8001/api/health', timeout=5) as r:
    if not (200 <= r.status < 400): raise SystemExit(r.status)
PY
echo V107_REV2_BACKEND_HEALTH=PASS

# Snapshot authoritative Shipping_Document fields BEFORE any REV2 mutation.
cat > /tmp/v107r2-before.js <<'JS'
const D=db.getSiblingDB('gpi_document_hub'); const C=D.getCollection('hub_documents');
const specs=[
 {id:'04a47c5e-9180-4b41-bbd2-fcbfb62d336b',expected:'5975975',label:'JBS_OUTBOUND'},
 {id:'f35038a9-6d26-49c5-8461-67cef2083171',expected:'57745',label:'STRATEGIC_OUTBOUND'}
];
const out=[];
for(const s of specs){
 const d=C.findOne({id:s.id},{_id:0,id:1,file_name:1,document_type:1,shipment_number:1,bol_number:1,bol_number_extracted:1,extracted_fields:1,normalized_fields:1});
 if(!d) throw new Error(s.label+': document missing');
 const bol=(d.normalized_fields&&d.normalized_fields.bol_number)||(d.extracted_fields&&d.extracted_fields.bol_number)||d.bol_number||d.bol_number_extracted||null;
 if(String(bol)!==s.expected) throw new Error(s.label+': BOL mismatch '+bol);
 if(d.shipment_number!=null && String(d.shipment_number)!==s.expected) throw new Error(s.label+': conflicting shipment_number '+d.shipment_number);
 out.push({label:s.label,id:s.id,file_name:d.file_name,bol_number:String(bol),shipment_number:d.shipment_number??null});
}
print('V107_REV2_BEFORE='+JSON.stringify(out));
JS
docker cp /tmp/v107r2-before.js "$mongo:/tmp/v107r2-before.js" >/dev/null; rm -f /tmp/v107r2-before.js
before_out=$(docker exec "$mongo" sh -lc '
 set -e
 if [ -n "${MONGO_INITDB_ROOT_USERNAME:-}" ] && [ -n "${MONGO_INITDB_ROOT_PASSWORD:-}" ]; then
   exec mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin /tmp/v107r2-before.js
 else exec mongosh --quiet /tmp/v107r2-before.js; fi
')
docker exec "$mongo" rm -f /tmp/v107r2-before.js >/dev/null 2>&1 || true
printf '%s\n' "$before_out" | tee "$RUN/before.txt"
echo V107_REV2_PREBACKFILL_TRUTH=PASS

# Retrieve W118228 and move JSON into backend as a file. Do NOT multiplex JSON and Python source on stdin.
cat > /tmp/v107r2-jbs.js <<'JS'
const D=db.getSiblingDB('gpi_document_hub');
const d=D.getCollection('hub_documents').findOne({id:'95ced52c-1521-43b6-b69e-4afc4ed600d5'},{_id:0,id:1,file_name:1,document_type:1,doc_type:1,suggested_job_type:1,vendor_canonical:1,vendor_name:1,vendor_raw:1,extracted_fields:1,normalized_fields:1,is_international:1,freight_direction:1,location_code:1,location_code_resolved:1,bc_po_resolved:1,po_number_clean:1,po_number_extracted:1,order_number:1,po_resolution:1,routing_details:1,sharepoint_folder_path:1,folder_routing_reason:1});
if(!d) throw new Error('W118228 target document missing'); print(JSON.stringify(d));
JS
docker cp /tmp/v107r2-jbs.js "$mongo:/tmp/v107r2-jbs.js" >/dev/null; rm -f /tmp/v107r2-jbs.js
jbs_json=$(docker exec "$mongo" sh -lc '
 set -e
 if [ -n "${MONGO_INITDB_ROOT_USERNAME:-}" ] && [ -n "${MONGO_INITDB_ROOT_PASSWORD:-}" ]; then
   exec mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin /tmp/v107r2-jbs.js
 else exec mongosh --quiet /tmp/v107r2-jbs.js; fi
')
docker exec "$mongo" rm -f /tmp/v107r2-jbs.js >/dev/null 2>&1 || true
[ -n "$jbs_json" ] || { echo 'W118228 Mongo JSON was empty.' >&2; exit 49; }
printf '%s' "$jbs_json" > "$RUN/W118228.json"
docker cp "$RUN/W118228.json" "$backend:/tmp/v107r2-W118228.json"

docker exec "$backend" python - <<'PY'
import json, inspect, asyncio
from services.folder_routing_service import determine_folder_path
with open('/tmp/v107r2-W118228.json','r',encoding='utf-8') as f: doc=json.load(f)
sig=inspect.signature(determine_folder_path)
print(f'V107_REV2_ROUTING_SIGNATURE={sig}')
values={
 'doc':doc,'document':doc,
 'doc_type':doc.get('document_type') or doc.get('doc_type') or doc.get('suggested_job_type'),
 'document_type':doc.get('document_type') or doc.get('doc_type') or doc.get('suggested_job_type'),
 'vendor_name':doc.get('vendor_canonical') or doc.get('vendor_name') or doc.get('vendor_raw') or '',
 'vendor':doc.get('vendor_canonical') or doc.get('vendor_name') or doc.get('vendor_raw') or '',
 'order_number':doc.get('po_number_extracted') or doc.get('po_number_clean') or (doc.get('extracted_fields') or {}).get('po_number') or (doc.get('normalized_fields') or {}).get('po_number') or doc.get('order_number') or '',
 'is_international':bool(doc.get('is_international') or (doc.get('extracted_fields') or {}).get('is_international') or (doc.get('normalized_fields') or {}).get('is_international')),
 'freight_direction':doc.get('freight_direction') or (doc.get('extracted_fields') or {}).get('freight_direction') or (doc.get('normalized_fields') or {}).get('freight_direction'),
 'location_code':doc.get('location_code_resolved') or doc.get('location_code'),
 'extracted':doc.get('extracted_fields') or {}, 'normalized':doc.get('normalized_fields') or {},
 'intelligence':doc.get('reference_intelligence') or {},
}
kwargs={}
for name,p in sig.parameters.items():
    if name in values: kwargs[name]=values[name]
    elif p.default is inspect._empty and p.kind not in (inspect.Parameter.VAR_POSITIONAL,inspect.Parameter.VAR_KEYWORD):
        raise SystemExit(f'Unsupported required routing parameter: {name}')
res=determine_folder_path(**kwargs)
if inspect.isawaitable(res): res=asyncio.run(res)
if isinstance(res,(tuple,list)):
    path=res[0] if res else None; reason=res[1] if len(res)>1 else None
elif isinstance(res,dict):
    path=res.get('folder_path') or res.get('path'); reason=res.get('reason')
else: path=str(res); reason=None
print('V107_REV2_JBS_INBOUND_REPLAY_PATH='+str(path))
print('V107_REV2_JBS_INBOUND_REPLAY_REASON='+str(reason))
if path != 'Warehouse Not International': raise SystemExit('Unexpected W118228 replay path: '+str(path))
PY
docker exec "$backend" rm -f /tmp/v107r2-W118228.json >/dev/null 2>&1 || true
echo V107_REV2_JBS_INBOUND_CURRENT_ROUTING_REPLAY=PASS

# Now perform exactly the two intended authoritative target-only canonical field updates.
cat > /tmp/v107r2-backfill.js <<'JS'
const D=db.getSiblingDB('gpi_document_hub'); const C=D.getCollection('hub_documents');
const specs=[
 {id:'04a47c5e-9180-4b41-bbd2-fcbfb62d336b',expected:'5975975',label:'JBS_OUTBOUND'},
 {id:'f35038a9-6d26-49c5-8461-67cef2083171',expected:'57745',label:'STRATEGIC_OUTBOUND'}
];
const changed=[]; const after=[];
for(const s of specs){
 const d=C.findOne({id:s.id},{_id:0,id:1,file_name:1,document_type:1,shipment_number:1,bol_number:1,bol_number_extracted:1,extracted_fields:1,normalized_fields:1});
 if(!d || d.document_type!=='Shipping_Document') throw new Error(s.label+': authoritative Shipping_Document missing/wrong type');
 const bol=(d.normalized_fields&&d.normalized_fields.bol_number)||(d.extracted_fields&&d.extracted_fields.bol_number)||d.bol_number||d.bol_number_extracted||null;
 if(String(bol)!==s.expected) throw new Error(s.label+': expected BOL '+s.expected+', found '+bol);
 if(d.shipment_number==null){ const r=C.updateOne({id:s.id,shipment_number:{$in:[null] }},{$set:{shipment_number:String(bol)}}); changed.push({label:s.label,modified:r.modifiedCount}); }
 else if(String(d.shipment_number)!==s.expected) throw new Error(s.label+': conflicting shipment_number '+d.shipment_number);
 const a=C.findOne({id:s.id},{_id:0,id:1,file_name:1,shipment_number:1,bol_number_extracted:1,extracted_fields:1,normalized_fields:1});
 const abol=(a.normalized_fields&&a.normalized_fields.bol_number)||(a.extracted_fields&&a.extracted_fields.bol_number)||a.bol_number_extracted||null;
 if(String(a.shipment_number)!==s.expected || String(abol)!==s.expected) throw new Error(s.label+': after verification failed');
 after.push({label:s.label,id:s.id,file_name:a.file_name,shipment_number:a.shipment_number,bol_number:String(abol)});
}
print('V107_REV2_CHANGED='+JSON.stringify(changed)); print('V107_REV2_AFTER='+JSON.stringify(after));
JS
docker cp /tmp/v107r2-backfill.js "$mongo:/tmp/v107r2-backfill.js" >/dev/null; rm -f /tmp/v107r2-backfill.js
backfill_out=$(docker exec "$mongo" sh -lc '
 set -e
 if [ -n "${MONGO_INITDB_ROOT_USERNAME:-}" ] && [ -n "${MONGO_INITDB_ROOT_PASSWORD:-}" ]; then
   exec mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin /tmp/v107r2-backfill.js
 else exec mongosh --quiet /tmp/v107r2-backfill.js; fi
')
docker exec "$mongo" rm -f /tmp/v107r2-backfill.js >/dev/null 2>&1 || true
printf '%s\n' "$backfill_out" | tee "$RUN/after.txt"
echo V107_REV2_JBS_OUTBOUND_CANONICAL_SHIPMENT=PASS
echo V107_REV2_STRATEGIC_OUTBOUND_57745_REGRESSION=PASS

# Final safety and non-durable patch evidence.
[ "$(sha256sum "$APP/$REL" | awk '{print $1}')" = "$BASELINE_SHA" ] || { echo 'Original host tree changed during REV2.' >&2; exit 50; }
[ "$(docker exec "$backend" sha256sum "/app/$REL" | awk '{print $1}')" = "$PATCHED_SHA" ] || { echo 'Container test patch changed during REV2.' >&2; exit 51; }
if docker exec "$backend" python -c 'import socket; s=socket.create_connection(("graph.microsoft.com",443),3); s.close()' >/dev/null 2>&1; then echo 'External egress unexpectedly available at closeout.' >&2; exit 52; fi
echo V107_REV2_ORIGINAL_HOST_TREE_UNCHANGED=PASS
echo V107_REV2_STATIC_SAFETY_PRESERVED=PASS
echo V107_REV2_STRATEGIC_INBOUND_STATUS=OPEN_CORPUS_INGESTION_REQUIRED
echo V107_REV2_PATCH_DURABILITY=TARGET_CONTAINER_TEST_ONLY
echo "V107_REV2_EVIDENCE_DIR=$RUN"
echo V107_REV2_NARROW_TARGET_FIX_REPLAY=PASS
'@

    $result = Invoke-SshScript -Ip $TargetIp -KnownHosts $KnownHosts -ScriptText $Remote
    $RawPath = Join-Path $DiagDir 'target-v107-rev2-resume.txt'
    Set-Content -LiteralPath $RawPath -Value $result.StdOut -Encoding utf8
    if (-not [string]::IsNullOrWhiteSpace($result.StdOut)) { Write-Host $result.StdOut }
    if (-not [string]::IsNullOrWhiteSpace($result.StdErr)) { Write-Host $result.StdErr -ForegroundColor DarkYellow }
    Require ($result.ExitCode -eq 0) "V107 REV2 remote closeout failed with exit code $($result.ExitCode)."

    foreach ($marker in @(
        'V107_REV2_TARGET_ISOLATION=PASS',
        'V107_REV2_EXISTING_PATCH_VERIFIED=PASS',
        'V107_REV2_BACKEND_HEALTH=PASS',
        'V107_REV2_PREBACKFILL_TRUTH=PASS',
        'V107_REV2_JBS_INBOUND_CURRENT_ROUTING_REPLAY=PASS',
        'V107_REV2_JBS_OUTBOUND_CANONICAL_SHIPMENT=PASS',
        'V107_REV2_STRATEGIC_OUTBOUND_57745_REGRESSION=PASS',
        'V107_REV2_ORIGINAL_HOST_TREE_UNCHANGED=PASS',
        'V107_REV2_STATIC_SAFETY_PRESERVED=PASS',
        'V107_REV2_NARROW_TARGET_FIX_REPLAY=PASS'
    )) { Require ($result.StdOut -match [regex]::Escape($marker)) "Missing required V107 REV2 marker: $marker" }

    Write-Section 'V107 REV2 FINAL RESULT'
    Write-Host 'JBS inbound          : CURRENT ROUTING REPLAY PROVEN -> Warehouse Not International'
    Write-Host 'JBS outbound         : canonical shipment_number=5975975 proven on target'
    Write-Host 'Strategic outbound   : canonical shipment_number=57745 preserved'
    Write-Host 'Strategic inbound    : OPEN - authentic W117105 isolated corpus test still required'
    Write-Host 'Runtime code patch   : VERIFIED TARGET-CONTAINER TEST PATCH / STILL NON-DURABLE'
    Write-Host 'Original host tree   : UNCHANGED'
    Write-Host 'Source VM            : NOT TOUCHED'
    Write-Host 'BC / SharePoint      : NO WRITES'
    Write-Host 'Production           : NOT TOUCHED'
    Write-Host "Diagnostics          : $DiagDir"
    Write-Host 'V107_WAREHOUSE_CANONICAL_SHIPMENT_TARGET_TEST=PASS' -ForegroundColor Green
    Write-Host 'NEXT: V108 DURABLE OVERLAY + AUTHENTIC STRATEGIC INBOUND W117105 CORPUS TEST.' -ForegroundColor Yellow
}
finally { try { Stop-Transcript | Out-Null } catch {} }
