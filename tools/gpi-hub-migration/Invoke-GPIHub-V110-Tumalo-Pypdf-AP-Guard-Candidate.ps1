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
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\v110-tumalo-pypdf-ap-guard\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
Start-Transcript -LiteralPath (Join-Path $DiagDir 'Invoke-GPIHub-V110-Tumalo-Pypdf-AP-Guard-Candidate.txt') -Force | Out-Null

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
    $Token = [guid]::NewGuid().ToString('N')
    $ErrFile = Join-Path $env:TEMP "gpi-v110-$Token.err.txt"
    $OldEap = $ErrorActionPreference
    $NativeVar = Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $OldNative = if ($null -ne $NativeVar) { $NativeVar.Value } else { $null }
    try {
        $ErrorActionPreference = 'Continue'
        if ($null -ne $NativeVar) { $PSNativeCommandUseErrorActionPreference = $false }
        $Output = & $FilePath @Arguments 2> $ErrFile
        $Code = $LASTEXITCODE
        $StdOut = (@($Output) | ForEach-Object { [string]$_ }) -join "`n"
        $StdErr = if (Test-Path -LiteralPath $ErrFile) { Get-Content -LiteralPath $ErrFile -Raw -ErrorAction SilentlyContinue } else { '' }
        $Result = [pscustomobject]@{ ExitCode=[int]$Code; StdOut=[string]$StdOut; StdErr=[string]$StdErr }
        if (-not $AllowFailure -and $Code -ne 0) { throw "$FilePath failed ($Code).`n$StdOut`n$StdErr" }
        return $Result
    }
    finally {
        $ErrorActionPreference = $OldEap
        if ($null -ne $NativeVar) { $PSNativeCommandUseErrorActionPreference = $OldNative }
        Remove-Item -LiteralPath $ErrFile -Force -ErrorAction SilentlyContinue
    }
}

function Get-KnownHostsForIp {
    param([Parameter(Mandatory)][string]$Ip)
    $DiagRoot = Join-Path $OperationalRoot '.gpi-diagnostics'
    foreach ($File in @(Get-ChildItem -LiteralPath $DiagRoot -Filter '*known_hosts*' -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)) {
        $Probe = Invoke-NativeText -FilePath 'ssh-keygen.exe' -Arguments @('-F',$Ip,'-f',$File.FullName) -AllowFailure
        if ($Probe.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($Probe.StdOut)) { return $File.FullName }
    }
    throw "No verified known_hosts for $Ip"
}

function Invoke-SshScript {
    param([Parameter(Mandatory)][string]$KnownHosts,[Parameter(Mandatory)][string]$ScriptText)
    $Token = [guid]::NewGuid().ToString('N')
    $ErrFile = Join-Path $env:TEMP "gpi-v110-ssh-$Token.err.txt"
    $Args = @('-i',$KeyPath,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',"UserKnownHostsFile=$KnownHosts",'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=20',"azureuser@$SourceIp",'bash -s')
    $OldEap = $ErrorActionPreference
    $NativeVar = Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $OldNative = if ($null -ne $NativeVar) { $NativeVar.Value } else { $null }
    try {
        $ErrorActionPreference = 'Continue'
        if ($null -ne $NativeVar) { $PSNativeCommandUseErrorActionPreference = $false }
        $Output = (($ScriptText -replace "`r`n","`n") | & ssh.exe @Args 2> $ErrFile)
        $Code = $LASTEXITCODE
        $StdOut = (@($Output) | ForEach-Object { [string]$_ }) -join "`n"
        $StdErr = if (Test-Path -LiteralPath $ErrFile) { Get-Content -LiteralPath $ErrFile -Raw -ErrorAction SilentlyContinue } else { '' }
        return [pscustomobject]@{ ExitCode=[int]$Code; StdOut=[string]$StdOut; StdErr=[string]$StdErr }
    }
    finally {
        $ErrorActionPreference = $OldEap
        if ($null -ne $NativeVar) { $PSNativeCommandUseErrorActionPreference = $OldNative }
        Remove-Item -LiteralPath $ErrFile -Force -ErrorAction SilentlyContinue
    }
}

function Section([string]$Title) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

try {
    Section 'V110 - TUMALO PYPDF AP GUARD CANDIDATE'
    Write-Host 'Classification       : AP PARITY BLOCKER CANDIDATE'
    Write-Host 'Purpose              : prove current fitz-based PDF guard is inert and pypdf restores intended deterministic semantics'
    Write-Host 'Authoritative corpus : two legacy Tumalo payable invoices'
    Write-Host 'Execution            : source temporary files / read-only Graph / no app replacement'
    Write-Host 'BC / SharePoint      : NO WRITES'
    Write-Host 'Production           : NOT TOUCHED'

    foreach ($Command in @('ssh.exe','ssh-keygen.exe')) {
        Require ($null -ne (Get-Command $Command -ErrorAction SilentlyContinue)) "$Command unavailable"
    }
    $KnownHosts = Get-KnownHostsForIp -Ip $SourceIp

    $Remote = @'
set -euo pipefail
EXPECTED_IMAGE='sha256:646051f6b0434b20ad429dec18c5f7b2a7d017c0fdec94f4bd77eaa7375fabb3'
EXPECTED_HELPER='2d2298b9c7e6315745d814e5437687caf463a44dec24d73d710b6d9e4e772117'
DRIVE='b!sGwtDnGpU0SknFYQW3UCWWUMVN5OAqNNqrsMXnSKBw-YAHZMq-H6QZCZOp4jgXfD'
ITEM1='016AISIVTXBUDWVTI5RNG3BSL2QLLIT6WC'
ITEM2='016AISIVRQPIBPTWFQUBGZMQWMZ46GUFFT'
backend=$(docker ps --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
[ -n "$backend" ] || { echo 'Source backend missing.' >&2; exit 71; }
[ "$(docker inspect "$backend" -f '{{.Image}}')" = "$EXPECTED_IMAGE" ] || { echo 'Source image drift.' >&2; exit 72; }
[ "$(docker exec "$backend" sha256sum /app/services/document_intel_helpers.py | awk '{print $1}')" = "$EXPECTED_HELPER" ] || { echo 'Source helper drift.' >&2; exit 73; }
health=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=4); print(r.status)')
case "$health" in
  2??|3??) ;;
  *) echo "Source backend unhealthy: $health" >&2; exit 74;;
esac

cat > /tmp/v110.py <<'PY'
import asyncio, json, os, tempfile
from pathlib import Path
import httpx
from pypdf import PdfReader
from services.sharepoint_service import _get_graph_token
from services.document_intel_helpers import _check_obvious_ap_invoice, _INVOICE_TEXT_PATTERNS, _CREDIT_MEMO_PATTERNS

DRIVE=os.environ['V110_DRIVE']
ITEMS=[os.environ['V110_ITEM1'],os.environ['V110_ITEM2']]
NAMES=['W118864_TUMALO_0312515_08252026.pdf','W118897_TUMALO_0312516_08262026.pdf']

async def main():
    token=await _get_graph_token()
    headers={'Authorization':f'Bearer {token}'}
    rows=[]
    async with httpx.AsyncClient(timeout=90.0,follow_redirects=True) as client:
        for item,name in zip(ITEMS,NAMES):
            response=await client.get(f'https://graph.microsoft.com/v1.0/drives/{DRIVE}/items/{item}/content',headers=headers)
            response.raise_for_status()
            fd,path=tempfile.mkstemp(suffix='.pdf')
            os.close(fd)
            Path(path).write_bytes(response.content)
            try:
                baseline=_check_obvious_ap_invoice(path,name)
                text=(PdfReader(path).pages[0].extract_text() or '')[:3000]
                invoice_matches=_INVOICE_TEXT_PATTERNS.findall(text)
                credit_matches=_CREDIT_MEMO_PATTERNS.findall(text)
                candidate=None
                if not credit_matches and len(invoice_matches)>=2:
                    candidate={
                        'suggested_job_type':'AP_Invoice',
                        'confidence':0.92,
                        'model':'candidate-pypdf-ap-invoice-text',
                        'indicator_count':len(invoice_matches),
                    }
                row={
                    'name':name,
                    'page1_chars':len(text),
                    'invoice_indicators':invoice_matches,
                    'invoice_indicator_count':len(invoice_matches),
                    'credit_indicator_count':len(credit_matches),
                    'baseline_guard':baseline,
                    'candidate_guard':candidate,
                }
                rows.append(row)
                print('V110_TUMALO_ROW='+json.dumps(row,sort_keys=True,default=str))
            finally:
                try: os.remove(path)
                except Exception: pass

    broken=all(r['baseline_guard'] is None and r['invoice_indicator_count']>=2 and r['credit_indicator_count']==0 for r in rows)
    candidate=all(r['candidate_guard'] and r['candidate_guard']['suggested_job_type']=='AP_Invoice' for r in rows)
    print('V110_BASELINE_FITZ_GUARD_BROKEN='+('PROVEN' if broken else 'NOT_PROVEN'))
    print('V110_PYPDF_AP_GUARD_CANDIDATE='+('PASS' if candidate else 'FAIL'))
    print('V110_TUMALO_PYPDF_SEMANTICS='+('PASS' if broken and candidate else 'INCOMPLETE'))

asyncio.run(main())
PY

docker cp /tmp/v110.py "$backend:/tmp/v110.py" >/dev/null
rm -f /tmp/v110.py
set +e
out=$(docker exec -e PYTHONPATH=/app -w /app -e V110_DRIVE="$DRIVE" -e V110_ITEM1="$ITEM1" -e V110_ITEM2="$ITEM2" "$backend" python /tmp/v110.py 2>&1)
code=$?
set -e
printf '%s\n' "$out"
docker exec "$backend" rm -f /tmp/v110.py >/dev/null 2>&1 || true
[ "$code" -eq 0 ] || { echo "V110 probe failed: $code" >&2; exit 75; }
printf '%s\n' "$out" | grep -Fq 'V110_TUMALO_PYPDF_SEMANTICS=PASS' || { echo 'V110 candidate semantics did not pass.' >&2; exit 76; }
health_after=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=4); print(r.status)')
case "$health_after" in
  2??|3??) ;;
  *) echo "Source backend unhealthy after V110: $health_after" >&2; exit 77;;
esac
echo V110_SOURCE_RUNTIME_UNCHANGED=PASS
'@

    $Result = Invoke-SshScript -KnownHosts $KnownHosts -ScriptText $Remote
    if ($Result.StdOut) { Write-Host $Result.StdOut }
    if ($Result.StdErr) { Write-Host $Result.StdErr -ForegroundColor DarkYellow }
    Set-Content -LiteralPath (Join-Path $DiagDir 'v110-source.txt') -Value $Result.StdOut -Encoding utf8

    Require ($Result.ExitCode -eq 0) "V110 failed with exit code $($Result.ExitCode)"
    Require ($Result.StdOut -match 'V110_TUMALO_PYPDF_SEMANTICS=PASS') 'V110 candidate did not pass'
    Require ($Result.StdOut -match 'V110_SOURCE_RUNTIME_UNCHANGED=PASS') 'V110 runtime marker missing'

    Section 'V110 RESULT'
    Write-Host 'V110_TUMALO_PYPDF_AP_GUARD_CANDIDATE_TEST=PASS' -ForegroundColor Green
    Write-Host "Diagnostics: $DiagDir"
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
