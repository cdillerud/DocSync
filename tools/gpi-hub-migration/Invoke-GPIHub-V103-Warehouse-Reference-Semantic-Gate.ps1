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
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\migration-v103-warehouse-semantic-gate\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
$TranscriptPath = Join-Path $DiagDir 'Invoke-GPIHub-V103-Warehouse-Reference-Semantic-Gate.txt'
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
    $stderrFile = Join-Path $env:TEMP "gpi-v103-$token.err.txt"
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
    $stderrFile = Join-Path $env:TEMP "gpi-v103-ssh-$token.err.txt"
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
    Write-Section 'V103 - WAREHOUSE REFERENCE SEMANTIC EVIDENCE GATE'
    Write-Host 'Classification      : PARITY BLOCKER VALIDATION'
    Write-Host 'Mode                : READ ONLY'
    Write-Host 'Purpose             : reject broad JBS/Strategic keyword false positives and require expected reference semantics'
    Write-Host 'Required semantics  : JBS inbound R-number; JBS outbound shipment number; Strategic inbound BOL number; Strategic outbound B/L number'
    Write-Host 'BC writes           : NONE'
    Write-Host 'SharePoint writes   : NONE'
    Write-Host 'Traffic cutover     : NONE'
    Write-Host 'Production          : NOT TOUCHED'

    Require (Test-Path -LiteralPath $KeyPath -PathType Leaf) "SSH key missing: $KeyPath"
    $KnownHosts = Get-KnownHostsForIp -Ip $TargetIp

    $Remote = @'
set -euo pipefail
PROJECT='gpi-hub-v100'
STATIC_NET='gpi-hub-v100-static-net'

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
[ "$(docker network inspect "$STATIC_NET" -f '{{.Internal}}')" = 'true' ] || { echo 'Static network is not internal.' >&2; exit 43; }
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
echo V103_TARGET_READ_ONLY_SAFETY=PASS

cat > /tmp/v103-semantic-gate.js <<'JS'
const D = db.getSiblingDB('gpi_document_hub');
const C = D.getCollection('hub_documents');
const MAX_EVIDENCE = 12;
const MAX_RECORDS = 20;

function scalar(v) {
  if (v === null || v === undefined) return null;
  if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') return String(v);
  return null;
}
function flatten(obj, path='', out=[], depth=0) {
  if (obj === null || obj === undefined || depth > 10 || out.length > 3000) return out;
  if (Array.isArray(obj)) {
    for (let i=0;i<Math.min(obj.length,50);i++) flatten(obj[i],`${path}[${i}]`,out,depth+1);
    return out;
  }
  if (typeof obj === 'object') {
    for (const [k,v] of Object.entries(obj)) {
      const p = path ? `${path}.${k}` : k;
      const s = scalar(v);
      if (s !== null && s.length <= 20000) out.push({path:p,value:s});
      else if (v && typeof v === 'object') flatten(v,p,out,depth+1);
    }
  }
  return out;
}
function first(items, re) {
  const x = items.find(e => re.test(e.path)); return x ? x.value : null;
}
function take(items, fn, max=MAX_EVIDENCE) {
  const out=[]; const seen=new Set();
  for (const e of items) {
    if (!fn(e)) continue;
    const k=`${e.path}|${e.value}`;
    if (seen.has(k)) continue;
    seen.add(k); out.push(e);
    if (out.length>=max) break;
  }
  return out;
}
function textLabeled(items,re) { return items.some(e => re.test(e.value)); }
function pathMatch(items,re) { return items.some(e => re.test(e.path) && e.value.trim() !== ''); }
function summarize(d, items, semantic, strength, evidence) {
  return {
    id: first(items,/(^|\.)(id|document_id)$/i) || String(d._id || ''),
    filename: first(items,/(^|\.)(filename|file_name|original_filename|original_file_name)$/i),
    document_type: first(items,/(^|\.)(document_type|classification|type)$/i),
    status: first(items,/(^|\.)(status|workflow_status|processing_status)$/i),
    semantic,
    strength,
    evidence,
    route_evidence: take(items,e => /(sharepoint|folder_routing|routing_details|route|destination|target_path|folder_path)/i.test(e.path) && e.value.trim() !== '',10),
    bc_evidence: take(items,e => /(po_resolution|bc_order_number|bc_record|bc_link|purchase_receipt|posted)/i.test(e.path) && e.value.trim() !== '',10)
  };
}
function classifyDirection(type, raw) {
  const t=(type||'').toLowerCase();
  const inbound = t==='warehouse_receipt' || /(warehouse[_ ]?receipt|\binbound\b|receiver|wh[_ -]?in)/i.test(raw);
  const outbound = t==='shipping_document' || /(\boutbound\b|shipment|shipping|bill of lading|\bbol\b|b\/l|wh[_ -]?out)/i.test(raw);
  if (inbound && !outbound) return 'inbound';
  if (outbound && !inbound) return 'outbound';
  if (inbound && outbound) return 'mixed';
  return 'unknown';
}
function semanticEvidence(group, items, raw, filename, type) {
  const pathR = take(items,e => /(^|\.)(r[_ -]?(number|no)|receipt[_ -]?(number|no)|receiver[_ -]?(number|no))$/i.test(e.path));
  const explicitRValue = take(items,e => /^R[- ]?\d{3,}$/i.test(e.value.trim()));
  const labeledR = take(items,e => /\bR\s*(number|no\.?|#)\s*[:#-]?\s*[A-Z0-9-]{3,}/i.test(e.value));

  const shipmentPath = take(items,e => /shipment.*(number|no|id)|shipment_number/i.test(e.path));
  const shipmentText = take(items,e => /shipment\s*(number|no\.?|#)\s*[:#-]?\s*[A-Z0-9-]{3,}/i.test(e.value));

  const bolPath = take(items,e => /(bol|bill.?of.?lading|b_l).*(number|no|id)|(^|\.)(bol|b_l)_?(number|no)?$/i.test(e.path));
  const bolText = take(items,e => /\b(BOL|B\/L|bill of lading)\s*(number|no\.?|#)\s*[:#-]?\s*[A-Z0-9-]{3,}/i.test(e.value));
  const bolLabelOnly = /\b(BOL|B\/L|bill of lading)\b/i.test(filename||'') || textLabeled(items,/\b(BOL|B\/L|bill of lading)\b/i);

  if (group==='JBS_INBOUND_R') {
    if (explicitRValue.length || labeledR.length || pathMatch(items,/(^|\.)r[_ -]?(number|no)$/i)) return {strength:'STRONG', evidence:[...explicitRValue,...labeledR,...take(pathR,e=>/(^|\.)r[_ -]?/i.test(e.path))].slice(0,MAX_EVIDENCE)};
    if (pathR.length) return {strength:'WEAK_RECEIPT_NUMBER_ONLY', evidence:pathR};
    return {strength:'NONE', evidence:[]};
  }
  if (group==='JBS_OUTBOUND_SHIPMENT') {
    if (shipmentPath.length || shipmentText.length) return {strength:'STRONG', evidence:[...shipmentPath,...shipmentText].slice(0,MAX_EVIDENCE)};
    return {strength:'NONE', evidence:[]};
  }
  if (group==='STRATEGIC_INBOUND_BOL' || group==='STRATEGIC_OUTBOUND_BL') {
    if (bolPath.length || bolText.length) return {strength:'STRONG', evidence:[...bolPath,...bolText].slice(0,MAX_EVIDENCE)};
    if (bolLabelOnly) return {strength:'WEAK_BOL_LABEL_ONLY', evidence:[{path:'filename_or_text_label',value:filename||'BOL label present'}]};
    return {strength:'NONE', evidence:[]};
  }
  return {strength:'NONE',evidence:[]};
}

const groups={
  JBS_INBOUND_R:{strong:[],weak:[],rejected:0},
  JBS_OUTBOUND_SHIPMENT:{strong:[],weak:[],rejected:0},
  STRATEGIC_INBOUND_BOL:{strong:[],weak:[],rejected:0},
  STRATEGIC_OUTBOUND_BL:{strong:[],weak:[],rejected:0}
};
let scanned=0, warehouseRelevant=0;
const cursor=C.find({});
while(cursor.hasNext()) {
  const d=cursor.next(); scanned++;
  const items=flatten(d);
  const raw=EJSON.stringify(d);
  const low=raw.toLowerCase();
  const filename=first(items,/(^|\.)(filename|file_name|original_filename|original_file_name)$/i)||'';
  const type=first(items,/(^|\.)(document_type|classification|type)$/i)||'';
  const direction=classifyDirection(type,raw);
  const isJbs=low.includes('jbs');
  const isStrategic=low.includes('strategic');
  if (!isJbs && !isStrategic) continue;
  if (!['warehouse_receipt','shipping_document','freight_document'].includes(type.toLowerCase()) && direction==='unknown') continue;
  warehouseRelevant++;

  let targetGroups=[];
  if (isJbs && direction==='inbound') targetGroups.push('JBS_INBOUND_R');
  if (isJbs && direction==='outbound') targetGroups.push('JBS_OUTBOUND_SHIPMENT');
  if (isStrategic && direction==='inbound') targetGroups.push('STRATEGIC_INBOUND_BOL');
  if (isStrategic && direction==='outbound') targetGroups.push('STRATEGIC_OUTBOUND_BL');
  for(const g of targetGroups) {
    const sem=semanticEvidence(g,items,raw,filename,type);
    const rec=summarize(d,items,g,sem.strength,sem.evidence);
    if (sem.strength==='STRONG') { if(groups[g].strong.length<MAX_RECORDS) groups[g].strong.push(rec); }
    else if (sem.strength.startsWith('WEAK')) { if(groups[g].weak.length<MAX_RECORDS) groups[g].weak.push(rec); }
    else groups[g].rejected++;
  }
}
const summary={};
for(const [g,v] of Object.entries(groups)) {
  summary[g]={strong_count:v.strong.length,weak_count:v.weak.length,rejected_count:v.rejected,status:v.strong.length>0?'STRONG_REFERENCE_EVIDENCE_PRESENT':(v.weak.length>0?'ONLY_WEAK_REFERENCE_EVIDENCE':'NO_SEMANTIC_REFERENCE_EVIDENCE')};
}
const result={generated_utc:new Date().toISOString(),scanned_documents:scanned,warehouse_relevant_documents:warehouseRelevant,summary,groups,interpretation:'Read-only semantic gate. STRONG means the expected reference convention is explicit in a persisted field or labeled text. WEAK means a related label/receipt field exists but the required reference-number semantics are not explicit. This still does not prove historical SharePoint delivery.'};
print('V103_JSON_BEGIN'); print(JSON.stringify(result)); print('V103_JSON_END');
JS

docker cp /tmp/v103-semantic-gate.js "$mongo:/tmp/v103-semantic-gate.js" >/dev/null
rm -f /tmp/v103-semantic-gate.js
mongo_out=$(docker exec "$mongo" sh -lc '
  set -e
  if [ -n "${MONGO_INITDB_ROOT_USERNAME:-}" ] && [ -n "${MONGO_INITDB_ROOT_PASSWORD:-}" ]; then
    exec mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin /tmp/v103-semantic-gate.js
  else
    exec mongosh --quiet /tmp/v103-semantic-gate.js
  fi
')
docker exec "$mongo" rm -f /tmp/v103-semantic-gate.js >/dev/null 2>&1 || true
printf '%s\n' "$mongo_out"
echo V103_WAREHOUSE_REFERENCE_SEMANTIC_SCAN=PASS
'@

    $result = Invoke-SshScript -Ip $TargetIp -KnownHosts $KnownHosts -ScriptText $Remote
    $rawPath = Join-Path $DiagDir 'target-v103-semantic-gate.txt'
    Set-Content -LiteralPath $rawPath -Value ($result.StdOut + "`n" + $result.StdErr) -Encoding utf8
    if (-not [string]::IsNullOrWhiteSpace($result.StdErr)) { Write-Host $result.StdErr -ForegroundColor DarkYellow }
    Require ($result.ExitCode -eq 0) "V103 semantic scan failed. See $rawPath"
    Require ($result.StdOut -match 'V103_TARGET_READ_ONLY_SAFETY=PASS') 'V103 target safety marker missing.'
    Require ($result.StdOut -match 'V103_WAREHOUSE_REFERENCE_SEMANTIC_SCAN=PASS') 'V103 scan PASS marker missing.'

    $jsonMatch = [regex]::Match($result.StdOut,'(?s)V103_JSON_BEGIN\s*(\{.*?\})\s*V103_JSON_END')
    Require ($jsonMatch.Success) 'V103 machine-readable JSON was not found.'
    $jsonText = $jsonMatch.Groups[1].Value
    $jsonPath = Join-Path $DiagDir 'warehouse-reference-semantic-gate.json'
    Set-Content -LiteralPath $jsonPath -Value $jsonText -Encoding utf8
    $gate = $jsonText | ConvertFrom-Json -Depth 60

    Write-Section 'V103 SEMANTIC GATE RESULT'
    Write-Host "Scanned documents        : $($gate.scanned_documents)"
    Write-Host "Warehouse-relevant docs  : $($gate.warehouse_relevant_documents)"
    $required=@('JBS_INBOUND_R','JBS_OUTBOUND_SHIPMENT','STRATEGIC_INBOUND_BOL','STRATEGIC_OUTBOUND_BL')
    $strongGroups=0
    foreach($g in $required) {
        $s=$gate.summary.$g
        Write-Host ("{0,-32}: strong={1,2} weak={2,2} rejected={3,5}  {4}" -f $g,[int]$s.strong_count,[int]$s.weak_count,[int]$s.rejected_count,[string]$s.status)
        if ([string]$s.status -eq 'STRONG_REFERENCE_EVIDENCE_PRESENT') { $strongGroups++ }
    }

    Write-Section 'V103 STRONG / WEAK EVIDENCE SHORTLIST'
    foreach($g in $required) {
        Write-Host "[$g]"
        $strong=@($gate.groups.$g.strong)
        $weak=@($gate.groups.$g.weak)
        foreach($rec in @($strong | Select-Object -First 3)) {
            Write-Host "  STRONG id=$($rec.id) file=$($rec.filename) type=$($rec.document_type)"
            foreach($e in @($rec.evidence)) { Write-Host "    ref=$($e.path) => $($e.value)" }
            foreach($e in @($rec.route_evidence | Select-Object -First 4)) { Write-Host "    route=$($e.path) => $($e.value)" }
        }
        foreach($rec in @($weak | Select-Object -First 2)) {
            Write-Host "  WEAK   id=$($rec.id) file=$($rec.filename) type=$($rec.document_type) strength=$($rec.strength)"
            foreach($e in @($rec.evidence)) { Write-Host "    ref=$($e.path) => $($e.value)" }
        }
        if ($strong.Count -eq 0 -and $weak.Count -eq 0) { Write-Host '  No semantic evidence survived the tightened gate.' }
    }

    Write-Host ''
    if ($strongGroups -eq 4) {
        Write-Host 'V103_REFERENCE_SEMANTICS=ALL_FOUR_STRONG' -ForegroundColor Green
    } else {
        Write-Host "V103_REFERENCE_SEMANTICS=PARTIAL_STRONG_$strongGroups`_OF_4" -ForegroundColor Yellow
    }
    Write-Host 'Important: even STRONG reference semantics do not prove actual historical SharePoint delivery.' -ForegroundColor Yellow
    Write-Host "Evidence JSON       : $jsonPath"
    Write-Host "Raw evidence        : $rawPath"
    Write-Host 'V103_WAREHOUSE_REFERENCE_SEMANTIC_GATE=PASS' -ForegroundColor Green
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
