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
$ProjectName = 'gpi-hub-v100'
$StaticNetwork = 'gpi-hub-v100-static-net'

$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\migration-v102-warehouse-reference-matrix\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
$TranscriptPath = Join-Path $DiagDir 'Invoke-GPIHub-V102-Warehouse-Reference-Matrix-Discovery.txt'
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
    $stderrFile = Join-Path $env:TEMP "gpi-v102-$token.err.txt"
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
    $stderrFile = Join-Path $env:TEMP "gpi-v102-ssh-$token.err.txt"
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
    Write-Section 'V102 - WAREHOUSE SQUARE9 REFERENCE-MATRIX DISCOVERY'
    Write-Host 'Classification      : PARITY BLOCKER DISCOVERY'
    Write-Host 'Mode                : READ ONLY'
    Write-Host 'Required patterns   : JBS inbound R-number; JBS outbound shipment; Strategic inbound BOL; Strategic outbound B/L'
    Write-Host 'Target              : STATIC ISOLATED MIGRATED RUNTIME'
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
UPLOADS='/gpi-hub-data/volumes/uploads'

backend=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
frontend=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=frontend' --format '{{.Names}}' | head -n 1)
mongo=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=mongodb' --format '{{.Names}}' | head -n 1)
[ -n "$backend" ] && [ -n "$frontend" ] && [ -n "$mongo" ] || { echo 'Required target service missing.' >&2; exit 41; }

for expected in \
  'GPI_MIGRATION_STATIC_RUNTIME=true' \
  'SHAREPOINT_TARGET=test' \
  'BC_WRITE_ENABLED=false' \
  'BC_BLOCK_PRODUCTION_WRITES=true' \
  'EMAIL_POLLING_ENABLED=false' \
  'SALES_EMAIL_POLLING_ENABLED=false' \
  'AUTO_POST_ENABLED=false' \
  'AUTO_CREATE_SALES_ORDER_ENABLED=false'; do
  docker inspect "$backend" -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fxq "$expected" || { echo "SAFETY_ENV_MISSING=$expected" >&2; exit 42; }
done
internal=$(docker network inspect "$STATIC_NET" -f '{{.Internal}}')
[ "$internal" = 'true' ] || { echo 'Static network is not internal.' >&2; exit 43; }
for c in "$backend" "$frontend" "$mongo"; do
  nets=$(docker inspect "$c" -f '{{range $k,$v := .NetworkSettings.Networks}}{{println $k}}{{end}}' | xargs)
  [ "$nets" = "$STATIC_NET" ] || { echo "UNEXPECTED_NETWORK=$c|$nets" >&2; exit 44; }
done
code=$(docker exec "$backend" python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=5).status)' | tail -n 1 | xargs)
[ "$code" = '200' ] || { echo "TARGET_HEALTH=$code" >&2; exit 45; }
if docker exec "$backend" python -c 'import socket; s=socket.create_connection(("graph.microsoft.com",443),3); s.close()' >/dev/null 2>&1; then
  echo 'Target unexpectedly has external egress.' >&2
  exit 46
fi
echo V102_TARGET_READ_ONLY_SAFETY=PASS

cat > /tmp/v102-warehouse-matrix.js <<'JS'
const D = db.getSiblingDB('gpi_document_hub');
const C = D.getCollection('hub_documents');
const total = C.estimatedDocumentCount();
const MAX_SCAN = 50000;
const MAX_PER_GROUP = 25;

function scalarString(v) {
  if (v === null || v === undefined) return null;
  if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') return String(v);
  return null;
}

function firstValue(obj, keys, depth=0) {
  if (!obj || typeof obj !== 'object' || depth > 7) return null;
  for (const [k,v] of Object.entries(obj)) {
    const lk = String(k).toLowerCase();
    if (keys.includes(lk)) {
      const s = scalarString(v);
      if (s !== null && s.length <= 500) return s;
    }
  }
  for (const v of Object.values(obj)) {
    if (v && typeof v === 'object') {
      if (Array.isArray(v)) {
        for (const item of v.slice(0,20)) {
          const hit = firstValue(item, keys, depth+1);
          if (hit !== null) return hit;
        }
      } else {
        const hit = firstValue(v, keys, depth+1);
        if (hit !== null) return hit;
      }
    }
  }
  return null;
}

function collectRefs(obj, path='', out=[], depth=0) {
  if (!obj || typeof obj !== 'object' || depth > 8 || out.length >= 20) return out;
  for (const [k,v] of Object.entries(obj)) {
    if (out.length >= 20) break;
    const p = path ? `${path}.${k}` : k;
    const lk = String(k).toLowerCase();
    const s = scalarString(v);
    const keyLooksRelevant = /(reference|receipt|shipment|bill.?of.?lading|\bbol\b|\bb.?l\b|r[_ -]?number|po[_ -]?number|order[_ -]?number)/i.test(lk);
    const valueLooksRelevant = s && (/\bR[- ]?\d{3,}\b/i.test(s) || /\bB\/?L\b/i.test(s) || /\bBOL\b/i.test(s));
    if (s !== null && s.length <= 500 && (keyLooksRelevant || valueLooksRelevant)) {
      out.push({path:p, value:s});
    }
    if (v && typeof v === 'object') {
      if (Array.isArray(v)) {
        for (let i=0; i<Math.min(v.length,20) && out.length<20; i++) collectRefs(v[i], `${p}[${i}]`, out, depth+1);
      } else {
        collectRefs(v, p, out, depth+1);
      }
    }
  }
  return out;
}

function summarize(d) {
  const id = firstValue(d,['id','document_id']) || String(d._id || '');
  return {
    id,
    filename: firstValue(d,['filename','file_name','original_filename','original_file_name','name']),
    document_type: firstValue(d,['document_type','classification','type']),
    status: firstValue(d,['status','workflow_status','processing_status']),
    sharepoint_path: firstValue(d,['sharepoint_path','folder_path','target_path','destination_path','sharepoint_folder']),
    reference_candidates: collectRefs(d).slice(0,12)
  };
}

const groups = {
  JBS_INBOUND_R: [],
  JBS_OUTBOUND_SHIPMENT: [],
  STRATEGIC_INBOUND_BOL: [],
  STRATEGIC_OUTBOUND_BL: [],
  JBS_DIRECTION_UNCLEAR: [],
  STRATEGIC_DIRECTION_UNCLEAR: []
};
const counts = Object.fromEntries(Object.keys(groups).map(k => [k,0]));
let scanned = 0;

const cursor = C.find({}).limit(Math.min(MAX_SCAN,total));
while (cursor.hasNext()) {
  const d = cursor.next();
  scanned++;
  const raw = EJSON.stringify(d);
  const low = raw.toLowerCase();
  const isJbs = low.includes('jbs');
  const isStrategic = low.includes('strategic');
  if (!isJbs && !isStrategic) continue;

  const inbound = /(warehouse[_ ]?receipt|inbound|receiver|receipt|wh[_ -]?in)/i.test(raw);
  const outbound = /(outbound|shipment|shipping|bill of lading|\bbol\b|b\/l|wh[_ -]?out)/i.test(raw);
  let group = null;
  if (isJbs && inbound && !outbound) group = 'JBS_INBOUND_R';
  else if (isJbs && outbound && !inbound) group = 'JBS_OUTBOUND_SHIPMENT';
  else if (isStrategic && inbound && !outbound) group = 'STRATEGIC_INBOUND_BOL';
  else if (isStrategic && outbound && !inbound) group = 'STRATEGIC_OUTBOUND_BL';
  else if (isJbs) group = 'JBS_DIRECTION_UNCLEAR';
  else if (isStrategic) group = 'STRATEGIC_DIRECTION_UNCLEAR';

  counts[group]++;
  if (groups[group].length < MAX_PER_GROUP) groups[group].push(summarize(d));
}

const result = {
  generated_utc: new Date().toISOString(),
  collection: 'gpi_document_hub.hub_documents',
  total_documents: total,
  scan_limit: MAX_SCAN,
  scanned_documents: scanned,
  scan_complete: total <= MAX_SCAN,
  requirements: {
    JBS_INBOUND_R: 'JBS inbound documents reference an R number',
    JBS_OUTBOUND_SHIPMENT: 'JBS outbound documents reference a shipment number',
    STRATEGIC_INBOUND_BOL: 'Strategic inbound documents reference a BOL number',
    STRATEGIC_OUTBOUND_BL: 'Strategic outbound documents reference a B/L number'
  },
  counts,
  candidates: groups,
  interpretation: 'Candidate discovery only. A candidate is not validated parity until reference semantics, BC resolution where applicable, and actual historical routing/delivery are proven.'
};
print('V102_JSON_BEGIN');
print(JSON.stringify(result));
print('V102_JSON_END');
JS

docker cp /tmp/v102-warehouse-matrix.js "$mongo:/tmp/v102-warehouse-matrix.js" >/dev/null
rm -f /tmp/v102-warehouse-matrix.js
mongo_out=$(docker exec "$mongo" sh -lc '
  set -e
  if [ -n "${MONGO_INITDB_ROOT_USERNAME:-}" ] && [ -n "${MONGO_INITDB_ROOT_PASSWORD:-}" ]; then
    exec mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin /tmp/v102-warehouse-matrix.js
  else
    exec mongosh --quiet /tmp/v102-warehouse-matrix.js
  fi
')
docker exec "$mongo" rm -f /tmp/v102-warehouse-matrix.js >/dev/null 2>&1 || true
printf '%s\n' "$mongo_out"

echo 'V102_UPLOAD_FILENAME_EVIDENCE_BEGIN'
find "$UPLOADS" -type f \( -iname '*jbs*' -o -iname '*strategic*' -o -iname '*bill*of*lading*' -o -iname '*shipment*' \) -printf '%P\n' 2>/dev/null | head -n 200 || true
echo 'V102_UPLOAD_FILENAME_EVIDENCE_END'

echo 'V102_SOURCE_TERM_EVIDENCE_BEGIN'
grep -R -n -i -E 'JBS|Strategic|WH[_ -]?in[_ -]?JBS|WH[_ -]?out[_ -]?JBS|WH[_ -]?out[_ -]?Strategic|bill of lading|shipment number|R number' "$APP/backend" "$APP/frontend" 2>/dev/null | head -n 300 || true
echo 'V102_SOURCE_TERM_EVIDENCE_END'

echo V102_WAREHOUSE_REFERENCE_MATRIX_DISCOVERY=PASS
'@

    $result = Invoke-SshScript -Ip $TargetIp -KnownHosts $KnownHosts -ScriptText $Remote
    $rawPath = Join-Path $DiagDir 'target-v102-warehouse-reference-matrix.txt'
    Set-Content -LiteralPath $rawPath -Value ($result.StdOut + "`n" + $result.StdErr) -Encoding utf8
    Write-Host $result.StdOut
    if (-not [string]::IsNullOrWhiteSpace($result.StdErr)) { Write-Host $result.StdErr -ForegroundColor DarkYellow }
    Require ($result.ExitCode -eq 0) "V102 discovery failed. See $rawPath"
    Require ($result.StdOut -match 'V102_TARGET_READ_ONLY_SAFETY=PASS') 'V102 target safety marker missing.'
    Require ($result.StdOut -match 'V102_WAREHOUSE_REFERENCE_MATRIX_DISCOVERY=PASS') 'V102 discovery PASS marker missing.'

    $jsonMatch = [regex]::Match($result.StdOut,'(?s)V102_JSON_BEGIN\s*(\{.*?\})\s*V102_JSON_END')
    Require ($jsonMatch.Success) 'V102 machine-readable discovery JSON was not found.'
    $jsonText = $jsonMatch.Groups[1].Value
    $jsonPath = Join-Path $DiagDir 'warehouse-reference-matrix-discovery.json'
    Set-Content -LiteralPath $jsonPath -Value $jsonText -Encoding utf8
    $matrix = $jsonText | ConvertFrom-Json -Depth 50

    Write-Section 'V102 DISCOVERY MATRIX'
    Write-Host "Hub documents       : $($matrix.total_documents)"
    Write-Host "Scanned             : $($matrix.scanned_documents)"
    Write-Host "Full collection scan: $($matrix.scan_complete)"
    foreach ($name in @('JBS_INBOUND_R','JBS_OUTBOUND_SHIPMENT','STRATEGIC_INBOUND_BOL','STRATEGIC_OUTBOUND_BL')) {
        $count = [int]$matrix.counts.$name
        $status = if ($count -gt 0) { 'CANDIDATE_FOUND' } else { 'NO_CANDIDATE_IN_SCAN' }
        Write-Host ("{0,-32}: {1,6}  {2}" -f $name,$count,$status)
    }

    $allFour = @('JBS_INBOUND_R','JBS_OUTBOUND_SHIPMENT','STRATEGIC_INBOUND_BOL','STRATEGIC_OUTBOUND_BL') | ForEach-Object { [int]$matrix.counts.$_ -gt 0 }
    if (($allFour | Where-Object { -not $_ }).Count -eq 0) {
        Write-Host 'V102_REQUIRED_PATTERN_CANDIDATES=ALL_FOUR_PRESENT' -ForegroundColor Green
    } else {
        Write-Host 'V102_REQUIRED_PATTERN_CANDIDATES=INCOMPLETE' -ForegroundColor Yellow
    }

    Write-Host ''
    Write-Host 'Important: candidate discovery is NOT a parity pass.' -ForegroundColor Yellow
    Write-Host 'Each candidate still requires authoritative reference semantics + BC resolution where applicable + actual routing/delivery proof.' -ForegroundColor Yellow
    Write-Host "Discovery JSON      : $jsonPath"
    Write-Host "Raw evidence        : $rawPath"
    Write-Host 'V102_WAREHOUSE_REFERENCE_MATRIX_DISCOVERY=PASS' -ForegroundColor Green
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
