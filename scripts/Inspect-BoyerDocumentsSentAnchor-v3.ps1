[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$PackageRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement\.alpackages"
$BoyerFile = Get-ChildItem -LiteralPath $PackageRoot -File -Filter "*.app" |
    Where-Object { $_.FullName -match "(?i)Boyer" } |
    Select-Object -First 1

if ($null -eq $BoyerFile) {
    throw "No Boyer .app package was found in $PackageRoot"
}

$BoyerPath = [string]$BoyerFile.FullName

Write-Host ""
Write-Host "Boyer package:" -ForegroundColor Cyan
Write-Host "  $BoyerPath"
Write-Host ""

$FileStream = [System.IO.File]::Open(
    $BoyerPath,
    [System.IO.FileMode]::Open,
    [System.IO.FileAccess]::Read,
    [System.IO.FileShare]::ReadWrite
)

$Archive = [System.IO.Compression.ZipArchive]::new(
    $FileStream,
    [System.IO.Compression.ZipArchiveMode]::Read,
    $false
)

try {
    $SymbolEntry = $null

    foreach ($Entry in $Archive.Entries) {
        $EntryPath = [string]$Entry.FullName

        if ($EntryPath -match "(?i)(^|/)SymbolReference\.json$") {
            $SymbolEntry = $Entry
            break
        }
    }

    if ($null -eq $SymbolEntry) {
        Write-Host "Package entries:" -ForegroundColor Yellow

        foreach ($Entry in $Archive.Entries) {
            Write-Host "  $([string]$Entry.FullName)"
        }

        throw "SymbolReference.json was not found in the Boyer package."
    }

    Write-Host "Symbol entry:"
    Write-Host "  $([string]$SymbolEntry.FullName)" -ForegroundColor Green
    Write-Host ""

    $Reader = [System.IO.StreamReader]::new($SymbolEntry.Open())

    try {
        $Raw = $Reader.ReadToEnd()
    }
    finally {
        $Reader.Dispose()
    }
}
finally {
    $Archive.Dispose()
    $FileStream.Dispose()
}

$Needle = "Documents Sent"
$Positions = New-Object System.Collections.Generic.List[int]
$StartAt = 0

while ($true) {
    $Position = $Raw.IndexOf(
        $Needle,
        $StartAt,
        [System.StringComparison]::OrdinalIgnoreCase
    )

    if ($Position -lt 0) {
        break
    }

    $Positions.Add($Position)
    $StartAt = $Position + $Needle.Length
}

if ($Positions.Count -eq 0) {
    throw "SymbolReference.json was read, but no Documents Sent caption was found."
}

Write-Host "Documents Sent occurrences: $($Positions.Count)" -ForegroundColor Green
Write-Host ""

for ($i = 0; $i -lt $Positions.Count; $i++) {
    $Position = $Positions[$i]
    $SnippetStart = [Math]::Max(0, $Position - 5000)
    $SnippetLength = [Math]::Min(10000, $Raw.Length - $SnippetStart)
    $Snippet = $Raw.Substring($SnippetStart, $SnippetLength)

    $Snippet = $Snippet `
        -replace '\},\{', "},`r`n{" `
        -replace '\],', "],`r`n" `
        -replace '\},', "},`r`n"

    Write-Host "============================================================" -ForegroundColor Magenta
    Write-Host " DOCUMENTS SENT OCCURRENCE $($i + 1)" -ForegroundColor Magenta
    Write-Host "============================================================" -ForegroundColor Magenta
    Write-Host $Snippet
    Write-Host ""
}

Write-Host "Read-only inspection complete. No project files were changed." -ForegroundColor Cyan
