[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$ProdRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement"
$PackageRoot = Join-Path $ProdRoot ".alpackages"
$SalesFile = Join-Path $ProdRoot "src\pageextension\GPISalesOrderRecordDocuments.PageExt.al"
$PurchaseFile = Join-Path $ProdRoot "src\pageextension\GPIPurchaseOrderRecordDocuments.PageExt.al"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Boyer Documents Sent anchor inspection v2" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "This script is read-only and does not modify project files."
Write-Host ""

foreach ($ProjectFile in @($SalesFile, $PurchaseFile)) {
    Write-Host "------------------------------------------------------------"
    Write-Host $ProjectFile -ForegroundColor Yellow
    Write-Host "------------------------------------------------------------"

    if (Test-Path -LiteralPath $ProjectFile) {
        Get-Content -LiteralPath $ProjectFile
    }
    else {
        Write-Host "NOT FOUND"
    }

    Write-Host ""
}

if (-not (Test-Path -LiteralPath $PackageRoot)) {
    throw "The production .alpackages folder was not found: $PackageRoot"
}

$BoyerPaths = @(
    Get-ChildItem -LiteralPath $PackageRoot -File -Filter *.app |
        Where-Object {
            $_.Name -like "Boyer And Associates_*" -or
            $_.Name -match "(?i)Boyer"
        } |
        ForEach-Object { [string]$_.FullName }
)

if ($BoyerPaths.Count -ne 1) {
    Write-Host "Boyer packages found: $($BoyerPaths.Count)"
    foreach ($Path in $BoyerPaths) {
        Write-Host "  $Path"
    }

    throw "Expected exactly one Boyer .app package in the production .alpackages folder."
}

$BoyerPath = [string]$BoyerPaths[0]

Write-Host "Boyer package:"
Write-Host "  $BoyerPath" -ForegroundColor Green
Write-Host ""

$FileStream = $null
$Archive = $null
$Reader = $null

try {
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

    $SymbolEntries = @(
        $Archive.Entries |
            Where-Object {
                $_.Name -ieq "SymbolReference.json" -or
                $_.FullName -match "(?i)(^|/)SymbolReference\.json$"
            }
    )

    if ($SymbolEntries.Count -ne 1) {
        Write-Host "Package entries containing 'Symbol' or ending in '.json':"
        foreach ($Entry in @($Archive.Entries)) {
            if (
                $Entry.FullName -match "(?i)Symbol" -or
                $Entry.FullName -match "(?i)\.json$"
            ) {
                Write-Host "  $($Entry.FullName)"
            }
        }

        throw "Expected exactly one SymbolReference.json entry, but found $($SymbolEntries.Count)."
    }

    $SymbolEntry = $SymbolEntries[0]
    $Reader = [System.IO.StreamReader]::new($SymbolEntry.Open())
    $Raw = $Reader.ReadToEnd()
}
finally {
    if ($null -ne $Reader) {
        $Reader.Dispose()
    }

    if ($null -ne $Archive) {
        $Archive.Dispose()
    }

    if ($null -ne $FileStream) {
        $FileStream.Dispose()
    }
}

$Needle = "Documents Sent"
$Occurrences = New-Object System.Collections.Generic.List[int]
$SearchFrom = 0

while ($true) {
    $Index = $Raw.IndexOf(
        $Needle,
        $SearchFrom,
        [System.StringComparison]::OrdinalIgnoreCase
    )

    if ($Index -lt 0) {
        break
    }

    $Occurrences.Add($Index)
    $SearchFrom = $Index + $Needle.Length
}

if ($Occurrences.Count -eq 0) {
    throw "SymbolReference.json was read successfully, but it contains no 'Documents Sent' text."
}

Write-Host "Documents Sent occurrences found: $($Occurrences.Count)" -ForegroundColor Green
Write-Host ""

for ($OccurrenceNumber = 0; $OccurrenceNumber -lt $Occurrences.Count; $OccurrenceNumber++) {
    $Index = $Occurrences[$OccurrenceNumber]
    $Start = [Math]::Max(0, $Index - 3500)
    $Length = [Math]::Min(7000, $Raw.Length - $Start)
    $Snippet = $Raw.Substring($Start, $Length)

    # Add line breaks to minified JSON without changing its text.
    $Snippet = $Snippet `
        -replace '\},\{', "},`r`n{" `
        -replace '\],', "],`r`n" `
        -replace '\},', "},`r`n"

    Write-Host "============================================================" -ForegroundColor Magenta
    Write-Host " DOCUMENTS SENT OCCURRENCE $($OccurrenceNumber + 1)" -ForegroundColor Magenta
    Write-Host "============================================================" -ForegroundColor Magenta
    Write-Host $Snippet
    Write-Host ""
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Inspection complete. No files were changed." -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
