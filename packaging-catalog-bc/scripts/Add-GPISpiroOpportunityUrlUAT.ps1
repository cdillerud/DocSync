[CmdletBinding()]
param(
    [string]$LinkerPath = "$PSScriptRoot\Link-GPISpiroUATContext.ps1"
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $LinkerPath)) {
    throw "Linker was not found: $LinkerPath"
}

$content = Get-Content -LiteralPath $LinkerPath -Raw

$old = @'
    Write-Host "Resolved stage       : $($selectedOpportunity.Stage)" -ForegroundColor Green
    Write-Host "Resolved owner       : $($selectedOpportunity.Owner)" -ForegroundColor Green
}
Write-Section 'SPIRO CONTACT DISCOVERY'
'@

$new = @'
    if ([string]::IsNullOrWhiteSpace([string]$selectedOpportunity.Url) -and
        -not [string]::IsNullOrWhiteSpace([string]$selectedOpportunity.Id)) {
        $selectedOpportunity.Url = "https://app.spiro.ai/opportunities/$($selectedOpportunity.Id)"
    }

    Write-Host "Resolved stage       : $($selectedOpportunity.Stage)" -ForegroundColor Green
    Write-Host "Resolved owner       : $($selectedOpportunity.Owner)" -ForegroundColor Green
    Write-Host "Resolved browser URL : $($selectedOpportunity.Url)" -ForegroundColor Green
}
Write-Section 'SPIRO CONTACT DISCOVERY'
'@

if (-not $content.Contains($old)) {
    throw 'Expected enrichment block was not found. The linker was not changed.'
}

$updated = $content.Replace($old, $new)

$backupPath = "$LinkerPath.before-opportunity-url-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Copy-Item -LiteralPath $LinkerPath -Destination $backupPath -Force

# Keep exactly one terminating newline and no extra blank line at EOF.
$updated = $updated.TrimEnd("`r", "`n") + "`r`n"
[System.IO.File]::WriteAllText($LinkerPath, $updated, [System.Text.UTF8Encoding]::new($false))

$null = [scriptblock]::Create((Get-Content -LiteralPath $LinkerPath -Raw))

Write-Host ''
Write-Host 'GPI Spiro opportunity URL patch complete.' -ForegroundColor Green
Write-Host "Linker : $LinkerPath"
Write-Host "Backup : $backupPath"
Write-Host 'Syntax : PASSED' -ForegroundColor Green
Write-Host 'Fallback browser route: https://app.spiro.ai/opportunities/<opportunity-id>'
