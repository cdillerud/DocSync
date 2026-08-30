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
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\ap-top10-legacy-inventory-ai\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
Start-Transcript -LiteralPath (Join-Path $DiagDir 'Invoke-GPIHub-AP-Top10-Legacy-Inventory-AI.txt') -Force | Out-Null

function Require([bool]$Condition,[string]$Message) { if (-not $Condition) { throw $Message } }

function Invoke-NativeText {
    param([Parameter(Mandatory)][string]$FilePath,[Parameter(Mandatory)][string[]]$Arguments,[switch]$AllowFailure)
    $token=[guid]::NewGuid().ToString('N')
    $stderrFile=Join-Path $env:TEMP "gpi-ap-top10-$token.err.txt"
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

function Invoke-SshScript([string]$KnownHosts,[string]$ScriptText) {
    $token=[guid]::NewGuid().ToString('N')
    $stderrFile=Join-Path $env:TEMP "gpi-ap-top10-ssh-$token.err.txt"
    $args=@('-i',$KeyPath,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',"UserKnownHostsFile=$KnownHosts",'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=20',"azureuser@$SourceIp",'bash -s')
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

function Section([string]$Title){Write-Host '';Write-Host ('='*120) -ForegroundColor Cyan;Write-Host $Title -ForegroundColor Cyan;Write-Host ('='*120) -ForegroundColor Cyan}

try {
    Section 'AP TOP-10 LEGACY PAYABLE INVENTORY + INITIAL AI CORPUS'
    Write-Host 'Classification       : PARITY BLOCKER AP CORPUS HARDENING'
    Write-Host 'Legacy authority     : DocsNAV SharePoint Zetadocs libraries'
    Write-Host 'Scope                : files beneath exact Purchase folders'
    Write-Host 'Ranking              : raw folder volume + exact-file dedupe + named vendor normalization'
    Write-Host 'Named mandatory seed : Tumalo Creek Transportation'
    Write-Host 'AI sample policy     : up to 3 representative docs per cohort vendor; read-only classifier only'
    Write-Host 'Source app/data      : NO APP CHANGE / NO MONGO WRITE / NO RESTART'
    Write-Host 'SharePoint           : READ ONLY'
    Write-Host 'BC                   : NO WRITES'
    Write-Host 'Production           : NOT TOUCHED'

    Require (Test-Path -LiteralPath $KeyPath -PathType Leaf) "SSH key missing: $KeyPath"
    foreach($cmd in 'ssh.exe','scp.exe','ssh-keygen.exe'){Require ($null-ne(Get-Command $cmd -ErrorAction SilentlyContinue)) "$cmd unavailable."}
    $Known=Get-KnownHostsForIp $SourceIp

    $Remote=@'
set -euo pipefail
EXPECTED_IMAGE='sha256:646051f6b0434b20ad429dec18c5f7b2a7d017c0fdec94f4bd77eaa7375fabb3'
EXPECTED_HELPER='2d2298b9c7e6315745d814e5437687caf463a44dec24d73d710b6d9e4e772117'
OUT='/tmp/gpi-ap-top10-result.json'
CSV='/tmp/gpi-ap-top10-ranking.csv'
SAMPLES='/tmp/gpi-ap-top10-ai-samples.json'
rm -f "$OUT" "$CSV" "$SAMPLES"
backend=$(docker ps --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
[ -n "$backend" ] || { echo 'Source backend missing.' >&2; exit 71; }
[ "$(docker inspect "$backend" -f '{{.Image}}')" = "$EXPECTED_IMAGE" ] || { echo 'Source backend image drift.' >&2; exit 72; }
[ "$(docker exec "$backend" sha256sum /app/services/document_intel_helpers.py | awk '{print $1}')" = "$EXPECTED_HELPER" ] || { echo 'Source AI helper drift.' >&2; exit 73; }
health=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=4); print(r.status)')
case "$health" in 2??|3??) ;; *) echo "Source backend unhealthy: $health" >&2; exit 74;; esac
echo "AP_TOP10_SOURCE_HEALTH_BEFORE=$health"
echo AP_TOP10_SOURCE_AUTHORITY=PASS

cat > /tmp/gpi-ap-top10.py <<'PY'
import asyncio, csv, hashlib, json, os, re, sys, types
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path
import httpx

# Run inside the already-live source backend so existing Graph/model credentials remain in place.
from services.sharepoint_service import _get_graph_token
from services.document_intel_helpers import classify_document_with_ai

SITE_HOST='gamerpackaging1.sharepoint.com'
SITE_PATH='/sites/DocsNAV'
DRIVE_NAMES={'Zetadocs','Zetadocs2021','Zetadocs2022','Zetadocs2023'}
MAX_AI_PER_VENDOR=3
MANDATORY_VENDOR='Tumalo Creek Transportation'
CORP_SUFFIX=re.compile(r'\b(incorporated|inc|llc|ltd|limited|corp|corporation|company|co)\b',re.I)


def clean_space(s):
    return re.sub(r'\s+',' ',str(s or '').replace('_',' ')).strip()

def normalize_vendor_key(s):
    x=clean_space(s).lower()
    x=CORP_SUFFIX.sub(' ',x)
    x=re.sub(r'[^a-z0-9]+',' ',x)
    return clean_space(x)

def display_vendor(raw):
    return clean_space(raw)

def logical_name(name):
    stem=Path(name).stem
    stem=re.sub(r'\(\d+\)$','',stem).strip()
    return stem.lower()

def file_hash_key(item):
    f=item.get('file') or {}
    hashes=(f.get('hashes') or {}) if isinstance(f,dict) else {}
    for k in ('sha256Hash','sha1Hash','quickXorHash'):
        if hashes.get(k): return f'{k}:{hashes[k]}'
    return f"fallback:{logical_name(item.get('name',''))}:{item.get('size',0)}"

def normalized_vendor_for_file(folder_vendor,name):
    # Explicit named-seed override: legacy routing sometimes stores Tumalo invoices beneath the related customer/PO vendor folder.
    if re.search(r'(?i)tumalo',name or ''):
        return MANDATORY_VENDOR
    return display_vendor(folder_vendor)

async def paged(client,url,headers):
    out=[]
    while url:
        r=await client.get(url,headers=headers)
        r.raise_for_status()
        data=r.json()
        out.extend(data.get('value',[]))
        url=data.get('@odata.nextLink')
    return out

async def children(client,headers,drive_id,item_id=None):
    base=(f'https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children' if item_id is None else f'https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/children')
    select='id,name,size,file,folder,createdDateTime,lastModifiedDateTime,webUrl,parentReference'
    return await paged(client,base+f'?$top=200&$select={select}',headers)

async def collect_purchase_files(client,headers,drive,folder_id,path_parts,folder_vendor,records):
    q=deque([(folder_id,path_parts)])
    while q:
        item_id,path=q.popleft()
        for item in await children(client,headers,drive['id'],item_id):
            name=item.get('name','')
            if item.get('folder') is not None:
                q.append((item['id'],path+[name]))
                continue
            if item.get('file') is None:
                continue
            normalized_vendor=normalized_vendor_for_file(folder_vendor,name)
            records.append({
                'drive_name':drive['name'],
                'drive_id':drive['id'],
                'item_id':item['id'],
                'name':name,
                'size':item.get('size',0),
                'web_url':item.get('webUrl'),
                'graph_url':f"https://graph.microsoft.com/v1.0/drives/{drive['id']}/items/{item['id']}",
                'created':item.get('createdDateTime'),
                'modified':item.get('lastModifiedDateTime'),
                'folder_vendor':display_vendor(folder_vendor),
                'normalized_vendor':normalized_vendor,
                'path':'/'.join(path+[name]),
                'content_key':file_hash_key(item),
                'logical_name':logical_name(name),
            })

async def inventory_drive(client,headers,drive,records,stats):
    # Generic folder traversal. Once an exact Purchase folder is found, count its descendants and do not descend through it again.
    q=deque([(None,[])])
    folders_seen=0
    purchase_folders=0
    while q:
        item_id,path=q.popleft()
        for item in await children(client,headers,drive['id'],item_id):
            if item.get('folder') is None:
                continue
            name=item.get('name','')
            folders_seen+=1
            newpath=path+[name]
            if name.casefold()=='purchase':
                purchase_folders+=1
                vendor=path[-1] if path else '(unknown)'
                await collect_purchase_files(client,headers,drive,item['id'],newpath,vendor,records)
                continue
            # Sales trees are explicitly out of AP scope; skip them to bound traversal.
            if name.casefold()=='sales':
                continue
            # Keep enough depth for current Zetadocs/GamerDocs/date/vendor/Purchase and yearly date/vendor/Purchase patterns.
            if len(newpath) <= 5:
                q.append((item['id'],newpath))
    stats[drive['name']]={'folders_seen':folders_seen,'purchase_folders':purchase_folders}


def dedupe(records):
    seen=set(); out=[]
    for r in records:
        # Exact-content hash when Graph exposes it; fallback remains scoped by normalized vendor to avoid cross-vendor accidental collapse.
        key=(normalize_vendor_key(r['normalized_vendor']),r['content_key'])
        if key in seen: continue
        seen.add(key); out.append(r)
    return out

def pick_samples(vendor_records):
    if not vendor_records: return []
    rows=sorted(vendor_records,key=lambda r:(r.get('modified') or '',r['name']))
    picks=[]
    idxs=[0,len(rows)//2,len(rows)-1]
    for i in idxs:
        r=rows[i]
        if r['item_id'] not in {x['item_id'] for x in picks}: picks.append(r)
    return picks[:MAX_AI_PER_VENDOR]

def has_token(obj,token):
    token=token.lower()
    if isinstance(obj,dict): return any(has_token(k,token) or has_token(v,token) for k,v in obj.items())
    if isinstance(obj,(list,tuple)): return any(has_token(v,token) for v in obj)
    return token in str(obj).lower()

def extract_field(obj,names):
    if not isinstance(obj,dict): return None
    wanted={n.lower() for n in names}
    for k,v in obj.items():
        if str(k).lower() in wanted and v not in (None,'',[],{}): return v
        if isinstance(v,dict):
            z=extract_field(v,names)
            if z not in (None,'',[],{}): return z
    return None

async def main():
    token=await _get_graph_token()
    headers={'Authorization':f'Bearer {token}'}
    timeout=httpx.Timeout(90.0,connect=20.0)
    async with httpx.AsyncClient(timeout=timeout,follow_redirects=True) as client:
        site=await client.get(f'https://graph.microsoft.com/v1.0/sites/{SITE_HOST}:{SITE_PATH}',headers=headers)
        site.raise_for_status(); site_id=site.json()['id']
        drives=await paged(client,f'https://graph.microsoft.com/v1.0/sites/{site_id}/drives?$top=100&$select=id,name,webUrl',headers)
        drives=[d for d in drives if d.get('name') in DRIVE_NAMES]
        found={d['name'] for d in drives}
        missing=sorted(DRIVE_NAMES-found)
        if missing: raise RuntimeError(f'Missing expected DocsNAV drives: {missing}')
        print('AP_TOP10_DRIVES='+json.dumps(sorted(found)))

        records=[]; stats={}
        for drive in sorted(drives,key=lambda d:d['name']):
            print('AP_TOP10_INVENTORY_DRIVE_START='+drive['name'])
            await inventory_drive(client,headers,drive,records,stats)
            print('AP_TOP10_INVENTORY_DRIVE_DONE='+drive['name']+'|records='+str(sum(1 for r in records if r['drive_name']==drive['name'])))

        raw_records=list(records)
        unique=dedupe(records)
        raw_folder=Counter(display_vendor(r['folder_vendor']) for r in raw_records)
        unique_folder=Counter(display_vendor(r['folder_vendor']) for r in unique)
        unique_norm=Counter(display_vendor(r['normalized_vendor']) for r in unique)
        print(f'AP_TOP10_PURCHASE_FILES_RAW={len(raw_records)}')
        print(f'AP_TOP10_PURCHASE_FILES_DEDUP={len(unique)}')
        print('AP_TOP10_LIBRARY_STATS='+json.dumps(stats,sort_keys=True))

        ranking=[]
        for vendor,count in unique_norm.most_common():
            ranking.append({
                'rank':len(ranking)+1,
                'vendor':vendor,
                'dedup_document_count':count,
                'raw_folder_document_count':raw_folder.get(vendor,0),
                'dedup_folder_document_count':unique_folder.get(vendor,0),
                'named_seed_override_count':sum(1 for r in unique if r['normalized_vendor']==vendor and r['folder_vendor']!=vendor),
            })
        top10=ranking[:10]
        cohort=[x['vendor'] for x in top10]
        if MANDATORY_VENDOR not in cohort:
            cohort.append(MANDATORY_VENDOR)
        print('AP_TOP10_RANKING_JSON='+json.dumps(top10,sort_keys=True))
        print('AP_TOP10_COHORT='+json.dumps(cohort))
        print('AP_TOP10_TUMALO_DEDUP_COUNT='+str(unique_norm.get(MANDATORY_VENDOR,0)))

        # Persist exhaustive inventory before model calls so the ranking evidence survives any later AI failure.
        result={
            'generated_utc':datetime.utcnow().isoformat()+'Z',
            'drives':sorted(found),
            'library_stats':stats,
            'raw_purchase_files':len(raw_records),
            'dedup_purchase_files':len(unique),
            'top10':top10,
            'cohort':cohort,
            'tumalo_dedup_count':unique_norm.get(MANDATORY_VENDOR,0),
            'ranking_method':'Files under exact Purchase folders across Zetadocs + 2021/2022/2023; exact-content hash dedupe when available; Tumalo filename override because legacy routing can store carrier invoices under related customer/vendor folders.',
        }
        Path('/tmp/gpi-ap-top10-result.json').write_text(json.dumps(result,indent=2,sort_keys=True),encoding='utf-8')
        with open('/tmp/gpi-ap-top10-ranking.csv','w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=['rank','vendor','dedup_document_count','raw_folder_document_count','dedup_folder_document_count','named_seed_override_count'])
            w.writeheader(); w.writerows(ranking)

        # Initial AI regression matrix: representative oldest/middle/newest logical docs for each cohort vendor.
        by_vendor=defaultdict(list)
        for r in unique: by_vendor[r['normalized_vendor']].append(r)
        ai_rows=[]
        for vendor in cohort:
            samples=pick_samples(by_vendor.get(vendor,[]))
            if not samples:
                ai_rows.append({'vendor':vendor,'status':'NO_SAMPLE_FOUND'})
                continue
            for idx,s in enumerate(samples,1):
                dl=f"https://graph.microsoft.com/v1.0/drives/{s['drive_id']}/items/{s['item_id']}/content"
                rr=await client.get(dl,headers=headers)
                rr.raise_for_status()
                tmp=f"/tmp/ap-top10-{hashlib.sha1((vendor+s['item_id']).encode()).hexdigest()[:16]}.pdf"
                Path(tmp).write_bytes(rr.content)
                try:
                    ai=await classify_document_with_ai(tmp,s['name'])
                    classification=extract_field(ai,['document_type','classification','doc_type','type'])
                    ai_vendor=extract_field(ai,['vendor_name','vendor','supplier_name','supplier'])
                    row={
                        'vendor_cohort':vendor,
                        'sample_index':idx,
                        'file_name':s['name'],
                        'drive_name':s['drive_name'],
                        'archive_folder_vendor':s['folder_vendor'],
                        'graph_url':s['graph_url'],
                        'modified':s['modified'],
                        'classification':classification,
                        'ai_vendor':ai_vendor,
                        'invoice_number':extract_field(ai,['invoice_number','invoice_no','invoice_num']),
                        'invoice_date':extract_field(ai,['invoice_date']),
                        'amount':extract_field(ai,['amount','invoice_amount','total_amount','total']),
                        'po_number':extract_field(ai,['po_number','purchase_order_number','purchase_order','po_numbers']),
                        'bol_number':extract_field(ai,['bol_number','bill_of_lading','shipment_number']),
                        'cohort_vendor_seen_in_ai':has_token(ai,vendor),
                        'tumalo_invoice_boundary_risk':(vendor==MANDATORY_VENDOR and str(classification or '').lower() not in {'ap_invoice','ap invoice'}),
                        'ai_result':ai,
                        'status':'CLASSIFIED'
                    }
                    ai_rows.append(row)
                    print('AP_TOP10_AI_SAMPLE='+json.dumps({k:row[k] for k in row if k!='ai_result'},sort_keys=True,default=str))
                finally:
                    try: Path(tmp).unlink()
                    except Exception: pass

        Path('/tmp/gpi-ap-top10-ai-samples.json').write_text(json.dumps(ai_rows,indent=2,sort_keys=True,default=str),encoding='utf-8')
        classified=[r for r in ai_rows if r.get('status')=='CLASSIFIED']
        tumalo=[r for r in classified if r.get('vendor_cohort')==MANDATORY_VENDOR]
        tumalo_risk=[r for r in tumalo if r.get('tumalo_invoice_boundary_risk')]
        print('AP_TOP10_AI_SAMPLE_COUNT='+str(len(classified)))
        print('AP_TOP10_TUMALO_AI_SAMPLE_COUNT='+str(len(tumalo)))
        print('AP_TOP10_TUMALO_CLASSIFICATION_RISK_COUNT='+str(len(tumalo_risk)))
        print('AP_TOP10_LEGACY_INVENTORY_AI=PASS')

asyncio.run(main())
PY

docker cp /tmp/gpi-ap-top10.py "$backend:/tmp/gpi-ap-top10.py" >/dev/null
rm -f /tmp/gpi-ap-top10.py
set +e
run_out=$(docker exec -e PYTHONPATH=/app -w /app "$backend" python /tmp/gpi-ap-top10.py 2>&1)
run_code=$?
set -e
printf '%s\n' "$run_out"
docker exec "$backend" rm -f /tmp/gpi-ap-top10.py >/dev/null 2>&1 || true
# Copy result artifacts out even if AI sampling failed after inventory creation.
for f in gpi-ap-top10-result.json gpi-ap-top10-ranking.csv gpi-ap-top10-ai-samples.json; do
  if docker exec "$backend" test -f "/tmp/$f"; then docker cp "$backend:/tmp/$f" "/tmp/$f" >/dev/null; fi
done
[ "$run_code" -eq 0 ] || { echo "AP Top-10 inventory/AI run failed with exit code $run_code" >&2; exit 75; }
printf '%s\n' "$run_out" | grep -Fq 'AP_TOP10_LEGACY_INVENTORY_AI=PASS' || { echo 'AP Top-10 final marker missing.' >&2; exit 76; }
health_after=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=4); print(r.status)')
case "$health_after" in 2??|3??) ;; *) echo "Source backend unhealthy after Top-10 run: $health_after" >&2; exit 77;; esac
echo "AP_TOP10_SOURCE_HEALTH_AFTER=$health_after"
echo AP_TOP10_SOURCE_RUNTIME_UNCHANGED=PASS
'@

    $r=Invoke-SshScript $Known $Remote
    Set-Content -LiteralPath (Join-Path $DiagDir 'source-ap-top10.txt') -Value $r.StdOut -Encoding utf8
    if($r.StdOut){Write-Host $r.StdOut}
    if($r.StdErr){Write-Host $r.StdErr -ForegroundColor DarkYellow}

    # Retrieve whatever evidence artifacts exist before enforcing final success.
    foreach($name in 'gpi-ap-top10-result.json','gpi-ap-top10-ranking.csv','gpi-ap-top10-ai-samples.json'){
        $local=Join-Path $DiagDir $name
        $scp=Invoke-NativeText -FilePath 'scp.exe' -Arguments @('-i',$KeyPath,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',"UserKnownHostsFile=$Known",'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=20',"azureuser@${SourceIp}:/tmp/$name",$local) -AllowFailure
        if($scp.ExitCode-eq0){Write-Host "AP_TOP10_ARTIFACT=$local"}
    }
    [void](Invoke-SshScript $Known "rm -f /tmp/gpi-ap-top10-result.json /tmp/gpi-ap-top10-ranking.csv /tmp/gpi-ap-top10-ai-samples.json`necho AP_TOP10_REMOTE_TEMP_CLEANUP=PASS")

    Require ($r.ExitCode-eq0) "AP Top-10 legacy inventory/AI phase failed with exit code $($r.ExitCode)."
    foreach($m in 'AP_TOP10_SOURCE_AUTHORITY=PASS','AP_TOP10_LEGACY_INVENTORY_AI=PASS','AP_TOP10_SOURCE_RUNTIME_UNCHANGED=PASS'){
        Require ($r.StdOut-match[regex]::Escape($m)) "Missing AP Top-10 marker: $m"
    }

    Section 'AP TOP-10 FINAL RESULT'
    $rank=@($r.StdOut-split"`n"|Where-Object{$_-like'AP_TOP10_RANKING_JSON=*'}|Select-Object -Last 1)
    $cohort=@($r.StdOut-split"`n"|Where-Object{$_-like'AP_TOP10_COHORT=*'}|Select-Object -Last 1)
    $tumalo=@($r.StdOut-split"`n"|Where-Object{$_-like'AP_TOP10_TUMALO_DEDUP_COUNT=*'}|Select-Object -Last 1)
    if($rank){Write-Host $rank[0]}
    if($cohort){Write-Host $cohort[0]}
    if($tumalo){Write-Host $tumalo[0]}
    Write-Host "Diagnostics          : $DiagDir"
    Write-Host 'AP_TOP10_PAYABLE_VENDOR_AI_CORPUS=INITIAL_PASS' -ForegroundColor Green
    Write-Host 'NEXT: inspect vendor-level defects, validate invoice/payment semantics against legacy authority + BC, and create deterministic regression guards before closing issue #19.' -ForegroundColor Yellow
}
finally { try{Stop-Transcript|Out-Null}catch{} }
