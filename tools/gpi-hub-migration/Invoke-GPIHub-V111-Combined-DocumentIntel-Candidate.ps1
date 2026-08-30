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
$ExpectedImage = 'sha256:646051f6b0434b20ad429dec18c5f7b2a7d017c0fdec94f4bd77eaa7375fabb3'
$ExpectedHelperSha = '2d2298b9c7e6315745d814e5437687caf463a44dec24d73d710b6d9e4e772117'
$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\v111-combined-document-intel-candidate\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
Start-Transcript -LiteralPath (Join-Path $DiagDir 'Invoke-GPIHub-V111-Combined-DocumentIntel-Candidate.txt') -Force | Out-Null

function Require([bool]$Condition,[string]$Message) { if (-not $Condition) { throw $Message } }

function Invoke-NativeText {
    param([string]$FilePath,[string[]]$Arguments,[switch]$AllowFailure)
    $token = [guid]::NewGuid().ToString('N')
    $err = Join-Path $env:TEMP "gpi-v111-$token.err.txt"
    $oldEap = $ErrorActionPreference
    $nativeVar = Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $oldNative = if ($null -ne $nativeVar) { $nativeVar.Value } else { $null }
    try {
        $ErrorActionPreference = 'Continue'
        if ($null -ne $nativeVar) { $PSNativeCommandUseErrorActionPreference = $false }
        $output = & $FilePath @Arguments 2> $err
        $code = $LASTEXITCODE
        $stdout = (@($output) | ForEach-Object { [string]$_ }) -join "`n"
        $stderr = if (Test-Path -LiteralPath $err) { Get-Content -LiteralPath $err -Raw -ErrorAction SilentlyContinue } else { '' }
        $result = [pscustomobject]@{ ExitCode=[int]$code; StdOut=$stdout; StdErr=$stderr }
        if (-not $AllowFailure -and $code -ne 0) { throw "$FilePath failed ($code).`n$stdout`n$stderr" }
        return $result
    }
    finally {
        $ErrorActionPreference = $oldEap
        if ($null -ne $nativeVar) { $PSNativeCommandUseErrorActionPreference = $oldNative }
        Remove-Item -LiteralPath $err -Force -ErrorAction SilentlyContinue
    }
}

function Get-KnownHosts([string]$Ip) {
    $root = Join-Path $OperationalRoot '.gpi-diagnostics'
    foreach ($file in @(Get-ChildItem -LiteralPath $root -Filter '*known_hosts*' -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)) {
        $probe = Invoke-NativeText 'ssh-keygen.exe' @('-F',$Ip,'-f',$file.FullName) -AllowFailure
        if ($probe.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($probe.StdOut)) { return $file.FullName }
    }
    throw "No verified known_hosts for $Ip"
}

function Invoke-Ssh([string]$Known,[string]$Text) {
    $token = [guid]::NewGuid().ToString('N')
    $err = Join-Path $env:TEMP "gpi-v111-ssh-$token.err.txt"
    $args = @('-i',$KeyPath,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',"UserKnownHostsFile=$Known",'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=20',"azureuser@$SourceIp",'bash -s')
    $oldEap = $ErrorActionPreference
    $nativeVar = Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $oldNative = if ($null -ne $nativeVar) { $nativeVar.Value } else { $null }
    try {
        $ErrorActionPreference = 'Continue'
        if ($null -ne $nativeVar) { $PSNativeCommandUseErrorActionPreference = $false }
        $output = (($Text -replace "`r`n","`n") | & ssh.exe @args 2> $err)
        $code = $LASTEXITCODE
        $stdout = (@($output) | ForEach-Object { [string]$_ }) -join "`n"
        $stderr = if (Test-Path -LiteralPath $err) { Get-Content -LiteralPath $err -Raw -ErrorAction SilentlyContinue } else { '' }
        return [pscustomobject]@{ ExitCode=[int]$code; StdOut=$stdout; StdErr=$stderr }
    }
    finally {
        $ErrorActionPreference = $oldEap
        if ($null -ne $nativeVar) { $PSNativeCommandUseErrorActionPreference = $oldNative }
        Remove-Item -LiteralPath $err -Force -ErrorAction SilentlyContinue
    }
}

function Section([string]$Title) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

try {
    Section 'V111 - COMBINED DOCUMENT INTELLIGENCE PARITY CANDIDATE'
    Write-Host 'Scope               : TEMPORARY SOURCE MODULE ONLY'
    Write-Host 'Primary authority   : PAGE 1 CLASSIFICATION UNCHANGED'
    Write-Host 'Primary refs        : EXPLICIT LABELS ONLY / NO SEMANTIC COERCION'
    Write-Host 'Supporting refs     : PAGES 2-5 / EXPLICIT LABELS ONLY'
    Write-Host 'PDF heuristics      : PYPDF / NO FITZ DEPENDENCY'
    Write-Host 'Source app/Mongo    : NO CHANGE / NO WRITE'
    Write-Host 'BC / SharePoint     : NO WRITES'
    Write-Host 'Production          : NOT TOUCHED'

    Require (Test-Path -LiteralPath $CorpusPath -PathType Leaf) "Missing W117105 corpus: $CorpusPath"
    $sha = (Get-FileHash -LiteralPath $CorpusPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Require ($sha -eq $CorpusSha) "W117105 corpus SHA mismatch: $sha"
    foreach ($cmd in 'ssh.exe','scp.exe','ssh-keygen.exe') { Require ($null -ne (Get-Command $cmd -ErrorAction SilentlyContinue)) "$cmd unavailable" }
    $Known = Get-KnownHosts $SourceIp
    $scp = Invoke-NativeText 'scp.exe' @('-i',$KeyPath,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',"UserKnownHostsFile=$Known",'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=20',$CorpusPath,"azureuser@${SourceIp}:/tmp/v111-w117105.pdf")
    Require ($scp.ExitCode -eq 0) 'W117105 staging failed.'

    $Remote = @'
set -euo pipefail
EXPECTED_IMAGE='sha256:646051f6b0434b20ad429dec18c5f7b2a7d017c0fdec94f4bd77eaa7375fabb3'
EXPECTED_HELPER='2d2298b9c7e6315745d814e5437687caf463a44dec24d73d710b6d9e4e772117'
EXPECTED_CORPUS='48410cadceaa411d65e51bd266be5c5942b4431cdede9e7a05b871e75a3a2c25'
DRIVE='b!sGwtDnGpU0SknFYQW3UCWWUMVN5OAqNNqrsMXnSKBw-YAHZMq-H6QZCZOp4jgXfD'
T1='016AISIVTXBUDWVTI5RNG3BSL2QLLIT6WC'
T2='016AISIVRQPIBPTWFQUBGZMQWMZ46GUFFT'
backend=$(docker ps --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
[ -n "$backend" ] || { echo 'Source backend missing.' >&2; exit 71; }
[ "$(docker inspect "$backend" -f '{{.Image}}')" = "$EXPECTED_IMAGE" ] || { echo 'Source image drift.' >&2; exit 72; }
[ "$(docker exec "$backend" sha256sum /app/services/document_intel_helpers.py | awk '{print $1}')" = "$EXPECTED_HELPER" ] || { echo 'Source helper drift.' >&2; exit 73; }
[ "$(sha256sum /tmp/v111-w117105.pdf | awk '{print $1}')" = "$EXPECTED_CORPUS" ] || { echo 'Corpus SHA mismatch.' >&2; exit 74; }
health=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=4); print(r.status)')
case "$health" in 2??|3??) ;; *) echo "Source unhealthy: $health" >&2; exit 75;; esac
echo V111_SOURCE_AUTHORITY=PASS

docker cp "$backend:/app/services/document_intel_helpers.py" /tmp/v111-helper.py
cat > /tmp/v111-patch.py <<'PY'
from pathlib import Path
p=Path('/tmp/v111-helper.py')
s=p.read_text(encoding='utf-8')
class_anchor='async def classify_document_with_ai(file_path: str, file_name: str) -> dict:\n'
if s.count(class_anchor)!=1: raise SystemExit('classify anchor count != 1')
insert=r'''
def _pypdf_first_page_text(file_path: str, max_chars: int = 3000) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        if not reader.pages:
            return ""
        return (reader.pages[0].extract_text() or "")[:max_chars]
    except Exception as exc:
        logger.debug("pypdf first-page text failed for %s: %s", file_path, exc)
        return ""


def _check_obvious_ap_invoice_pypdf(file_path: str, file_name: str) -> dict | None:
    fn_lower = file_name.lower()
    if not fn_lower.endswith('.pdf'):
        return None
    page_text = _pypdf_first_page_text(file_path, 3000)
    if not page_text:
        return None
    credit_matches = _CREDIT_MEMO_PATTERNS.findall(page_text)
    if credit_matches:
        fields = {"credit_memo_detected_by": "pypdf_text_pattern"}
        inv_m = _re.search(r'(?:credit\s+)?(?:invoice|memo)\s*#?\s*[:\s]*([A-Z0-9-]{2,20})', page_text, _re.IGNORECASE)
        amt_m = _re.search(r'(?:credit\s+memo\s+total|total|amount)[:\s]*-?\$?([\d,]+\.?\d*)', page_text, _re.IGNORECASE)
        if inv_m: fields['credit_memo_number'] = inv_m.group(1).strip()
        if amt_m: fields['amount'] = amt_m.group(1).strip()
        return {"suggested_job_type":"Credit_Memo","confidence":0.94,"model":"heuristic-credit-memo-pypdf","extracted_fields":fields}
    invoice_matches = _INVOICE_TEXT_PATTERNS.findall(page_text)
    if len(invoice_matches) >= 2 and not _PL_FILENAME_PATTERNS.search(fn_lower) and not _BOL_FILENAME_PATTERNS.search(fn_lower):
        fields = {"ap_invoice_detected_by":"pypdf_text_pattern"}
        inv_m = _re.search(r'invoice\s*#?\s*[:\s]*([A-Z0-9-]{2,20})', page_text, _re.IGNORECASE)
        amt_m = _re.search(r'(?:balance\s+due|amount\s+due|total)[:\s]*\$?([\d,]+\.?\d*)', page_text, _re.IGNORECASE)
        if inv_m: fields['invoice_number'] = inv_m.group(1).strip()
        if amt_m: fields['amount'] = amt_m.group(1).strip()
        return {"suggested_job_type":"AP_Invoice","confidence":0.92,"model":"heuristic-ap-invoice-pypdf","extracted_fields":fields}
    return None


def _extract_primary_labeled_references(file_path: str) -> tuple[dict, list]:
    text = _pypdf_first_page_text(file_path, 5000)
    if not text:
        return {}, []
    specs = [
        ('receipt_number', r'\bReceipt\s+(?:Number|No\.?|#)\s*[:#]?\s*([A-Z0-9-]{3,30})', 'Receipt Number'),
        ('reference_number', r'\bReference\s*#\s*[:#]?\s*([A-Z0-9-]{3,30})', 'Reference #'),
        ('shipment_number', r'\bShipment\s*#\s*[:#]?\s*([A-Z0-9-]{3,30})', 'Shipment #'),
        ('bol_number', r'\b(?:BOL|B/L|Bill\s+of\s+Lading)\s*(?:Number|No\.?|#)?\s*[:#]?\s*([A-Z0-9-]{3,30})', 'BOL'),
        ('load_number', r'\bLoad\s*#\s*[:#]?\s*([A-Z0-9-]{3,30})', 'Load #'),
        ('po_number', r'\b(?:PO|Purchase\s+Order)\s*(?:Number|No\.?|#)?\s*[:#]?\s*(W?[A-Z0-9-]{3,30})', 'PO'),
    ]
    refs = {}; evidence = []
    for field, pattern, label in specs:
        m = _re.search(pattern, text, _re.IGNORECASE)
        if not m: continue
        value = m.group(1).strip()
        refs[field] = value
        evidence.append({'field':field,'value':value,'printed_label':label,'page':1,'source':'pypdf_primary_label'})
    return refs, evidence


def _merge_primary_labeled_references(fields: dict, refs: dict, evidence: list) -> dict:
    out = dict(fields or {})
    conflicts = list(out.get('primary_reference_conflicts') or [])
    for key, value in (refs or {}).items():
        existing = out.get(key)
        if existing in (None,'',[],{}):
            out[key] = value
        elif str(existing).strip().casefold() != str(value).strip().casefold():
            conflicts.append({'field':key,'model_value':existing,'labeled_value':value})
            out[f'labeled_{key}'] = value
    if conflicts: out['primary_reference_conflicts'] = conflicts
    if evidence: out['primary_reference_evidence'] = evidence
    return out

_SUPPORTING_REFERENCE_ALIASES = {
    'receipt_number':'receipt_number','warehouse_receipt_number':'receipt_number','reference_number':'reference_number',
    'shipment_number':'shipment_number','bol_number':'bol_number','bill_of_lading_number':'bol_number',
    'pro_number':'pro_number','load_number':'load_number','tracking_number':'tracking_number',
    'po_number':'po_number','purchase_order_number':'po_number','customer_po':'po_number','order_number':'order_number'
}
_SUPPORTING_REFERENCE_PROMPT = """Extract reference metadata from SUPPORTING pages only. Do not classify. Extract only values explicitly printed next to recognizable labels. Preserve semantics: Receipt Number -> receipt_number; Reference # -> reference_number; Shipment # -> shipment_number; BOL/Bill of Lading -> bol_number; PRO -> pro_number; Load # -> load_number; Tracking -> tracking_number; PO/Purchase Order/Customer PO -> po_number; Order -> order_number. Never infer one label from another. JSON only: {\"references\":{...},\"evidence\":[{\"field\":\"...\",\"value\":\"...\",\"printed_label\":\"...\",\"page_in_supporting_pdf\":1}]}."""

def _merge_supporting_reference_fields(primary_fields: dict, supporting: dict) -> dict:
    out = dict(primary_fields or {})
    conflicts = list(out.get('supporting_reference_conflicts') or [])
    refs = supporting.get('references',supporting) if isinstance(supporting,dict) else {}
    if not isinstance(refs,dict): return out
    for raw_key,value in refs.items():
        key = _SUPPORTING_REFERENCE_ALIASES.get(str(raw_key).strip().lower())
        if not key or value in (None,'',[],{}): continue
        values = value if isinstance(value,list) else [value]
        for candidate in values:
            if candidate in (None,''): continue
            candidate = str(candidate).strip(); existing = out.get(key)
            if existing in (None,'',[],{}): out[key] = candidate; continue
            existing_values = existing if isinstance(existing,list) else [existing]
            if any(str(x).strip().casefold()==candidate.casefold() for x in existing_values): continue
            skey = f'supporting_{key}s'; bucket = out.get(skey)
            if not isinstance(bucket,list): bucket = [] if bucket in (None,'') else [bucket]
            if not any(str(x).strip().casefold()==candidate.casefold() for x in bucket): bucket.append(candidate)
            out[skey] = bucket; conflicts.append({'field':key,'primary':existing,'supporting':candidate})
    if conflicts: out['supporting_reference_conflicts'] = conflicts
    evidence = supporting.get('evidence') if isinstance(supporting,dict) else None
    if evidence: out['supporting_reference_evidence'] = evidence
    return out

async def _call_llm_for_supporting_references(file_path: str, page_count: int) -> dict:
    if page_count <= 1 or not EMERGENT_LLM_KEY: return {}
    from emergentintegrations.llm.chat import LlmChat, UserMessage, FileContentWithMimeType
    from pypdf import PdfReader, PdfWriter
    import tempfile
    reader = PdfReader(file_path)
    if len(reader.pages) <= 1: return {}
    writer = PdfWriter()
    for idx in range(1,min(len(reader.pages),5)): writer.add_page(reader.pages[idx])
    if len(writer.pages) == 0: return {}
    fd,support_path = tempfile.mkstemp(suffix='.pdf'); os.close(fd)
    try:
        with open(support_path,'wb') as f: writer.write(f)
        chat = LlmChat(api_key=EMERGENT_LLM_KEY,session_id=f'support-refs-{uuid.uuid4()}',system_message=_SUPPORTING_REFERENCE_PROMPT).with_model('gemini','gemini-2.5-pro')
        msg = UserMessage(text='Extract only explicitly labeled supporting-page references. JSON only.',file_contents=[FileContentWithMimeType(file_path=support_path,mime_type='application/pdf')])
        response = (await chat.send_message(msg)).strip()
        if response.startswith('```'): response = re.sub(r'^```(?:json)?\s*|\s*```$','',response,flags=re.I|re.S).strip()
        parsed = json.loads(response)
        return parsed if isinstance(parsed,dict) else {}
    finally:
        try: os.remove(support_path)
        except Exception: pass

'''
s=s.replace(class_anchor,insert+class_anchor,1)
old='''        _check_obvious_ap_invoice(file_path, file_name)\n        or _check_obvious_packing_list(file_path, file_name)'''
new='''        _check_obvious_ap_invoice_pypdf(file_path, file_name)\n        or _check_obvious_packing_list(file_path, file_name)'''
if s.count(old)!=1: raise SystemExit('heuristic expression anchor count != 1')
s=s.replace(old,new,1)
needle='''        extracted = result.get("extracted_fields", {})\n        logger.info('''
replacement='''        extracted = result.get("extracted_fields", {})\n        if result.get("document_type") in {"Warehouse_Receipt","Shipping_Document","Freight_Document","Order_Confirmation"}:\n            primary_refs, primary_evidence = _extract_primary_labeled_references(file_path)\n            extracted = _merge_primary_labeled_references(extracted, primary_refs, primary_evidence)\n            if page_count > 1:\n                try:\n                    supporting = await _call_llm_for_supporting_references(file_path, page_count)\n                    extracted = _merge_supporting_reference_fields(extracted, supporting)\n                except Exception as supporting_error:\n                    logger.warning("Supporting reference pass failed for '%s': %s", file_name, supporting_error)\n            result["extracted_fields"] = extracted\n        logger.info('''
if s.count(needle)!=1: raise SystemExit('result merge anchor count != 1')
s=s.replace(needle,replacement,1)
p.write_text(s,encoding='utf-8')
print('V111_PATCH_APPLIED=PASS')
PY
python3 /tmp/v111-patch.py
python3 -m py_compile /tmp/v111-helper.py
patched_sha=$(sha256sum /tmp/v111-helper.py | awk '{print $1}')
echo "V111_PATCHED_HELPER_SHA=$patched_sha"
docker cp /tmp/v111-helper.py "$backend:/tmp/v111-helper.py" >/dev/null
docker cp /tmp/v111-w117105.pdf "$backend:/tmp/v111-w117105.pdf" >/dev/null

cat > /tmp/v111-probe.py <<'PY'
import asyncio, importlib.util, json, os, sys, tempfile, types
from pathlib import Path
import httpx

async def empty(*args,**kwargs): return ''
fb=types.ModuleType('services.classification_feedback_service'); fb.build_few_shot_prompt_section=empty; fb.build_vendor_hints_prompt_section=empty; sys.modules['services.classification_feedback_service']=fb
loop=types.ModuleType('services.feedback_loop_service'); loop.build_feedback_context_for_prompt=empty; sys.modules['services.feedback_loop_service']=loop
vendor=types.ModuleType('services.vendor_inference_service'); vendor.infer_vendor=lambda *a,**k:(None,None); sys.modules['services.vendor_inference_service']=vendor

spec=importlib.util.spec_from_file_location('v111_candidate','/tmp/v111-helper.py'); candidate=importlib.util.module_from_spec(spec); spec.loader.exec_module(candidate)
from services.sharepoint_service import _get_graph_token

def has(obj,t):
    t=t.lower()
    if isinstance(obj,dict): return any(has(k,t) or has(v,t) for k,v in obj.items())
    if isinstance(obj,(list,tuple)): return any(has(v,t) for v in obj)
    return t in str(obj).lower()

def typ(obj): return obj.get('suggested_job_type') if isinstance(obj,dict) else None

async def main():
    w='/tmp/v111-w117105.pdf'; wn='W117105_Strategic Warehousing_122625_.pdf'
    wr=await candidate.classify_document_with_ai(w,wn)
    print('V111_W117105='+json.dumps(wr,sort_keys=True,default=str))
    checks={
      'class':typ(wr)=='Warehouse_Receipt',
      'po':has(wr,'W117105'),
      'receipt':has(wr,'962222-1'),
      'reference':has(wr,'815734'),
      'shipment':has(wr,'ER25-1560')
    }
    print('V111_W117105_CHECKS='+json.dumps(checks,sort_keys=True))

    token=await _get_graph_token(); headers={'Authorization':f'Bearer {token}'}
    drive=os.environ['V111_DRIVE']; items=[os.environ['V111_T1'],os.environ['V111_T2']]
    names=['W118864_TUMALO_0312515_08252026.pdf','W118897_TUMALO_0312516_08262026.pdf']
    tumalo=[]
    async with httpx.AsyncClient(timeout=90.0,follow_redirects=True) as c:
        for item,name in zip(items,names):
            r=await c.get(f'https://graph.microsoft.com/v1.0/drives/{drive}/items/{item}/content',headers=headers); r.raise_for_status()
            fd,path=tempfile.mkstemp(suffix='.pdf'); os.close(fd); Path(path).write_bytes(r.content)
            try:
                guard=candidate._check_obvious_ap_invoice_pypdf(path,name)
                tumalo.append({'name':name,'guard':guard})
                print('V111_TUMALO='+json.dumps(tumalo[-1],sort_keys=True,default=str))
            finally:
                try: os.remove(path)
                except Exception: pass
    tumalo_ok=all(x['guard'] and x['guard'].get('suggested_job_type')=='AP_Invoice' for x in tumalo)
    print('V111_TUMALO_GUARD='+('PASS' if tumalo_ok else 'FAIL'))
    print('V111_COMBINED_CANDIDATE='+('PASS' if all(checks.values()) and tumalo_ok else 'FAIL'))

asyncio.run(main())
PY

docker cp /tmp/v111-probe.py "$backend:/tmp/v111-probe.py" >/dev/null
rm -f /tmp/v111-probe.py
set +e
out=$(docker exec -e PYTHONPATH=/app -w /app -e V111_DRIVE="$DRIVE" -e V111_T1="$T1" -e V111_T2="$T2" "$backend" python /tmp/v111-probe.py 2>&1)
code=$?
set -e
printf '%s\n' "$out"
docker exec "$backend" rm -f /tmp/v111-helper.py /tmp/v111-probe.py /tmp/v111-w117105.pdf >/dev/null 2>&1 || true
[ "$code" -eq 0 ] || { echo "V111 probe failed: $code" >&2; exit 76; }
printf '%s\n' "$out" | grep -Fq 'V111_COMBINED_CANDIDATE=PASS' || { echo 'V111 combined candidate did not pass.' >&2; exit 77; }
health_after=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=4); print(r.status)')
case "$health_after" in 2??|3??) ;; *) echo "Source unhealthy after probe: $health_after" >&2; exit 78;; esac
echo V111_SOURCE_RUNTIME_UNCHANGED=PASS
'@

    $r = Invoke-Ssh $Known $Remote
    Set-Content -LiteralPath (Join-Path $DiagDir 'source-v111.txt') -Value $r.StdOut -Encoding utf8
    if ($r.StdOut) { Write-Host $r.StdOut }
    if ($r.StdErr) { Write-Host $r.StdErr -ForegroundColor DarkYellow }
    Require ($r.ExitCode -eq 0) "V111 failed with exit code $($r.ExitCode)."
    foreach ($marker in 'V111_SOURCE_AUTHORITY=PASS','V111_PATCH_APPLIED=PASS','V111_COMBINED_CANDIDATE=PASS','V111_SOURCE_RUNTIME_UNCHANGED=PASS') {
        Require ($r.StdOut -match [regex]::Escape($marker)) "Missing V111 marker: $marker"
    }

    # Export exact candidate helper from source host to controller diagnostics for later SHA-gated durable target overlay.
    $remoteExport = Invoke-Ssh $Known "backend=`$(docker ps --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n1); docker cp \"`$backend:/app/services/document_intel_helpers.py\" /tmp/v111-baseline-helper.py >/dev/null; echo V111_BASELINE_EXPORT_READY=PASS"
    Require ($remoteExport.ExitCode -eq 0) 'V111 baseline export preparation failed.'

    Section 'V111 RESULT'
    Write-Host 'V111_COMBINED_DOCUMENT_INTEL_CANDIDATE_TEST=PASS' -ForegroundColor Green
    Write-Host 'Next: create exact code delta/durable target overlay only from the proven candidate implementation; source operational tree remains unchanged.' -ForegroundColor Yellow
    Write-Host "Diagnostics: $DiagDir"
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
