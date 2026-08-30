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
$TargetApp = '/gpi-hub-data/apps/gpi-hub'
$BackendPort = 18005
$FrontendPort = 18080

$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\gui-truth-audit\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null

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
    $stderrFile = Join-Path $env:TEMP "gpi-gui-audit-$token.err.txt"
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
    $stderrFile = Join-Path $env:TEMP "gpi-gui-audit-ssh-$token.err.txt"
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

Write-Section 'GPI HUB GUI TRUTH / FUNCTION / REPORTING AUDIT — READ ONLY'
Write-Host "Target VM       : $TargetIp"
Write-Host "Target app      : $TargetApp"
Write-Host 'Mongo writes    : NONE'
Write-Host 'BC writes       : NONE'
Write-Host 'SharePoint writes: NONE'
Write-Host 'Production      : NOT TOUCHED'
Write-Host 'Traffic cutover : NONE'

Require (Test-Path -LiteralPath $KeyPath -PathType Leaf) "SSH key missing: $KeyPath"
$KnownHosts = Get-KnownHostsForIp -Ip $TargetIp

$Remote = @'
set -euo pipefail
APP='/gpi-hub-data/apps/gpi-hub'
OUT='/tmp/gpi-gui-truth-audit.json'
[ -d "$APP" ] || { echo "Target app missing: $APP" >&2; exit 31; }
command -v python3 >/dev/null 2>&1 || { echo 'python3 missing' >&2; exit 32; }

python3 - "$APP" "$OUT" <<'PY'
import ast, json, os, re, sys
from pathlib import Path

app = Path(sys.argv[1])
out = Path(sys.argv[2])
frontend = app / 'frontend' / 'src'
backend = app / 'backend'

TEXT_EXTS = {'.js','.jsx','.ts','.tsx','.py'}
MAX_BYTES = 2_000_000

status_terms = [
    'Completed','Complete','Ready','Ready to Post','ReadyForPost','No action required',
    'Needs Review','Blocked','Failed','Error','Warning','Validated','Validation','Routed',
    'Posted','Linked','SkippedDuplicate','Duplicate','Captured','Processing','Ambiguous',
    'Automation','Automation Rate','Workflow','Readiness','100%','Success','Healthy'
]

frontend_files=[]
frontend_routes=[]
frontend_api_calls=[]
ui_status_hits=[]
reporting_hits=[]
button_action_hits=[]
backend_endpoints=[]
python_parse_errors=[]

string_re = re.compile(r"(['\"])(.{1,180}?)\1")
route_patterns = [
    re.compile(r'<Route[^>]+path\s*=\s*["\']([^"\']+)["\']', re.I),
    re.compile(r'path\s*:\s*["\']([^"\']+)["\']', re.I),
]
api_patterns = [
    re.compile(r'fetch\s*\(\s*([`"\'])(/api/[^`"\']+)\1'),
    re.compile(r'axios\.(get|post|put|patch|delete)\s*\(\s*([`"\'])(/api/[^`"\']+)\2', re.I),
    re.compile(r'\.(get|post|put|patch|delete)\s*\(\s*([`"\'])(/api/[^`"\']+)\2', re.I),
]
button_re = re.compile(r'(onClick|onSubmit|mutation|retry|reprocess|approve|post|route|delete|archive|save|sync|evaluate)', re.I)
report_re = re.compile(r'(dashboard|metric|analytics|report|count|rate|aging|backlog|trend|summary)', re.I)

if frontend.exists():
    for p in frontend.rglob('*'):
        if not p.is_file() or p.suffix.lower() not in {'.js','.jsx','.ts','.tsx'}:
            continue
        try:
            if p.stat().st_size > MAX_BYTES: continue
            text=p.read_text(errors='replace')
        except Exception:
            continue
        rel=str(p.relative_to(app))
        frontend_files.append(rel)
        for pat in route_patterns:
            for m in pat.finditer(text):
                frontend_routes.append({'file':rel,'route':m.group(1)})
        for pat in api_patterns:
            for m in pat.finditer(text):
                groups=m.groups()
                method='UNKNOWN'
                path=''
                if len(groups)==2:
                    if groups[0].lower() in {'get','post','put','patch','delete'}:
                        method=groups[0].upper(); path=groups[1]
                    else:
                        path=groups[1]
                elif len(groups)>=3:
                    method=groups[0].upper(); path=groups[2]
                if not path: path=groups[-1]
                frontend_api_calls.append({'file':rel,'method':method,'path':path})
        low=text.lower()
        for term in status_terms:
            if term.lower() in low:
                ui_status_hits.append({'file':rel,'term':term})
        if report_re.search(text):
            reporting_hits.append(rel)
        if button_re.search(text):
            button_action_hits.append(rel)

# Backend FastAPI static inventory.
if backend.exists():
    for p in backend.rglob('*.py'):
        try:
            if p.stat().st_size > MAX_BYTES: continue
            text=p.read_text(errors='replace')
            tree=ast.parse(text, filename=str(p))
        except Exception as e:
            python_parse_errors.append({'file':str(p.relative_to(app)),'error':str(e)})
            continue
        rel=str(p.relative_to(app))
        router_prefix={}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                fn=node.value.func
                fn_name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else '')
                if fn_name=='APIRouter':
                    prefix=''
                    for kw in node.value.keywords:
                        if kw.arg=='prefix' and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value,str):
                            prefix=kw.value.value
                    for target in node.targets:
                        if isinstance(target,ast.Name): router_prefix[target.id]=prefix
        for node in tree.body:
            if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)): continue
            for dec in node.decorator_list:
                if not isinstance(dec,ast.Call) or not isinstance(dec.func,ast.Attribute): continue
                method=dec.func.attr.lower()
                if method not in {'get','post','put','patch','delete','options','head'}: continue
                base=''
                if isinstance(dec.func.value,ast.Name): base=router_prefix.get(dec.func.value.id,'')
                path=''
                if dec.args and isinstance(dec.args[0],ast.Constant) and isinstance(dec.args[0].value,str):
                    path=dec.args[0].value
                full=(base.rstrip('/') + '/' + path.lstrip('/')) if path else (base or '/')
                mutating=method in {'post','put','patch','delete'}
                backend_endpoints.append({
                    'file':rel,'method':method.upper(),'path':full,'handler':node.name,
                    'mutating':mutating
                })

# Normalize/dedupe.
def uniq(items, key):
    seen=set(); out=[]
    for x in items:
        k=key(x)
        if k in seen: continue
        seen.add(k); out.append(x)
    return out

frontend_routes=uniq(frontend_routes, lambda x:(x['file'],x['route']))
frontend_api_calls=uniq(frontend_api_calls, lambda x:(x['file'],x['method'],x['path']))
ui_status_hits=uniq(ui_status_hits, lambda x:(x['file'],x['term']))
backend_endpoints=uniq(backend_endpoints, lambda x:(x['method'],x['path'],x['handler']))
reporting_hits=sorted(set(reporting_hits))
button_action_hits=sorted(set(button_action_hits))

# Cross-reference frontend /api paths to backend endpoint patterns using coarse literal prefix matching.
backend_paths=[e['path'] for e in backend_endpoints]
frontend_unmatched=[]
for call in frontend_api_calls:
    raw=call['path']
    literal=re.split(r'[$:{]',raw,1)[0].rstrip('/')
    if literal and not any(bp.startswith(literal) or literal.startswith(bp.split('{',1)[0].rstrip('/')) for bp in backend_paths):
        frontend_unmatched.append(call)

openapi=None
try:
    import urllib.request
    with urllib.request.urlopen('http://127.0.0.1:18005/openapi.json', timeout=3) as r:
        openapi=json.load(r)
except Exception as e:
    openapi={'unavailable':str(e)}

summary={
    'frontend_file_count':len(frontend_files),
    'frontend_route_count':len(frontend_routes),
    'frontend_api_call_count':len(frontend_api_calls),
    'backend_endpoint_count':len(backend_endpoints),
    'backend_mutating_endpoint_count':sum(1 for e in backend_endpoints if e['mutating']),
    'ui_status_term_hit_count':len(ui_status_hits),
    'reporting_candidate_file_count':len(reporting_hits),
    'button_action_candidate_file_count':len(button_action_hits),
    'frontend_unmatched_api_count':len(frontend_unmatched),
    'python_parse_error_count':len(python_parse_errors),
}

result={
    'schema_version':'1.0',
    'audit_type':'read_only_gui_truth_function_reporting_inventory',
    'app_root':str(app),
    'summary':summary,
    'frontend_routes':frontend_routes,
    'frontend_api_calls':frontend_api_calls,
    'frontend_unmatched_api_calls':frontend_unmatched,
    'backend_endpoints':backend_endpoints,
    'ui_status_terms':ui_status_hits,
    'reporting_candidate_files':reporting_hits,
    'button_action_candidate_files':button_action_hits,
    'python_parse_errors':python_parse_errors,
    'openapi':openapi,
}
out.write_text(json.dumps(result,indent=2,sort_keys=True))
print(json.dumps(summary,sort_keys=True))
PY

cat "$OUT"
rm -f "$OUT"
PYEOF=unused
'@

$result = Invoke-SshScript -Ip $TargetIp -KnownHosts $KnownHosts -ScriptText $Remote
Require ($result.ExitCode -eq 0) "GUI truth audit failed.`n$($result.StdOut)`n$($result.StdErr)"

$raw = $result.StdOut
$firstBrace = $raw.IndexOf('{')
Require ($firstBrace -ge 0) 'Audit did not return JSON.'
# The first JSON object is the one-line summary; the full audit is the final multi-line object.
$fullStart = $raw.IndexOf("{`n", $firstBrace)
if ($fullStart -lt 0) { $fullStart = $raw.LastIndexOf('{') }
$fullJson = $raw.Substring($fullStart)
$audit = $fullJson | ConvertFrom-Json -Depth 100

$JsonPath = Join-Path $DiagDir 'gui-truth-audit.json'
$SummaryPath = Join-Path $DiagDir 'gui-truth-audit-summary.txt'
$EndpointCsv = Join-Path $DiagDir 'backend-endpoints.csv'
$FrontendApiCsv = Join-Path $DiagDir 'frontend-api-calls.csv'
$StatusCsv = Join-Path $DiagDir 'ui-status-terms.csv'

$fullJson | Set-Content -LiteralPath $JsonPath -Encoding utf8
$audit.backend_endpoints | Export-Csv -LiteralPath $EndpointCsv -NoTypeInformation -Encoding utf8
$audit.frontend_api_calls | Export-Csv -LiteralPath $FrontendApiCsv -NoTypeInformation -Encoding utf8
$audit.ui_status_terms | Export-Csv -LiteralPath $StatusCsv -NoTypeInformation -Encoding utf8

$summary = @()
$summary += "Frontend files                    : $($audit.summary.frontend_file_count)"
$summary += "Frontend routes                   : $($audit.summary.frontend_route_count)"
$summary += "Frontend API calls                : $($audit.summary.frontend_api_call_count)"
$summary += "Backend endpoints                 : $($audit.summary.backend_endpoint_count)"
$summary += "Mutating backend endpoints        : $($audit.summary.backend_mutating_endpoint_count)"
$summary += "UI status/label hits              : $($audit.summary.ui_status_term_hit_count)"
$summary += "Reporting candidate files         : $($audit.summary.reporting_candidate_file_count)"
$summary += "Action/button candidate files     : $($audit.summary.button_action_candidate_file_count)"
$summary += "Frontend unmatched API calls      : $($audit.summary.frontend_unmatched_api_count)"
$summary += "Python parse errors               : $($audit.summary.python_parse_error_count)"
$summary += ""
$summary += "JSON                              : $JsonPath"
$summary += "Backend endpoints CSV             : $EndpointCsv"
$summary += "Frontend API CSV                  : $FrontendApiCsv"
$summary += "UI status terms CSV               : $StatusCsv"
$summary | Set-Content -LiteralPath $SummaryPath -Encoding utf8

Write-Section 'GUI TRUTH AUDIT RESULT'
$summary | ForEach-Object { Write-Host $_ }
Write-Host ''
Write-Host 'GPI_GUI_TRUTH_AUDIT_READ_ONLY=PASS' -ForegroundColor Green
Write-Host 'No Mongo, BC, SharePoint, Production, or traffic mutations were performed.' -ForegroundColor Green
