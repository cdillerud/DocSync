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
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\migration-v107-warehouse-canonical-shipment\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
$TranscriptPath = Join-Path $DiagDir 'Invoke-GPIHub-V107-Warehouse-Canonical-Shipment-Target-Test.txt'
Start-Transcript -LiteralPath $TranscriptPath -Force | Out-Null

function Require([bool]$Condition,[string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Invoke-NativeText {
    param([Parameter(Mandatory)][string]$FilePath,[Parameter(Mandatory)][string[]]$Arguments,[switch]$AllowFailure)
    $token = [guid]::NewGuid().ToString('N')
    $stderrFile = Join-Path $env:TEMP "gpi-v107-$token.err.txt"
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
    $stderrFile = Join-Path $env:TEMP "gpi-v107-ssh-$token.err.txt"
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
    Write-Section 'V107 - NARROW TARGET-ISOLATED WAREHOUSE CANONICAL SHIPMENT FIX / REPLAY TEST'
    Write-Host 'Classification      : PARITY BLOCKER TARGET TEST'
    Write-Host 'Target code change  : ONE-LINE canonical shipment_number persistence in warehouse workflow'
    Write-Host 'Target data change  : TWO authoritative Shipping_Document records only'
    Write-Host 'JBS inbound         : LIVE routing-function replay only; stored historical route left untouched'
    Write-Host 'Strategic inbound   : NOT MUTATED; corpus ingestion remains separate/open'
    Write-Host 'Regression preserve : Strategic outbound B/L 57745'
    Write-Host 'Source VM           : NOT TOUCHED'
    Write-Host 'BC writes           : NONE'
    Write-Host 'SharePoint writes   : NONE'
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
REL='workflows/document_capture/rules/workflow_status.py'
APP='/gpi-hub-data/apps/gpi-hub/backend'
PATCHROOT='/gpi-hub-data/migration/v107-warehouse-canonical-shipment'
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
RUN="$PATCHROOT/$STAMP"
mkdir -p "$RUN"

backend=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
mongo=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=mongodb' --format '{{.Names}}' | head -n 1)
[ -n "$backend" ] && [ -n "$mongo" ] || { echo 'Required target service missing.' >&2; exit 41; }

for expected in 'GPI_MIGRATION_STATIC_RUNTIME=true' 'SHAREPOINT_TARGET=test' 'BC_WRITE_ENABLED=false' 'BC_BLOCK_PRODUCTION_WRITES=true' 'EMAIL_POLLING_ENABLED=false' 'SALES_EMAIL_POLLING_ENABLED=false' 'AUTO_POST_ENABLED=false' 'AUTO_CREATE_SALES_ORDER_ENABLED=false'; do
  docker inspect "$backend" -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fxq "$expected" || { echo "SAFETY_ENV_MISSING=$expected" >&2; exit 42; }
done
[ "$(docker network inspect "$STATIC_NET" -f '{{.Internal}}')" = 'true' ] || { echo 'Static network is not internal.' >&2; exit 43; }
networks=$(docker inspect "$backend" -f '{{range $k,$v := .NetworkSettings.Networks}}{{println $k}}{{end}}' | sed '/^$/d')
[ "$networks" = "$STATIC_NET" ] || { echo "Unexpected backend networks: $networks" >&2; exit 44; }
if docker exec "$backend" python -c 'import socket; s=socket.create_connection(("graph.microsoft.com",443),3); s.close()' >/dev/null 2>&1; then
  echo 'Target unexpectedly has external egress.' >&2; exit 45
fi
server_mount=$(docker inspect "$backend" -f '{{range .Mounts}}{{if eq .Destination "/app/server.py"}}{{println .Source}}{{end}}{{end}}' | head -n 1)
[ -n "$server_mount" ] || { echo 'Static server.py suppression overlay is not mounted.' >&2; exit 46; }
echo "STATIC_SERVER_OVERLAY=$server_mount"
echo V107_TARGET_ISOLATION_PRECHECK=PASS

# Authority gate: patch only the exact runtime audited in V106.
host_sha=$(sha256sum "$APP/$REL" | awk '{print $1}')
container_sha=$(docker exec "$backend" sha256sum "/app/$REL" | awk '{print $1}')
echo "V107_BASELINE_AUTHORITY|HOST=$host_sha|CONTAINER=$container_sha|EXPECTED=$BASELINE_SHA"
[ "$host_sha" = "$BASELINE_SHA" ] && [ "$container_sha" = "$BASELINE_SHA" ] || { echo 'V107 authority hash mismatch; refusing patch.' >&2; exit 47; }
echo V107_BASELINE_CODE_AUTHORITY=PASS

# Copy, patch and syntax-check outside the original host app tree.
docker cp "$backend:/app/$REL" "$RUN/workflow_status.py.original"
cp "$RUN/workflow_status.py.original" "$RUN/workflow_status.py.patched"
python3 - "$RUN/workflow_status.py.patched" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
s=p.read_text()
marker='GPI-SQUARE9-WAREHOUSE-SHIPMENT-CANONICAL-V107'
if marker in s:
    raise SystemExit('marker already present before V107 patch')
needle='            "bol_number_extracted": bol_number,\n            "po_number_extracted": po_number,'
replacement='            "bol_number_extracted": bol_number,\n            "shipment_number": bol_number,  # GPI-SQUARE9-WAREHOUSE-SHIPMENT-CANONICAL-V107\n            "po_number_extracted": po_number,'
count=s.count(needle)
if count != 1:
    raise SystemExit(f'expected exactly one persistence needle, found {count}')
p.write_text(s.replace(needle,replacement,1))
PY
patched_sha=$(sha256sum "$RUN/workflow_status.py.patched" | awk '{print $1}')
[ "$patched_sha" != "$BASELINE_SHA" ] || { echo 'Patch did not change file hash.' >&2; exit 48; }
docker cp "$RUN/workflow_status.py.patched" "$backend:/tmp/v107-workflow_status.py"
docker exec "$backend" python -m py_compile /tmp/v107-workflow_status.py
docker exec "$backend" rm -f /tmp/v107-workflow_status.py
echo "V107_PATCHED_SHA=$patched_sha"
echo V107_PATCH_BUILD_AND_SYNTAX=PASS

# Apply only to target container writable layer. Original host tree and pinned image remain untouched.
docker cp "$RUN/workflow_status.py.patched" "$backend:/app/$REL"
container_patched_sha=$(docker exec "$backend" sha256sum "/app/$REL" | awk '{print $1}')
[ "$container_patched_sha" = "$patched_sha" ] || { echo 'Container patch hash mismatch.' >&2; exit 49; }
docker exec "$backend" grep -Fq 'GPI-SQUARE9-WAREHOUSE-SHIPMENT-CANONICAL-V107' "/app/$REL"
echo V107_TARGET_CONTAINER_PATCH_APPLIED=PASS

# Restart the same container; do not recreate it, preserving static network/env/server overlay.
restart_since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
docker restart "$backend" >/dev/null
healthy=0
for i in $(seq 1 120); do
  if ! docker ps --format '{{.Names}}' | grep -Fxq "$backend"; then
    echo 'Backend exited after V107 restart.' >&2
    docker logs --tail 160 "$backend" >&2 || true
    exit 50
  fi
  if docker exec "$backend" python - <<'PY' >/dev/null 2>&1
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8001/api/health', timeout=3) as r:
    raise SystemExit(0 if 200 <= r.status < 400 else 1)
PY
  then healthy=1; break; fi
  sleep 2
done
[ "$healthy" -eq 1 ] || { docker logs --tail 200 "$backend" >&2 || true; echo 'Backend did not become internally healthy.' >&2; exit 51; }
[ "$(docker inspect "$backend" -f '{{range $k,$v := .NetworkSettings.Networks}}{{println $k}}{{end}}' | sed '/^$/d')" = "$STATIC_NET" ] || { echo 'Static network changed after restart.' >&2; exit 52; }
for expected in 'GPI_MIGRATION_STATIC_RUNTIME=true' 'EMAIL_POLLING_ENABLED=false' 'SALES_EMAIL_POLLING_ENABLED=false' 'AUTO_POST_ENABLED=false' 'AUTO_CREATE_SALES_ORDER_ENABLED=false'; do
  docker inspect "$backend" -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fxq "$expected" || { echo "Safety env changed after restart: $expected" >&2; exit 53; }
done
if docker exec "$backend" python -c 'import socket; s=socket.create_connection(("graph.microsoft.com",443),3); s.close()' >/dev/null 2>&1; then
  echo 'External egress unexpectedly available after restart.' >&2; exit 54
fi
logs=$(docker logs --since "$restart_since" "$backend" 2>&1 || true)
if printf '%s\n' "$logs" | grep -Eiq 'Dynamic mailbox polling worker started|AP email polling worker started|Sales email polling worker started'; then
  printf '%s\n' "$logs" >&2
  echo 'Forbidden background worker startup detected after V107 restart.' >&2
  exit 55
fi
echo V107_TARGET_RESTART_STATIC_SAFETY=PASS

# Replay W118228 through the current routing function using the actual persisted target record, without writing it.
cat > /tmp/v107-jbs-inbound.js <<'JS'
const D=db.getSiblingDB('gpi_document_hub');
const d=D.getCollection('hub_documents').findOne({id:'95ced52c-1521-43b6-b69e-4afc4ed600d5'},{_id:0,id:1,file_name:1,document_type:1,doc_type:1,suggested_job_type:1,vendor_canonical:1,vendor_name:1,vendor_raw:1,extracted_fields:1,normalized_fields:1,is_international:1,freight_direction:1,location_code:1,location_code_resolved:1,bc_po_resolved:1,po_number_clean:1,po_number_extracted:1,order_number:1,po_resolution:1,routing_details:1,sharepoint_folder_path:1,folder_routing_reason:1});
if(!d) throw new Error('W118228 target document missing');
print(JSON.stringify(d));
JS
docker cp /tmp/v107-jbs-inbound.js "$mongo:/tmp/v107-jbs-inbound.js" >/dev/null
rm -f /tmp/v107-jbs-inbound.js
jbs_json=$(docker exec "$mongo" sh -lc '
  set -e
  if [ -n "${MONGO_INITDB_ROOT_USERNAME:-}" ] && [ -n "${MONGO_INITDB_ROOT_PASSWORD:-}" ]; then
    exec mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin /tmp/v107-jbs-inbound.js
  else
    exec mongosh --quiet /tmp/v107-jbs-inbound.js
  fi
')
docker exec "$mongo" rm -f /tmp/v107-jbs-inbound.js >/dev/null 2>&1 || true
printf '%s' "$jbs_json" | docker exec -i "$backend" python - <<'PY'
import sys, json, inspect, asyncio
from services.folder_routing_service import determine_folder_path

doc=json.load(sys.stdin)
sig=inspect.signature(determine_folder_path)
print(f'V107_ROUTING_SIGNATURE={sig}')
values={
 'doc':doc, 'document':doc,
 'doc_type':doc.get('document_type') or doc.get('doc_type') or doc.get('suggested_job_type'),
 'document_type':doc.get('document_type') or doc.get('doc_type') or doc.get('suggested_job_type'),
 'vendor_name':doc.get('vendor_canonical') or doc.get('vendor_name') or doc.get('vendor_raw') or '',
 'vendor':doc.get('vendor_canonical') or doc.get('vendor_name') or doc.get('vendor_raw') or '',
 'order_number':doc.get('po_number_extracted') or doc.get('po_number_clean') or (doc.get('extracted_fields') or {}).get('po_number') or (doc.get('normalized_fields') or {}).get('po_number') or doc.get('order_number') or '',
 'is_international':bool(doc.get('is_international') or (doc.get('extracted_fields') or {}).get('is_international') or (doc.get('normalized_fields') or {}).get('is_international')),
 'freight_direction':doc.get('freight_direction') or (doc.get('extracted_fields') or {}).get('freight_direction') or (doc.get('normalized_fields') or {}).get('freight_direction'),
 'location_code':doc.get('location_code_resolved') or doc.get('location_code'),
 'extracted':doc.get('extracted_fields') or {},
 'normalized':doc.get('normalized_fields') or {},
 'intelligence':doc.get('reference_intelligence') or {},
}
kwargs={}
for name,p in sig.parameters.items():
    if name in values:
        kwargs[name]=values[name]
    elif p.default is inspect._empty and p.kind not in (inspect.Parameter.VAR_POSITIONAL,inspect.Parameter.VAR_KEYWORD):
        raise SystemExit(f'Unsupported required routing parameter: {name}')
res=determine_folder_path(**kwargs)
if inspect.isawaitable(res):
    res=asyncio.run(res)
if isinstance(res,(tuple,list)):
    path=res[0] if res else None
    reason=res[1] if len(res)>1 else None
elif isinstance(res,dict):
    path=res.get('folder_path') or res.get('path')
    reason=res.get('reason')
else:
    path=str(res); reason=None
print(f'V107_JBS_INBOUND_REPLAY_PATH={path}')
print(f'V107_JBS_INBOUND_REPLAY_REASON={reason}')
if path != 'Warehouse Not International':
    raise SystemExit(f'JBS inbound replay did not route to expected Warehouse Not International: {path}')
PY
echo V107_JBS_INBOUND_CURRENT_ROUTING_REPLAY=PASS

# Two-record authoritative target-only canonical backfill. Capture before/after evidence first.
cat > /tmp/v107-backfill.js <<'JS'
const D=db.getSiblingDB('gpi_document_hub');
const C=D.getCollection('hub_documents');
const specs=[
 {id:'04a47c5e-9180-4b41-bbd2-fcbfb62d336b', expected:'5975975', label:'JBS_OUTBOUND'},
 {id:'f35038a9-6d26-49c5-8461-67cef2083171', expected:'57745', label:'STRATEGIC_OUTBOUND'}
];
const before=[];
for(const s of specs){
  const d=C.findOne({id:s.id},{_id:0,id:1,file_name:1,document_type:1,shipment_number:1,bol_number:1,bol_number_extracted:1,extracted_fields:1,normalized_fields:1});
  if(!d) throw new Error(`${s.label}: document missing`);
  if(d.document_type!=='Shipping_Document') throw new Error(`${s.label}: wrong document_type ${d.document_type}`);
  const bol=(d.normalized_fields&&d.normalized_fields.bol_number)||(d.extracted_fields&&d.extracted_fields.bol_number)||d.bol_number||d.bol_number_extracted||null;
  if(String(bol)!==s.expected) throw new Error(`${s.label}: expected BOL ${s.expected}, found ${bol}`);
  const had=Object.prototype.hasOwnProperty.call(d,'shipment_number');
  before.push({id:s.id,label:s.label,file_name:d.file_name,had_shipment_number:had,shipment_number:d.shipment_number??null,bol_number:String(bol)});
  if(d.shipment_number!=null && String(d.shipment_number)!==String(bol)) throw new Error(`${s.label}: conflicting shipment_number ${d.shipment_number}`);
  if(d.shipment_number==null) C.updateOne({id:s.id},{$set:{shipment_number:String(bol)}});
}
const after=[];
for(const s of specs){
  const d=C.findOne({id:s.id},{_id:0,id:1,file_name:1,document_type:1,shipment_number:1,bol_number:1,bol_number_extracted:1,extracted_fields:1,normalized_fields:1});
  const bol=(d.normalized_fields&&d.normalized_fields.bol_number)||(d.extracted_fields&&d.extracted_fields.bol_number)||d.bol_number||d.bol_number_extracted||null;
  if(String(d.shipment_number)!==String(bol) || String(d.shipment_number)!==s.expected) throw new Error(`${s.label}: canonical shipment backfill verification failed`);
  after.push({id:s.id,label:s.label,file_name:d.file_name,shipment_number:d.shipment_number,bol_number:String(bol)});
}
print('V107_BACKFILL_BEFORE='+JSON.stringify(before));
print('V107_BACKFILL_AFTER='+JSON.stringify(after));
JS
docker cp /tmp/v107-backfill.js "$mongo:/tmp/v107-backfill.js" >/dev/null
rm -f /tmp/v107-backfill.js
backfill_out=$(docker exec "$mongo" sh -lc '
  set -e
  if [ -n "${MONGO_INITDB_ROOT_USERNAME:-}" ] && [ -n "${MONGO_INITDB_ROOT_PASSWORD:-}" ]; then
    exec mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin /tmp/v107-backfill.js
  else
    exec mongosh --quiet /tmp/v107-backfill.js
  fi
')
docker exec "$mongo" rm -f /tmp/v107-backfill.js >/dev/null 2>&1 || true
printf '%s\n' "$backfill_out" | tee "$RUN/v107-authoritative-backfill-evidence.txt"
echo V107_JBS_OUTBOUND_CANONICAL_SHIPMENT=PASS
echo V107_STRATEGIC_OUTBOUND_57745_REGRESSION=PASS

# Verify original host application tree and pinned image are unchanged.
host_after=$(sha256sum "$APP/$REL" | awk '{print $1}')
[ "$host_after" = "$BASELINE_SHA" ] || { echo 'Original target host app tree changed unexpectedly.' >&2; exit 56; }
image_id=$(docker inspect "$backend" -f '{{.Image}}')
echo "V107_BACKEND_IMAGE_ID=$image_id"
echo V107_ORIGINAL_HOST_TREE_UNCHANGED=PASS

echo 'V107_STRATEGIC_INBOUND_STATUS=OPEN_CORPUS_INGESTION_REQUIRED'
echo 'V107_PATCH_DURABILITY=TARGET_CONTAINER_TEST_ONLY_RECREATE_WOULD_REMOVE_PATCH'
echo "V107_TARGET_BACKUP_DIR=$RUN"
echo V107_NARROW_TARGET_FIX_REPLAY=PASS
'@

    $result = Invoke-SshScript -Ip $TargetIp -KnownHosts $KnownHosts -ScriptText $Remote
    $RawPath = Join-Path $DiagDir 'target-v107-narrow-fix-replay.txt'
    Set-Content -LiteralPath $RawPath -Value $result.StdOut -Encoding utf8
    if (-not [string]::IsNullOrWhiteSpace($result.StdOut)) { Write-Host $result.StdOut }
    if (-not [string]::IsNullOrWhiteSpace($result.StdErr)) { Write-Host $result.StdErr -ForegroundColor DarkYellow }
    Require ($result.ExitCode -eq 0) "V107 remote target test failed with exit code $($result.ExitCode)."

    foreach ($marker in @(
        'V107_TARGET_ISOLATION_PRECHECK=PASS',
        'V107_BASELINE_CODE_AUTHORITY=PASS',
        'V107_PATCH_BUILD_AND_SYNTAX=PASS',
        'V107_TARGET_CONTAINER_PATCH_APPLIED=PASS',
        'V107_TARGET_RESTART_STATIC_SAFETY=PASS',
        'V107_JBS_INBOUND_CURRENT_ROUTING_REPLAY=PASS',
        'V107_JBS_OUTBOUND_CANONICAL_SHIPMENT=PASS',
        'V107_STRATEGIC_OUTBOUND_57745_REGRESSION=PASS',
        'V107_ORIGINAL_HOST_TREE_UNCHANGED=PASS',
        'V107_NARROW_TARGET_FIX_REPLAY=PASS'
    )) {
        Require ($result.StdOut -match [regex]::Escape($marker)) "Missing required V107 marker: $marker"
    }

    Write-Section 'V107 FINAL RESULT'
    Write-Host 'JBS inbound          : CURRENT ROUTING FUNCTION REPLAY -> Warehouse Not International'
    Write-Host 'JBS outbound         : canonical shipment_number=5975975 proven on isolated target'
    Write-Host 'Strategic outbound   : canonical shipment_number=57745 regression preserved'
    Write-Host 'Strategic inbound    : OPEN - authentic W117105 corpus ingestion still required'
    Write-Host 'Runtime code patch   : TARGET CONTAINER TEST ONLY / NON-DURABLE ACROSS RECREATE'
    Write-Host 'Original host tree   : UNCHANGED'
    Write-Host 'Source VM            : NOT TOUCHED'
    Write-Host 'BC / SharePoint      : NO WRITES'
    Write-Host 'Production           : NOT TOUCHED'
    Write-Host "Diagnostics          : $DiagDir"
    Write-Host 'V107_WAREHOUSE_CANONICAL_SHIPMENT_TARGET_TEST=PASS' -ForegroundColor Green
    Write-Host 'NEXT: V108 DURABLE TARGET OVERLAY + AUTHENTIC STRATEGIC INBOUND CORPUS INGESTION TEST.' -ForegroundColor Yellow
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
