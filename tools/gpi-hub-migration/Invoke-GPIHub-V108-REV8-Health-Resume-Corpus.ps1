#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$Rev7 = Join-Path $ToolRoot 'Invoke-GPIHub-V108-REV7-Safety-Resume-Corpus.ps1'
if (-not (Test-Path -LiteralPath $Rev7 -PathType Leaf)) { throw "V108 REV7 source missing: $Rev7" }

$Raw = Get-Content -LiteralPath $Rev7 -Raw

$TargetOld = @'
health=$(docker exec "$backend" python - <<'PY'
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8001/api/health', timeout=4) as r: print(r.status)
PY
)
[ "$health" -ge 200 ] && [ "$health" -lt 400 ] || { echo "Backend health failed: $health" >&2; exit 58; }
'@
$TargetNew = @'
health=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health", timeout=4); print(r.status); r.close()')
case "$health" in ''|*[!0-9]*) echo "Backend health returned non-numeric value: $health" >&2; exit 58;; esac
[ "$health" -ge 200 ] && [ "$health" -lt 400 ] || { echo "Backend health failed: $health" >&2; exit 58; }
'@

$SourceBeforeOld = @'
health_before=$(docker exec "$backend" python - <<'PY'
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8001/api/health', timeout=4) as r: print(r.status)
PY
)
[ "$health_before" -ge 200 ] && [ "$health_before" -lt 400 ] || { echo 'Source backend unhealthy before AI probe.' >&2; exit 75; }
'@
$SourceBeforeNew = @'
health_before=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health", timeout=4); print(r.status); r.close()')
case "$health_before" in ''|*[!0-9]*) echo "Source backend health returned non-numeric value before AI probe: $health_before" >&2; exit 75;; esac
[ "$health_before" -ge 200 ] && [ "$health_before" -lt 400 ] || { echo 'Source backend unhealthy before AI probe.' >&2; exit 75; }
'@

$SourceAfterOld = @'
health_after=$(docker exec "$backend" python - <<'PY'
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8001/api/health', timeout=4) as r: print(r.status)
PY
)
[ "$health_after" -ge 200 ] && [ "$health_after" -lt 400 ] || { echo 'Source backend unhealthy after AI probe.' >&2; exit 78; }
'@
$SourceAfterNew = @'
health_after=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health", timeout=4); print(r.status); r.close()')
case "$health_after" in ''|*[!0-9]*) echo "Source backend health returned non-numeric value after AI probe: $health_after" >&2; exit 78;; esac
[ "$health_after" -ge 200 ] && [ "$health_after" -lt 400 ] || { echo 'Source backend unhealthy after AI probe.' >&2; exit 78; }
'@

foreach ($pair in @(
    @($TargetOld.Trim(),$TargetNew.Trim(),'target'),
    @($SourceBeforeOld.Trim(),$SourceBeforeNew.Trim(),'source-before'),
    @($SourceAfterOld.Trim(),$SourceAfterNew.Trim(),'source-after')
)) {
    if (-not $Raw.Contains([string]$pair[0])) { throw "REV8 expected $($pair[2]) health block not found; refusing broad patch." }
    $Raw = $Raw.Replace([string]$pair[0],[string]$pair[1])
}

if ($Raw -match 'health(?:_before|_after)?=\$\(docker exec "\$backend" python - <<') {
    throw 'REV8 generated script still contains a docker-exec Python stdin health probe.'
}

$Generated = Join-Path $ToolRoot 'Invoke-GPIHub-V108-REV8.generated.ps1'
Set-Content -LiteralPath $Generated -Value $Raw -Encoding utf8
$tokens=$null; $errors=$null
[void][System.Management.Automation.Language.Parser]::ParseFile($Generated,[ref]$tokens,[ref]$errors)
if (@($errors).Count -gt 0) { throw ('REV8 generated parser failed: ' + ((@($errors) | ForEach-Object Message) -join '; ')) }

Write-Host 'V108_REV8_TARGET_HEALTH_PROBE_PATCH=PASS' -ForegroundColor Green
Write-Host 'V108_REV8_SOURCE_HEALTH_PROBES_PATCH=PASS' -ForegroundColor Green
Write-Host 'V108_REV8_GENERATED_PARSER=PASS' -ForegroundColor Green
Write-Host "Generated script: $Generated"
Write-Host 'V108_REV8_ENTRY_WRAPPER=PASS' -ForegroundColor Cyan
& $Generated
