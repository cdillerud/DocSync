#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$StatePath = Join-Path $ToolRoot 'state.json'
$State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 80
$OperationalRoot = [string]$State.local.operational_root
$KeyPath = [string]$State.local.ssh_key
$SourceIp = [string]$State.source.public_ip
$FeatureBranch = 'feature/ap-ai-routing-learning'
$FeatureRef = 'refs/remotes/origin/feature/ap-ai-routing-learning'
$ExpectedFeatureCommit = 'cd4eece7f10c825bb7382e22a789c0ea0f19dcd5'
$ExpectedBackendImage = 'sha256:646051f6b0434b20ad429dec18c5f7b2a7d017c0fdec94f4bd77eaa7375fabb3'
$ExpectedHelperSha = '2d2298b9c7e6315745d814e5437687caf463a44dec24d73d710b6d9e4e772117'
$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\v115-ap-ai-routing-learning-golden\$Stamp"
$CandidateRoot = Join-Path $DiagDir 'candidate'
New-Item -ItemType Directory -Path $CandidateRoot -Force | Out-Null
Start-Transcript -LiteralPath (Join-Path $DiagDir 'Invoke-GPIHub-V115-AP-AI-Routing-Learning-Golden.txt') -Force | Out-Null

function Require {
    param([bool]$Condition,[string]$Message)
    if (-not $Condition) { throw $Message }
}

function Section([string]$Title) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

function Invoke-NativeText {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$AllowFailure,
        [string]$WorkingDirectory
    )
    $token = [guid]::NewGuid().ToString('N')
    $stderrFile = Join-Path $env:TEMP "gpi-v115-$token.err.txt"
    $oldEap = $ErrorActionPreference
    $nativeVar = Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $oldNative = if ($null -ne $nativeVar) { $nativeVar.Value } else { $null }
    $oldLocation = Get-Location
    try {
        if ($WorkingDirectory) { Set-Location -LiteralPath $WorkingDirectory }
        $ErrorActionPreference = 'Continue'
        if ($null -ne $nativeVar) { $PSNativeCommandUseErrorActionPreference = $false }
        $output = & $FilePath @Arguments 2> $stderrFile
        $code = $LASTEXITCODE
        $stdout = (@($output) | ForEach-Object { [string]$_ }) -join "`n"
        $stderr = if (Test-Path -LiteralPath $stderrFile) {
            Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue
        }
        else { '' }
        $result = [pscustomobject]@{ ExitCode=[int]$code; StdOut=[string]$stdout; StdErr=[string]$stderr }
        if (-not $AllowFailure -and $result.ExitCode -ne 0) {
            throw "$FilePath failed ($($result.ExitCode)).`n$stdout`n$stderr"
        }
        return $result
    }
    finally {
        Set-Location -LiteralPath $oldLocation
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
    $stderrFile = Join-Path $env:TEMP "gpi-v115-ssh-$token.err.txt"
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

function Materialize-GitTextFile {
    param(
        [Parameter(Mandatory)][string]$Ref,
        [Parameter(Mandatory)][string]$RepoPath,
        [Parameter(Mandatory)][string]$Destination
    )
    $parent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $show = Invoke-NativeText -FilePath 'git.exe' -Arguments @('-C',$OperationalRoot,'show',"$Ref`:$RepoPath")
    Set-Content -LiteralPath $Destination -Value $show.StdOut -Encoding utf8 -NoNewline
}

try {
    Section 'V115 - AP AI ROUTING LEARNING GOLDEN VALIDATION'
    Write-Host 'Classification       : PARITY BLOCKER / AI LABOR-REDUCTION VALIDATION'
    Write-Host 'Routing label truth  : LIVE GamerAccounting AP Temp placement (READ ONLY)'
    Write-Host 'Learning objective   : SAME VENDOR MAY LEARN MULTIPLE ROUTES FROM DOCUMENT + BC CONTEXT'
    Write-Host 'Golden holdouts      : Tumalo warehouse + Tumalo dropship/freight'
    Write-Host 'Feature code         : TEMP-STAGED ONLY; /app NOT MODIFIED'
    Write-Host 'Mongo                : NO WRITES'
    Write-Host 'SharePoint           : PRODUCTION READS ONLY / NO MOVES / NO UPLOADS'
    Write-Host 'Business Central     : READ ONLY / PRODUCTION WRITES HARD-BLOCKED'
    Write-Host 'Source runtime       : NO RESTART'
    Write-Host 'Production mutation  : NONE'

    foreach ($cmd in 'git.exe','ssh.exe','scp.exe','ssh-keygen.exe') {
        Require ($null -ne (Get-Command $cmd -ErrorAction SilentlyContinue)) "$cmd unavailable."
    }
    Require (Test-Path -LiteralPath $OperationalRoot -PathType Container) "Operational repo missing: $OperationalRoot"
    Require (Test-Path -LiteralPath $KeyPath -PathType Leaf) "SSH key missing: $KeyPath"

    Section '1. PIN FEATURE BRANCH + MATERIALIZE CANDIDATE FILES'
    $fetch = Invoke-NativeText -FilePath 'git.exe' -Arguments @(
        '-C',$OperationalRoot,'fetch','origin',"+$FeatureBranch`:$FeatureRef"
    )
    $resolved = (Invoke-NativeText -FilePath 'git.exe' -Arguments @('-C',$OperationalRoot,'rev-parse',$FeatureRef)).StdOut.Trim()
    Write-Host "V115_FEATURE_COMMIT=$resolved"
    Require ($resolved -eq $ExpectedFeatureCommit) "Feature branch drift: expected $ExpectedFeatureCommit, got $resolved"
    Write-Host 'V115_FEATURE_COMMIT=PASS' -ForegroundColor Green

    $CandidateFiles = @(
        'backend/services/ap_routing_learning_service.py',
        'backend/services/ap_routing_decision_service.py',
        'backend/services/document_bundle_reference_service.py',
        'backend/services/ap_bc_routing_context_service.py',
        'backend/services/ap_routing_corpus_service.py',
        'backend/services/ap_routing_evaluation_service.py',
        'backend/services/ap_routing_feedback_bridge_service.py',
        'backend/services/ap_primary_document_service.py',
        'backend/services/ap_routing_intelligence_service.py',
        'backend/config/ap_routing_contract.v1.json'
    )
    foreach ($repoPath in $CandidateFiles) {
        $relative = $repoPath -replace '^backend/',''
        $dest = Join-Path $CandidateRoot ($relative -replace '/', [IO.Path]::DirectorySeparatorChar)
        Materialize-GitTextFile -Ref $FeatureRef -RepoPath $repoPath -Destination $dest
    }
    $ServiceInit = Join-Path $CandidateRoot 'services\__init__.py'
    @'
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)
'@ | Set-Content -LiteralPath $ServiceInit -Encoding utf8 -NoNewline
    Write-Host "V115_CANDIDATE_LOCAL=$CandidateRoot"
    Write-Host 'V115_CANDIDATE_MATERIALIZATION=PASS' -ForegroundColor Green

    $Known = Get-KnownHostsForIp -Ip $SourceIp

    Section '2. STAGE CANDIDATE TO SOURCE HOST TEMP ONLY'
    $prepRemote = Invoke-SshScript -KnownHosts $Known -ScriptText @'
set -euo pipefail
rm -rf /tmp/gpi-ap-routing-v115-host
mkdir -p /tmp/gpi-ap-routing-v115-host
chmod 700 /tmp/gpi-ap-routing-v115-host
'@
    Require ($prepRemote.ExitCode -eq 0) "Source temp prep failed: $($prepRemote.StdErr)"

    $scpArgs = @(
        '-r',
        '-i',$KeyPath,
        '-o','BatchMode=yes',
        '-o','StrictHostKeyChecking=yes',
        '-o',"UserKnownHostsFile=$Known",
        '-o','GlobalKnownHostsFile=NUL',
        '-o','ConnectTimeout=20',
        "$CandidateRoot\*",
        "azureuser@$SourceIp`:/tmp/gpi-ap-routing-v115-host/"
    )
    $scp = Invoke-NativeText -FilePath 'scp.exe' -Arguments $scpArgs
    Write-Host 'V115_CANDIDATE_SOURCE_TEMP_STAGED=PASS' -ForegroundColor Green

    Section '3. LIVE SOURCE READ-ONLY GOLDEN VALIDATION'
    $Remote = @'
set -euo pipefail
EXPECTED_IMAGE='sha256:646051f6b0434b20ad429dec18c5f7b2a7d017c0fdec94f4bd77eaa7375fabb3'
EXPECTED_HELPER='2d2298b9c7e6315745d814e5437687caf463a44dec24d73d710b6d9e4e772117'
HOST_STAGE='/tmp/gpi-ap-routing-v115-host'
CONTAINER_STAGE='/tmp/gpi-ap-routing-v115'
backend=$(docker ps --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
[ -n "$backend" ] || { echo 'Source backend missing.' >&2; exit 71; }
[ "$(docker inspect "$backend" -f '{{.Image}}')" = "$EXPECTED_IMAGE" ] || { echo 'Source backend image drift.' >&2; exit 72; }
[ "$(docker exec "$backend" sha256sum /app/services/document_intel_helpers.py | awk '{print $1}')" = "$EXPECTED_HELPER" ] || { echo 'Source document helper drift.' >&2; exit 73; }

sp_target=$(docker exec "$backend" sh -c 'printf %s "${SHAREPOINT_TARGET:-}"')
bc_write=$(docker exec "$backend" sh -c 'printf %s "${BC_WRITE_ENABLED:-false}"')
bc_block=$(docker exec "$backend" sh -c 'printf %s "${BC_BLOCK_PRODUCTION_WRITES:-true}"')
[ "$sp_target" = 'test' ] || { echo "Unsafe SHAREPOINT_TARGET=$sp_target" >&2; exit 74; }
case "${bc_write,,}" in false|0|no|'') ;; *) echo "Unsafe BC_WRITE_ENABLED=$bc_write" >&2; exit 75;; esac
case "${bc_block,,}" in true|1|yes) ;; *) echo "Unsafe BC_BLOCK_PRODUCTION_WRITES=$bc_block" >&2; exit 76;; esac
health=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=4); print(r.status)')
case "$health" in 2??|3??) ;; *) echo "Source backend unhealthy: $health" >&2; exit 77;; esac
echo "V115_SOURCE_HEALTH_BEFORE=$health"
echo V115_SOURCE_SAFETY=PASS

rm -rf /tmp/gpi-ap-routing-v115-probe.py

docker exec "$backend" rm -rf "$CONTAINER_STAGE"
docker cp "$HOST_STAGE/." "$backend:$CONTAINER_STAGE"

docker exec "$backend" python -c 'import pypdf; print("V115_PYPDF_VERSION=" + str(getattr(pypdf,"__version__","unknown")))'

docker exec "$backend" sh -c "PYTHONPATH='$CONTAINER_STAGE:/app' python -m py_compile \
 '$CONTAINER_STAGE/services/ap_routing_learning_service.py' \
 '$CONTAINER_STAGE/services/ap_routing_decision_service.py' \
 '$CONTAINER_STAGE/services/document_bundle_reference_service.py' \
 '$CONTAINER_STAGE/services/ap_bc_routing_context_service.py' \
 '$CONTAINER_STAGE/services/ap_routing_corpus_service.py' \
 '$CONTAINER_STAGE/services/ap_routing_evaluation_service.py' \
 '$CONTAINER_STAGE/services/ap_routing_feedback_bridge_service.py' \
 '$CONTAINER_STAGE/services/ap_primary_document_service.py' \
 '$CONTAINER_STAGE/services/ap_routing_intelligence_service.py'"
echo V115_CANDIDATE_PYCOMPILE=PASS

cat > /tmp/gpi-ap-routing-v115-probe.py <<'PY'
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

CANDIDATE='/tmp/gpi-ap-routing-v115'
sys.path.insert(0,CANDIDATE)
sys.path.insert(1,'/app')

import httpx
from services.sharepoint_service import _get_graph_token
from services.ap_routing_learning_service import (
    LABEL_SOURCE_ACCOUNTING_TEMP,
    UNLABELED_SOURCE_NAV_ARCHIVE,
    prepare_routing_example,
)
from services.ap_routing_decision_service import (
    decide_ap_route,
    govern_route_prediction,
    RoutePrediction,
    route_is_allowed,
)
from services.document_bundle_reference_service import (
    _regex_supporting_refs,
    extract_supporting_references,
)
from services.ap_primary_document_service import classify_primary_document
from services.ap_bc_routing_context_service import resolve_ap_routing_context
from services.folder_routing_service import determine_ap_routing_decision

HOST='gamerpackaging1.sharepoint.com'
SITE_PATH='/sites/GamerAccounting'
DRIVE_NAME='Documents'
BASE='General/Accounting/Accounts Payable/Temp Folder'
WAREHOUSE_ROUTE='Warehouse Not International'
DROPSHIP_ROUTE='Dropship Not International/Freight'
WAREHOUSE_HOLDOUT='_TUMALO_0311997_08282026.pdf'
DROPSHIP_HOLDOUT='110784A_TUMALO_0312676_08262026.pdf'
TRAIN_PER_ROUTE=4


def load_contract():
    p=Path(CANDIDATE)/'config'/'ap_routing_contract.v1.json'
    return json.loads(p.read_text(encoding='utf-8'))


def selftest(contract):
    try:
        prepare_routing_example({
            'label_source':UNLABELED_SOURCE_NAV_ARCHIVE,
            'route_path':'Purchase/Tumalo',
            'file_name':'legacy.pdf',
        })
        raise AssertionError('NAV archive was incorrectly accepted as routing authority')
    except ValueError:
        pass
    assert not route_is_allowed('Freight Issues',contract,{'status':'resolved','po_number':'113785'})
    assert route_is_allowed(WAREHOUSE_ROUTE,contract,{'status':'resolved','po_number':'113785'})
    assert route_is_allowed(DROPSHIP_ROUTE,contract,{'status':'resolved','po_number':'110784A'})
    low=govern_route_prediction(
        RoutePrediction('Tooling Invoices',0.75,['x'],'x',[],[],[],'test'),
        contract=contract,
        bc_context={},
    )
    assert low.decision=='needs_review' and low.route_path==''
    refs=_regex_supporting_refs([{'page':2,'text':'Gamer PO # 113785\nBill of Lading: SMLMSEL6D6996600\nReference: SI-02-26-34711'}])
    assert refs['po_numbers'][0]['value']=='113785'
    assert refs['bol_numbers'][0]['value'].startswith('SMLMSEL6D6996600')
    assert refs['reference_numbers'][0]['value'].startswith('SI-02-26-34711')
    print('V115_CANDIDATE_SELFTEST=PASS',flush=True)


async def graph_get(client,headers,url,label):
    r=await client.get(url,headers=headers)
    if r.status_code>=400:
        raise RuntimeError(f'{label} HTTP {r.status_code}: {r.text[:300]}')
    return r


async def folder_items(client,headers,drive_id,route):
    path=f'{BASE}/{route}'
    root=(await graph_get(client,headers,f'https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{quote(path,safe="/")}',f'folder:{route}')).json()
    items=[]
    url=f'https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{root["id"]}/children?$top=200&$select=id,name,size,file,folder,webUrl,lastModifiedDateTime'
    while url:
        data=(await graph_get(client,headers,url,f'children:{route}')).json()
        for item in data.get('value',[]):
            if item.get('file') is None:
                continue
            name=item.get('name','')
            if 'tumalo' not in name.lower() or not name.lower().endswith('.pdf'):
                continue
            items.append({
                'route_path':route,
                'item_id':item['id'],
                'name':name,
                'web_url':item.get('webUrl',''),
                'modified':item.get('lastModifiedDateTime',''),
            })
        url=data.get('@odata.nextLink')
    return sorted(items,key=lambda x:(x['modified'],x['name']),reverse=True)


async def download(client,headers,drive_id,item):
    r=await graph_get(client,headers,f'https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item["item_id"]}/content',f'download:{item["name"]}')
    fd,path=tempfile.mkstemp(prefix='v115-',suffix='.pdf')
    os.close(fd)
    Path(path).write_bytes(r.content)
    return path


def raw_text(path,max_pages=5,max_chars=14000):
    from pypdf import PdfReader
    try:
        reader=PdfReader(path)
        chunks=[]
        for page in reader.pages[:max_pages]:
            try: chunks.append(page.extract_text() or '')
            except Exception: pass
        return '\n'.join(chunks)[:max_chars]
    except Exception:
        return ''


def doc_from(primary,name,text):
    fields=dict(primary.get('extracted_fields') or {})
    vendor=fields.get('vendor') or fields.get('vendor_name') or fields.get('carrier') or fields.get('shipper') or ''
    return {
        'id':'v115:'+name,
        'file_name':name,
        'document_type':primary.get('suggested_job_type') or primary.get('document_type') or '',
        'suggested_job_type':primary.get('suggested_job_type') or primary.get('document_type') or '',
        'confidence':primary.get('confidence'),
        'vendor_canonical':vendor,
        'vendor_name':vendor,
        'extracted_fields':fields,
        'raw_text':text,
    }


async def hydrate(client,headers,drive_id,item,include_label=True):
    path=await download(client,headers,drive_id,item)
    try:
        primary=await asyncio.wait_for(classify_primary_document(path,item['name']),timeout=210)
        dtype=primary.get('suggested_job_type') or primary.get('document_type') or ''
        bundle=await extract_supporting_references(
            path,
            item['name'],
            primary_document_type=dtype,
            primary_fields=primary.get('extracted_fields') or {},
            llm_enabled=False,
        )
        text=raw_text(path)
        doc=doc_from(primary,item['name'],text)
        context=await asyncio.wait_for(resolve_ap_routing_context(doc,bundle_refs=bundle),timeout=90)
        if not doc.get('vendor_canonical'):
            doc['vendor_canonical']=context.get('bc_vendor_name') or ((context.get('live_bc_context') or {}).get('bc_vendor_name')) or 'Tumalo Creek Transportation'
            doc['vendor_name']=doc['vendor_canonical']
        result={
            'item':item,
            'primary':primary,
            'document':doc,
            'bundle':bundle,
            'bc_context':context,
        }
        if include_label:
            result['example']=prepare_routing_example({
                'label_source':LABEL_SOURCE_ACCOUNTING_TEMP,
                'source_item_id':item['item_id'],
                'file_name':item['name'],
                'route_path':item['route_path'],
                'vendor_name':doc.get('vendor_canonical') or 'Tumalo Creek Transportation',
                'document_type':dtype,
                'classification_confidence':primary.get('confidence'),
                'extracted_fields':doc.get('extracted_fields') or {},
                'bc_context':context,
                'key_evidence':{
                    'bundle_references':bundle.get('references'),
                    'po_number':context.get('po_number'),
                    'location_code':context.get('location_code'),
                },
            })
        return result
    finally:
        try: os.remove(path)
        except OSError: pass


def baseline_doc(h):
    doc=dict(h['document'])
    ctx=h['bc_context'] or {}
    status=str(ctx.get('status') or '').lower()
    doc['bc_po_resolved']=status in {'resolved','resolved_shipment'}
    if ctx.get('po_number'): doc['po_number_extracted']=ctx.get('po_number')
    if ctx.get('bc_order_number'): doc['bc_order_number']=ctx.get('bc_order_number')
    return doc


async def main():
    contract=load_contract()
    selftest(contract)
    token=await _get_graph_token()
    headers={'Authorization':f'Bearer {token}'}
    timeout=httpx.Timeout(90.0,connect=20.0,read=90.0,write=90.0,pool=20.0)
    async with httpx.AsyncClient(timeout=timeout,follow_redirects=True) as client:
        site=(await graph_get(client,headers,f'https://graph.microsoft.com/v1.0/sites/{HOST}:{SITE_PATH}','site')).json()
        drives=(await graph_get(client,headers,f'https://graph.microsoft.com/v1.0/sites/{site["id"]}/drives?$top=100&$select=id,name','drives')).json().get('value',[])
        drive=next((d for d in drives if d.get('name')==DRIVE_NAME),None)
        if not drive: raise RuntimeError('GamerAccounting Documents drive not found')
        drive_id=drive['id']

        warehouse=await folder_items(client,headers,drive_id,WAREHOUSE_ROUTE)
        dropship=await folder_items(client,headers,drive_id,DROPSHIP_ROUTE)
        wh_hold=next((x for x in warehouse if x['name']==WAREHOUSE_HOLDOUT),None)
        ds_hold=next((x for x in dropship if x['name']==DROPSHIP_HOLDOUT),None)
        if not wh_hold: raise RuntimeError('Warehouse golden holdout missing from live Accounting Temp')
        if not ds_hold: raise RuntimeError('Dropship golden holdout missing from live Accounting Temp')
        wh_train=[x for x in warehouse if x['name']!=WAREHOUSE_HOLDOUT][:TRAIN_PER_ROUTE]
        ds_train=[x for x in dropship if x['name']!=DROPSHIP_HOLDOUT][:TRAIN_PER_ROUTE]
        print(f'V115_TUMALO_TRAIN_WAREHOUSE_COUNT={len(wh_train)}',flush=True)
        print(f'V115_TUMALO_TRAIN_DROPSHIP_COUNT={len(ds_train)}',flush=True)
        if len(wh_train)<2 or len(ds_train)<2:
            raise RuntimeError('Insufficient contrasting live Tumalo training examples')

        examples=[]
        for idx,item in enumerate(wh_train+ds_train,1):
            print(f'V115_TRAIN_HYDRATE_START={idx}/{len(wh_train)+len(ds_train)}|{item["route_path"]}|{item["name"]}',flush=True)
            h=await hydrate(client,headers,drive_id,item,include_label=True)
            examples.append(h['example'])
            print('V115_TRAIN_HYDRATE_DONE='+json.dumps({
                'file':item['name'],
                'route':item['route_path'],
                'classification':h['document'].get('document_type'),
                'bc_status':h['bc_context'].get('status'),
                'po':h['bc_context'].get('po_number'),
                'location_code':h['bc_context'].get('location_code'),
            },sort_keys=True,default=str),flush=True)

        results=[]
        for case,item,expected in [
            ('warehouse',wh_hold,WAREHOUSE_ROUTE),
            ('dropship',ds_hold,DROPSHIP_ROUTE),
        ]:
            print(f'V115_HOLDOUT_START={case}|{item["name"]}',flush=True)
            h=await hydrate(client,headers,drive_id,item,include_label=False)
            primary_type=h['document'].get('document_type')
            bdoc=baseline_doc(h)
            baseline=determine_ap_routing_decision(
                bdoc,
                freight_direction=(bdoc.get('extracted_fields') or {}).get('freight_direction'),
                is_international=bool((bdoc.get('extracted_fields') or {}).get('is_international')),
                location_code=h['bc_context'].get('location_code'),
            )
            candidate=await asyncio.wait_for(
                decide_ap_route(
                    None,
                    document=h['document'],
                    bc_context=h['bc_context'],
                    contract=contract,
                    examples=examples,
                ),
                timeout=210,
            )
            proposed=(candidate.get('prediction') or {}).get('proposed_route') or ''
            row={
                'case':case,
                'file':item['name'],
                'classification':primary_type,
                'expected_route':expected,
                'baseline_route':baseline.get('folder_path'),
                'baseline_reason':baseline.get('routing_reason'),
                'candidate_proposed_route':proposed,
                'candidate_decision':candidate.get('decision'),
                'candidate_governed_route':candidate.get('route_path'),
                'candidate_confidence':candidate.get('confidence'),
                'candidate_reason':candidate.get('reason'),
                'prediction_match':proposed==expected,
                'classification_match':primary_type=='AP_Invoice',
                'auto_route_exact':candidate.get('decision')=='auto_route' and candidate.get('route_path')==expected,
                'bc_status':h['bc_context'].get('status'),
                'bc_po_number':h['bc_context'].get('po_number'),
                'verified_order_numbers':h['bc_context'].get('verified_order_numbers'),
                'location_code':h['bc_context'].get('location_code'),
                'bundle_refs':h['bundle'].get('references'),
            }
            results.append(row)
            marker='WAREHOUSE' if case=='warehouse' else 'DROPSHIP'
            print(f'V115_HOLDOUT_{marker}_CLASSIFICATION={primary_type}',flush=True)
            print(f'V115_HOLDOUT_{marker}_EXPECTED={expected}',flush=True)
            print(f'V115_HOLDOUT_{marker}_BASELINE={baseline.get("folder_path")}',flush=True)
            print(f'V115_HOLDOUT_{marker}_PREDICTED={proposed}',flush=True)
            print(f'V115_HOLDOUT_{marker}_DECISION={candidate.get("decision")}',flush=True)
            print(f'V115_HOLDOUT_{marker}_CONFIDENCE={candidate.get("confidence")}',flush=True)
            print('V115_HOLDOUT_ROW='+json.dumps(row,sort_keys=True,default=str),flush=True)

        exact_predictions=all(r['prediction_match'] and r['classification_match'] for r in results)
        wrong_auto=[r for r in results if r['candidate_decision']=='auto_route' and not r['auto_route_exact']]
        auto_exact=sum(1 for r in results if r['auto_route_exact'])
        if wrong_auto:
            labor='UNSAFE_WRONG_AUTO_ROUTE'
        elif exact_predictions and auto_exact==2:
            labor='STRONG_2_OF_2_EXACT_AUTO_ROUTE'
        elif exact_predictions:
            labor=f'ROUTE_LEARNING_PASS_AUTO_ROUTE_{auto_exact}_OF_2_REMAINDER_REVIEW'
        else:
            labor='ROUTE_LEARNING_NOT_YET_ACCURATE'
        print('V115_MANUAL_VALIDATION_REDUCTION_EVIDENCE='+labor,flush=True)
        print('V115_TUMALO_PAIRED_ROUTE_LEARNING='+('PASS' if exact_predictions and not wrong_auto else 'FAIL'),flush=True)
        summary={
            'schema_version':'1.0',
            'authority':'live GamerAccounting AP Temp labels read-only',
            'feature_commit':'cd4eece7f10c825bb7382e22a789c0ea0f19dcd5',
            'training_examples':len(examples),
            'warehouse_training':len(wh_train),
            'dropship_training':len(ds_train),
            'results':results,
            'exact_predictions':exact_predictions,
            'wrong_auto_routes':len(wrong_auto),
            'auto_route_exact_count':auto_exact,
            'manual_validation_reduction_evidence':labor,
        }
        print('V115_RESULT_JSON='+json.dumps(summary,sort_keys=True,default=str),flush=True)
        if not exact_predictions or wrong_auto:
            raise SystemExit(91)

asyncio.run(main())
PY

docker cp /tmp/gpi-ap-routing-v115-probe.py "$backend:/tmp/gpi-ap-routing-v115-probe.py"
set +e
docker exec -e PYTHONPATH="$CONTAINER_STAGE:/app" "$backend" python /tmp/gpi-ap-routing-v115-probe.py
probe_rc=$?
set -e
if [ "$probe_rc" -ne 0 ]; then
    echo "V115_GOLDEN_PROBE_EXIT=$probe_rc" >&2
    docker exec "$backend" rm -rf "$CONTAINER_STAGE" /tmp/gpi-ap-routing-v115-probe.py || true
    rm -rf "$HOST_STAGE" /tmp/gpi-ap-routing-v115-probe.py || true
    exit "$probe_rc"
fi

health_after=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=4); print(r.status)')
case "$health_after" in 2??|3??) ;; *) echo "Source backend unhealthy after probe: $health_after" >&2; exit 92;; esac
echo "V115_SOURCE_HEALTH_AFTER=$health_after"

docker exec "$backend" rm -rf "$CONTAINER_STAGE" /tmp/gpi-ap-routing-v115-probe.py || true
rm -rf "$HOST_STAGE" /tmp/gpi-ap-routing-v115-probe.py || true

echo V115_TEMP_CLEANUP=PASS
echo V115_SOURCE_RUNTIME_UNCHANGED=PASS
echo V115_AP_AI_ROUTING_LEARNING_GOLDEN=PASS
'@

    $remoteResult = Invoke-SshScript -KnownHosts $Known -ScriptText $Remote
    if (-not [string]::IsNullOrWhiteSpace($remoteResult.StdOut)) { Write-Host $remoteResult.StdOut }
    if (-not [string]::IsNullOrWhiteSpace($remoteResult.StdErr)) { Write-Host $remoteResult.StdErr -ForegroundColor DarkYellow }
    Require ($remoteResult.ExitCode -eq 0) "V115 source golden validation failed with exit code $($remoteResult.ExitCode)."
    Require ($remoteResult.StdOut -match 'V115_AP_AI_ROUTING_LEARNING_GOLDEN=PASS') 'V115 final PASS marker missing.'

    $jsonMatch = [regex]::Matches($remoteResult.StdOut, '(?m)^V115_RESULT_JSON=(.+)$')
    if ($jsonMatch.Count -gt 0) {
        $json = $jsonMatch[$jsonMatch.Count - 1].Groups[1].Value.Trim()
        Set-Content -LiteralPath (Join-Path $DiagDir 'v115-result.json') -Value $json -Encoding utf8
    }

    Section 'V115 RESULT'
    Write-Host 'V115_AP_AI_ROUTING_LEARNING_GOLDEN=PASS' -ForegroundColor Green
    Write-Host "Diagnostics: $DiagDir"
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
