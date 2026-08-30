#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$StatePath = Join-Path $ToolRoot 'state.json'
$ManifestPath = Join-Path $ToolRoot 'v104-warehouse-historical-authority.json'
$State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 50
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json -Depth 50

$OperationalRoot = [string]$State.local.operational_root
$KeyPath = [string]$State.local.ssh_key
$TargetIp = [string]$State.target.public_ip
$ProjectName = 'gpi-hub-v100'
$StaticNetwork = 'gpi-hub-v100-static-net'

$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\migration-v104-warehouse-historical-authority\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
$TranscriptPath = Join-Path $DiagDir 'Invoke-GPIHub-V104-Warehouse-Historical-Authority-Reconciliation.txt'
Start-Transcript -LiteralPath $TranscriptPath -Force | Out-Null

function Require([bool]$Condition,[string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Invoke-NativeText {
    param([Parameter(Mandatory)][string]$FilePath,[Parameter(Mandatory)][string[]]$Arguments,[switch]$AllowFailure)
    $token = [guid]::NewGuid().ToString('N')
    $stderrFile = Join-Path $env:TEMP "gpi-v104-$token.err.txt"
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
    $stderrFile = Join-Path $env:TEMP "gpi-v104-ssh-$token.err.txt"
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
    Write-Section 'V104 - WAREHOUSE HISTORICAL AUTHORITY RECONCILIATION'
    Write-Host 'Classification      : PARITY BLOCKER VALIDATION'
    Write-Host 'Mode                : READ ONLY'
    Write-Host 'Historical authority: USER SHAREPOINT DocsNAV/Zetadocs evidence manifest'
    Write-Host 'Target              : STATIC ISOLATED MIGRATED RUNTIME'
    Write-Host 'BC writes           : NONE'
    Write-Host 'SharePoint writes   : NONE'
    Write-Host 'Traffic cutover     : NONE'
    Write-Host 'Production          : NOT TOUCHED'

    Require (Test-Path -LiteralPath $ManifestPath -PathType Leaf) "Historical authority manifest missing: $ManifestPath"
    $caseIds = @($Manifest.cases | ForEach-Object { [string]$_.case_id })
    foreach ($required in @('JBS_INBOUND_R','JBS_OUTBOUND_SHIPMENT','STRATEGIC_INBOUND_BOL','STRATEGIC_OUTBOUND_BL')) {
        Require ($caseIds -contains $required) "Historical authority manifest missing case $required"
    }
    Write-Host 'V104_HISTORICAL_AUTHORITY_MANIFEST=PASS' -ForegroundColor Green

    Require (Test-Path -LiteralPath $KeyPath -PathType Leaf) "SSH key missing: $KeyPath"
    Require ($null -ne (Get-Command ssh.exe -ErrorAction SilentlyContinue)) 'ssh.exe unavailable.'
    Require ($null -ne (Get-Command ssh-keygen.exe -ErrorAction SilentlyContinue)) 'ssh-keygen.exe unavailable.'
    $KnownHosts = Get-KnownHostsForIp -Ip $TargetIp

    $Remote = @'
set -euo pipefail
PROJECT='gpi-hub-v100'
STATIC_NET='gpi-hub-v100-static-net'
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
echo V104_TARGET_READ_ONLY_SAFETY=PASS

cat > /tmp/v104-reconcile.js <<'JS'
const D = db.getSiblingDB('gpi_document_hub');
const C = D.getCollection('hub_documents');

function sid(d) { return String((d && (d.id || d.document_id || d._id)) || ''); }
function scalar(v) { return (v===null || v===undefined) ? null : ((typeof v==='string'||typeof v==='number'||typeof v==='boolean') ? String(v) : null); }
function flatten(obj, path='', out=[], depth=0) {
  if (!obj || typeof obj !== 'object' || depth > 9 || out.length > 4000) return out;
  for (const [k,v] of Object.entries(obj)) {
    const p = path ? `${path}.${k}` : k;
    const s = scalar(v);
    if (s !== null && s.length <= 2000) out.push({path:p,value:s});
    if (v && typeof v === 'object') {
      if (Array.isArray(v)) { for (let i=0;i<Math.min(v.length,50);i++) flatten(v[i],`${p}[${i}]`,out,depth+1); }
      else flatten(v,p,out,depth+1);
    }
  }
  return out;
}
function byId(id) {
  if (!id) return null;
  return C.findOne({id}) || C.findOne({document_id:id}) || null;
}
function findTokens(tokens, max=12) {
  const want = tokens.map(x=>String(x).toLowerCase());
  const out=[];
  const cur=C.find({});
  while(cur.hasNext() && out.length<max) {
    const d=cur.next(); const raw=EJSON.stringify(d).toLowerCase();
    if (want.every(t=>raw.includes(t))) out.push(d);
  }
  return out;
}
function refs(d) {
  return flatten(d).filter(x=>/(receipt|shipment|bol|bill.?of.?lading|load|reference|order|po_number|sharepoint|folder|destination)/i.test(x.path)).slice(0,80);
}
function hits(d, values) {
  const f=flatten(d); const vals=values.filter(Boolean).map(v=>String(v).toLowerCase());
  return f.filter(x=>vals.some(v=>x.value.toLowerCase().includes(v))).slice(0,60);
}
function typeOf(d){ const f=flatten(d); const x=f.find(x=>/(^|\.)(document_type|classification|type)$/i.test(x.path)); return x?x.value:null; }
function fileOf(d){ const f=flatten(d); const x=f.find(x=>/(^|\.)(filename|file_name|original_filename|original_file_name)$/i.test(x.path)); return x?x.value:null; }
function routeUrls(d){ return flatten(d).filter(x=>/sharepoint.*(url|path)|sharepoint_web_url|destination_path|folder_path/i.test(x.path)).slice(0,20); }
function explicitPathHit(d, re, value) { return flatten(d).some(x=>re.test(x.path) && (!value || x.value.toLowerCase().includes(String(value).toLowerCase()))); }
function rawHas(d,value){ return !!d && EJSON.stringify(d).toLowerCase().includes(String(value).toLowerCase()); }
function summary(d){ return d?{id:sid(d),filename:fileOf(d),document_type:typeOf(d),refs:refs(d),routes:routeUrls(d)}:null; }

const result={generated_utc:new Date().toISOString(),collection:'gpi_document_hub.hub_documents',cases:{},matrix_closed:false};

// JBS inbound: exact R-number authority exists.
{
  const d=byId('95ced52c-1521-43b6-b69e-4afc4ed600d5') || findTokens(['w118228','r72713'],1)[0] || null;
  const refMatch=!!d && (explicitPathHit(d,/receipt_number/i,'R72713') || rawHas(d,'R72713'));
  const routes=routeUrls(d);
  const routeConflict=routes.some(x=>/miscellaneous documents|misc invoices/i.test(x.value));
  result.cases.JBS_INBOUND_R={historical_authority:'PROVEN_R72713',target:summary(d),target_reference_match:refMatch,target_route_conflict:routeConflict,status:!d?'TARGET_RECORD_MISSING':(!refMatch?'TARGET_REFERENCE_GAP':(routeConflict?'REFERENCE_MATCH_ROUTE_CONFLICT':'REFERENCE_MATCH_ROUTE_NEEDS_AUTHORITY'))};
}

// JBS outbound: historical packet is authoritative, but exact shipment-number identity remains unresolved.
{
  const d=byId('04a47c5e-9180-4b41-bbd2-fcbfb62d336b') || findTokens(['111244','jbs'],1)[0] || null;
  const values=['111244','545299334','PO-019363','595995'];
  const h=d?hits(d,values):[];
  const explicitShipment=d?flatten(d).filter(x=>/shipment_number|shipment_no|shipment\.number/i.test(x.path)).slice(0,20):[];
  result.cases.JBS_OUTBOUND_SHIPMENT={historical_authority:'PACKET_PROVEN_EXACT_SHIPMENT_NUMBER_UNRESOLVED',target:summary(d),historical_identifier_hits:h,explicit_shipment_fields:explicitShipment,status:!d?'TARGET_RECORD_MISSING':(explicitShipment.length>0?'TARGET_HAS_SHIPMENT_FIELD_NEEDS_AUTHORITY':'SHIPMENT_REFERENCE_NOT_NORMALIZED')};
}

// Strategic inbound: authentic W117105 Strategic packet exists. Reject unrelated AP invoice as representative proof.
{
  const docs=findTokens(['w117105'],12);
  const strategic=docs.filter(d=>/strategic/i.test(EJSON.stringify(d)));
  const bolStrong=strategic.filter(d=>flatten(d).some(x=>/(bol_number|bill.?of.?lading)/i.test(x.path) && x.value.trim().length>0));
  result.cases.STRATEGIC_INBOUND_BOL={historical_authority:'AUTHENTIC_W117105_STRATEGIC_PACKET_PROVEN_BOL_IDENTITY_UNRESOLVED',target_candidates:strategic.slice(0,8).map(summary),explicit_bol_candidates:bolStrong.slice(0,8).map(summary),status:strategic.length===0?'AUTHENTIC_PACKET_NOT_FOUND_IN_TARGET':(bolStrong.length===0?'AUTHENTIC_PACKET_FOUND_BOL_NOT_NORMALIZED':'TARGET_HAS_BOL_FIELD_NEEDS_HISTORICAL_LABEL_CONFIRMATION')};
}

// Strategic outbound: exact printed B/L #57745 authority.
{
  const d=byId('f35038a9-6d26-49c5-8461-67cef2083171') || findTokens(['114049','strategic'],1)[0] || null;
  const exact=!!d && explicitPathHit(d,/(bol_number|bill.?of.?lading)/i,'57745');
  const raw=!!d && rawHas(d,'57745');
  result.cases.STRATEGIC_OUTBOUND_BL={historical_authority:'PROVEN_BILL_OF_LADING_57745',target:summary(d),target_explicit_bl_match:exact,target_raw_contains_57745:raw,status:!d?'TARGET_RECORD_MISSING':(exact?'BL_REFERENCE_MATCH':(raw?'BL_PRESENT_BUT_NOT_NORMALIZED':'BL_REFERENCE_MISSING'))};
}

const statuses=Object.values(result.cases).map(x=>x.status);
result.open_blockers=statuses.filter(s=>!['BL_REFERENCE_MATCH'].includes(s)).length;
result.matrix_closed = result.open_blockers===0;
print('V104_JSON_BEGIN');
print(JSON.stringify(result));
print('V104_JSON_END');
JS

docker cp /tmp/v104-reconcile.js "$mongo:/tmp/v104-reconcile.js" >/dev/null
rm -f /tmp/v104-reconcile.js
mongo_out=$(docker exec "$mongo" sh -lc '
  set -e
  if [ -n "${MONGO_INITDB_ROOT_USERNAME:-}" ] && [ -n "${MONGO_INITDB_ROOT_PASSWORD:-}" ]; then
    exec mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin /tmp/v104-reconcile.js
  else
    exec mongosh --quiet /tmp/v104-reconcile.js
  fi
')
docker exec "$mongo" rm -f /tmp/v104-reconcile.js >/dev/null 2>&1 || true
printf '%s\n' "$mongo_out"
echo V104_HISTORICAL_AUTHORITY_RECONCILIATION_REMOTE=PASS
'@

    $result = Invoke-SshScript -Ip $TargetIp -KnownHosts $KnownHosts -ScriptText $Remote
    $rawPath = Join-Path $DiagDir 'target-v104-historical-authority-reconciliation.txt'
    Set-Content -LiteralPath $rawPath -Value ($result.StdOut + "`n" + $result.StdErr) -Encoding utf8
    Write-Host $result.StdOut
    if (-not [string]::IsNullOrWhiteSpace($result.StdErr)) { Write-Host $result.StdErr -ForegroundColor DarkYellow }
    Require ($result.ExitCode -eq 0) "V104 remote reconciliation failed. See $rawPath"
    Require ($result.StdOut -match 'V104_TARGET_READ_ONLY_SAFETY=PASS') 'V104 target safety marker missing.'
    Require ($result.StdOut -match 'V104_HISTORICAL_AUTHORITY_RECONCILIATION_REMOTE=PASS') 'V104 remote PASS marker missing.'

    $jsonMatch = [regex]::Match($result.StdOut,'(?s)V104_JSON_BEGIN\s*(\{.*?\})\s*V104_JSON_END')
    Require ($jsonMatch.Success) 'V104 machine-readable result JSON was not found.'
    $jsonText = $jsonMatch.Groups[1].Value
    $jsonPath = Join-Path $DiagDir 'warehouse-historical-authority-reconciliation.json'
    Set-Content -LiteralPath $jsonPath -Value $jsonText -Encoding utf8
    $r = $jsonText | ConvertFrom-Json -Depth 50

    Write-Section 'V104 AUTHORITY / TARGET RECONCILIATION RESULT'
    foreach ($name in @('JBS_INBOUND_R','JBS_OUTBOUND_SHIPMENT','STRATEGIC_INBOUND_BOL','STRATEGIC_OUTBOUND_BL')) {
        $c = $r.cases.$name
        Write-Host ("{0,-32}: {1}" -f $name,[string]$c.status)
        if ($null -ne $c.target -and $null -ne $c.target.id) {
            Write-Host "  target id   : $($c.target.id)"
            Write-Host "  target file : $($c.target.filename)"
            Write-Host "  target type : $($c.target.document_type)"
        }
        if ($name -eq 'STRATEGIC_INBOUND_BOL' -and $null -ne $c.target_candidates) {
            Write-Host "  W117105/Strategic target candidates: $(@($c.target_candidates).Count)"
            Write-Host "  Explicit BOL candidates             : $(@($c.explicit_bol_candidates).Count)"
        }
    }

    Write-Host ''
    Write-Host "Open Warehouse matrix blockers : $($r.open_blockers)"
    if ([bool]$r.matrix_closed) {
        Write-Host 'V104_WAREHOUSE_REFERENCE_MATRIX=CLOSED' -ForegroundColor Green
    } else {
        Write-Host 'V104_WAREHOUSE_REFERENCE_MATRIX=OPEN' -ForegroundColor Yellow
    }
    Write-Host 'Important: V104 PASS means historical authority was reconciled; it does NOT mean the Warehouse parity blocker is closed.' -ForegroundColor Yellow
    Write-Host "Authority manifest : $ManifestPath"
    Write-Host "Result JSON        : $jsonPath"
    Write-Host "Raw evidence       : $rawPath"
    Write-Host 'V104_HISTORICAL_AUTHORITY_RECONCILIATION=PASS' -ForegroundColor Green
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
