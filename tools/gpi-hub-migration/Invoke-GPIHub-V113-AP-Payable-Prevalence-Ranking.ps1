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
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\v113-ap-payable-prevalence\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
Start-Transcript -LiteralPath (Join-Path $DiagDir 'Invoke-GPIHub-V113-AP-Payable-Prevalence-Ranking.txt') -Force | Out-Null

function Require([bool]$Condition,[string]$Message) { if (-not $Condition) { throw $Message } }

function Invoke-NativeText {
    param([string]$FilePath,[string[]]$Arguments,[switch]$AllowFailure)
    $token=[guid]::NewGuid().ToString('N')
    $err=Join-Path $env:TEMP "gpi-v113-$token.err.txt"
    $oldEap=$ErrorActionPreference
    $nativeVar=Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $oldNative=if($null-ne$nativeVar){$nativeVar.Value}else{$null}
    try {
        $ErrorActionPreference='Continue'
        if($null-ne$nativeVar){$PSNativeCommandUseErrorActionPreference=$false}
        $output=& $FilePath @Arguments 2> $err
        $code=$LASTEXITCODE
        $stdout=(@($output)|ForEach-Object{[string]$_}) -join "`n"
        $stderr=if(Test-Path -LiteralPath $err){Get-Content -LiteralPath $err -Raw -ErrorAction SilentlyContinue}else{''}
        $result=[pscustomobject]@{ExitCode=[int]$code;StdOut=$stdout;StdErr=$stderr}
        if(-not$AllowFailure -and $code-ne0){throw "$FilePath failed ($code).`n$stdout`n$stderr"}
        return $result
    }
    finally {
        $ErrorActionPreference=$oldEap
        if($null-ne$nativeVar){$PSNativeCommandUseErrorActionPreference=$oldNative}
        Remove-Item -LiteralPath $err -Force -ErrorAction SilentlyContinue
    }
}

function Get-KnownHosts([string]$Ip) {
    $root=Join-Path $OperationalRoot '.gpi-diagnostics'
    foreach($file in @(Get-ChildItem -LiteralPath $root -Filter '*known_hosts*' -File -Recurse -ErrorAction SilentlyContinue|Sort-Object LastWriteTime -Descending)){
        $probe=Invoke-NativeText 'ssh-keygen.exe' @('-F',$Ip,'-f',$file.FullName) -AllowFailure
        if($probe.ExitCode-eq0 -and -not[string]::IsNullOrWhiteSpace($probe.StdOut)){return $file.FullName}
    }
    throw "No verified known_hosts for $Ip"
}

function Invoke-Ssh([string]$Known,[string]$Text) {
    $token=[guid]::NewGuid().ToString('N')
    $err=Join-Path $env:TEMP "gpi-v113-ssh-$token.err.txt"
    $args=@('-i',$KeyPath,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',"UserKnownHostsFile=$Known",'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=20',"azureuser@$SourceIp",'bash -s')
    $oldEap=$ErrorActionPreference
    $nativeVar=Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $oldNative=if($null-ne$nativeVar){$nativeVar.Value}else{$null}
    try {
        $ErrorActionPreference='Continue'
        if($null-ne$nativeVar){$PSNativeCommandUseErrorActionPreference=$false}
        $output=(($Text-replace"`r`n","`n")|& ssh.exe @args 2>$err)
        $code=$LASTEXITCODE
        $stdout=(@($output)|ForEach-Object{[string]$_}) -join "`n"
        $stderr=if(Test-Path -LiteralPath $err){Get-Content -LiteralPath $err -Raw -ErrorAction SilentlyContinue}else{''}
        return [pscustomobject]@{ExitCode=[int]$code;StdOut=$stdout;StdErr=$stderr}
    }
    finally {
        $ErrorActionPreference=$oldEap
        if($null-ne$nativeVar){$PSNativeCommandUseErrorActionPreference=$oldNative}
        Remove-Item -LiteralPath $err -Force -ErrorAction SilentlyContinue
    }
}

function Section([string]$Title){Write-Host '';Write-Host('='*120)-ForegroundColor Cyan;Write-Host $Title -ForegroundColor Cyan;Write-Host('='*120)-ForegroundColor Cyan}

try {
    Section 'V113 - AP PAYABLE PREVALENCE RANKING'
    Write-Host 'Classification       : PARITY BLOCKER REFINEMENT'
    Write-Host 'Purpose              : convert Purchase-folder activity ranking into AP_Invoice-weighted payable ranking'
    Write-Host 'Candidates           : TOP 30 BY DEDUP PURCHASE VOLUME FROM REV3'
    Write-Host 'Initial sampling     : 8 STRATIFIED DOCS / VENDOR'
    Write-Host 'Deepening            : +12 DOCS FOR RANK-BOUNDARY OVERLAP VENDORS'
    Write-Host 'Inventory            : 4 DRIVES ENUMERATED CONCURRENTLY; ONLY TOP-30 RECORDS RETAINED'
    Write-Host 'AI concurrency       : 3'
    Write-Host 'Source app/data      : NO APP CHANGE / NO MONGO WRITE / NO RESTART'
    Write-Host 'SharePoint           : READ ONLY'
    Write-Host 'BC                   : NO WRITES'
    Write-Host 'Production           : NOT TOUCHED'

    $rankingFile = Get-ChildItem -LiteralPath (Join-Path $OperationalRoot '.gpi-diagnostics\ap-top10-rev3-delta') -Filter 'gpi-ap-top10-rev3-ranking.csv' -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    Require ($null-ne$rankingFile) 'No REV3 ranking artifact found. Run AP Top-10 REV3 first.'
    $ranking=@(Import-Csv -LiteralPath $rankingFile.FullName)
    Require ($ranking.Count-ge 30) "REV3 ranking artifact has only $($ranking.Count) vendors; expected >=30."
    $top30=@($ranking|Sort-Object {[int]$_.rank}|Select-Object -First 30)
    $candidateJson=Join-Path $DiagDir 'v113-candidates.json'
    $top30|Select-Object rank,vendor,dedup_document_count|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $candidateJson -Encoding utf8
    Write-Host "V113_RANKING_SOURCE=$($rankingFile.FullName)"
    Write-Host 'V113_TOP30_CANDIDATES=PASS' -ForegroundColor Green

    foreach($cmd in 'ssh.exe','scp.exe','ssh-keygen.exe'){Require($null-ne(Get-Command $cmd -ErrorAction SilentlyContinue))"$cmd unavailable"}
    $Known=Get-KnownHosts $SourceIp
    $scp=Invoke-NativeText 'scp.exe' @('-i',$KeyPath,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',"UserKnownHostsFile=$Known",'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=20',$candidateJson,"azureuser@${SourceIp}:/tmp/v113-candidates.json")
    Require($scp.ExitCode-eq0)'V113 candidate staging failed.'

    $Remote=@'
set -euo pipefail
EXPECTED_IMAGE='sha256:646051f6b0434b20ad429dec18c5f7b2a7d017c0fdec94f4bd77eaa7375fabb3'
EXPECTED_HELPER='2d2298b9c7e6315745d814e5437687caf463a44dec24d73d710b6d9e4e772117'
backend=$(docker ps --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}'|head -n1)
[ -n "$backend" ] || { echo 'Source backend missing.' >&2; exit 71; }
[ "$(docker inspect "$backend" -f '{{.Image}}')" = "$EXPECTED_IMAGE" ] || { echo 'Source image drift.' >&2; exit 72; }
[ "$(docker exec "$backend" sha256sum /app/services/document_intel_helpers.py|awk '{print $1}')" = "$EXPECTED_HELPER" ] || { echo 'Source helper drift.' >&2; exit 73; }
health=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=4); print(r.status)')
case "$health" in 2??|3??);;*)echo "Source unhealthy: $health" >&2;exit 74;;esac
echo V113_SOURCE_AUTHORITY=PASS

docker cp /tmp/v113-candidates.json "$backend:/tmp/v113-candidates.json" >/dev/null
rm -f /tmp/v113-candidates.json
cat > /tmp/v113.py <<'PY'
import asyncio, gzip, hashlib, json, math, os, re, tempfile, time
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote
import httpx
from services.sharepoint_service import _get_graph_token
from services.document_intel_helpers import classify_document_with_ai

SITE_HOST='gamerpackaging1.sharepoint.com'; SITE_PATH='/sites/DocsNAV'
DRIVE_NAMES={'Zetadocs','Zetadocs2021','Zetadocs2022','Zetadocs2023'}
INITIAL_N=8; DEEP_N=12; AI_CONCURRENCY=3
CORP_SUFFIX=re.compile(r'\b(incorporated|inc|llc|ltd|limited|corp|corporation|company|co)\b',re.I)

def clean(s): return re.sub(r'\s+',' ',str(s or '').replace('_',' ')).strip()
def key(s):
    x=CORP_SUFFIX.sub(' ',clean(s).lower()); x=re.sub(r'[^a-z0-9]+',' ',x); return clean(x)
def purchase_vendor(parent):
    parts=[p for p in unquote(str(parent or '')).replace('\\','/').split('/') if p]
    lower=[p.casefold() for p in parts]
    idxs=[i for i,p in enumerate(lower) if p=='purchase']
    if not idxs:return None
    i=idxs[-1]; return parts[i-1] if i>0 else None
def logical_name(name): return re.sub(r'\(\d+\)$','',Path(name).stem).strip().lower()
def hash_key(item):
    hashes=((item.get('file') or {}).get('hashes') or {})
    for n in ('sha256Hash','sha1Hash','quickXorHash'):
        if hashes.get(n):return f'{n}:{hashes[n]}'
    return f"fallback:{logical_name(item.get('name',''))}:{item.get('size',0)}"
def normalize_vendor(folder,name):
    if re.search(r'(?i)tumalo',name or ''): return 'Tumalo Creek Transportation'
    return clean(folder)
def wilson(kv,n,z=1.96):
    if n<=0:return (0.0,1.0)
    p=kv/n; den=1+z*z/n; center=(p+z*z/(2*n))/den; margin=z*math.sqrt((p*(1-p)+z*z/(4*n))/n)/den
    return (max(0,center-margin),min(1,center+margin))
def stratified(rows,n,exclude=None):
    exclude=set(exclude or [])
    rows=sorted(rows,key=lambda r:(r.get('modified') or '',r['name'],r['item_id']))
    avail=[r for r in rows if r['item_id'] not in exclude]
    if len(avail)<=n:return avail
    out=[]
    for i in range(n):
        pos=round(i*(len(avail)-1)/(n-1)) if n>1 else len(avail)//2
        r=avail[pos]
        if r['item_id'] not in {x['item_id'] for x in out}:out.append(r)
    if len(out)<n:
        for r in avail:
            if r['item_id'] not in {x['item_id'] for x in out}:out.append(r)
            if len(out)>=n:break
    return out[:n]

async def get(client,url,headers,label):
    try:
        r=await client.get(url,headers=headers);r.raise_for_status();return r
    except Exception as e:
        print(f'V113_GRAPH_ERROR|{label}|{type(e).__name__}:{e}',flush=True);raise

async def enumerate_drive(client,headers,drive,wanted):
    url=f"https://graph.microsoft.com/v1.0/drives/{drive['id']}/root/delta?$top=200"
    page=0;scanned=0;kept=[];start=time.monotonic()
    while url:
        page+=1;data=(await get(client,url,headers,f"{drive['name']}:{page}")).json();items=data.get('value',[]);scanned+=len(items)
        for item in items:
            if item.get('file') is None or item.get('deleted') is not None:continue
            folder=purchase_vendor((item.get('parentReference') or {}).get('path',''))
            if not folder:continue
            vendor=normalize_vendor(folder,item.get('name',''))
            if key(vendor) not in wanted:continue
            kept.append({'drive':drive['name'],'drive_id':drive['id'],'item_id':item['id'],'name':item.get('name',''),'modified':item.get('lastModifiedDateTime'),'vendor':vendor,'vendor_key':key(vendor),'content_key':hash_key(item)})
        if page%25==0:
            print(f"V113_SCAN_HEARTBEAT|drive={drive['name']}|page={page}|scanned={scanned}|kept={len(kept)}|elapsed={time.monotonic()-start:.0f}",flush=True)
        url=data.get('@odata.nextLink')
    print(f"V113_SCAN_DONE|drive={drive['name']}|pages={page}|scanned={scanned}|kept={len(kept)}|elapsed={time.monotonic()-start:.0f}",flush=True)
    return kept

async def main():
    candidates=json.loads(Path('/tmp/v113-candidates.json').read_text())
    cand={key(x['vendor']):{'rank':int(x['rank']),'vendor':x['vendor'],'volume':int(x['dedup_document_count'])} for x in candidates}
    wanted=set(cand)
    token=await _get_graph_token();headers={'Authorization':f'Bearer {token}'}
    timeout=httpx.Timeout(90.0,connect=20.0,read=90.0,write=90.0,pool=20.0)
    async with httpx.AsyncClient(timeout=timeout,follow_redirects=True) as client:
        site=(await get(client,f'https://graph.microsoft.com/v1.0/sites/{SITE_HOST}:{SITE_PATH}',headers,'site')).json();site_id=site['id']
        drives=(await get(client,f'https://graph.microsoft.com/v1.0/sites/{site_id}/drives?$top=100&$select=id,name',headers,'drives')).json().get('value',[])
        drives=[d for d in drives if d.get('name') in DRIVE_NAMES]
        if {d['name'] for d in drives}!=DRIVE_NAMES:raise RuntimeError('Expected DocsNAV drives missing')
        results=await asyncio.gather(*(enumerate_drive(client,headers,d,wanted) for d in drives))
        rows=[r for group in results for r in group]
        seen=set();unique=[]
        for r in rows:
            k=(r['vendor_key'],r['content_key'])
            if k in seen:continue
            seen.add(k);unique.append(r)
        by=defaultdict(list)
        for r in unique:by[r['vendor_key']].append(r)
        print(f'V113_RETAINED_RAW={len(rows)}',flush=True);print(f'V113_RETAINED_DEDUP={len(unique)}',flush=True)

        # Cache compact authority for future sampling without another full Graph enumeration.
        cache='/tmp/v113-top30-inventory.jsonl.gz'
        with gzip.open(cache,'wt',encoding='utf-8') as f:
            for r in unique:f.write(json.dumps(r,separators=(',',':'))+'\n')

        sem=asyncio.Semaphore(AI_CONCURRENCY); sample_rows=[]
        async def classify_one(vk,r,stage,index,total):
            async with sem:
                label=f"{stage}:{cand[vk]['vendor']}:{index}/{total}";start=time.monotonic();print(f'V113_AI_START|{label}|{r["name"]}',flush=True)
                url=f"https://graph.microsoft.com/v1.0/drives/{r['drive_id']}/items/{r['item_id']}/content"
                try:
                    rr=await get(client,url,headers,label);suffix=Path(r['name']).suffix or '.bin';fd,path=tempfile.mkstemp(suffix=suffix);os.close(fd);Path(path).write_bytes(rr.content)
                    try:
                        ai=await asyncio.wait_for(classify_document_with_ai(path,r['name']),timeout=180)
                    finally:
                        try:os.remove(path)
                        except Exception:pass
                    cls=(ai or {}).get('suggested_job_type') if isinstance(ai,dict) else None
                    status='OK'
                except Exception as e:
                    ai={'error':f'{type(e).__name__}:{e}'};cls=None;status='ERROR'
                out={'vendor':cand[vk]['vendor'],'vendor_key':vk,'item_id':r['item_id'],'name':r['name'],'modified':r['modified'],'stage':stage,'classification':cls,'is_ap_invoice':cls=='AP_Invoice','status':status,'elapsed_sec':round(time.monotonic()-start,1),'ai':ai}
                print('V113_AI_DONE='+json.dumps({k:v for k,v in out.items() if k!='ai'},sort_keys=True,default=str),flush=True);return out

        async def run_stage(vkeys,n,stage,exclude_map=None):
            tasks=[]
            for vk in vkeys:
                picks=stratified(by.get(vk,[]),n,(exclude_map or {}).get(vk,set()))
                for i,r in enumerate(picks,1):tasks.append(classify_one(vk,r,stage,i,len(picks)))
            if not tasks:return []
            return await asyncio.gather(*tasks)

        initial=await run_stage(list(cand),INITIAL_N,'initial');sample_rows.extend(initial)
        def summarize(rows_for):
            out=[]
            for vk,meta in cand.items():
                rs=[r for r in rows_for if r['vendor_key']==vk];ok=[r for r in rs if r['status']=='OK'];k_ap=sum(1 for r in ok if r['is_ap_invoice']);n=len(ok);lo,hi=wilson(k_ap,n);rate=(k_ap/n if n else 0)
                out.append({'raw_rank':meta['rank'],'vendor':meta['vendor'],'purchase_volume':meta['volume'],'sample_n':n,'sample_errors':len(rs)-n,'ap_invoice_hits':k_ap,'ap_rate':rate,'ap_rate_low95':lo,'ap_rate_high95':hi,'estimated_ap_docs':round(meta['volume']*rate),'estimated_ap_low95':round(meta['volume']*lo),'estimated_ap_high95':round(meta['volume']*hi)})
            return sorted(out,key=lambda x:(-x['estimated_ap_docs'],x['raw_rank']))
        s1=summarize(sample_rows);rank10=s1[9] if len(s1)>=10 else s1[-1]
        boundary_candidates=[x for x in s1 if x['estimated_ap_high95']>=rank10['estimated_ap_low95']]
        boundary_keys={key(x['vendor']) for x in boundary_candidates}
        print('V113_INITIAL_RANKING='+json.dumps(s1,sort_keys=True),flush=True)
        print('V113_BOUNDARY_CANDIDATES='+json.dumps([x['vendor'] for x in boundary_candidates]),flush=True)

        exclude=defaultdict(set)
        for r in sample_rows:exclude[r['vendor_key']].add(r['item_id'])
        deep=await run_stage(sorted(boundary_keys),DEEP_N,'deep',exclude);sample_rows.extend(deep)
        final=summarize(sample_rows)
        rank10=final[9] if len(final)>=10 else final[-1]
        outsiders=[x for x in final[10:] if x['estimated_ap_high95']>=rank10['estimated_ap_low95']]
        disposition='RESOLVED' if not outsiders else 'UNRESOLVED_OVERLAPPING_CONFIDENCE'
        print('V113_FINAL_RANKING='+json.dumps(final,sort_keys=True),flush=True)
        print('V113_PAYABLE_TOP10='+json.dumps(final[:10],sort_keys=True),flush=True)
        print('V113_RANKING_BOUNDARY='+disposition,flush=True)
        Path('/tmp/v113-result.json').write_text(json.dumps({'method':'AI prevalence weighted against REV3 dedup Purchase volume','initial_n':INITIAL_N,'deep_n':DEEP_N,'final_ranking':final,'top10':final[:10],'boundary_disposition':disposition},indent=2,sort_keys=True),encoding='utf-8')
        Path('/tmp/v113-ai-samples.json').write_text(json.dumps(sample_rows,indent=2,sort_keys=True,default=str),encoding='utf-8')
        print('V113_AP_PAYABLE_PREVALENCE=PASS',flush=True)

asyncio.run(main())
PY

docker cp /tmp/v113.py "$backend:/tmp/v113.py" >/dev/null
rm -f /tmp/v113.py
set +e
out=$(docker exec -e PYTHONPATH=/app -w /app "$backend" python /tmp/v113.py 2>&1);code=$?
set -e
printf '%s\n' "$out"
for f in v113-result.json v113-ai-samples.json v113-top30-inventory.jsonl.gz;do if docker exec "$backend" test -f "/tmp/$f";then docker cp "$backend:/tmp/$f" "/tmp/$f" >/dev/null;fi;done
docker exec "$backend" rm -f /tmp/v113.py /tmp/v113-candidates.json /tmp/v113-result.json /tmp/v113-ai-samples.json /tmp/v113-top30-inventory.jsonl.gz >/dev/null 2>&1 || true
[ "$code" -eq 0 ] || { echo "V113 failed: $code" >&2;exit 75; }
printf '%s\n' "$out"|grep -Fq 'V113_AP_PAYABLE_PREVALENCE=PASS' || { echo 'V113 final marker missing.' >&2;exit 76; }
health_after=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=4); print(r.status)');case "$health_after" in 2??|3??);;*)exit 77;;esac
echo V113_SOURCE_RUNTIME_UNCHANGED=PASS
'@

    $r=Invoke-Ssh $Known $Remote
    Set-Content -LiteralPath (Join-Path $DiagDir 'source-v113.txt') -Value $r.StdOut -Encoding utf8
    if($r.StdOut){Write-Host $r.StdOut}
    if($r.StdErr){Write-Host $r.StdErr -ForegroundColor DarkYellow}

    foreach($name in 'v113-result.json','v113-ai-samples.json','v113-top30-inventory.jsonl.gz'){
        $get=Invoke-NativeText 'scp.exe' @('-i',$KeyPath,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',"UserKnownHostsFile=$Known",'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=20',"azureuser@${SourceIp}:/tmp/$name",(Join-Path $DiagDir $name)) -AllowFailure
        if($get.ExitCode-eq0){Write-Host "V113_ARTIFACT=$(Join-Path $DiagDir $name)"}
    }
    [void](Invoke-Ssh $Known "rm -f /tmp/v113-result.json /tmp/v113-ai-samples.json /tmp/v113-top30-inventory.jsonl.gz`necho V113_REMOTE_TEMP_CLEANUP=PASS")

    Require($r.ExitCode-eq0)"V113 failed with exit code $($r.ExitCode)."
    foreach($m in 'V113_SOURCE_AUTHORITY=PASS','V113_AP_PAYABLE_PREVALENCE=PASS','V113_SOURCE_RUNTIME_UNCHANGED=PASS'){Require($r.StdOut-match[regex]::Escape($m))"Missing V113 marker: $m"}
    Section 'V113 RESULT'
    $top=@($r.StdOut-split"`n"|Where-Object{$_-like'V113_PAYABLE_TOP10=*'}|Select-Object -Last 1);if($top){Write-Host $top[0]}
    $boundary=@($r.StdOut-split"`n"|Where-Object{$_-like'V113_RANKING_BOUNDARY=*'}|Select-Object -Last 1);if($boundary){Write-Host $boundary[0]}
    Write-Host 'V113_AP_PAYABLE_PREVALENCE_RANKING=PASS' -ForegroundColor Green
    Write-Host "Diagnostics: $DiagDir"
}
finally { try{Stop-Transcript|Out-Null}catch{} }
