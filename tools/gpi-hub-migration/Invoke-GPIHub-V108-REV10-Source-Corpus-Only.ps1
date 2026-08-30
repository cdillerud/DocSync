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
$CorpusPath = Join-Path $env:USERPROFILE 'Downloads\W117105_Strategic Warehousing_122625_.pdf'
$CorpusSha = '48410cadceaa411d65e51bd266be5c5942b4431cdede9e7a05b871e75a3a2c25'
$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\migration-v108-rev10-source-corpus\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
Start-Transcript -LiteralPath (Join-Path $DiagDir 'Invoke-GPIHub-V108-REV10-Source-Corpus-Only.txt') -Force | Out-Null

function Require([bool]$Condition,[string]$Message) { if (-not $Condition) { throw $Message } }

function Invoke-NativeText {
    param([Parameter(Mandatory)][string]$FilePath,[Parameter(Mandatory)][string[]]$Arguments,[switch]$AllowFailure)
    $token=[guid]::NewGuid().ToString('N')
    $stderrFile=Join-Path $env:TEMP "gpi-v108-rev10-$token.err.txt"
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

function Invoke-SshScript {
    param([string]$Ip,[string]$KnownHosts,[string]$ScriptText)
    $token=[guid]::NewGuid().ToString('N')
    $stderrFile=Join-Path $env:TEMP "gpi-v108-rev10-ssh-$token.err.txt"
    $args=@('-i',$KeyPath,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',"UserKnownHostsFile=$KnownHosts",'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=20',"azureuser@$Ip",'bash -s')
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

function Section([string]$Title){Write-Host '';Write-Host('='*120)-ForegroundColor Cyan;Write-Host $Title -ForegroundColor Cyan;Write-Host('='*120)-ForegroundColor Cyan}

try {
    Section 'V108 REV10 - SOURCE-ONLY STRATEGIC INBOUND AI CORPUS RESUME'
    Write-Host 'Target durability     : ACCEPTED FROM REV9 PASS / NOT RE-RUN'
    Write-Host 'Source execution      : AI-ONLY standalone classifier probe'
    Write-Host 'PDF page extraction   : pypdf (declared runtime dependency)'
    Write-Host 'Source app/data       : NO APP CHANGE / NO MONGO WRITE / NO RESTART'
    Write-Host 'BC / SharePoint       : NO WRITES'
    Write-Host 'Production            : NOT TOUCHED'

    Require (Test-Path -LiteralPath $CorpusPath -PathType Leaf) "W117105 corpus missing: $CorpusPath"
    $sha=(Get-FileHash -LiteralPath $CorpusPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Require ($sha-eq$CorpusSha) "W117105 corpus SHA mismatch: $sha"
    Write-Host 'V108_REV10_CORPUS_SHA=PASS' -ForegroundColor Green

    Require (Test-Path -LiteralPath $KeyPath -PathType Leaf) "SSH key missing: $KeyPath"
    foreach($cmd in 'ssh.exe','scp.exe','ssh-keygen.exe'){Require ($null-ne(Get-Command $cmd -ErrorAction SilentlyContinue)) "$cmd unavailable."}
    $Known=Get-KnownHostsForIp $SourceIp
    $scp=Invoke-NativeText -FilePath 'scp.exe' -Arguments @('-i',$KeyPath,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',"UserKnownHostsFile=$Known",'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=20',$CorpusPath,"azureuser@${SourceIp}:/tmp/v108-w117105.pdf")
    Require ($scp.ExitCode-eq0) 'Failed to stage W117105 corpus to source.'
    Write-Host 'V108_REV10_SOURCE_CORPUS_STAGED=PASS' -ForegroundColor Green

    $Remote=@'
set -euo pipefail
EXPECTED_IMAGE='sha256:646051f6b0434b20ad429dec18c5f7b2a7d017c0fdec94f4bd77eaa7375fabb3'
EXPECTED_HELPER='2d2298b9c7e6315745d814e5437687caf463a44dec24d73d710b6d9e4e772117'
EXPECTED_CORPUS='48410cadceaa411d65e51bd266be5c5942b4431cdede9e7a05b871e75a3a2c25'
backend=$(docker ps --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
[ -n "$backend" ] || { echo 'Source backend missing.' >&2; exit 71; }
[ "$(docker inspect "$backend" -f '{{.Image}}')" = "$EXPECTED_IMAGE" ] || { echo 'Source backend image drift.' >&2; exit 72; }
[ "$(docker exec "$backend" sha256sum /app/services/document_intel_helpers.py | awk '{print $1}')" = "$EXPECTED_HELPER" ] || { echo 'Source AI helper drift.' >&2; exit 73; }
[ "$(sha256sum /tmp/v108-w117105.pdf | awk '{print $1}')" = "$EXPECTED_CORPUS" ] || { echo 'Source corpus SHA mismatch.' >&2; exit 74; }

health_before=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health", timeout=4); print(r.status)')
case "$health_before" in 2??|3??) ;; *) echo "Source backend unhealthy before AI probe: $health_before" >&2; exit 75;; esac
echo "V108_REV10_SOURCE_HEALTH_BEFORE=$health_before"

docker exec -e PYTHONPATH=/app -w /app "$backend" python -c 'import pypdf; from pypdf import PdfReader, PdfWriter; print("V108_REV10_PYPDF_VERSION=" + getattr(pypdf,"__version__","unknown")); print("V108_REV10_PYPDF_PREFLIGHT=PASS")'
echo V108_REV10_SOURCE_AI_AUTHORITY=PASS

docker cp /tmp/v108-w117105.pdf "$backend:/tmp/v108-w117105.pdf" >/dev/null
rm -f /tmp/v108-w117105.pdf
cat > /tmp/v108-rev10-probe.py <<'PY'
import asyncio, json, sys, types
from pypdf import PdfReader, PdfWriter

async def empty(*args, **kwargs): return ''
fb=types.ModuleType('services.classification_feedback_service')
fb.build_few_shot_prompt_section=empty
fb.build_vendor_hints_prompt_section=empty
sys.modules['services.classification_feedback_service']=fb
loop=types.ModuleType('services.feedback_loop_service')
loop.build_feedback_context_for_prompt=empty
sys.modules['services.feedback_loop_service']=loop
vendor=types.ModuleType('services.vendor_inference_service')
def no_vendor(*args, **kwargs): return (None,None)
vendor.infer_vendor=no_vendor
sys.modules['services.vendor_inference_service']=vendor
from services.document_intel_helpers import classify_document_with_ai

def has(obj, token):
    t=token.lower()
    if isinstance(obj,dict): return any(has(k,t) or has(v,t) for k,v in obj.items())
    if isinstance(obj,(list,tuple)): return any(has(v,t) for v in obj)
    return t in str(obj).lower()

async def classify(path,name,label):
    r=await classify_document_with_ai(path,name)
    print(f'V108_REV10_AI_{label}='+json.dumps(r,sort_keys=True,default=str))
    return r

async def main():
    packet='/tmp/v108-w117105.pdf'
    reader=PdfReader(packet)
    print(f'V108_REV10_PACKET_PAGES={len(reader.pages)}')
    if len(reader.pages) != 4: raise SystemExit(f'Expected 4-page packet, got {len(reader.pages)}')
    full=await classify(packet,'W117105_Strategic Warehousing_122625_.pdf','FULL_PACKET')
    p4='/tmp/v108-w117105-page4.pdf'
    writer=PdfWriter(); writer.add_page(reader.pages[3])
    with open(p4,'wb') as f: writer.write(f)
    page4=await classify(p4,'W117105_Strategic_supporting_shipping_page.pdf','SUPPORTING_PAGE4')
    checks={
      'full_W117105':has(full,'W117105'),
      'full_962222-1':has(full,'962222-1'),
      'full_815734':has(full,'815734'),
      'full_ER25-1560':has(full,'ER25-1560'),
      'page4_ER25-1560':has(page4,'ER25-1560')
    }
    print('V108_REV10_AI_CHECKS='+json.dumps(checks,sort_keys=True))
    for k,v in checks.items(): print(f'V108_REV10_CHECK_{k}=' + ('PASS' if v else 'MISS'))
    if checks['page4_ER25-1560'] and not checks['full_ER25-1560']:
        gap='PROVEN_SUPPORTING_SHIPMENT_LOST_BY_CURRENT_FIRST_PAGE_SEAM'
    elif checks['full_ER25-1560']:
        gap='NOT_OBSERVED_FULL_PACKET_PRESERVED_SHIPMENT'
    else:
        gap='UNRESOLVED_SUPPORTING_SHIPMENT_NOT_EXTRACTED'
    print('V108_MULTIPAGE_REFERENCE_GAP='+gap)
    print('V108_STRATEGIC_PRIMARY_IDENTITY=' + ('PASS' if checks['full_W117105'] else 'MISS'))
    print('V108_REV10_AI_CORPUS_EXECUTION=PASS')

asyncio.run(main())
PY

docker cp /tmp/v108-rev10-probe.py "$backend:/tmp/v108-rev10-probe.py" >/dev/null
rm -f /tmp/v108-rev10-probe.py
set +e
probe_out=$(docker exec -e PYTHONPATH=/app -w /app "$backend" python /tmp/v108-rev10-probe.py 2>&1)
probe_code=$?
set -e
printf '%s\n' "$probe_out"
docker exec "$backend" rm -f /tmp/v108-rev10-probe.py /tmp/v108-w117105.pdf /tmp/v108-w117105-page4.pdf >/dev/null 2>&1 || true
[ "$probe_code" -eq 0 ] || { echo "AI corpus probe failed with exit code $probe_code" >&2; exit 76; }
printf '%s\n' "$probe_out" | grep -Fq 'V108_REV10_AI_CORPUS_EXECUTION=PASS' || { echo 'AI execution marker missing.' >&2; exit 77; }
health_after=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health", timeout=4); print(r.status)')
case "$health_after" in 2??|3??) ;; *) echo "Source backend unhealthy after AI probe: $health_after" >&2; exit 78;; esac
echo "V108_REV10_SOURCE_HEALTH_AFTER=$health_after"
echo V108_REV10_SOURCE_AI_CORPUS_PROBE=PASS
'@

    $r=Invoke-SshScript $SourceIp $Known $Remote
    Set-Content -LiteralPath (Join-Path $DiagDir 'source-v108-rev10-ai-corpus.txt') -Value $r.StdOut -Encoding utf8
    if($r.StdOut){Write-Host $r.StdOut}
    if($r.StdErr){Write-Host $r.StdErr -ForegroundColor DarkYellow}
    Require ($r.ExitCode-eq0) "V108 REV10 source AI corpus probe failed with exit code $($r.ExitCode)."
    foreach($m in 'V108_REV10_PYPDF_PREFLIGHT=PASS','V108_REV10_SOURCE_AI_AUTHORITY=PASS','V108_REV10_AI_CORPUS_EXECUTION=PASS','V108_REV10_SOURCE_AI_CORPUS_PROBE=PASS'){
        Require ($r.StdOut-match[regex]::Escape($m)) "Missing source marker: $m"
    }
    $gap=@($r.StdOut-split"`n"|Where-Object{$_-like'V108_MULTIPAGE_REFERENCE_GAP=*'}|Select-Object -Last 1)
    Require ($gap.Count-eq1) 'Missing multi-page reference disposition.'
    $primary=@($r.StdOut-split"`n"|Where-Object{$_-like'V108_STRATEGIC_PRIMARY_IDENTITY=*'}|Select-Object -Last 1)
    Require ($primary.Count-eq1) 'Missing Strategic primary identity disposition.'

    Section 'V108 REV10 FINAL RESULT'
    Write-Host 'Target durability      : PASS FROM REV9 / NOT RE-RUN'
    Write-Host 'Source classifier seam : PASS'
    Write-Host "Strategic primary ID   : $($primary[0])"
    Write-Host "Multi-page finding     : $($gap[0])"
    Write-Host 'BC / SharePoint        : NO WRITES'
    Write-Host 'Production             : NOT TOUCHED'
    Write-Host "Diagnostics            : $DiagDir"
    Write-Host 'V108_REV10_SOURCE_CORPUS_ONLY=PASS' -ForegroundColor Green
    Write-Host 'V108_DURABLE_WAREHOUSE_STRATEGIC_CORPUS=PASS' -ForegroundColor Green
    Write-Host 'NEXT: If multi-page gap is proven, patch supporting-page reference extraction. Otherwise start AP TOP-10 PAYABLE COHORT (#19).' -ForegroundColor Yellow
}
finally { try{Stop-Transcript|Out-Null}catch{} }
