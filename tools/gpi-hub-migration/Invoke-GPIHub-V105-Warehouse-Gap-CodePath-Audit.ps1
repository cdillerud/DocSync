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
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\migration-v105-warehouse-codepath-audit\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
$TranscriptPath = Join-Path $DiagDir 'Invoke-GPIHub-V105-Warehouse-Gap-CodePath-Audit.txt'
Start-Transcript -LiteralPath $TranscriptPath -Force | Out-Null

function Require([bool]$Condition,[string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Invoke-NativeText {
    param([Parameter(Mandatory)][string]$FilePath,[Parameter(Mandatory)][string[]]$Arguments,[switch]$AllowFailure)
    $token = [guid]::NewGuid().ToString('N')
    $stderrFile = Join-Path $env:TEMP "gpi-v105-$token.err.txt"
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
    $stderrFile = Join-Path $env:TEMP "gpi-v105-ssh-$token.err.txt"
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
    Write-Section 'V105 - TARGETED WAREHOUSE GAP CODE-PATH AUDIT'
    Write-Host 'Classification      : PARITY BLOCKER FIX DESIGN'
    Write-Host 'Mode                : READ ONLY'
    Write-Host 'Defect 1            : JBS inbound R-number extracted but routed to Misc Invoices'
    Write-Host 'Defect 2            : JBS outbound BOL/shipment reference not normalized to explicit shipment field'
    Write-Host 'Defect 3            : authentic Strategic inbound W117105 packet absent from restored Hub'
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
APP='/gpi-hub-data/apps/gpi-hub'
BACKEND="$APP/backend"
UPLOADS='/gpi-hub-data/volumes/uploads'
backend=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
mongo=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=mongodb' --format '{{.Names}}' | head -n 1)
[ -n "$backend" ] && [ -n "$mongo" ] || { echo 'Required target service missing.' >&2; exit 51; }
for expected in 'GPI_MIGRATION_STATIC_RUNTIME=true' 'SHAREPOINT_TARGET=test' 'BC_WRITE_ENABLED=false' 'BC_BLOCK_PRODUCTION_WRITES=true' 'EMAIL_POLLING_ENABLED=false' 'SALES_EMAIL_POLLING_ENABLED=false' 'AUTO_POST_ENABLED=false' 'AUTO_CREATE_SALES_ORDER_ENABLED=false'; do
  docker inspect "$backend" -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fxq "$expected" || { echo "SAFETY_ENV_MISSING=$expected" >&2; exit 52; }
done
[ "$(docker network inspect "$STATIC_NET" -f '{{.Internal}}')" = 'true' ] || { echo 'Static network is not internal.' >&2; exit 53; }
if docker exec "$backend" python -c 'import socket; s=socket.create_connection(("graph.microsoft.com",443),3); s.close()' >/dev/null 2>&1; then
  echo 'Target unexpectedly has external egress.' >&2; exit 54
fi
echo V105_TARGET_READ_ONLY_SAFETY=PASS

printf '\nV105_RUNTIME_SOURCE_HASHES_BEGIN\n'
for f in \
  "$BACKEND/services/folder_routing_service.py" \
  "$BACKEND/services/reference_intelligence_service.py" \
  "$BACKEND/services/po_resolution_service.py" \
  "$BACKEND/services/auto_clear_service.py" \
  "$BACKEND/server.py"; do
  if [ -f "$f" ]; then sha256sum "$f"; else echo "MISSING=$f"; fi
done
echo V105_RUNTIME_SOURCE_HASHES_END
echo V105_RUNTIME_SOURCE_HASHES=PASS

printf '\nV105_ROUTING_CODE_CONTEXT_BEGIN\n'
python3 - "$BACKEND" <<'PY'
import os, re, sys
root=sys.argv[1]
patterns=[
 ('MISC_REASON', re.compile(r'Miscellaneous document needing approval|Misc Invoices - need approval',re.I)),
 ('WAREHOUSE_TYPE', re.compile(r'Warehouse_Receipt|WAREHOUSE_RECEIPT',re.I)),
 ('ROUTING', re.compile(r'folder_routing_reason|sharepoint_folder_path|folder_routing_details|route.*warehouse|warehouse.*route',re.I)),
]
seen=set()
for base,dirs,files in os.walk(root):
    dirs[:] = [d for d in dirs if d not in {'__pycache__','.venv','venv','node_modules'}]
    for fn in files:
        if not fn.endswith('.py'): continue
        p=os.path.join(base,fn)
        try: lines=open(p,encoding='utf-8',errors='replace').read().splitlines()
        except Exception: continue
        for i,line in enumerate(lines):
            tags=[tag for tag,rx in patterns if rx.search(line)]
            if not tags: continue
            key=(p,max(0,i-5),min(len(lines),i+7))
            if key in seen: continue
            seen.add(key)
            print(f'FILE={os.path.relpath(p,root)} LINE={i+1} TAGS={",".join(tags)}')
            for j in range(key[1],key[2]): print(f'{j+1:5}: {lines[j]}')
            print('---')
            if len(seen)>=80: raise SystemExit
PY
echo V105_ROUTING_CODE_CONTEXT_END
echo V105_ROUTING_CODE_CONTEXT=PASS

printf '\nV105_REFERENCE_NORMALIZATION_CODE_CONTEXT_BEGIN\n'
python3 - "$BACKEND" <<'PY'
import os,re,sys
root=sys.argv[1]
patterns=[
 ('SHIPMENT',re.compile(r'shipment_number|shipment_no|semantic_type.{0,40}shipment',re.I)),
 ('BOL',re.compile(r'bol_number|bill.?of.?lading',re.I)),
 ('CANONICAL',re.compile(r'normalized_fields|canonical_fields|reference_candidates',re.I)),
]
seen=set()
for base,dirs,files in os.walk(root):
    dirs[:] = [d for d in dirs if d not in {'__pycache__','.venv','venv','node_modules'}]
    for fn in files:
        if not fn.endswith('.py'): continue
        p=os.path.join(base,fn)
        try: lines=open(p,encoding='utf-8',errors='replace').read().splitlines()
        except Exception: continue
        for i,line in enumerate(lines):
            tags=[tag for tag,rx in patterns if rx.search(line)]
            if not tags or ('SHIPMENT' not in tags and 'BOL' not in tags): continue
            key=(p,max(0,i-6),min(len(lines),i+8))
            if key in seen: continue
            seen.add(key)
            print(f'FILE={os.path.relpath(p,root)} LINE={i+1} TAGS={",".join(tags)}')
            for j in range(key[1],key[2]): print(f'{j+1:5}: {lines[j]}')
            print('---')
            if len(seen)>=100: raise SystemExit
PY
echo V105_REFERENCE_NORMALIZATION_CODE_CONTEXT_END
echo V105_REFERENCE_NORMALIZATION_CODE_CONTEXT=PASS

printf '\nV105_STRATEGIC_INBOUND_UPLOAD_EVIDENCE_BEGIN\n'
find "$UPLOADS" -type f \( -iname '*W117105*' -o -iname '*Strategic*' \) -printf '%P\n' 2>/dev/null | head -n 250 || true
echo V105_STRATEGIC_INBOUND_UPLOAD_EVIDENCE_END

cat > /tmp/v105-w117105-audit.js <<'JS'
const D=db.getSiblingDB('gpi_document_hub');
const names=D.getCollectionNames().sort();
const fields=['id','document_id','filename','file_name','original_filename','original_file_name','source_filename','subject','po_number','po_number_raw','po_number_clean','extracted_fields.po_number','normalized_fields.po_number','validation_results.normalized_fields.po_number','folder_routing_details.order_number','routing_details.order_number'];
print('V105_W117105_COLLECTION_AUDIT_BEGIN');
for (const name of names) {
  const C=D.getCollection(name);
  let hit=null;
  try {
    const ors=fields.map(f=>({[f]:{$regex:'W117105',$options:'i'}}));
    hit=C.findOne({$or:ors});
  } catch(e) {}
  if (hit) {
    const out={collection:name,id:String(hit.id||hit.document_id||hit._id||''),filename:hit.filename||hit.file_name||hit.original_filename||hit.original_file_name||hit.source_filename||'',subject:hit.subject||'',po_number:hit.po_number||hit.po_number_raw||hit.po_number_clean||((hit.extracted_fields||{}).po_number)||((hit.normalized_fields||{}).po_number)||''};
    print(JSON.stringify(out));
  }
}
print('V105_W117105_COLLECTION_AUDIT_END');
JS
docker cp /tmp/v105-w117105-audit.js "$mongo:/tmp/v105-w117105-audit.js" >/dev/null
rm -f /tmp/v105-w117105-audit.js
if docker exec "$mongo" sh -lc '
  set -e
  if [ -n "${MONGO_INITDB_ROOT_USERNAME:-}" ] && [ -n "${MONGO_INITDB_ROOT_PASSWORD:-}" ]; then
    exec mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin /tmp/v105-w117105-audit.js
  else
    exec mongosh --quiet /tmp/v105-w117105-audit.js
  fi
'; then :; else echo 'W117105_COLLECTION_AUDIT_FAILED' >&2; exit 55; fi
docker exec "$mongo" rm -f /tmp/v105-w117105-audit.js >/dev/null 2>&1 || true
echo V105_STRATEGIC_INBOUND_REPRESENTATION_AUDIT=PASS

echo V105_CODE_PATH_AUDIT_REMOTE=PASS
'@

    $result = Invoke-SshScript -Ip $TargetIp -KnownHosts $KnownHosts -ScriptText $Remote
    $rawPath = Join-Path $DiagDir 'target-v105-warehouse-codepath-audit.txt'
    Set-Content -LiteralPath $rawPath -Value ($result.StdOut + "`n" + $result.StdErr) -Encoding utf8
    Write-Host $result.StdOut
    if (-not [string]::IsNullOrWhiteSpace($result.StdErr)) { Write-Host $result.StdErr -ForegroundColor DarkYellow }

    Require ($result.ExitCode -eq 0) "V105 remote audit failed. See $rawPath"
    foreach ($marker in @(
        'V105_TARGET_READ_ONLY_SAFETY=PASS',
        'V105_RUNTIME_SOURCE_HASHES=PASS',
        'V105_ROUTING_CODE_CONTEXT=PASS',
        'V105_REFERENCE_NORMALIZATION_CODE_CONTEXT=PASS',
        'V105_STRATEGIC_INBOUND_REPRESENTATION_AUDIT=PASS',
        'V105_CODE_PATH_AUDIT_REMOTE=PASS'
    )) {
        Require ($result.StdOut -match [regex]::Escape($marker)) "V105 marker missing: $marker"
    }

    Write-Section 'V105 FINAL RESULT'
    Write-Host 'Runtime source           : AUDITED FROM EXACT MIGRATED TARGET TREE'
    Write-Host 'JBS inbound path         : CODE CONTEXT CAPTURED'
    Write-Host 'JBS outbound normalization: CODE CONTEXT CAPTURED'
    Write-Host 'Strategic inbound        : UPLOAD + MONGO REPRESENTATION EVIDENCE CAPTURED'
    Write-Host 'Strategic outbound       : 57745 REGRESSION CONSTRAINT PRESERVED'
    Write-Host 'Target mutations         : NONE'
    Write-Host 'Production               : NOT TOUCHED'
    Write-Host "Diagnostics              : $DiagDir"
    Write-Host 'V105_TARGETED_WAREHOUSE_CODE_PATH_AUDIT=PASS' -ForegroundColor Green
    Write-Host 'NEXT: V106 NARROW TARGET-ONLY FIX/TEST PLAN FROM V105 EVIDENCE.' -ForegroundColor Yellow
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
