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
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\v114-accounting-temp-golden-route-audit\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
Start-Transcript -LiteralPath (Join-Path $DiagDir 'Invoke-GPIHub-V114-Accounting-Temp-Golden-Route-Audit.txt') -Force | Out-Null

function Require([bool]$Condition,[string]$Message) { if (-not $Condition) { throw $Message } }

function Invoke-NativeText {
    param([string]$FilePath,[string[]]$Arguments,[switch]$AllowFailure)
    $token=[guid]::NewGuid().ToString('N');$err=Join-Path $env:TEMP "gpi-v114-$token.err.txt"
    $oldEap=$ErrorActionPreference;$nativeVar=Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue;$oldNative=if($null-ne$nativeVar){$nativeVar.Value}else{$null}
    try {
        $ErrorActionPreference='Continue';if($null-ne$nativeVar){$PSNativeCommandUseErrorActionPreference=$false}
        $output=& $FilePath @Arguments 2>$err;$code=$LASTEXITCODE;$stdout=(@($output)|ForEach-Object{[string]$_})-join"`n";$stderr=if(Test-Path -LiteralPath $err){Get-Content -LiteralPath $err -Raw -ErrorAction SilentlyContinue}else{''}
        $result=[pscustomobject]@{ExitCode=[int]$code;StdOut=$stdout;StdErr=$stderr};if(-not$AllowFailure -and $code-ne0){throw "$FilePath failed ($code).`n$stdout`n$stderr"};return $result
    }
    finally {$ErrorActionPreference=$oldEap;if($null-ne$nativeVar){$PSNativeCommandUseErrorActionPreference=$oldNative};Remove-Item -LiteralPath $err -Force -ErrorAction SilentlyContinue}
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
    $token=[guid]::NewGuid().ToString('N');$err=Join-Path $env:TEMP "gpi-v114-ssh-$token.err.txt"
    $args=@('-i',$KeyPath,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',"UserKnownHostsFile=$Known",'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=20',"azureuser@$SourceIp",'bash -s')
    $oldEap=$ErrorActionPreference;$nativeVar=Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue;$oldNative=if($null-ne$nativeVar){$nativeVar.Value}else{$null}
    try {
        $ErrorActionPreference='Continue';if($null-ne$nativeVar){$PSNativeCommandUseErrorActionPreference=$false}
        $output=(($Text-replace"`r`n","`n")|& ssh.exe @args 2>$err);$code=$LASTEXITCODE;$stdout=(@($output)|ForEach-Object{[string]$_})-join"`n";$stderr=if(Test-Path -LiteralPath $err){Get-Content -LiteralPath $err -Raw -ErrorAction SilentlyContinue}else{''};return [pscustomobject]@{ExitCode=[int]$code;StdOut=$stdout;StdErr=$stderr}
    }
    finally {$ErrorActionPreference=$oldEap;if($null-ne$nativeVar){$PSNativeCommandUseErrorActionPreference=$oldNative};Remove-Item -LiteralPath $err -Force -ErrorAction SilentlyContinue}
}

function Section([string]$Title){Write-Host '';Write-Host('='*120)-ForegroundColor Cyan;Write-Host $Title -ForegroundColor Cyan;Write-Host('='*120)-ForegroundColor Cyan}

try {
    Section 'V114 - ACCOUNTING TEMP GOLDEN ROUTE AUDIT'
    Write-Host 'Classification       : PARITY BLOCKER EVIDENCE'
    Write-Host 'Routing authority    : LIVE GamerAccounting AP Temp Folder (READ ONLY)'
    Write-Host 'Legacy NAV/Zetadocs  : NOT USED AS ROUTE LABEL AUTHORITY'
    Write-Host 'Golden pair          : SAME CARRIER / DIFFERENT CORRECT TEMP QUEUES'
    Write-Host 'BC context           : EXISTING PO RESOLUTION SERVICE / READ ONLY'
    Write-Host 'Source app/Mongo     : NO APP CHANGE / NO MONGO WRITE / NO RESTART'
    Write-Host 'SharePoint           : PRODUCTION READS ONLY / NO WRITES'
    Write-Host 'BC                   : READ ONLY'
    Write-Host 'Production mutation  : NONE'

    foreach($cmd in 'ssh.exe','scp.exe','ssh-keygen.exe'){Require($null-ne(Get-Command $cmd -ErrorAction SilentlyContinue))"$cmd unavailable"}
    Require(Test-Path -LiteralPath $KeyPath -PathType Leaf)"SSH key missing: $KeyPath"
    $Known=Get-KnownHosts $SourceIp

    $Remote=@'
set -euo pipefail
EXPECTED_IMAGE='sha256:646051f6b0434b20ad429dec18c5f7b2a7d017c0fdec94f4bd77eaa7375fabb3'
backend=$(docker ps --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}'|head -n1)
[ -n "$backend" ] || { echo 'Source backend missing.' >&2; exit 71; }
[ "$(docker inspect "$backend" -f '{{.Image}}')" = "$EXPECTED_IMAGE" ] || { echo 'Source image drift.' >&2; exit 72; }
host_router='/data/apps/gpi-hub/backend/services/folder_routing_service.py'
container_router='/app/services/folder_routing_service.py'
[ -f "$host_router" ] || { echo 'Source host router missing.' >&2; exit 73; }
host_sha=$(sha256sum "$host_router"|awk '{print $1}')
container_sha=$(docker exec "$backend" sha256sum "$container_router"|awk '{print $1}')
[ "$host_sha" = "$container_sha" ] || { echo "Router host/container drift: $host_sha != $container_sha" >&2; exit 74; }
health=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=4); print(r.status)')
case "$health" in 2??|3??);;*)echo "Source unhealthy: $health" >&2;exit 75;;esac
echo "V114_ROUTER_SHA=$container_sha"
echo V114_SOURCE_AUTHORITY=PASS

cat > /tmp/v114.py <<'PY'
import asyncio, json, os, tempfile, time
from pathlib import Path
from urllib.parse import quote, unquote
import httpx
from services.sharepoint_service import _get_graph_token
from services.document_intel_helpers import classify_document_with_ai
from services.po_resolution_service import resolve_po_from_document
from services.folder_routing_service import determine_ap_routing_decision, FOLDER_STRUCTURE

HOST='gamerpackaging1.sharepoint.com'
SITE_PATH='/sites/GamerAccounting'
DRIVE_NAME='Documents'
BASE='General/Accounting/Accounts Payable/Temp Folder'
CASES=[
  {
    'id':'tumalo_warehouse',
    'path':BASE+'/Warehouse Not International/_TUMALO_0311997_08282026.pdf',
    'gold_route':'Warehouse Not International',
    'expected_class':'AP_Invoice',
    'authority_note':'live Accounting Temp placement; invoice 0311997 / Gamer PO 113785-113786'
  },
  {
    'id':'tumalo_dropship_freight',
    'path':BASE+'/Dropship Not International/Freight/110784A_TUMALO_0312676_08262026.pdf',
    'gold_route':'Dropship Not International/Freight',
    'expected_class':'AP_Invoice',
    'authority_note':'live Accounting Temp placement; invoice 0312676 / BOL 110784A PU 3610281'
  },
]

async def get(client,url,headers,label):
    r=await client.get(url,headers=headers);r.raise_for_status();return r

def flatten_metadata():
    out=set()
    for spec in FOLDER_STRUCTURE.values():
        root=str(spec.get('path') or '').strip('/')
        if root: out.add(root)
        subs=spec.get('subfolders')
        if isinstance(subs,dict):
            for sub in subs: out.add((root+'/'+str(sub).strip('/')).strip('/'))
    return sorted(out)

async def list_tree(client,headers,drive_id):
    folders=set(); files=[]
    async def walk(item_id,rel,depth):
        if depth>4:return
        url=f'https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/children?$top=200'
        while url:
            data=(await get(client,url,headers,'tree')).json()
            for item in data.get('value',[]):
                name=item.get('name',''); child=(rel+'/'+name).strip('/')
                if item.get('folder') is not None:
                    folders.add(child); await walk(item['id'],child,depth+1)
                elif item.get('file') is not None:
                    files.append({'path':child,'id':item['id'],'name':name})
            url=data.get('@odata.nextLink')
    root_url=f'https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{quote(BASE,safe="/")}'
    root=(await get(client,root_url,headers,'base')).json()
    await walk(root['id'],'',0)
    return folders,files

def make_doc(ai,name):
    ai=ai or {}; extracted=dict(ai.get('extracted_fields') or {})
    doc={
      'id':'v114-'+name,
      'file_name':name,
      'document_type':ai.get('suggested_job_type') or ai.get('document_type') or '',
      'suggested_job_type':ai.get('suggested_job_type') or ai.get('document_type') or '',
      'extracted_fields':extracted,
    }
    for k in ('vendor','vendor_name','carrier','shipper','po_number','bol_number','order_number','invoice_number','invoice_description','description','is_international','freight_direction'):
        if extracted.get(k) not in (None,''):
            doc[k]=extracted.get(k)
    if not doc.get('vendor_name'):
        doc['vendor_name']=extracted.get('vendor') or extracted.get('carrier') or extracted.get('shipper') or ''
    return doc

async def main():
    token=await _get_graph_token();headers={'Authorization':f'Bearer {token}'}
    timeout=httpx.Timeout(90.0,connect=20.0,read=90.0,write=90.0,pool=20.0)
    async with httpx.AsyncClient(timeout=timeout,follow_redirects=True) as client:
        site=(await get(client,f'https://graph.microsoft.com/v1.0/sites/{HOST}:{SITE_PATH}',headers,'site')).json();site_id=site['id']
        drives=(await get(client,f'https://graph.microsoft.com/v1.0/sites/{site_id}/drives?$top=100&$select=id,name',headers,'drives')).json().get('value',[])
        drive=next((d for d in drives if d.get('name')==DRIVE_NAME),None)
        if not drive: raise RuntimeError('GamerAccounting Documents drive not found')
        folders,files=await list_tree(client,headers,drive['id'])
        print(f'V114_LIVE_FOLDER_COUNT={len(folders)}',flush=True)
        print(f'V114_LIVE_FILE_COUNT={len(files)}',flush=True)
        metadata=flatten_metadata();missing_meta=[p for p in metadata if p not in folders]
        print('V114_ROUTER_METADATA_MISSING_PATHS='+json.dumps(missing_meta,sort_keys=True),flush=True)

        rows=[]
        for i,case in enumerate(CASES,1):
            print(f"V114_GOLDEN_START|{i}/{len(CASES)}|{case['id']}",flush=True)
            url=f"https://graph.microsoft.com/v1.0/drives/{drive['id']}/root:/{quote(case['path'],safe='/')}:/content"
            r=await get(client,url,headers,case['id']);suffix=Path(case['path']).suffix or '.pdf';fd,path=tempfile.mkstemp(suffix=suffix);os.close(fd);Path(path).write_bytes(r.content)
            try:
                ai=await asyncio.wait_for(classify_document_with_ai(path,Path(case['path']).name),timeout=180)
                doc=make_doc(ai,Path(case['path']).name)
                # Resolve extracted/file-name references against BC read-only before routing.
                resolution=await resolve_po_from_document(doc)
                status=resolution.get('status') or ''
                doc['po_resolution']=resolution
                doc['bc_po_resolved']=status in {'resolved','resolved_shipment'}
                if resolution.get('po_number'): doc['po_number_extracted']=resolution.get('po_number')
                if resolution.get('bc_entity_type'): doc['bc_entity_type']=resolution.get('bc_entity_type')
                if resolution.get('bc_order_number'): doc['bc_order_number']=resolution.get('bc_order_number')
                extracted=doc.get('extracted_fields') or {}
                freight_direction=extracted.get('freight_direction') or doc.get('freight_direction')
                is_int=bool(extracted.get('is_international') or doc.get('is_international'))
                route=determine_ap_routing_decision(doc,freight_direction=freight_direction,is_international=is_int)
                row={
                  'case':case['id'],'file':Path(case['path']).name,
                  'expected_class':case['expected_class'],'classification':doc.get('document_type'),
                  'classification_match':doc.get('document_type')==case['expected_class'],
                  'gold_route':case['gold_route'],'predicted_route':route.get('folder_path'),
                  'route_match':route.get('folder_path')==case['gold_route'],
                  'routing_status':route.get('routing_status'),'routing_reason':route.get('routing_reason'),
                  'bc_resolution_status':status,'bc_po_number':resolution.get('po_number'),
                  'bc_entity_type':resolution.get('bc_entity_type'),'bc_order_number':resolution.get('bc_order_number'),
                  'bc_lookup_source':resolution.get('lookup_source'),'bc_match_method':resolution.get('match_method'),
                  'authority_note':case['authority_note'],
                  'extracted_fields':extracted,
                }
                rows.append(row);print('V114_GOLDEN_ROW='+json.dumps(row,sort_keys=True,default=str),flush=True)
            finally:
                try:os.remove(path)
                except Exception:pass
        defects=[r for r in rows if not r['classification_match'] or not r['route_match']]
        route_defects=[r for r in rows if not r['route_match']]
        class_defects=[r for r in rows if not r['classification_match']]
        print(f'V114_CLASSIFICATION_DEFECTS={len(class_defects)}',flush=True)
        print(f'V114_ROUTE_DEFECTS={len(route_defects)}',flush=True)
        print('V114_GOLDEN_DISPOSITION='+('PASS' if not defects else 'PARITY_BLOCKER_PROVEN'),flush=True)
        result={'schema_version':'1.0','authority':'live GamerAccounting AP Temp Folder read-only','live_folders':sorted(folders),'router_metadata_paths':metadata,'router_metadata_missing_paths':missing_meta,'golden_rows':rows,'classification_defects':len(class_defects),'route_defects':len(route_defects),'disposition':'PASS' if not defects else 'PARITY_BLOCKER_PROVEN'}
        Path('/tmp/v114-result.json').write_text(json.dumps(result,indent=2,sort_keys=True,default=str),encoding='utf-8')
        print('V114_ACCOUNTING_TEMP_GOLDEN_ROUTE_AUDIT=PASS',flush=True)

asyncio.run(main())
PY

docker cp /tmp/v114.py "$backend:/tmp/v114.py" >/dev/null
rm -f /tmp/v114.py
set +e
out=$(docker exec -e PYTHONPATH=/app -w /app "$backend" python /tmp/v114.py 2>&1);code=$?
set -e
printf '%s\n' "$out"
if docker exec "$backend" test -f /tmp/v114-result.json;then docker cp "$backend:/tmp/v114-result.json" /tmp/v114-result.json >/dev/null;fi
docker exec "$backend" rm -f /tmp/v114.py /tmp/v114-result.json >/dev/null 2>&1 || true
[ "$code" -eq 0 ] || { echo "V114 probe failed: $code" >&2;exit 76; }
printf '%s\n' "$out"|grep -Fq 'V114_ACCOUNTING_TEMP_GOLDEN_ROUTE_AUDIT=PASS' || { echo 'V114 final marker missing.' >&2;exit 77; }
health_after=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=4); print(r.status)');case "$health_after" in 2??|3??);;*)exit 78;;esac
echo V114_SOURCE_RUNTIME_UNCHANGED=PASS
'@

    $r=Invoke-Ssh $Known $Remote
    Set-Content -LiteralPath (Join-Path $DiagDir 'source-v114.txt') -Value $r.StdOut -Encoding utf8
    if($r.StdOut){Write-Host $r.StdOut};if($r.StdErr){Write-Host $r.StdErr -ForegroundColor DarkYellow}
    $get=Invoke-NativeText 'scp.exe' @('-i',$KeyPath,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',"UserKnownHostsFile=$Known",'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=20',"azureuser@${SourceIp}:/tmp/v114-result.json",(Join-Path $DiagDir 'v114-result.json')) -AllowFailure
    if($get.ExitCode-eq0){Write-Host "V114_ARTIFACT=$(Join-Path $DiagDir 'v114-result.json')"}
    [void](Invoke-Ssh $Known "rm -f /tmp/v114-result.json`necho V114_REMOTE_TEMP_CLEANUP=PASS")

    Require($r.ExitCode-eq0)"V114 failed with exit code $($r.ExitCode)."
    foreach($m in 'V114_SOURCE_AUTHORITY=PASS','V114_ACCOUNTING_TEMP_GOLDEN_ROUTE_AUDIT=PASS','V114_SOURCE_RUNTIME_UNCHANGED=PASS'){Require($r.StdOut-match[regex]::Escape($m))"Missing V114 marker: $m"}
    Section 'V114 RESULT'
    $disp=@($r.StdOut-split"`n"|Where-Object{$_-like'V114_GOLDEN_DISPOSITION=*'}|Select-Object -Last 1);if($disp){Write-Host $disp[0]}
    $routes=@($r.StdOut-split"`n"|Where-Object{$_-like'V114_ROUTE_DEFECTS=*'}|Select-Object -Last 1);if($routes){Write-Host $routes[0]}
    Write-Host 'V114_ACCOUNTING_TEMP_GOLDEN_ROUTE_AUDIT_SCRIPT=PASS' -ForegroundColor Green
    Write-Host "Diagnostics: $DiagDir"
}
finally {try{Stop-Transcript|Out-Null}catch{}}
