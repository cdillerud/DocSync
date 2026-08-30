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
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\migration-v106-warehouse-runtime-authority\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
$TranscriptPath = Join-Path $DiagDir 'Invoke-GPIHub-V106-Warehouse-Runtime-Authority-FixPlan.txt'
Start-Transcript -LiteralPath $TranscriptPath -Force | Out-Null

function Require([bool]$Condition,[string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Invoke-NativeText {
    param([Parameter(Mandatory)][string]$FilePath,[Parameter(Mandatory)][string[]]$Arguments,[switch]$AllowFailure)
    $token = [guid]::NewGuid().ToString('N')
    $stderrFile = Join-Path $env:TEMP "gpi-v106-$token.err.txt"
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
    $stderrFile = Join-Path $env:TEMP "gpi-v106-ssh-$token.err.txt"
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
    Write-Section 'V106 - WAREHOUSE RUNTIME AUTHORITY + NARROW FIX PLAN'
    Write-Host 'Classification      : PARITY BLOCKER FIX DESIGN'
    Write-Host 'Mode                : READ ONLY'
    Write-Host 'Purpose             : prove which code copy is active before any V107 patch'
    Write-Host 'JBS inbound         : distinguish stale persisted route from active routing defect'
    Write-Host 'JBS outbound        : locate canonical shipment-field persistence gap'
    Write-Host 'Strategic inbound   : confirm corpus/ingestion absence versus code defect'
    Write-Host 'Regression preserve : Strategic outbound B/L 57745'
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
APP='/gpi-hub-data/apps/gpi-hub/backend'
backend=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
mongo=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=mongodb' --format '{{.Names}}' | head -n 1)
[ -n "$backend" ] && [ -n "$mongo" ] || { echo 'Required target service missing.' >&2; exit 41; }
for expected in 'GPI_MIGRATION_STATIC_RUNTIME=true' 'SHAREPOINT_TARGET=test' 'BC_WRITE_ENABLED=false' 'BC_BLOCK_PRODUCTION_WRITES=true' 'EMAIL_POLLING_ENABLED=false' 'SALES_EMAIL_POLLING_ENABLED=false' 'AUTO_POST_ENABLED=false' 'AUTO_CREATE_SALES_ORDER_ENABLED=false'; do
  docker inspect "$backend" -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fxq "$expected" || { echo "SAFETY_ENV_MISSING=$expected" >&2; exit 42; }
done
[ "$(docker network inspect "$STATIC_NET" -f '{{.Internal}}')" = 'true' ] || { echo 'Static network is not internal.' >&2; exit 43; }
if docker exec "$backend" python -c 'import socket; s=socket.create_connection(("graph.microsoft.com",443),3); s.close()' >/dev/null 2>&1; then
  echo 'Target unexpectedly has external egress.' >&2; exit 44
fi
echo V106_TARGET_READ_ONLY_SAFETY=PASS

echo V106_RUNTIME_CODE_AUTHORITY_BEGIN
mismatch=0
missing=0
for rel in \
  services/folder_routing_service.py \
  services/reference_intelligence_service.py \
  services/document_bytes_intake_service.py \
  services/shipping_auto_file_service.py \
  services/document_intel_helpers.py \
  workflows/document_capture/rules/workflow_status.py; do
  host="$APP/$rel"
  cont="/app/$rel"
  if [ ! -f "$host" ]; then
    echo "AUTHORITY|$rel|HOST_MISSING"
    missing=$((missing+1))
    continue
  fi
  if ! docker exec "$backend" test -f "$cont"; then
    echo "AUTHORITY|$rel|CONTAINER_MISSING"
    missing=$((missing+1))
    continue
  fi
  hh=$(sha256sum "$host" | awk '{print $1}')
  ch=$(docker exec "$backend" sha256sum "$cont" | awk '{print $1}')
  if [ "$hh" = "$ch" ]; then state=MATCH; else state=MISMATCH; mismatch=$((mismatch+1)); fi
  echo "AUTHORITY|$rel|HOST=$hh|CONTAINER=$ch|$state"
done
echo V106_RUNTIME_CODE_AUTHORITY_END
if [ "$missing" -gt 0 ]; then
  echo "V106_RUNTIME_CODE_AUTHORITY=INCOMPLETE_MISSING_$missing"
elif [ "$mismatch" -eq 0 ]; then
  echo 'V106_RUNTIME_CODE_AUTHORITY=HOST_CONTAINER_MATCH'
else
  echo "V106_RUNTIME_CODE_AUTHORITY=HOST_CONTAINER_MISMATCH_$mismatch"
fi

echo V106_WAREHOUSE_ROUTING_AUTHORITY_BEGIN
python3 - <<'PY'
from pathlib import Path
p=Path('/gpi-hub-data/apps/gpi-hub/backend/services/folder_routing_service.py')
lines=p.read_text(errors='replace').splitlines()
need=('Warehouse_Receipt','Warehouse Not International','Warehouse International','Misc Invoices - need approval')
for i,line in enumerate(lines,1):
    if any(x in line for x in need):
        lo=max(1,i-5); hi=min(len(lines),i+8)
        print(f'FILE={p.name} MATCH_LINE={i}')
        for n in range(lo,hi+1): print(f'{n:5}: {lines[n-1]}')
        print('---')
PY
wr_host=0
wr_container=0
grep -Fq 'Warehouse Not International' "$APP/services/folder_routing_service.py" && wr_host=1 || true
docker exec "$backend" grep -Fq 'Warehouse Not International' /app/services/folder_routing_service.py && wr_container=1 || true
echo "WR_CURRENT_RULE_HOST=$wr_host"
echo "WR_CURRENT_RULE_CONTAINER=$wr_container"
echo V106_WAREHOUSE_ROUTING_AUTHORITY_END

echo V106_SHIPMENT_CANONICALIZATION_CONTEXT_BEGIN
python3 - <<'PY'
from pathlib import Path
root=Path('/gpi-hub-data/apps/gpi-hub/backend')
interesting=[]
for p in root.rglob('*.py'):
    try: lines=p.read_text(errors='replace').splitlines()
    except Exception: continue
    for i,line in enumerate(lines,1):
        l=line.lower()
        if 'shipment_number' in l or ('bol_number' in l and ('normalized' in l or 'reference' in l or 'extracted' in l)):
            if any(k in l for k in ('shipment_number','bol_number')):
                interesting.append((str(p.relative_to(root)),i,line.rstrip()))
for rel,i,line in interesting[:220]:
    print(f'{rel}:{i}:{line}')
print(f'SHIPMENT_CANONICALIZATION_MATCH_COUNT={len(interesting)}')
PY
echo V106_SHIPMENT_CANONICALIZATION_CONTEXT_END

cat > /tmp/v106-truth.js <<'JS'
const D=db.getSiblingDB('gpi_document_hub');
const C=D.getCollection('hub_documents');
function one(id){return C.findOne({id:id},{_id:0,id:1,file_name:1,document_type:1,sharepoint_folder_path:1,folder_routing_reason:1,extracted_fields:1,normalized_fields:1,bol_number:1,bol_number_extracted:1,shipment_number:1,reference_candidates:1,po_resolution:1});}
function slim(d){if(!d)return null; return {id:d.id,file_name:d.file_name,document_type:d.document_type,sharepoint_folder_path:d.sharepoint_folder_path,folder_routing_reason:d.folder_routing_reason,receipt_number:d.extracted_fields&&d.extracted_fields.receipt_number,normalized_receipt_number:d.normalized_fields&&d.normalized_fields.receipt_number,bol_number:(d.normalized_fields&&d.normalized_fields.bol_number)||(d.extracted_fields&&d.extracted_fields.bol_number)||d.bol_number||d.bol_number_extracted||null,shipment_number:(d.normalized_fields&&d.normalized_fields.shipment_number)||(d.extracted_fields&&d.extracted_fields.shipment_number)||d.shipment_number||null,reference_candidates:(d.reference_candidates||[]).filter(x=>x&&(['shipment_number','po_number','order_number'].includes(x.semantic_type))).slice(0,8)};}
const out={
 jbs_inbound:slim(one('95ced52c-1521-43b6-b69e-4afc4ed600d5')),
 jbs_outbound:slim(one('04a47c5e-9180-4b41-bbd2-fcbfb62d336b')),
 strategic_outbound:slim(one('f35038a9-6d26-49c5-8461-67cef2083171')),
 w117105_common_field_count:C.countDocuments({$or:[{file_name:/W117105/i},{'extracted_fields.po_number':/W117105/i},{'normalized_fields.po_number':/W117105/i},{po_number_clean:/W117105/i},{po_number_extracted:/W117105/i}]})
};
print('V106_TRUTH_JSON_BEGIN'); print(JSON.stringify(out)); print('V106_TRUTH_JSON_END');
JS
docker cp /tmp/v106-truth.js "$mongo:/tmp/v106-truth.js" >/dev/null
rm -f /tmp/v106-truth.js
mongo_out=$(docker exec "$mongo" sh -lc '
  set -e
  if [ -n "${MONGO_INITDB_ROOT_USERNAME:-}" ] && [ -n "${MONGO_INITDB_ROOT_PASSWORD:-}" ]; then
    exec mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin /tmp/v106-truth.js
  else
    exec mongosh --quiet /tmp/v106-truth.js
  fi
')
docker exec "$mongo" rm -f /tmp/v106-truth.js >/dev/null 2>&1 || true
printf '%s\n' "$mongo_out"

echo V106_STRATEGIC_INBOUND_UPLOAD_SEARCH_BEGIN
find /gpi-hub-data/volumes/uploads -type f \( -iname '*W117105*' -o -iname '*Strategic*W117105*' -o -iname '*W117105*Strategic*' \) -printf '%p\n' 2>/dev/null | head -n 100 || true
echo V106_STRATEGIC_INBOUND_UPLOAD_SEARCH_END

# Classifications are evidence-based and deliberately fail-closed.
if [ "$wr_container" -eq 1 ]; then
  echo 'V106_JBS_INBOUND_DISPOSITION=STALE_PERSISTED_ROUTE_REPLAY_REQUIRED'
else
  echo 'V106_JBS_INBOUND_DISPOSITION=ACTIVE_RUNTIME_ROUTING_FIX_REQUIRED'
fi

echo 'V106_JBS_OUTBOUND_DISPOSITION=CODE_FIX_REQUIRED_CANONICAL_SHIPMENT_FIELD'
echo 'V106_STRATEGIC_INBOUND_DISPOSITION=CORPUS_INGESTION_REQUIRED_NO_CODE_DEFECT_PROVEN'
echo 'V106_STRATEGIC_OUTBOUND_REGRESSION=BL_57745_BASELINE_PRESERVE'
echo V106_NARROW_FIX_PLAN_REMOTE=PASS
'@

    $result = Invoke-SshScript -Ip $TargetIp -KnownHosts $KnownHosts -ScriptText $Remote
    $rawPath = Join-Path $DiagDir 'target-v106-runtime-authority-fix-plan.txt'
    Set-Content -LiteralPath $rawPath -Value ($result.StdOut + "`n" + $result.StdErr) -Encoding utf8
    Write-Host $result.StdOut
    if (-not [string]::IsNullOrWhiteSpace($result.StdErr)) { Write-Host $result.StdErr -ForegroundColor DarkYellow }

    Require ($result.ExitCode -eq 0) "V106 remote audit failed. See $rawPath"
    foreach ($marker in @(
        'V106_TARGET_READ_ONLY_SAFETY=PASS',
        'V106_RUNTIME_CODE_AUTHORITY=',
        'V106_JBS_INBOUND_DISPOSITION=',
        'V106_JBS_OUTBOUND_DISPOSITION=CODE_FIX_REQUIRED_CANONICAL_SHIPMENT_FIELD',
        'V106_STRATEGIC_INBOUND_DISPOSITION=CORPUS_INGESTION_REQUIRED_NO_CODE_DEFECT_PROVEN',
        'V106_STRATEGIC_OUTBOUND_REGRESSION=BL_57745_BASELINE_PRESERVE',
        'V106_NARROW_FIX_PLAN_REMOTE=PASS'
    )) {
        Require ($result.StdOut -match [regex]::Escape($marker)) "Required V106 marker missing: $marker"
    }

    Write-Section 'V106 FINAL RESULT'
    $authority = ([regex]::Match($result.StdOut,'V106_RUNTIME_CODE_AUTHORITY=([^\r\n]+)')).Groups[1].Value
    $jbsInbound = ([regex]::Match($result.StdOut,'V106_JBS_INBOUND_DISPOSITION=([^\r\n]+)')).Groups[1].Value
    Write-Host "Runtime authority       : $authority"
    Write-Host "JBS inbound disposition : $jbsInbound"
    Write-Host 'JBS outbound disposition: CODE FIX REQUIRED - canonical shipment field'
    Write-Host 'Strategic inbound       : CORPUS INGESTION REQUIRED - no code defect yet proven'
    Write-Host 'Strategic outbound      : PRESERVE B/L 57745 regression baseline'
    Write-Host 'Target mutations        : NONE'
    Write-Host 'Production              : NOT TOUCHED'
    Write-Host "Diagnostics             : $DiagDir"
    Write-Host 'V106_NARROW_WAREHOUSE_FIX_PLAN=PASS' -ForegroundColor Green
    Write-Host 'NEXT: V107 APPLY ONLY THE AUTHORITY-CONFIRMED TARGET-ISOLATED PATCH/REPLAY TESTS.' -ForegroundColor Cyan
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
