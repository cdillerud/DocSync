[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs",
    [string]$OutputPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path -Path $RepoRoot -ChildPath ("GPI-ExtendedText-ReportSource-{0}.txt" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
}

$ProductionRoot = Join-Path -Path $RepoRoot -ChildPath "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path -Path $RepoRoot -ChildPath "bc-extension\zetadocs-replacement-tests"

$Files = New-Object System.Collections.ArrayList

function Add-CaptureFile {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    $ResolvedPath = (Resolve-Path -LiteralPath $Path).Path

    if (-not $Files.Contains($ResolvedPath)) {
        [void]$Files.Add($ResolvedPath)
    }
}

$DirectFiles = @(
    (Join-Path -Path $ProductionRoot -ChildPath "app.json"),
    (Join-Path -Path $TestRoot -ChildPath "app.json"),
    (Join-Path -Path $ProductionRoot -ChildPath "CHANGELOG.md")
)

foreach ($DirectFile in $DirectFiles) {
    Add-CaptureFile -Path $DirectFile
}

$FoldersToCapture = @(
    (Join-Path -Path $ProductionRoot -ChildPath "src\report"),
    (Join-Path -Path $ProductionRoot -ChildPath "src\reportextension"),
    (Join-Path -Path $ProductionRoot -ChildPath "src\reportlayout"),
    (Join-Path -Path $ProductionRoot -ChildPath "src\layout"),
    (Join-Path -Path $ProductionRoot -ChildPath "src\codeunit"),
    (Join-Path -Path $ProductionRoot -ChildPath "src\permissions"),
    (Join-Path -Path $ProductionRoot -ChildPath "src\permission"),
    (Join-Path -Path $TestRoot -ChildPath "src\codeunit")
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
    "Customer Open Order",
    "Extended Text",
    "ExtendedText",
    "Integer",
    "Item"
)

foreach ($Folder in $FoldersToCapture) {
    if (-not (Test-Path -LiteralPath $Folder)) {
        continue
    }

    $ChildFiles = Get-ChildItem -LiteralPath $Folder -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in @(".al", ".rdl", ".rdlc", ".json", ".docx") }

    foreach ($ChildFile in $ChildFiles) {
        $FullName = $ChildFile.FullName
        $ShouldInclude = $false

        if ($FullName -match "\\src\\report(layout|extension)?\\" -or $FullName -match "\\src\\layout\\") {
            $ShouldInclude = $true
        }

        if (-not $ShouldInclude -and $ChildFile.Extension -in @(".al", ".json")) {
            $Text = Get-Content -LiteralPath $FullName -Raw -ErrorAction SilentlyContinue

            foreach ($Keyword in $ReportKeywords) {
                if ($Text -like "*$Keyword*") {
                    $ShouldInclude = $true
                    break
                }
            }
        }

        if ($ShouldInclude) {
            Add-CaptureFile -Path $FullName
        }
    }
}

if ($Files.Count -eq 0) {
    throw "No files were found to capture. Confirm RepoRoot is correct: $RepoRoot"
}

$Lines = New-Object System.Collections.ArrayList

function Add-Line {
    param([string]$Text)
    [void]$Lines.Add($Text)
}

Add-Line "GPI Extended Text Report Source Capture"
Add-Line "Generated: $(Get-Date -Format o)"
Add-Line "RepoRoot: $RepoRoot"
Add-Line ""
Add-Line "================================================================================"
Add-Line "GIT STATUS"
Add-Line "================================================================================"

try {
    Push-Location $RepoRoot
    $GitStatus = git status --short 2>$null

    if ($LASTEXITCODE -eq 0) {
        if ($GitStatus) {
            foreach ($StatusLine in $GitStatus) {
                Add-Line ([string]$StatusLine)
            }
        }
        else {
            Add-Line "Clean working tree."
        }
    }
    else {
        Add-Line "Git status unavailable."
    }
}
finally {
    Pop-Location
}

Add-Line ""
Add-Line "================================================================================"
Add-Line "CAPTURED FILES"
Add-Line "================================================================================"

foreach ($File in $Files) {
    $Relative = $File.Substring($RepoRoot.Length).TrimStart('\')
    $Hash = (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash
    Add-Line "$Relative | SHA256: $Hash"
}

foreach ($File in $Files) {
    $Relative = $File.Substring($RepoRoot.Length).TrimStart('\')
    $Hash = (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash

    Add-Line ""
    Add-Line "================================================================================"
    Add-Line "FILE: $Relative"
    Add-Line "SHA256: $Hash"
    Add-Line "================================================================================"

    $Extension = [System.IO.Path]::GetExtension($File)
    if ($Extension -ieq ".docx") {
        Add-Line "[Binary DOCX layout captured by file path/hash only]"
    }
    else {
        Add-Line (Get-Content -LiteralPath $File -Raw)
    }
}

$Encoding = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($OutputPath, ($Lines -join [Environment]::NewLine), $Encoding)

Write-Host ""
Write-Host "Created extended-text report source capture:" -ForegroundColor Green
Write-Host $OutputPath
Write-Host ""
Write-Host "Files captured: $($Files.Count)"
Write-Host "Upload this file here." -ForegroundColor Yellow
