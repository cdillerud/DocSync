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
$SourceIp = [string]$State.source.public_ip
$TargetIp = [string]$State.target.public_ip
$TargetApp = '/gpi-hub-data/apps/gpi-hub'
$ProjectName = 'gpi-hub-v100'
$BackendPort = 18005
$FrontendPort = 18080

$WarehouseDocId = '43e0e6a3-31c1-40fb-be29-958d19bd511b'
$ApDocId = 'ff80f4bd-acac-4037-9f91-a77459954e6d'

$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\migration-v101-target-parity\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
$TranscriptPath = Join-Path $DiagDir 'Invoke-GPIHub-V101-Target-Parity.txt'
Start-Transcript -LiteralPath $TranscriptPath -Force | Out-Null

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
    $stderrFile = Join-Path $env:TEMP "gpi-v101-$token.err.txt"
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
            throw "$FilePath failed ($($result.ExitCode)).`n$($result.StdOut)`n$($result.StdErr)"
        }
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
    param(
        [Parameter(Mandatory)][string]$Ip,
        [Parameter(Mandatory)][string]$KnownHosts,
        [Parameter(Mandatory)][string]$ScriptText
    )
    $token = [guid]::NewGuid().ToString('N')
    $stderrFile = Join-Path $env:TEMP "gpi-v101-ssh-$token.err.txt"
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

function Write-Section([string]$Title) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

try {
    Write-Section 'V101 TARGET PARITY PRESERVATION VALIDATION'
    Write-Host "Target VM          : $TargetIp"
    Write-Host "Source rollback    : $SourceIp"
    Write-Host 'Scope              : Warehouse + AP + duplicate/idempotency + safety'
    Write-Host 'BC writes          : NONE'
    Write-Host 'SharePoint writes  : NONE'
    Write-Host 'Traffic cutover    : NONE'
    Write-Host 'Production         : NOT TOUCHED'

    Require (Test-Path -LiteralPath $KeyPath -PathType Leaf) "SSH key missing: $KeyPath"
    $TargetKnownHosts = Get-KnownHostsForIp -Ip $TargetIp
    $SourceKnownHosts = Get-KnownHostsForIp -Ip $SourceIp

    Write-Section '1. TARGET RUNTIME / SAFETY PRECHECK'
    $TargetPrecheck = @'
set -euo pipefail
PROJECT='gpi-hub-v100'
BACKEND_PORT=18005
FRONTEND_PORT=18080

for svc in mongodb backend frontend; do
  cid=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter "label=com.docker.compose.service=$svc" --format '{{.ID}}' | head -n 1)
  [ -n "$cid" ] || { echo "MISSING_SERVICE=$svc" >&2; exit 31; }
  echo "SERVICE=$svc|$cid"
done

backend=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
for expected in 'SHAREPOINT_TARGET=test' 'BC_WRITE_ENABLED=false' 'BC_BLOCK_PRODUCTION_WRITES=true'; do
  docker inspect "$backend" -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fxq "$expected" || { echo "SAFETY_ENV_MISSING=$expected" >&2; exit 32; }
  echo "SAFETY_ENV=$expected"
done

code=$(curl -sS -o /tmp/v101-backend.out -w '%{http_code}' "http://127.0.0.1:$BACKEND_PORT/health" || true)
if [ "$code" -lt 200 ] 2>/dev/null || [ "$code" -ge 400 ] 2>/dev/null; then
  code=$(curl -sS -o /tmp/v101-backend.out -w '%{http_code}' "http://127.0.0.1:$BACKEND_PORT/" || true)
fi
[ "$code" -ge 200 ] 2>/dev/null && [ "$code" -lt 400 ] 2>/dev/null || { echo "BACKEND_HTTP=$code" >&2; exit 33; }
echo "BACKEND_HTTP=$code"

fcode=$(curl -sS -o /tmp/v101-frontend.out -w '%{http_code}' "http://127.0.0.1:$FRONTEND_PORT/" || true)
[ "$fcode" -ge 200 ] 2>/dev/null && [ "$fcode" -lt 400 ] 2>/dev/null || { echo "FRONTEND_HTTP=$fcode" >&2; exit 34; }
echo "FRONTEND_HTTP=$fcode"
echo V101_TARGET_SAFETY_PRECHECK=PASS
'@
    $pre = Invoke-SshScript -Ip $TargetIp -KnownHosts $TargetKnownHosts -ScriptText $TargetPrecheck
    Write-Host $pre.StdOut
    Require ($pre.ExitCode -eq 0) "Target safety precheck failed.`n$($pre.StdOut)`n$($pre.StdErr)"
    Require ($pre.StdOut -match 'V101_TARGET_SAFETY_PRECHECK=PASS') 'Target safety PASS marker missing.'

    Write-Section '2. AUTHORITATIVE PERSISTED DOCUMENT TRUTH'
    $TruthTemplate = @'
set -euo pipefail
PROJECT='gpi-hub-v100'
WAREHOUSE_ID='__WAREHOUSE_ID__'
AP_ID='__AP_ID__'

mongo=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=mongodb' --format '{{.Names}}' | head -n 1)
[ -n "$mongo" ] || { echo 'Mongo container missing' >&2; exit 41; }

read_doc() {
  local id="$1"
  docker exec -e QUERY_DOC_ID="$id" "$mongo" sh -lc '
    set -e
    js='"'"'const id=process.env.QUERY_DOC_ID; const d=db.getSiblingDB("gpi_document_hub").hub_documents.findOne({$or:[{id:id},{document_id:id},{_id:id}]}); if(!d){quit(44)}; print(EJSON.stringify(d));'"'"'
    if [ -n "${MONGO_INITDB_ROOT_USERNAME:-}" ] && [ -n "${MONGO_INITDB_ROOT_PASSWORD:-}" ]; then
      exec mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --eval "$js"
    else
      exec mongosh --quiet --eval "$js"
    fi
  '
}

warehouse=$(read_doc "$WAREHOUSE_ID")
ap=$(read_doc "$AP_ID")
printf '%s\n' "$warehouse" > /tmp/v101-warehouse.json
printf '%s\n' "$ap" > /tmp/v101-ap.json

python3 - <<'PY'
import json

def load(path):
    with open(path,encoding='utf-8') as f: return json.load(f)

def scalars(obj):
    vals=[]
    if isinstance(obj,dict):
        for k,v in obj.items():
            vals.append(str(k))
            vals.extend(scalars(v))
    elif isinstance(obj,list):
        for v in obj: vals.extend(scalars(v))
    elif obj is not None:
        vals.append(str(obj))
    return vals

def require(cond,msg):
    if not cond: raise SystemExit(msg)

w=load('/tmp/v101-warehouse.json')
a=load('/tmp/v101-ap.json')
wvals=set(scalars(w)); avals=set(scalars(a))

require('Warehouse_Receipt' in wvals,'warehouse document type not preserved')
require('W118093' in wvals,'warehouse PO W118093 not preserved')
require('purchase_receipt' in wvals,'warehouse BC entity purchase_receipt not preserved')
require('267206' in wvals,'warehouse BC receipt 267206 not preserved')
require('d6a893ff-9045-f111-a820-7ced8dd4cbd4' in wvals,'warehouse BC record id not preserved')
require('bc_api' in wvals,'warehouse live BC lookup-source evidence not preserved')
require('Temp Folder/Warehouse Not International' in wvals,'warehouse SharePoint path not preserved')
print('V101_W118093_PERSISTED_TRUTH=PASS')

require('AP_Invoice' in avals,'AP document type not preserved')
require('126157114-AR' in avals,'AP invoice number not preserved')
require('109032' in avals,'AP PO 109032 not preserved')
require(any(v in avals for v in ['Cargo Modules LLC','CARGOMO']),'AP vendor identity not preserved')
require('645479' in avals,'AP posted purchase invoice candidate 645479 not preserved')
require('5564df18-171f-f111-8340-7ced8d8956c8' in avals,'AP posted purchase invoice candidate id not preserved')
print('V101_AP_SCENARIO2_PERSISTED_TRUTH=PASS')
print('V101_AP_LIVE_SHAREPOINT_AUTHORITY=STILL_REQUIRES_PROOF')
PY

echo 'WAREHOUSE_JSON_BEGIN'
cat /tmp/v101-warehouse.json
echo 'WAREHOUSE_JSON_END'
echo 'AP_JSON_BEGIN'
cat /tmp/v101-ap.json
echo 'AP_JSON_END'
rm -f /tmp/v101-warehouse.json /tmp/v101-ap.json
echo V101_PERSISTED_TRUTH=PASS
'@
    $TruthScript = $TruthTemplate.Replace('__WAREHOUSE_ID__',$WarehouseDocId).Replace('__AP_ID__',$ApDocId)
    $truth = Invoke-SshScript -Ip $TargetIp -KnownHosts $TargetKnownHosts -ScriptText $TruthScript
    Set-Content -LiteralPath (Join-Path $DiagDir 'target-persisted-truth.txt') -Value ($truth.StdOut + "`n" + $truth.StdErr) -Encoding utf8
    # Avoid printing full document JSON to the console; only print PASS/status markers.
    (($truth.StdOut -split "`n") | Where-Object { $_ -match '^V101_' }) | ForEach-Object { Write-Host $_ }
    Require ($truth.ExitCode -eq 0) "Persisted truth validation failed. See $DiagDir\target-persisted-truth.txt"
    foreach ($marker in @('V101_W118093_PERSISTED_TRUTH=PASS','V101_AP_SCENARIO2_PERSISTED_TRUTH=PASS','V101_PERSISTED_TRUTH=PASS')) {
        Require ($truth.StdOut -match [regex]::Escape($marker)) "Required persisted-truth marker missing: $marker"
    }

    Write-Section '3. DUPLICATE / IDEMPOTENCY PROTECTIONS'
    $Dedupe = @'
set -euo pipefail
PROJECT='gpi-hub-v100'
APP='/gpi-hub-data/apps/gpi-hub'
mongo=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=mongodb' --format '{{.Names}}' | head -n 1)
[ -n "$mongo" ] || exit 51

# Find the validated mail-intake uniqueness index anywhere in the target DB without mutating anything.
docker exec "$mongo" sh -lc '
  set -e
  js='"'"'const D=db.getSiblingDB("gpi_document_hub"); let hits=[]; for(const n of D.getCollectionNames()){ try{ for(const i of D.getCollection(n).getIndexes()){ if(i.name==="uniq_msgid_hash") hits.push({collection:n,index:i}); }}catch(e){} } print(EJSON.stringify(hits));'"'"'
  if [ -n "${MONGO_INITDB_ROOT_USERNAME:-}" ] && [ -n "${MONGO_INITDB_ROOT_PASSWORD:-}" ]; then
    exec mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --eval "$js"
  else
    exec mongosh --quiet --eval "$js"
  fi
' > /tmp/v101-index.json

python3 - <<'PY'
import json
x=json.load(open('/tmp/v101-index.json'))
if not x: raise SystemExit('uniq_msgid_hash index missing')
if not any(bool(h.get('index',{}).get('unique')) for h in x): raise SystemExit('uniq_msgid_hash exists but is not unique')
print('V101_DUPLICATE_UNIQUE_INDEX=PASS')
PY

# Preserve the previously validated code branch semantics on the copied exact app tree.
grep -R -q --include='*.py' 'SkippedDuplicate' "$APP/backend" || { echo 'SkippedDuplicate branch marker missing' >&2; exit 52; }
grep -R -q --include='*.py' 'uniq_msgid_hash' "$APP/backend" || { echo 'uniq_msgid_hash source marker missing' >&2; exit 53; }
echo V101_DUPLICATE_BRANCH_SOURCE=PASS
rm -f /tmp/v101-index.json
echo V101_DUPLICATE_IDEMPOTENCY=PASS
'@
    $dedupe = Invoke-SshScript -Ip $TargetIp -KnownHosts $TargetKnownHosts -ScriptText $Dedupe
    Write-Host $dedupe.StdOut
    Require ($dedupe.ExitCode -eq 0) "Duplicate/idempotency validation failed.`n$($dedupe.StdOut)`n$($dedupe.StdErr)"
    Require ($dedupe.StdOut -match 'V101_DUPLICATE_IDEMPOTENCY=PASS') 'Duplicate/idempotency PASS marker missing.'

    Write-Section '4. FAIL-CLOSED / NEEDS REVIEW SOURCE PRESERVATION'
    $FailClosed = @'
set -euo pipefail
APP='/gpi-hub-data/apps/gpi-hub'
[ -d "$APP/backend" ]
# Read-only source preservation checks; V101 does not invoke a mutating reprocess endpoint.
grep -R -qi --include='*.py' 'needs_review' "$APP/backend" || { echo 'needs_review semantics missing from copied backend' >&2; exit 61; }
grep -R -qi --include='*.py' 'ambig' "$APP/backend/services/parity_engine" "$APP/backend/services" 2>/dev/null || { echo 'ambiguity semantics missing from copied backend' >&2; exit 62; }
echo V101_FAIL_CLOSED_SOURCE_PRESERVED=PASS
'@
    $fc = Invoke-SshScript -Ip $TargetIp -KnownHosts $TargetKnownHosts -ScriptText $FailClosed
    Write-Host $fc.StdOut
    Require ($fc.ExitCode -eq 0) "Fail-closed source preservation failed.`n$($fc.StdOut)`n$($fc.StdErr)"

    Write-Section '5. SOURCE ROLLBACK CHECKPOINT HEALTH'
    $SourceHealth = @'
set -euo pipefail
count=$(docker ps --filter 'label=com.docker.compose.project=gpi-hub' --format '{{.Names}}' | wc -l | xargs)
[ "$count" -ge 3 ] || { echo "SOURCE_RUNNING_COUNT=$count" >&2; exit 71; }
code=$(curl -sS -o /tmp/v101-source.out -w '%{http_code}' http://127.0.0.1:8005/health || true)
if [ "$code" -lt 200 ] 2>/dev/null || [ "$code" -ge 400 ] 2>/dev/null; then
  code=$(curl -sS -o /tmp/v101-source.out -w '%{http_code}' http://127.0.0.1:8005/ || true)
fi
[ "$code" -ge 200 ] 2>/dev/null && [ "$code" -lt 400 ] 2>/dev/null || { echo "SOURCE_HTTP=$code" >&2; exit 72; }
echo "SOURCE_RUNNING_COUNT=$count"
echo "SOURCE_HTTP=$code"
echo V101_SOURCE_ROLLBACK_HEALTH=PASS
'@
    $src = Invoke-SshScript -Ip $SourceIp -KnownHosts $SourceKnownHosts -ScriptText $SourceHealth
    Write-Host $src.StdOut
    Require ($src.ExitCode -eq 0) "Source rollback checkpoint health failed.`n$($src.StdOut)`n$($src.StdErr)"

    Write-Section 'V101 FINAL RESULT'
    Write-Host 'TARGET RUNTIME               : HEALTHY / ISOLATED'
    Write-Host 'TARGET SAFETY ENV            : PASS'
    Write-Host 'W118093 WAREHOUSE TRUTH      : PRESERVED'
    Write-Host 'AP SCENARIO 2 TRUTH          : PRESERVED'
    Write-Host 'AP LIVE SHAREPOINT AUTHORITY : STILL OPEN / NOT CLAIMED'
    Write-Host 'DUPLICATE / IDEMPOTENCY      : PRESERVED'
    Write-Host 'FAIL-CLOSED SOURCE SEMANTICS : PRESERVED'
    Write-Host 'SOURCE ROLLBACK              : HEALTHY'
    Write-Host 'TRAFFIC CUTOVER              : NONE'
    Write-Host 'PRODUCTION                   : NOT TOUCHED'
    Write-Host "DIAGNOSTICS                  : $DiagDir"
    Write-Host ''
    Write-Host 'NEXT                         : GUI TRUTH AUDIT + REMAINING AP/SHAREPOINT AUTHORITY BLOCKER' -ForegroundColor Cyan
    Write-Host 'V101_TARGET_PARITY_PRESERVATION=PASS' -ForegroundColor Green
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
