[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)

$Targets = @(
    @{ Path = 'bc-extension\zetadocs-replacement\src\codeunit\GPISalesReturnEmail.Codeunit.al'; Expected = 2 },
    @{ Path = 'bc-extension\zetadocs-replacement\src\codeunit\GPIPurchaseReturnEmail.Codeunit.al'; Expected = 2 },
    @{ Path = 'bc-extension\zetadocs-replacement\src\codeunit\GPITransferEmail.Codeunit.al'; Expected = 2 },
    @{ Path = 'bc-extension\zetadocs-replacement\src\codeunit\GPICustomerOpenOrderEmail.Codeunit.al'; Expected = 7 }
)

$PendingWrites = @()

foreach ($Target in $Targets) {
    $FullPath = Join-Path $RepoRoot $Target.Path
    if (-not (Test-Path -LiteralPath $FullPath)) {
        throw "Required file not found: $FullPath"
    }

    $Content = [System.IO.File]::ReadAllText($FullPath)
    $Old = '        Commit();'
    $New = '        DeliveryTransportMgt.CommitChanges();'
    $Count = ([regex]::Matches($Content, [regex]::Escape($Old))).Count

    if ($Count -eq 0 -and $Content.Contains($New)) {
        Write-Host "[SKIP] Commit boundary already applied: $($Target.Path)" -ForegroundColor Yellow
        continue
    }

    if ($Count -ne $Target.Expected) {
        throw "Expected $($Target.Expected) Commit() calls in $($Target.Path), but found $Count. No files were changed."
    }

    if (-not $Content.Contains('DeliveryTransportMgt: Codeunit "GPI Delivery Transport Mgt.";')) {
        throw "The delivery transport variable is missing from $($Target.Path). No files were changed."
    }

    $PendingWrites += [pscustomobject]@{
        Path = $FullPath
        Content = $Content.Replace($Old, $New)
    }
}

foreach ($Write in $PendingWrites) {
    [System.IO.File]::WriteAllText($Write.Path, $Write.Content, $Utf8NoBom)
    Write-Host "[OK] Applied commit boundary: $($Write.Path)" -ForegroundColor Green
}

Set-Location $RepoRoot
$RdlChanges = @(git diff --name-only -- 'bc-extension/zetadocs-replacement/src/reportlayout/*.rdl')

Write-Host ''
Write-Host 'Workflow commit boundary patch completed.' -ForegroundColor Green
Write-Host 'No RDLC file was modified by this script.' -ForegroundColor Green
Write-Host ''
Write-Host 'Existing local RDLC changes still present:' -ForegroundColor Cyan
$RdlChanges | ForEach-Object { Write-Host "  $_" }
