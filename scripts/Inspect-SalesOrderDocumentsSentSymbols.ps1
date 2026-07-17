[CmdletBinding()]
param(
    [Parameter()]
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.IO.Compression.FileSystem

$Patterns = @(
    "Sales Order Documents Sent",
    "Sales Confirm Ready",
    "Order Confirmation Sent",
    "Picklist Sent",
    "Prepayment Sent",
    "Documents Sent"
)

$OutputPath = Join-Path $RepoRoot "SalesOrder-DocumentsSent-SymbolDiscovery.txt"
$Results = [System.Collections.Generic.List[string]]::new()

function Add-Header {
    param([string]$Text)

    $Results.Add("")
    $Results.Add("=" * 100)
    $Results.Add($Text)
    $Results.Add("=" * 100)
}

function Add-TextMatches {
    param(
        [string]$SourceName,
        [string]$Text
    )

    foreach ($Pattern in $Patterns) {
        $Start = 0

        while ($true) {
            $Index = $Text.IndexOf(
                $Pattern,
                $Start,
                [System.StringComparison]::OrdinalIgnoreCase
            )

            if ($Index -lt 0) {
                break
            }

            $ContextStart = [Math]::Max(0, $Index - 700)
            $ContextLength = [Math]::Min(
                $Text.Length - $ContextStart,
                1400
            )

            Add-Header "$SourceName | Match: $Pattern"
            $Results.Add($Text.Substring($ContextStart, $ContextLength))
            $Start = $Index + $Pattern.Length
        }
    }
}

if (-not (Test-Path -LiteralPath $RepoRoot)) {
    throw "Repository folder not found: $RepoRoot"
}

$Results.Add("Sales Order Documents Sent Symbol Discovery")
$Results.Add("Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
$Results.Add("Repository: $RepoRoot")

# Search all likely source and metadata files throughout the complete repository.
$TextFiles = Get-ChildItem -LiteralPath $RepoRoot -Recurse -File |
    Where-Object {
        $_.Extension -in @(".al", ".json", ".txt", ".xml", ".md")
    } |
    Sort-Object FullName

foreach ($File in $TextFiles) {
    try {
        $Text = Get-Content -LiteralPath $File.FullName -Raw
        Add-TextMatches -SourceName $File.FullName -Text $Text
    }
    catch {
        $Results.Add("Unable to read text file: $($File.FullName)")
        $Results.Add($_.Exception.Message)
    }
}

# Search downloaded AL symbol packages and any locally built .app files.
$AppFiles = Get-ChildItem -LiteralPath $RepoRoot -Recurse -File -Filter "*.app" |
    Sort-Object FullName

foreach ($AppFile in $AppFiles) {
    $Archive = $null

    try {
        $Archive = [System.IO.Compression.ZipFile]::OpenRead($AppFile.FullName)

        foreach ($Entry in $Archive.Entries) {
            if ($Entry.Length -eq 0) {
                continue
            }

            $Extension = [System.IO.Path]::GetExtension($Entry.FullName)

            if ($Extension -notin @(".al", ".json", ".txt", ".xml")) {
                continue
            }

            $Stream = $null
            $Reader = $null

            try {
                $Stream = $Entry.Open()
                $Reader = New-Object System.IO.StreamReader($Stream)
                $Text = $Reader.ReadToEnd()

                Add-TextMatches `
                    -SourceName "$($AppFile.FullName) :: $($Entry.FullName)" `
                    -Text $Text
            }
            finally {
                if ($Reader) {
                    $Reader.Dispose()
                }
                elseif ($Stream) {
                    $Stream.Dispose()
                }
            }
        }
    }
    catch {
        $Results.Add("Unable to inspect app package: $($AppFile.FullName)")
        $Results.Add($_.Exception.Message)
    }
    finally {
        if ($Archive) {
            $Archive.Dispose()
        }
    }
}

if ($Results.Count -le 3) {
    $Results.Add("")
    $Results.Add("No matching source or symbol text was found.")
}

$Results | Set-Content -LiteralPath $OutputPath -Encoding utf8

Write-Host ""
Write-Host "============================================================"
Write-Host " Sales Order Documents Sent discovery complete"
Write-Host "============================================================"
Write-Host ""
Write-Host "No source files were changed."
Write-Host "No versions were changed."
Write-Host "No RDLC files were touched."
Write-Host ""
Write-Host "Output:"
Write-Host "  $OutputPath"
Write-Host ""
Write-Host "Open it with:"
Write-Host "  notepad `"$OutputPath`""
