[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProdRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests"
$BuildScript = Join-Path $RepoRoot "scripts\Prepare-GPIALTests.ps1"

foreach ($Path in @($ProdRoot, $TestRoot, $BuildScript)) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Required path was not found: $Path"
    }
}

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$OutputRoot = Join-Path $RepoRoot ".gpi-build-input\GamerDocuments-$Timestamp"
$BundlePath = Join-Path $RepoRoot "GamerDocuments-BuildInput-$Timestamp.txt"
$ZipPath = Join-Path $RepoRoot "GamerDocuments-BuildInput-$Timestamp.zip"

New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )

    $Encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $Encoding)
}

function Add-UniquePath {
    param(
        [Parameter(Mandatory)]
        [System.Collections.Generic.HashSet[string]]$Set,

        [Parameter(Mandatory)]
        [string]$Path
    )

    [void]$Set.Add([System.IO.Path]::GetFullPath($Path))
}

$Selected = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)

foreach ($Path in @(
    (Join-Path $ProdRoot "app.json"),
    (Join-Path $TestRoot "app.json"),
    (Join-Path $ProdRoot "CHANGELOG.md"),
    $BuildScript
)) {
    if (Test-Path -LiteralPath $Path) {
        Add-UniquePath -Set $Selected -Path $Path
    }
}

$ProdAlFiles = @(Get-ChildItem -LiteralPath $ProdRoot -Recurse -File -Filter "*.al")
$TestAlFiles = @(Get-ChildItem -LiteralPath $TestRoot -Recurse -File -Filter "*.al")

$ExactPatterns = @(
    '"GPI Record Documents FactBox"',
    '"GPI Record Document"',
    '"GPI Record Document Mgt\."',
    '"GPI Record Document Path Mgt\."',
    '"GPI Document Delivery Log"',
    '"GPI Delivery Document Type"',
    '"GPI SharePoint Archive"',
    '"GPI Archive Path Mgt\."',
    'GPIRecordDocuments',
    'SetSourceContext\s*\('
)

$BehaviorPatterns = @(
    'DeliveryLog',
    'ArchivePendingDocuments',
    'ArchiveDelivery',
    'Archive.*Document',
    'Email\.Send',
    'EmailMessage',
    'SendDocument',
    'SendEmail',
    'OpenDocument',
    'DownloadFromStream',
    'Hyperlink\s*\(',
    'CreateInStream',
    'CreateOutStream',
    'Report\.SaveAs',
    'SaveAsPdf'
)

foreach ($File in $ProdAlFiles) {
    $Text = Get-Content -LiteralPath $File.FullName -Raw

    $IsExact = $false
    foreach ($Pattern in $ExactPatterns) {
        if ($Text -match $Pattern) {
            $IsExact = $true
            break
        }
    }

    $IsBehavior = $false
    if (
        $Text -match '"GPI Document Delivery Log"' -or
        $Text -match '"GPI Record Document"' -or
        $Text -match '"GPI SharePoint Archive"'
    ) {
        foreach ($Pattern in $BehaviorPatterns) {
            if ($Text -match $Pattern) {
                $IsBehavior = $true
                break
            }
        }
    }

    $IsPermission = $File.Name -match '(?i)Permission'
    $IsOrderSurface =
        $Text -match '(?i)extends\s+"Sales Order"' -or
        $Text -match '(?i)extends\s+"Purchase Order"'

    if ($IsExact -or $IsBehavior -or $IsPermission -or $IsOrderSurface) {
        Add-UniquePath -Set $Selected -Path $File.FullName
    }
}

foreach ($File in $TestAlFiles) {
    $Text = Get-Content -LiteralPath $File.FullName -Raw

    if (
        $Text -match '"GPI Document Delivery Log"' -or
        $Text -match '"GPI Record Document"' -or
        $Text -match '"GPI Record Documents FactBox"' -or
        $Text -match '"GPI SharePoint Archive"' -or
        $Text -match '"GPI Delivery Document Type"'
    ) {
        Add-UniquePath -Set $Selected -Path $File.FullName
    }
}

$SelectedPaths = @($Selected | Sort-Object)

if ($SelectedPaths.Count -lt 8) {
    throw "Only $($SelectedPaths.Count) relevant files were identified. Expected at least 8. No project files were changed."
}

$ManifestLines = New-Object 'System.Collections.Generic.List[string]'
$ManifestLines.Add("Gamer Documents Unified History Build Input")
$ManifestLines.Add("Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')")
$ManifestLines.Add("Repository: $RepoRoot")
$ManifestLines.Add("Production project: $ProdRoot")
$ManifestLines.Add("Test project: $TestRoot")
$ManifestLines.Add("Selected files: $($SelectedPaths.Count)")
$ManifestLines.Add("")

foreach ($AppJson in @(
    (Join-Path $ProdRoot "app.json"),
    (Join-Path $TestRoot "app.json")
)) {
    if (Test-Path -LiteralPath $AppJson) {
        $App = Get-Content -LiteralPath $AppJson -Raw | ConvertFrom-Json
        $ManifestLines.Add(
            "App: $($App.name) | Publisher: $($App.publisher) | Version: $($App.version) | ID: $($App.id)"
        )
    }
}

$ManifestLines.Add("")
$ManifestLines.Add("Git status:")

try {
    $GitStatus = & git -C $RepoRoot status --short 2>&1
    if ($LASTEXITCODE -eq 0) {
        if (@($GitStatus).Count -eq 0) {
            $ManifestLines.Add("  (clean)")
        }
        else {
            foreach ($Line in @($GitStatus)) {
                $ManifestLines.Add("  $Line")
            }
        }
    }
    else {
        $ManifestLines.Add("  git status failed: $($GitStatus -join ' ')")
    }
}
catch {
    $ManifestLines.Add("  git status unavailable: $($_.Exception.Message)")
}

$ManifestLines.Add("")
$ManifestLines.Add("Selected files:")

foreach ($Path in $SelectedPaths) {
    $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
    $Hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    $ManifestLines.Add("  $RelativePath | SHA256=$Hash")

    $Destination = Join-Path $OutputRoot $RelativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
    Copy-Item -LiteralPath $Path -Destination $Destination -Force
}

$ManifestPath = Join-Path $OutputRoot "MANIFEST.txt"
Write-Utf8NoBom -Path $ManifestPath -Content (($ManifestLines -join [Environment]::NewLine) + [Environment]::NewLine)

$Builder = New-Object System.Text.StringBuilder
[void]$Builder.AppendLine(($ManifestLines -join [Environment]::NewLine))
[void]$Builder.AppendLine("")
[void]$Builder.AppendLine("=" * 120)
[void]$Builder.AppendLine("FULL SOURCE")
[void]$Builder.AppendLine("=" * 120)

foreach ($Path in $SelectedPaths) {
    $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')

    [void]$Builder.AppendLine("")
    [void]$Builder.AppendLine("=" * 120)
    [void]$Builder.AppendLine($RelativePath)
    [void]$Builder.AppendLine("=" * 120)
    [void]$Builder.AppendLine((Get-Content -LiteralPath $Path -Raw))
}

Write-Utf8NoBom -Path $BundlePath -Content $Builder.ToString()

if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}

Compress-Archive -Path (Join-Path $OutputRoot "*") -DestinationPath $ZipPath -CompressionLevel Optimal

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " Gamer Documents build input captured" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Files captured: $($SelectedPaths.Count)"
Write-Host "Text bundle:    $BundlePath"
Write-Host "ZIP bundle:     $ZipPath"
Write-Host ""
Write-Host "No AL source, app version, package, or environment was modified." -ForegroundColor Yellow
Write-Host "Upload the text bundle to the ChatGPT conversation." -ForegroundColor Cyan
