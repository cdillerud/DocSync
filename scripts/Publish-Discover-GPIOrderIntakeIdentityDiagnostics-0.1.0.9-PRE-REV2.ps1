#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$EnableInstall
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$BasePath = 'scripts/Publish-Discover-GPIOrderIntakeIdentityDiagnostics-0.1.0.9-PRE.ps1'
$ExpectedBaseBlob = '354fcb695fb1ce8aac477dfc48dff31f0573e30c'

if (-not $EnableInstall) {
    throw 'REFUSING INSTALL: rerun REV2 with -EnableInstall for this exact PRE-only diagnostics upgrade.'
}

Push-Location $RepoRoot
try {
    $headBlob = (& git rev-parse "HEAD:$BasePath").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($headBlob)) {
        throw "Could not resolve committed base harness at HEAD:$BasePath"
    }
    if ($headBlob -ne $ExpectedBaseBlob) {
        throw "Committed base harness changed. Expected $ExpectedBaseBlob; got $headBlob."
    }

    $source = (& git show "HEAD:$BasePath") -join "`n"
    if ([string]::IsNullOrWhiteSpace($source)) {
        throw 'Committed base harness content was empty.'
    }

    $old = 'throw "Read-only API marker missing from $requiredPath: $marker"'
    $new = 'throw "Read-only API marker missing from ${requiredPath}: $marker"'
    $patchCount = ([regex]::Matches($source, [regex]::Escape($old))).Count

    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE 0.1.0.9 - IDENTITY DIAGNOSTICS PUBLISH/DISCOVERY REV2 / PARSER FIX' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host "Committed base blob      : $ExpectedBaseBlob"
    Write-Host "HEAD base blob           : $headBlob"
    Write-Host "Parser-fix patch target  : $patchCount / 1"
    Write-Host 'Correction                : delimit $requiredPath before literal colon in diagnostic error string'
    Write-Host 'Pre-execution syntax gate : PowerShell Parser.ParseInput; zero parse errors required'
    Write-Host 'Target app                : GPI Order Intake 0.1.0.9'
    Write-Host 'Package SHA               : 8092784D61A9FF5E930B8D4034C7FACF99BA7087CC75EB348FF5E59968C9894F'
    Write-Host 'Extension mutation        : exact 0.1.0.9 PRE upgrade only'
    Write-Host 'Business-data writes      : NONE' -ForegroundColor Green
    Write-Host 'Sales-order action        : NOT CALLED / NOT PRESENT' -ForegroundColor Green
    Write-Host 'Production                : HARD BLOCKED' -ForegroundColor Green
    Write-Host ('=' * 120) -ForegroundColor Cyan

    if ($patchCount -ne 1) {
        throw "Expected exactly one parser-fix patch target; found $patchCount."
    }

    $patched = $source.Replace($old, $new)
    if ($patched.Contains($old)) {
        throw 'Original invalid interpolation remains after patch.'
    }
    if (-not $patched.Contains($new)) {
        throw 'Corrected interpolation marker is missing after patch.'
    }

    $tokens = $null
    $parseErrors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseInput(
        $patched,
        [ref]$tokens,
        [ref]$parseErrors
    )

    $parseErrors = @($parseErrors)
    if ($parseErrors.Count -ne 0) {
        foreach ($parseError in $parseErrors) {
            Write-Host ("PARSE_ERROR|message={0}|text={1}" -f $parseError.Message,$parseError.Extent.Text) -ForegroundColor Red
        }
        throw "Patched 0.1.0.9 identity diagnostics harness still has $($parseErrors.Count) PowerShell parse error(s). BC was not contacted."
    }

    Write-Host 'Pre-execution PowerShell syntax gate: PASS' -ForegroundColor Green
    Write-Host ''

    $tempPath = Join-Path $PSScriptRoot ('.GPIOrderIntake-IdentityDiagnostics-0.1.0.9-REV2-' + [guid]::NewGuid().ToString('N') + '.tmp.ps1')
    try {
        Set-Content -LiteralPath $tempPath -Value $patched -Encoding utf8NoBOM -NoNewline
        & $tempPath -EnableInstall
        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
            throw "Patched identity diagnostics harness exited with code $LASTEXITCODE."
        }
    }
    finally {
        Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
    }
}
finally {
    Pop-Location
}
