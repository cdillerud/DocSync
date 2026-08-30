#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$State = Get-Content -LiteralPath (Join-Path $ToolRoot 'state.json') -Raw | ConvertFrom-Json -Depth 50
$OperationalRoot = [string]$State.local.operational_root
$KeyPath = [string]$State.local.ssh_key
$SourceIp = [string]$State.source.public_ip
$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\ap-top10-rev3-delta\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
Start-Transcript -LiteralPath (Join-Path $DiagDir 'Invoke-GPIHub-AP-Top10-REV3-Delta.txt') -Force | Out-Null

function Require {
    param([bool]$Condition,[string]$Message)
    if (-not $Condition) { throw $Message }
}

function Invoke-NativeText {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$AllowFailure
    )
    $token = [guid]::NewGuid().ToString('N')
    $stderrFile = Join-Path $env:TEMP "gpi-ap-top10-rev3-$token.err.txt"
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
            throw "$FilePath failed ($($result.ExitCode)).`n$stdout`n$stderr"
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
    foreach ($file in @(Get-ChildItem -LiteralPath $diagRoot -Filter '*known_hosts*' -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)) {
        $probe = Invoke-NativeText -FilePath 'ssh-keygen.exe' -Arguments @('-F',$Ip,'-f',$file.FullName) -AllowFailure
        if ($probe.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($probe.StdOut)) { return $file.FullName }
    }
    throw "No Azure-verified known_hosts file found for $Ip."
}

function Invoke-SshScript {
    param(
        [Parameter(Mandatory)][string]$KnownHosts,
        [Parameter(Mandatory)][string]$ScriptText
    )
    $token = [guid]::NewGuid().ToString('N')
    $stderrFile = Join-Path $env:TEMP "gpi-ap-top10-rev3-ssh-$token.err.txt"
    $args = @(
        '-i',$KeyPath,
        '-o','BatchMode=yes',
        '-o','StrictHostKeyChecking=yes',
        '-o',"UserKnownHostsFile=$KnownHosts",
        '-o','GlobalKnownHostsFile=NUL',
        '-o','ConnectTimeout=20',
        "azureuser@$SourceIp",
        'bash -s'
    )
    $oldEap = $ErrorActionPreference
    $nativeVar = Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $oldNative = if ($null -ne $nativeVar) { $nativeVar.Value } else { $null }
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

function Section([string]$Title) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

try {
    Section 'AP TOP-10 REV3 - DELTA INVENTORY + AI CORPUS'
    Write-Host 'Classification       : PARITY BLOCKER AP CORPUS HARDENING'
    Write-Host 'Inventory method     : GRAPH DRIVE DELTA / FLAT PAGED ENUMERATION'
    Write-Host 'Legacy scope         : DocsNAV Zetadocs + 2021 + 2022 + 2023'
    Write-Host 'Purchase filter      : parent path contains exact Purchase segment'
    Write-Host 'Progress             : heartbeat every Graph page and every AI sample'
    Write-Host 'Graph timeout        : 90 seconds per request'
    Write-Host 'AI timeout           : 180 seconds per sample'
    Write-Host 'Source app/data      : NO APP CHANGE / NO MONGO WRITE / NO RESTART'
    Write-Host 'SharePoint           : READ ONLY'
    Write-Host 'BC                   : NO WRITES'
    Write-Host 'Production           : NOT TOUCHED'

    Require (Test-Path -LiteralPath $KeyPath -PathType Leaf) "SSH key missing: $KeyPath"
    foreach ($cmd in 'ssh.exe','scp.exe','ssh-keygen.exe') {
        Require ($null -ne (Get-Command $cmd -ErrorAction SilentlyContinue)) "$cmd unavailable."
    }
    $Known = Get-KnownHostsForIp -Ip $SourceIp

    $Remote = @'
set -euo pipefail
EXPECTED_IMAGE='sha256:646051f6b0434b20ad429dec18c5f7b2a7d017c0fdec94f4bd77eaa7375fabb3'
EXPECTED_HELPER='2d2298b9c7e6315745d814e5437687caf463a44dec24d73d710b6d9e4e772117'
backend=$(docker ps --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
[ -n "$backend" ] || { echo 'Source backend missing.' >&2; exit 71; }
[ "$(docker inspect "$backend" -f '{{.Image}}')" = "$EXPECTED_IMAGE" ] || { echo 'Source backend image drift.' >&2; exit 72; }
[ "$(docker exec "$backend" sha256sum /app/services/document_intel_helpers.py | awk '{print $1}')" = "$EXPECTED_HELPER" ] || { echo 'Source AI helper drift.' >&2; exit 73; }
health=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=4); print(r.status)')
case "$health" in 2??|3??) ;; *) echo "Source backend unhealthy: $health" >&2; exit 74;; esac
echo "AP_TOP10_REV3_SOURCE_HEALTH_BEFORE=$health"
echo AP_TOP10_REV3_SOURCE_AUTHORITY=PASS

cat > /tmp/gpi-ap-top10-rev3.py <<'PY'
import asyncio, csv, hashlib, json, os, re, sys, time, types
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote
import httpx

from services.sharepoint_service import _get_graph_token
from services.document_intel_helpers import classify_document_with_ai

SITE_HOST='gamerpackaging1.sharepoint.com'
SITE_PATH='/sites/DocsNAV'
DRIVE_NAMES={'Zetadocs','Zetadocs2021','Zetadocs2022','Zetadocs2023'}
MANDATORY_VENDOR='Tumalo Creek Transportation'
MAX_AI_PER_VENDOR=3
CORP_SUFFIX=re.compile(r'\b(incorporated|inc|llc|ltd|limited|corp|corporation|company|co)\b',re.I)


def clean_space(s):
    return re.sub(r'\s+',' ',str(s or '').replace('_',' ')).strip()

def normalize_vendor_key(s):
    x=clean_space(s).lower()
    x=CORP_SUFFIX.sub(' ',x)
    x=re.sub(r'[^a-z0-9]+',' ',x)
    return clean_space(x)

def display_vendor(s):
    return clean_space(s)

def logical_name(name):
    stem=Path(name).stem
    stem=re.sub(r'\(\d+\)$','',stem).strip()
    return stem.lower()

def file_hash_key(item):
    hashes=((item.get('file') or {}).get('hashes') or {})
    for k in ('sha256Hash','sha1Hash','quickXorHash'):
        if hashes.get(k): return f'{k}:{hashes[k]}'
    return f"fallback:{logical_name(item.get('name',''))}:{item.get('size',0)}"

def purchase_vendor_from_parent(parent_path):
    path=unquote(str(parent_path or '')).replace('\\','/')
    parts=[p for p in path.split('/') if p]
    lower=[p.casefold() for p in parts]
    purchase_indexes=[i for i,p in enumerate(lower) if p=='purchase']
    if not purchase_indexes:
        return None
    idx=purchase_indexes[-1]
    return parts[idx-1] if idx>0 else '(unknown)'

def normalized_vendor_for_file(folder_vendor,name):
    if re.search(r'(?i)tumalo',name or ''):
        return MANDATORY_VENDOR
    return display_vendor(folder_vendor)

def dedupe(records):
    seen=set(); out=[]
    for r in records:
        key=(normalize_vendor_key(r['normalized_vendor']),r['content_key'])
        if key in seen: continue
        seen.add(key); out.append(r)
    return out

def pick_samples(rows):
    rows=sorted(rows,key=lambda r:(r.get('modified') or '',r['name']))
    if not rows: return []
    picks=[]
    for idx in (0,len(rows)//2,len(rows)-1):
        r=rows[idx]
        if r['item_id'] not in {x['item_id'] for x in picks}: picks.append(r)
    return picks[:MAX_AI_PER_VENDOR]

def extract_field(obj,names):
    if not isinstance(obj,dict): return None
    wanted={n.lower() for n in names}
    for k,v in obj.items():
        if str(k).lower() in wanted and v not in (None,'',[],{}): return v
        if isinstance(v,dict):
            nested=extract_field(v,names)
            if nested not in (None,'',[],{}): return nested
    return None

async def graph_get(client,url,headers,label):
    started=time.monotonic()
    try:
        r=await client.get(url,headers=headers)
        r.raise_for_status()
        return r
    except Exception as e:
        elapsed=time.monotonic()-started
        print(f'AP_TOP10_REV3_GRAPH_ERROR|label={label}|elapsed={elapsed:.1f}|error={type(e).__name__}:{e}',flush=True)
        raise

async def enumerate_drive_delta(client,headers,drive):
    url=f"https://graph.microsoft.com/v1.0/drives/{drive['id']}/root/delta?$top=200"
    page=0; scanned=0; purchase=[]; started=time.monotonic()
    while url:
        page+=1
        r=await graph_get(client,url,headers,f"delta:{drive['name']}:page:{page}")
        data=r.json(); items=data.get('value',[]); scanned+=len(items)
        for item in items:
            if item.get('file') is None or item.get('deleted') is not None:
                continue
            parent=(item.get('parentReference') or {}).get('path','')
            folder_vendor=purchase_vendor_from_parent(parent)
            if not folder_vendor:
                continue
            name=item.get('name','')
            purchase.append({
                'drive_name':drive['name'],
                'drive_id':drive['id'],
                'item_id':item['id'],
                'name':name,
                'size':item.get('size',0),
                'created':item.get('createdDateTime'),
                'modified':item.get('lastModifiedDateTime'),
                'folder_vendor':display_vendor(folder_vendor),
                'normalized_vendor':normalized_vendor_for_file(folder_vendor,name),
                'parent_path':unquote(str(parent)),
                'content_key':file_hash_key(item),
                'graph_url':f"https://graph.microsoft.com/v1.0/drives/{drive['id']}/items/{item['id']}",
            })
        elapsed=time.monotonic()-started
        print(f"AP_TOP10_REV3_HEARTBEAT|drive={drive['name']}|page={page}|scanned={scanned}|purchase_files={len(purchase)}|elapsed_sec={elapsed:.0f}",flush=True)
        url=data.get('@odata.nextLink')
    return purchase,{'pages':page,'items_scanned':scanned,'purchase_files':len(purchase),'elapsed_sec':round(time.monotonic()-started,1)}

async def main():
    token=await _get_graph_token(); headers={'Authorization':f'Bearer {token}'}
    timeout=httpx.Timeout(90.0,connect=20.0,read=90.0,write=90.0,pool=20.0)
    async with httpx.AsyncClient(timeout=timeout,follow_redirects=True) as client:
        site=await graph_get(client,f'https://graph.microsoft.com/v1.0/sites/{SITE_HOST}:{SITE_PATH}',headers,'site')
        site_id=site.json()['id']
        drives_resp=await graph_get(client,f'https://graph.microsoft.com/v1.0/sites/{site_id}/drives?$top=100&$select=id,name,webUrl',headers,'drives')
        drives=[d for d in drives_resp.json().get('value',[]) if d.get('name') in DRIVE_NAMES]
        found={d['name'] for d in drives}; missing=sorted(DRIVE_NAMES-found)
        if missing: raise RuntimeError(f'Missing expected DocsNAV drives: {missing}')
        print('AP_TOP10_REV3_DRIVES='+json.dumps(sorted(found)),flush=True)

        records=[]; stats={}
        for drive in sorted(drives,key=lambda d:d['name']):
            print('AP_TOP10_REV3_DRIVE_START='+drive['name'],flush=True)
            rows,st=await enumerate_drive_delta(client,headers,drive)
            records.extend(rows); stats[drive['name']]=st
            print('AP_TOP10_REV3_DRIVE_DONE='+drive['name']+'|'+json.dumps(st,sort_keys=True),flush=True)

        raw_records=list(records); unique=dedupe(records)
        key_counts=Counter(normalize_vendor_key(r['normalized_vendor']) for r in unique)
        label_votes=defaultdict(Counter)
        for r in unique: label_votes[normalize_vendor_key(r['normalized_vendor'])][display_vendor(r['normalized_vendor'])]+=1
        mandatory_key=normalize_vendor_key(MANDATORY_VENDOR)
        labels={}
        for key in key_counts:
            labels[key]=MANDATORY_VENDOR if key==mandatory_key else label_votes[key].most_common(1)[0][0]
        for r in unique: r['normalized_vendor']=labels[normalize_vendor_key(r['normalized_vendor'])]
        unique_norm=Counter(r['normalized_vendor'] for r in unique)
        folder_raw=Counter(normalize_vendor_key(r['folder_vendor']) for r in raw_records)
        folder_unique=Counter(normalize_vendor_key(r['folder_vendor']) for r in unique)

        ranking=[]
        for vendor,count in unique_norm.most_common():
            vk=normalize_vendor_key(vendor)
            ranking.append({
                'rank':len(ranking)+1,
                'vendor':vendor,
                'dedup_document_count':count,
                'raw_folder_document_count':folder_raw.get(vk,0),
                'dedup_folder_document_count':folder_unique.get(vk,0),
                'named_seed_override_count':sum(1 for r in unique if r['normalized_vendor']==vendor and normalize_vendor_key(r['folder_vendor'])!=vk),
            })
        top10=ranking[:10]; cohort=[r['vendor'] for r in top10]
        if MANDATORY_VENDOR not in cohort: cohort.append(MANDATORY_VENDOR)
        print(f'AP_TOP10_REV3_PURCHASE_FILES_RAW={len(raw_records)}',flush=True)
        print(f'AP_TOP10_REV3_PURCHASE_FILES_DEDUP={len(unique)}',flush=True)
        print('AP_TOP10_REV3_RANKING_JSON='+json.dumps(top10,sort_keys=True),flush=True)
        print('AP_TOP10_REV3_COHORT='+json.dumps(cohort),flush=True)
        print('AP_TOP10_REV3_TUMALO_DEDUP_COUNT='+str(unique_norm.get(MANDATORY_VENDOR,0)),flush=True)

        result={
            'generated_utc':datetime.now(timezone.utc).isoformat(),
            'method':'Graph drive delta flat enumeration',
            'drives':sorted(found),
            'stats':stats,
            'raw_purchase_files':len(raw_records),
            'dedup_purchase_files':len(unique),
            'top10':top10,
            'cohort':cohort,
            'tumalo_dedup_count':unique_norm.get(MANDATORY_VENDOR,0),
        }
        Path('/tmp/gpi-ap-top10-rev3-result.json').write_text(json.dumps(result,indent=2,sort_keys=True),encoding='utf-8')
        with open('/tmp/gpi-ap-top10-rev3-ranking.csv','w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=['rank','vendor','dedup_document_count','raw_folder_document_count','dedup_folder_document_count','named_seed_override_count'])
            w.writeheader(); w.writerows(ranking)

        by_vendor=defaultdict(list)
        for r in unique: by_vendor[r['normalized_vendor']].append(r)
        ai_rows=[]; total_samples=sum(len(pick_samples(by_vendor.get(v,[]))) for v in cohort); current=0
        for vendor in cohort:
            samples=pick_samples(by_vendor.get(vendor,[]))
            if not samples:
                ai_rows.append({'vendor_cohort':vendor,'status':'NO_SAMPLE_FOUND'}); continue
            for idx,s in enumerate(samples,1):
                current+=1
                print(f"AP_TOP10_REV3_AI_START|sample={current}/{total_samples}|vendor={vendor}|file={s['name']}",flush=True)
                dl=f"https://graph.microsoft.com/v1.0/drives/{s['drive_id']}/items/{s['item_id']}/content"
                rr=await graph_get(client,dl,headers,f'ai-download:{vendor}:{idx}')
                tmp=f"/tmp/ap-top10-rev3-{hashlib.sha1((vendor+s['item_id']).encode()).hexdigest()[:16]}.pdf"
                Path(tmp).write_bytes(rr.content)
                started=time.monotonic()
                try:
                    try:
                        ai=await asyncio.wait_for(classify_document_with_ai(tmp,s['name']),timeout=180)
                        status='CLASSIFIED'
                    except asyncio.TimeoutError:
                        ai={'error':'AI_TIMEOUT_180_SECONDS'}; status='AI_TIMEOUT'
                    classification=extract_field(ai,['suggested_job_type','document_type','classification','doc_type','type'])
                    row={
                        'vendor_cohort':vendor,'sample_index':idx,'file_name':s['name'],'archive_folder_vendor':s['folder_vendor'],
                        'classification':classification,'ai_vendor':extract_field(ai,['vendor_name','vendor','supplier_name','supplier']),
                        'invoice_number':extract_field(ai,['invoice_number','invoice_no','invoice_num']),'invoice_date':extract_field(ai,['invoice_date']),
                        'amount':extract_field(ai,['amount','invoice_amount','total_amount','total']),'po_number':extract_field(ai,['po_number','purchase_order_number','purchase_order','po_numbers']),
                        'bol_number':extract_field(ai,['bol_number','bill_of_lading','shipment_number']),'status':status,'ai_result':ai,
                        'tumalo_invoice_boundary_risk':vendor==MANDATORY_VENDOR and str(classification or '').casefold() not in {'ap_invoice','ap invoice'},
                    }
                    ai_rows.append(row)
                    print(f"AP_TOP10_REV3_AI_DONE|sample={current}/{total_samples}|vendor={vendor}|classification={classification}|status={status}|elapsed_sec={time.monotonic()-started:.1f}",flush=True)
                finally:
                    try: Path(tmp).unlink()
                    except Exception: pass

        Path('/tmp/gpi-ap-top10-rev3-ai-samples.json').write_text(json.dumps(ai_rows,indent=2,sort_keys=True,default=str),encoding='utf-8')
        classified=[r for r in ai_rows if r.get('status')=='CLASSIFIED']
        tumalo=[r for r in classified if r.get('vendor_cohort')==MANDATORY_VENDOR]
        risks=[r for r in tumalo if r.get('tumalo_invoice_boundary_risk')]
        print('AP_TOP10_REV3_AI_SAMPLE_COUNT='+str(len(classified)),flush=True)
        print('AP_TOP10_REV3_TUMALO_AI_SAMPLE_COUNT='+str(len(tumalo)),flush=True)
        print('AP_TOP10_REV3_TUMALO_CLASSIFICATION_RISK_COUNT='+str(len(risks)),flush=True)
        print('AP_TOP10_REV3_DELTA_INVENTORY_AI=PASS',flush=True)

asyncio.run(main())
PY

docker cp /tmp/gpi-ap-top10-rev3.py "$backend:/tmp/gpi-ap-top10-rev3.py" >/dev/null
rm -f /tmp/gpi-ap-top10-rev3.py
set +e
run_out=$(docker exec -e PYTHONPATH=/app -w /app "$backend" python /tmp/gpi-ap-top10-rev3.py 2>&1)
run_code=$?
set -e
printf '%s\n' "$run_out"
docker exec "$backend" rm -f /tmp/gpi-ap-top10-rev3.py >/dev/null 2>&1 || true
for f in gpi-ap-top10-rev3-result.json gpi-ap-top10-rev3-ranking.csv gpi-ap-top10-rev3-ai-samples.json; do
  if docker exec "$backend" test -f "/tmp/$f"; then docker cp "$backend:/tmp/$f" "/tmp/$f" >/dev/null; fi
done
[ "$run_code" -eq 0 ] || { echo "AP Top-10 REV3 failed with exit code $run_code" >&2; exit 75; }
printf '%s\n' "$run_out" | grep -Fq 'AP_TOP10_REV3_DELTA_INVENTORY_AI=PASS' || { echo 'AP Top-10 REV3 final marker missing.' >&2; exit 76; }
health_after=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=4); print(r.status)')
case "$health_after" in 2??|3??) ;; *) echo "Source backend unhealthy after Top-10 REV3: $health_after" >&2; exit 77;; esac
echo "AP_TOP10_REV3_SOURCE_HEALTH_AFTER=$health_after"
echo AP_TOP10_REV3_SOURCE_RUNTIME_UNCHANGED=PASS
'@

    $Run = Invoke-SshScript -KnownHosts $Known -ScriptText $Remote
    Set-Content -LiteralPath (Join-Path $DiagDir 'source-ap-top10-rev3.txt') -Value $Run.StdOut -Encoding utf8
    if ($Run.StdOut) { Write-Host $Run.StdOut }
    if ($Run.StdErr) { Write-Host $Run.StdErr -ForegroundColor DarkYellow }

    foreach ($name in 'gpi-ap-top10-rev3-result.json','gpi-ap-top10-rev3-ranking.csv','gpi-ap-top10-rev3-ai-samples.json') {
        $Local = Join-Path $DiagDir $name
        $Pull = Invoke-NativeText -FilePath 'scp.exe' -Arguments @('-i',$KeyPath,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',"UserKnownHostsFile=$Known",'-o','GlobalKnownHostsFile=NUL',"azureuser@${SourceIp}:/tmp/$name",$Local) -AllowFailure
        if ($Pull.ExitCode -eq 0) { Write-Host "AP_TOP10_REV3_ARTIFACT=$Local" }
    }
    [void](Invoke-SshScript -KnownHosts $Known -ScriptText "rm -f /tmp/gpi-ap-top10-rev3-result.json /tmp/gpi-ap-top10-rev3-ranking.csv /tmp/gpi-ap-top10-rev3-ai-samples.json`necho AP_TOP10_REV3_REMOTE_TEMP_CLEANUP=PASS")

    Require ($Run.ExitCode -eq 0) "AP Top-10 REV3 failed with exit code $($Run.ExitCode)."
    foreach ($marker in 'AP_TOP10_REV3_SOURCE_AUTHORITY=PASS','AP_TOP10_REV3_DELTA_INVENTORY_AI=PASS','AP_TOP10_REV3_SOURCE_RUNTIME_UNCHANGED=PASS') {
        Require ($Run.StdOut -match [regex]::Escape($marker)) "Missing AP Top-10 REV3 marker: $marker"
    }

    Section 'AP TOP-10 REV3 FINAL RESULT'
    Write-Host "Diagnostics          : $DiagDir"
    Write-Host 'AP_TOP10_PAYABLE_VENDOR_AI_CORPUS=INITIAL_PASS_REV3_DELTA' -ForegroundColor Green
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
