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
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\v109-supporting-reference-candidate\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
Start-Transcript -LiteralPath (Join-Path $DiagDir 'Invoke-GPIHub-V109-Supporting-Reference-Candidate-Test.txt') -Force | Out-Null

function Require([bool]$Condition,[string]$Message){if(-not$Condition){throw $Message}}
function Invoke-NativeText {
    param([string]$FilePath,[string[]]$Arguments,[switch]$AllowFailure)
    $token=[guid]::NewGuid().ToString('N');$err=Join-Path $env:TEMP "gpi-v109-$token.err.txt"
    $old=$ErrorActionPreference;$nv=Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue;$on=if($null-ne$nv){$nv.Value}else{$null}
    try{$ErrorActionPreference='Continue';if($null-ne$nv){$PSNativeCommandUseErrorActionPreference=$false};$o=& $FilePath @Arguments 2>$err;$c=$LASTEXITCODE;$so=(@($o)|%{[string]$_})-join"`n";$se=if(Test-Path $err){Get-Content $err -Raw -ErrorAction SilentlyContinue}else{''};$r=[pscustomobject]@{ExitCode=[int]$c;StdOut=$so;StdErr=$se};if(-not$AllowFailure-and$c-ne0){throw "$FilePath failed ($c).`n$so`n$se"};return $r}
    finally{$ErrorActionPreference=$old;if($null-ne$nv){$PSNativeCommandUseErrorActionPreference=$on};Remove-Item $err -Force -ErrorAction SilentlyContinue}
}
function Get-KnownHostsForIp([string]$Ip){$d=Join-Path $OperationalRoot '.gpi-diagnostics';foreach($f in @(Get-ChildItem $d -Filter '*known_hosts*' -File -Recurse -ErrorAction SilentlyContinue|Sort-Object LastWriteTime -Descending)){$p=Invoke-NativeText 'ssh-keygen.exe' @('-F',$Ip,'-f',$f.FullName) -AllowFailure;if($p.ExitCode-eq0-and-not[string]::IsNullOrWhiteSpace($p.StdOut)){return $f.FullName}};throw "No verified known_hosts for $Ip"}
function Invoke-SshScript([string]$Known,[string]$Text){$token=[guid]::NewGuid().ToString('N');$err=Join-Path $env:TEMP "gpi-v109-ssh-$token.err.txt";$args=@('-i',$KeyPath,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',"UserKnownHostsFile=$Known",'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=20',"azureuser@$SourceIp",'bash -s');$old=$ErrorActionPreference;$nv=Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue;$on=if($null-ne$nv){$nv.Value}else{$null};try{$ErrorActionPreference='Continue';if($null-ne$nv){$PSNativeCommandUseErrorActionPreference=$false};$o=(($Text-replace"`r`n","`n")|& ssh.exe @args 2>$err);$c=$LASTEXITCODE;$so=(@($o)|%{[string]$_})-join"`n";$se=if(Test-Path $err){Get-Content $err -Raw -ErrorAction SilentlyContinue}else{''};return [pscustomobject]@{ExitCode=[int]$c;StdOut=$so;StdErr=$se}}finally{$ErrorActionPreference=$old;if($null-ne$nv){$PSNativeCommandUseErrorActionPreference=$on};Remove-Item $err -Force -ErrorAction SilentlyContinue}}
function Section([string]$t){Write-Host '';Write-Host('='*120)-ForegroundColor Cyan;Write-Host $t -ForegroundColor Cyan;Write-Host('='*120)-ForegroundColor Cyan}

try{
    Section 'V109 - BOUNDED SUPPORTING-PAGE REFERENCE CANDIDATE TEST'
    Write-Host 'Classification authority : PAGE 1 UNCHANGED'
    Write-Host 'Supporting pass          : PAGES 2-5 / LABELED REFERENCE FIELDS ONLY'
    Write-Host 'Conflict policy          : NEVER OVERWRITE PRIMARY; PRESERVE SUPPORTING VALUES + CONFLICTS'
    Write-Host 'Execution                : TEMPORARY MODULE INSIDE SOURCE CONTAINER'
    Write-Host 'Source app tree / Mongo  : NO CHANGE / NO WRITE'
    Write-Host 'BC / SharePoint          : NO WRITES'
    Write-Host 'Production               : NOT TOUCHED'
    Require(Test-Path $CorpusPath -PathType Leaf)"Missing W117105 corpus";$sha=(Get-FileHash $CorpusPath -Algorithm SHA256).Hash.ToLowerInvariant();Require($sha-eq$CorpusSha)"W117105 SHA mismatch"
    foreach($cmd in 'ssh.exe','scp.exe','ssh-keygen.exe'){Require($null-ne(Get-Command $cmd -ErrorAction SilentlyContinue))"$cmd unavailable"}
    $Known=Get-KnownHostsForIp $SourceIp
    $scp=Invoke-NativeText 'scp.exe' @('-i',$KeyPath,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',"UserKnownHostsFile=$Known",'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=20',$CorpusPath,"azureuser@${SourceIp}:/tmp/v109-w117105.pdf");Require($scp.ExitCode-eq0)'Corpus stage failed'

    $Remote=@'
set -euo pipefail
EXPECTED_IMAGE='sha256:646051f6b0434b20ad429dec18c5f7b2a7d017c0fdec94f4bd77eaa7375fabb3'
EXPECTED_HELPER='2d2298b9c7e6315745d814e5437687caf463a44dec24d73d710b6d9e4e772117'
EXPECTED_CORPUS='48410cadceaa411d65e51bd266be5c5942b4431cdede9e7a05b871e75a3a2c25'
backend=$(docker ps --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}'|head -n1)
[ -n "$backend" ] || { echo 'Source backend missing.' >&2; exit 71; }
[ "$(docker inspect "$backend" -f '{{.Image}}')" = "$EXPECTED_IMAGE" ] || { echo 'Source image drift.' >&2; exit 72; }
[ "$(docker exec "$backend" sha256sum /app/services/document_intel_helpers.py|awk '{print $1}')" = "$EXPECTED_HELPER" ] || { echo 'Helper drift.' >&2; exit 73; }
[ "$(sha256sum /tmp/v109-w117105.pdf|awk '{print $1}')" = "$EXPECTED_CORPUS" ] || { echo 'Corpus SHA mismatch.' >&2; exit 74; }
health=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=4); print(r.status)');case "$health" in 2??|3??);;*)exit 75;;esac
echo V109_SOURCE_AUTHORITY=PASS

docker cp "$backend:/app/services/document_intel_helpers.py" /tmp/v109-helper.py
cat > /tmp/v109-patch.py <<'PY'
from pathlib import Path
p=Path('/tmp/v109-helper.py')
s=p.read_text(encoding='utf-8')
anchor='async def _call_llm_for_extraction(file_path: str, file_name: str) -> dict:\n'
if s.count(anchor)!=1: raise SystemExit('V109 helper anchor count != 1')
helper=r'''
_SUPPORTING_REFERENCE_ALIASES = {
    "receipt_number": "receipt_number",
    "warehouse_receipt_number": "receipt_number",
    "reference_number": "reference_number",
    "shipment_number": "shipment_number",
    "bol_number": "bol_number",
    "bill_of_lading_number": "bol_number",
    "pro_number": "pro_number",
    "load_number": "load_number",
    "tracking_number": "tracking_number",
    "po_number": "po_number",
    "purchase_order_number": "po_number",
    "customer_po": "po_number",
    "order_number": "order_number",
}

_SUPPORTING_REFERENCE_PROMPT = """You extract reference metadata from SUPPORTING pages of a business-document bundle. Do NOT classify the document and do NOT change the primary page-1 document type. Extract only values that are explicitly printed next to a recognizable label. Preserve label semantics exactly: Receipt Number -> receipt_number; Reference # -> reference_number; Shipment # -> shipment_number; BOL/Bill of Lading -> bol_number; PRO -> pro_number; Load -> load_number; Tracking -> tracking_number; PO/Purchase Order/Customer PO -> po_number; Order -> order_number. Never infer one label from another. Return JSON only as {\"references\":{...},\"evidence\":[{\"field\":\"...\",\"value\":\"...\",\"printed_label\":\"...\",\"page_in_supporting_pdf\":1}]}. Omit uncertain fields."""

def _merge_supporting_reference_fields(primary_fields: dict, supporting: dict) -> dict:
    out = dict(primary_fields or {})
    conflicts = list(out.get("supporting_reference_conflicts") or [])
    refs = supporting.get("references", supporting) if isinstance(supporting, dict) else {}
    if not isinstance(refs, dict):
        return out
    for raw_key, value in refs.items():
        key = _SUPPORTING_REFERENCE_ALIASES.get(str(raw_key).strip().lower())
        if not key or value in (None, "", [], {}):
            continue
        values = value if isinstance(value, list) else [value]
        for candidate in values:
            if candidate in (None, ""):
                continue
            candidate = str(candidate).strip()
            existing = out.get(key)
            if existing in (None, "", [], {}):
                out[key] = candidate
                continue
            existing_values = existing if isinstance(existing, list) else [existing]
            if any(str(x).strip().casefold() == candidate.casefold() for x in existing_values):
                continue
            skey = f"supporting_{key}s"
            bucket = out.get(skey)
            if not isinstance(bucket, list):
                bucket = [] if bucket in (None, "") else [bucket]
            if not any(str(x).strip().casefold() == candidate.casefold() for x in bucket):
                bucket.append(candidate)
            out[skey] = bucket
            conflicts.append({"field": key, "primary": existing, "supporting": candidate})
    if conflicts:
        out["supporting_reference_conflicts"] = conflicts
    evidence = supporting.get("evidence") if isinstance(supporting, dict) else None
    if evidence:
        out["supporting_reference_evidence"] = evidence
    return out

async def _call_llm_for_supporting_references(file_path: str, file_name: str, page_count: int) -> dict:
    if page_count <= 1 or not EMERGENT_LLM_KEY:
        return {}
    from emergentintegrations.llm.chat import LlmChat, UserMessage, FileContentWithMimeType
    from pypdf import PdfReader, PdfWriter
    import tempfile
    reader = PdfReader(file_path)
    if len(reader.pages) <= 1:
        return {}
    writer = PdfWriter()
    # Bounded pass: supporting pages 2-5 only. Primary page 1 never enters this call.
    for idx in range(1, min(len(reader.pages), 5)):
        writer.add_page(reader.pages[idx])
    if len(writer.pages) == 0:
        return {}
    fd, support_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        with open(support_path, "wb") as f:
            writer.write(f)
        chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"support-refs-{uuid.uuid4()}", system_message=_SUPPORTING_REFERENCE_PROMPT).with_model("gemini", "gemini-2.5-pro")
        msg = UserMessage(text="Extract only explicitly labeled supporting-page references. JSON only.", file_contents=[FileContentWithMimeType(file_path=support_path, mime_type="application/pdf")])
        response = (await chat.send_message(msg)).strip()
        if response.startswith("```"):
            response = re.sub(r"^```(?:json)?\s*|\s*```$", "", response, flags=re.I | re.S).strip()
        parsed = json.loads(response)
        return parsed if isinstance(parsed, dict) else {}
    finally:
        try: os.remove(support_path)
        except Exception: pass

'''
s=s.replace(anchor,helper+anchor,1)
needle='''        result = json.loads(response_text)\n\n        extracted = result.get("extracted_fields", {})\n'''
replacement='''        result = json.loads(response_text)\n\n        extracted = result.get("extracted_fields", {})\n        if page_count > 1 and result.get("document_type") in {"Warehouse_Receipt", "Shipping_Document", "Freight_Document", "Order_Confirmation"}:\n            try:\n                supporting = await _call_llm_for_supporting_references(file_path, file_name, page_count)\n                extracted = _merge_supporting_reference_fields(extracted, supporting)\n                result["extracted_fields"] = extracted\n                logger.info("Supporting reference pass merged for '%s': fields=%d", file_name, len(extracted))\n            except Exception as supporting_error:\n                logger.warning("Supporting reference pass failed for '%s': %s", file_name, supporting_error)\n\n'''
if s.count(needle)!=1: raise SystemExit('V109 result merge anchor count != 1')
s=s.replace(needle,replacement,1)
p.write_text(s,encoding='utf-8')
print('V109_PATCH_APPLIED=PASS')
PY
python3 /tmp/v109-patch.py
python3 -m py_compile /tmp/v109-helper.py
patched_sha=$(sha256sum /tmp/v109-helper.py|awk '{print $1}')
echo "V109_PATCHED_HELPER_SHA=$patched_sha"
docker cp /tmp/v109-helper.py "$backend:/tmp/v109-helper.py" >/dev/null
docker cp /tmp/v109-w117105.pdf "$backend:/tmp/v109-w117105.pdf" >/dev/null

cat > /tmp/v109-probe.py <<'PY'
import asyncio, importlib.util, json, sys, types

# Suppress feedback DB reads so baseline and candidate compare only the extraction seam.
async def empty(*args, **kwargs): return ''
fb=types.ModuleType('services.classification_feedback_service');fb.build_few_shot_prompt_section=empty;fb.build_vendor_hints_prompt_section=empty;sys.modules['services.classification_feedback_service']=fb
loop=types.ModuleType('services.feedback_loop_service');loop.build_feedback_context_for_prompt=empty;sys.modules['services.feedback_loop_service']=loop
vendor=types.ModuleType('services.vendor_inference_service');vendor.infer_vendor=lambda *a,**k:(None,None);sys.modules['services.vendor_inference_service']=vendor

from services.document_intel_helpers import classify_document_with_ai as baseline
spec=importlib.util.spec_from_file_location('v109_candidate','/tmp/v109-helper.py');candidate=importlib.util.module_from_spec(spec);spec.loader.exec_module(candidate)

def has(obj,t):
    t=t.lower()
    if isinstance(obj,dict): return any(has(k,t) or has(v,t) for k,v in obj.items())
    if isinstance(obj,(list,tuple)): return any(has(v,t) for v in obj)
    return t in str(obj).lower()

async def main():
    p='/tmp/v109-w117105.pdf';n='W117105_Strategic Warehousing_122625_.pdf'
    b=await baseline(p,n);c=await candidate.classify_document_with_ai(p,n)
    print('V109_BASELINE='+json.dumps(b,sort_keys=True,default=str))
    print('V109_CANDIDATE='+json.dumps(c,sort_keys=True,default=str))
    bt=b.get('suggested_job_type');ct=c.get('suggested_job_type')
    print('V109_PRIMARY_CLASS_BASELINE='+str(bt));print('V109_PRIMARY_CLASS_CANDIDATE='+str(ct))
    print('V109_PRIMARY_CLASS_PRESERVED='+('PASS' if bt==ct else 'FAIL'))
    checks={
      'candidate_W117105':has(c,'W117105'),
      'candidate_962222-1':has(c,'962222-1'),
      'candidate_815734':has(c,'815734'),
      'candidate_ER25-1560':has(c,'ER25-1560'),
    }
    print('V109_CHECKS='+json.dumps(checks,sort_keys=True))
    for k,v in checks.items(): print('V109_'+k+'='+('PASS' if v else 'MISS'))
    print('V109_SUPPORTING_REFERENCE_CANDIDATE='+('PASS' if checks['candidate_ER25-1560'] and bt==ct else 'INCOMPLETE'))
asyncio.run(main())
PY
docker cp /tmp/v109-probe.py "$backend:/tmp/v109-probe.py" >/dev/null
set +e
out=$(docker exec -e PYTHONPATH=/app -w /app "$backend" python /tmp/v109-probe.py 2>&1);code=$?
set -e
printf '%s\n' "$out"
docker exec "$backend" rm -f /tmp/v109-helper.py /tmp/v109-w117105.pdf /tmp/v109-probe.py >/dev/null 2>&1 || true
rm -f /tmp/v109-helper.py /tmp/v109-w117105.pdf /tmp/v109-patch.py /tmp/v109-probe.py
[ "$code" -eq 0 ] || { echo "V109 probe failed: $code" >&2; exit 76; }
printf '%s\n' "$out"|grep -Fq 'V109_PRIMARY_CLASS_PRESERVED=PASS' || { echo 'Primary class changed.' >&2; exit 77; }
health_after=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=4); print(r.status)');case "$health_after" in 2??|3??);;*)exit 78;;esac
echo V109_SOURCE_RUNTIME_UNCHANGED=PASS
'@

    $r=Invoke-SshScript $Known $Remote;if($r.StdOut){Write-Host $r.StdOut};if($r.StdErr){Write-Host $r.StdErr -ForegroundColor DarkYellow};Set-Content (Join-Path $DiagDir 'v109-source.txt') $r.StdOut -Encoding utf8
    Require($r.ExitCode-eq0)"V109 failed with exit code $($r.ExitCode)";Require($r.StdOut-match'V109_SOURCE_RUNTIME_UNCHANGED=PASS')'V109 runtime marker missing'
    Section 'V109 RESULT';$disp=@($r.StdOut-split"`n"|?{$_-like'V109_SUPPORTING_REFERENCE_CANDIDATE=*'}|Select-Object -Last 1);if($disp){Write-Host $disp[0]};Write-Host "Diagnostics: $DiagDir";Write-Host 'V109_SUPPORTING_REFERENCE_CANDIDATE_TEST=PASS' -ForegroundColor Green
}
finally{try{Stop-Transcript|Out-Null}catch{}}
