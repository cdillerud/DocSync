[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs",
    [string]$OutputPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $RepoRoot ("GPI-ExtendedText-ReportSource-{0}.txt" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
}

$ProductionRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests"

$PathsToCapture = @(
    Join-Path $ProductionRoot "app.json",
    Join-Path $TestRoot "app.json",
    Join-Path $ProductionRoot "CHANGELOG.md"
)

$FoldersToCapture = @(
    Join-Path $ProductionRoot "src\report",
    Join-Path $ProductionRoot "src\reportextension",
    Join-Path $ProductionRoot "src\reportlayout",
    Join-Path $ProductionRoot "src\codeunit",
    Join-Path $ProductionRoot "src\permissions",
    Join-Path $TestRoot "src\codeunit"
)

$ReportKeywords = @(
    "GPI Sales Order Confirmation",
    "GPI Prepayment Notice",
    "GPI Pick Ticket",
    "GPI Blanket Sales Order",
    "GPI Sales Invoice",
    "GPI Sales Credit Memo",
    "GPI Drop Ship Purchase Order",
    "GPI Warehouse Purchase Order",
    "GPI Warehouse Receiving Notice",
    "GPI Sales Return Auth",
    "GPI Sales Return WH Notice",
    "GPI Purchase Return Order",
    "GPI Purchase Return Pick",
    "GPI Transfer Pick List",
    "GPI Transfer Receipt Notice",
    "Customer Open Order"
)

function Add-File {
    param(
        [Parameter(Mandatory)][System.Collections.Generic.List[string]]$List,
        [Parameter(Mandatory)][string]$Path
    )

    if ((Test-Path -LiteralPath $Path) -and (-not $List.Contains($Path))) {
        $List.Add($Path)
    }
}

$Files = [System.Collections.Generic.List[string]]::new()

foreach ($Path in $PathsToCapture) {
    Add-File -List $Files -Path $Path
}

foreach ($Folder in $FoldersToCapture) {
    if (Test-Path -LiteralPath $Folder) {
        Get-ChildItem -LiteralPath $Folder -Recurse -File |
            Where-Object {
                $_.Extension -in @(".al", ".rdl", ".rdlc", ".json")
            } |
            ForEach-Object {
                $FullName = $_.FullName
                $ShouldInclude = $false

                if ($FullName -match "\\src\\report(layout|extension)?\\") {
                    $ShouldInclude = $true
                }

                if (-not $ShouldInclude) {
                    $Text = Get-Content -LiteralPath $FullName -Raw -ErrorAction SilentlyContinue
                    foreach ($Keyword in $ReportKeywords) {
                        if ($Text -like "*$Keyword*") {
                            $ShouldInclude = $true
                            break
                        }
                    }

                    if ($Text -like "*Extended Text*" -or $Text -like "*ExtendedText*") {
                        $ShouldInclude = $true
                    }
                }

                if ($ShouldInclude) {
                    Add-File -List $Files -Path $FullName
                }
            }
    }
}

$Lines = [System.Collections.Generic.List[string]]::new()
$Lines.Add("GPI Extended Text Report Source Capture")
$Lines.Add("Generated: $(Get-Date -Format o)")
$Lines.Add("RepoRoot: $RepoRoot")
$Lines.Add("")
$Lines.Add("================================================================================")
$Lines.Add("GIT STATUS")
$Lines.Add("================================================================================")
try {
    Push-Location $RepoRoot
    $GitStatus = git status --short 2>$null
    if ($LASTEXITCODE -eq 0) {
        $Lines.AddRange([string[]]$GitStatus)
    }
    else {
        $Lines.Add("Git status unavailable.")
    }
}
finally {
    Pop-Location
}

$Lines.Add("")
$Lines.Add("================================================================================")
$Lines.Add("CAPTURED FILES")
$Lines.Add("================================================================================")
foreach ($File in $Files) {
    $Relative = $File.Substring($RepoRoot.Length).TrimStart('\')
    $Hash = (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash
    $Lines.Add("$Relative | SHA256: $Hash")
}

foreach ($File in $Files) {
    $Relative = $File.Substring($RepoRoot.Length).TrimStart('\')
    $Hash = (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash

    $Lines.Add("")
    $Lines.Add("================================================================================")
    $Lines.Add("FILE: $Relative")
    $Lines.Add("SHA256: $Hash")
    $Lines.Add("================================================================================")
    $Lines.Add((Get-Content -LiteralPath $File -Raw))
}

$Encoding = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($OutputPath, ($Lines -join [Environment]::NewLine), $Encoding)

Write-Host ""
Write-Host "Created extended-text report source capture:" -ForegroundColor Green
Write-Host $OutputPath
Write-Host ""
Write-Host "Upload this file here. It includes report AL, report layouts, related codeunits, permissions, and test codeunits." -ForegroundColor Yellow
