[CmdletBinding()]
param(
    [Parameter()]
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProdSrc = Join-Path $RepoRoot "bc-extension\zetadocs-replacement\src"
$OutFile = Join-Path $RepoRoot "SalesOrder-FactBox-Discovery.txt"

if (-not (Test-Path -LiteralPath $ProdSrc)) {
    throw "Source folder not found: $ProdSrc"
}

$Lines = [System.Collections.Generic.List[string]]::new()
$Lines.Add("Sales Order FactBox Discovery")
$Lines.Add("Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
$Lines.Add("Source: $ProdSrc")
$Lines.Add("")

$Files = Get-ChildItem -LiteralPath $ProdSrc -Recurse -File -Filter "*.al" |
    Sort-Object FullName

foreach ($File in $Files) {
    $Text = Get-Content -LiteralPath $File.FullName -Raw

    $Relevant =
        ($Text -match '(?i)extends\s+"Sales Order"') -or
        ($Text -match '(?i)Documents?\s+Sent') -or
        ($Text -match '(?i)GPIRecordDocuments') -or
        ($Text -match '(?i)FactBoxes')

    if (-not $Relevant) {
        continue
    }

    $Matches = Select-String -LiteralPath $File.FullName `
        -Pattern @(
            'pageextension\s+\d+.*extends\s+"Sales Order"',
            'add(first|last|after|before)\s*\(',
            'part\s*\(',
            "Caption\s*=\s*'[^']*Documents[^']*'",
            'GPIRecordDocuments',
            'Record Documents FactBox',
            'Documents Sent',
            'DocumentsSent'
        ) `
        -Context 2,4

    if (-not $Matches) {
        continue
    }

    $Lines.Add("=" * 90)
    $Lines.Add($File.FullName)
    $Lines.Add("=" * 90)

    foreach ($Match in $Matches) {
        foreach ($ContextLine in $Match.Context.PreContext) {
            $Lines.Add($ContextLine)
        }

        $Lines.Add(">> " + $Match.Line)

        foreach ($ContextLine in $Match.Context.PostContext) {
            $Lines.Add($ContextLine)
        }

        $Lines.Add("")
    }
}

$Lines | Set-Content -LiteralPath $OutFile -Encoding utf8

Write-Host ""
Write-Host "============================================================"
Write-Host " Sales Order FactBox discovery complete"
Write-Host "============================================================"
Write-Host ""
Write-Host "No source files were changed."
Write-Host "No versions were changed."
Write-Host "No RDLC files were touched."
Write-Host ""
Write-Host "Output file:"
Write-Host "  $OutFile"
Write-Host ""
Write-Host "Open the file with:"
Write-Host "  notepad `"$OutFile`""
