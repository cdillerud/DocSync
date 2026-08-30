#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$ExpectedCorpus = Join-Path $env:USERPROFILE 'Downloads\W117105_Strategic Warehousing_122625_.pdf'
$ExpectedSha = '48410cadceaa411d65e51bd266be5c5942b4431cdede9e7a05b871e75a3a2c25'

if (-not (Test-Path -LiteralPath $ExpectedCorpus -PathType Leaf)) {
    throw "REV6 requires the SHA-verified W117105 corpus already retrieved by REV5: $ExpectedCorpus"
}
$sha = (Get-FileHash -LiteralPath $ExpectedCorpus -Algorithm SHA256).Hash.ToLowerInvariant()
if ($sha -ne $ExpectedSha) { throw "REV6 corpus SHA mismatch: $sha" }
Write-Host 'V108_REV6_LOCAL_CORPUS_SHA=PASS' -ForegroundColor Green

$Main = Join-Path $ToolRoot 'Invoke-GPIHub-V108-Durable-Warehouse-Strategic-Corpus.ps1'
if (-not (Test-Path -LiteralPath $Main -PathType Leaf)) { throw "V108 base script missing: $Main" }
$Raw = Get-Content -LiteralPath $Main -Raw

$SshNeedle = @'
StdErr=(if (Test-Path -LiteralPath $stderrFile) { Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue } else { '' })
'@
$SshReplacement = @'
StdErr=$(if (Test-Path -LiteralPath $stderrFile) { Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue } else { '' })
'@
if (-not $Raw.Contains($SshNeedle.Trim())) { throw 'REV6 SSH StdErr runtime-expression pattern not found; refusing broad patch.' }
$Patched = $Raw.Replace($SshNeedle.Trim(), $SshReplacement.Trim())

$ProbeNeedle = 'probe_out=$(docker exec "$backend" python /tmp/v108-probe.py 2>&1)'
$ProbeReplacement = 'probe_out=$(docker exec -e PYTHONPATH=/app -w /app "$backend" python /tmp/v108-probe.py 2>&1)'
if (-not $Patched.Contains($ProbeNeedle)) { throw 'REV6 AI probe invocation pattern not found; refusing broad patch.' }
$Patched = $Patched.Replace($ProbeNeedle,$ProbeReplacement)

if ($Patched.Contains('StdErr=(if ')) { throw 'REV6 generated script still contains invalid StdErr=(if runtime expression.' }
if (-not $Patched.Contains('StdErr=$(if ')) { throw 'REV6 generated script missing corrected StdErr subexpression.' }
if (-not $Patched.Contains('docker exec -e PYTHONPATH=/app -w /app "$backend" python /tmp/v108-probe.py')) { throw 'REV6 generated script missing AI probe PYTHONPATH repair.' }

$Generated = Join-Path $ToolRoot 'Invoke-GPIHub-V108-REV6.generated.ps1'
Set-Content -LiteralPath $Generated -Value $Patched -Encoding utf8
$tokens = $null; $errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($Generated,[ref]$tokens,[ref]$errors)
if (@($errors).Count -gt 0) {
    throw ('REV6 generated parser failed: ' + ((@($errors) | ForEach-Object Message) -join '; '))
}

Write-Host 'V108_REV6_SSH_STDERR_SUBEXPRESSION_PATCH=PASS' -ForegroundColor Green
Write-Host 'V108_REV6_AI_PROBE_PYTHONPATH_PATCH=PASS' -ForegroundColor Green
Write-Host 'V108_REV6_GENERATED_PARSER=PASS' -ForegroundColor Green
Write-Host "Generated script: $Generated"
Write-Host 'V108_REV6_ENTRY_WRAPPER=PASS' -ForegroundColor Cyan
& $Generated
