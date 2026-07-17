[CmdletBinding()]
param(
    [Parameter()]
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$BoyerAppId = "65994cd5-4d6f-497e-abc0-767b8c392608"
$BoyerName = "Boyer And Associates Custom Package"
$OutputPath = Join-Path $RepoRoot "Boyer-SalesOrder-FactBox-Symbols-v2.txt"

$SearchTerms = @(
    "Sales Order Documents Sent",
    "Sales Confirm Ready",
    "Order Confirmation Sent",
    "Pick List Ready",
    "Picklist Sent",
    "Prepayment Ready",
    "Prepayment Sent",
    "Sales Order"
)

$Lines = [System.Collections.Generic.List[string]]::new()
$Lines.Add("Boyer Sales Order FactBox Symbol Discovery v2")
$Lines.Add("Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
$Lines.Add("Boyer App ID: $BoyerAppId")
$Lines.Add("Repository: $RepoRoot")
$Lines.Add("")

function Find-ZipStart {
    param(
        [Parameter(Mandatory)]
        [byte[]]$Bytes
    )

    for ($Index = 0; $Index -le ($Bytes.Length - 4); $Index++) {
        if (
            $Bytes[$Index] -eq 0x50 -and
            $Bytes[$Index + 1] -eq 0x4B -and
            $Bytes[$Index + 2] -eq 0x03 -and
            $Bytes[$Index + 3] -eq 0x04
        ) {
            return $Index
        }
    }

    return -1
}

function Add-Section {
    param(
        [Parameter(Mandatory)]
        [string]$Title
    )

    $Lines.Add("")
    $Lines.Add("=" * 120)
    $Lines.Add($Title)
    $Lines.Add("=" * 120)
}

function Add-RawContexts {
    param(
        [Parameter(Mandatory)]
        [string]$Source,

        [Parameter(Mandatory)]
        [string]$Text
    )

    foreach ($Term in $SearchTerms) {
        $Start = 0

        while ($true) {
            $Index = $Text.IndexOf(
                $Term,
                $Start,
                [System.StringComparison]::OrdinalIgnoreCase
            )

            if ($Index -lt 0) {
                break
            }

            $ContextStart = [Math]::Max(0, $Index - 1600)
            $ContextLength = [Math]::Min(
                $Text.Length - $ContextStart,
                3200
            )

            Add-Section "$Source | RAW MATCH: $Term"
            $Lines.Add($Text.Substring($ContextStart, $ContextLength))

            $Start = $Index + $Term.Length
        }
    }
}

function Test-ObjectContainsSearchTerm {
    param(
        [Parameter(Mandatory)]
        $Object
    )

    $Json = $Object | ConvertTo-Json -Depth 30 -Compress

    foreach ($Term in $SearchTerms) {
        if (
            $Json.IndexOf(
                $Term,
                [System.StringComparison]::OrdinalIgnoreCase
            ) -ge 0
        ) {
            return $true
        }
    }

    return $false
}

function Walk-JsonObject {
    param(
        [Parameter(Mandatory)]
        $Object,

        [Parameter(Mandatory)]
        [string]$Path,

        [Parameter(Mandatory)]
        [string]$Source
    )

    if ($null -eq $Object) {
        return
    }

    if ($Object -is [string] -or $Object.GetType().IsPrimitive) {
        return
    }

    if ($Object -is [System.Collections.IDictionary]) {
        if (Test-ObjectContainsSearchTerm -Object $Object) {
            Add-Section "$Source | JSON OBJECT: $Path"
            $Lines.Add(($Object | ConvertTo-Json -Depth 30))
        }

        foreach ($Key in $Object.Keys) {
            Walk-JsonObject `
                -Object $Object[$Key] `
                -Path "$Path.$Key" `
                -Source $Source
        }

        return
    }

    if ($Object -is [System.Collections.IEnumerable] -and -not ($Object -is [string])) {
        $Index = 0
        foreach ($Item in $Object) {
            Walk-JsonObject `
                -Object $Item `
                -Path "$Path[$Index]" `
                -Source $Source
            $Index++
        }

        return
    }

    $Properties = @($Object.PSObject.Properties)

    if ($Properties.Count -gt 0) {
        if (Test-ObjectContainsSearchTerm -Object $Object) {
            Add-Section "$Source | JSON OBJECT: $Path"
            $Lines.Add(($Object | ConvertTo-Json -Depth 30))
        }

        foreach ($Property in $Properties) {
            Walk-JsonObject `
                -Object $Property.Value `
                -Path "$Path.$($Property.Name)" `
                -Source $Source
        }
    }
}

if (-not (Test-Path -LiteralPath $RepoRoot)) {
    throw "Repository folder not found: $RepoRoot"
}

$AppFiles = @(
    Get-ChildItem -LiteralPath $RepoRoot -Recurse -Force -File -Filter "*.app" |
        Sort-Object FullName
)

Add-Section "APP PACKAGES FOUND"
if ($AppFiles.Count -eq 0) {
    $Lines.Add("No .app packages were found anywhere under the repository.")
}
else {
    foreach ($AppFile in $AppFiles) {
        $Lines.Add($AppFile.FullName)
    }
}

$BoyerPackagesFound = 0

foreach ($AppFile in $AppFiles) {
    $Bytes = [System.IO.File]::ReadAllBytes($AppFile.FullName)
    $ZipStart = Find-ZipStart -Bytes $Bytes

    if ($ZipStart -lt 0) {
        continue
    }

    $PayloadLength = $Bytes.Length - $ZipStart
    $Payload = New-Object byte[] $PayloadLength
    [Array]::Copy($Bytes, $ZipStart, $Payload, 0, $PayloadLength)

    $MemoryStream = $null
    $Archive = $null
    $EntryTexts = @{}

    try {
        $MemoryStream = New-Object System.IO.MemoryStream(,$Payload)
        $Archive = New-Object System.IO.Compression.ZipArchive(
            $MemoryStream,
            [System.IO.Compression.ZipArchiveMode]::Read,
            $false
        )

        foreach ($Entry in $Archive.Entries) {
            if ($Entry.Length -eq 0) {
                continue
            }

            $Extension = [System.IO.Path]::GetExtension($Entry.FullName)

            if ($Extension -notin @(".json", ".xml", ".txt", ".al")) {
                continue
            }

            $EntryStream = $null
            $Reader = $null

            try {
                $EntryStream = $Entry.Open()
                $Reader = New-Object System.IO.StreamReader($EntryStream)
                $EntryTexts[$Entry.FullName] = $Reader.ReadToEnd()
            }
            finally {
                if ($Reader) {
                    $Reader.Dispose()
                }
                elseif ($EntryStream) {
                    $EntryStream.Dispose()
                }
            }
        }

        $IdentityText = ($EntryTexts.Values -join "`n")
        $IsBoyer =
            ($IdentityText.IndexOf(
                $BoyerAppId,
                [System.StringComparison]::OrdinalIgnoreCase
            ) -ge 0) -or
            ($IdentityText.IndexOf(
                $BoyerName,
                [System.StringComparison]::OrdinalIgnoreCase
            ) -ge 0) -or
            ($AppFile.Name.IndexOf(
                "Boyer",
                [System.StringComparison]::OrdinalIgnoreCase
            ) -ge 0)

        if (-not $IsBoyer) {
            continue
        }

        $BoyerPackagesFound++
        Add-Section "BOYER PACKAGE $BoyerPackagesFound"
        $Lines.Add($AppFile.FullName)

        foreach ($EntryName in ($EntryTexts.Keys | Sort-Object)) {
            $EntryText = [string]$EntryTexts[$EntryName]
            $Source = "$($AppFile.FullName) :: $EntryName"

            Add-RawContexts -Source $Source -Text $EntryText

            if ([System.IO.Path]::GetExtension($EntryName) -eq ".json") {
                try {
                    $JsonObject = $EntryText | ConvertFrom-Json
                    Walk-JsonObject `
                        -Object $JsonObject `
                        -Path '$' `
                        -Source $Source
                }
                catch {
                    Add-Section "$Source | JSON PARSE ERROR"
                    $Lines.Add($_.Exception.Message)
                }
            }
        }
    }
    catch {
        Add-Section "PACKAGE INSPECTION ERROR"
        $Lines.Add($AppFile.FullName)
        $Lines.Add($_.Exception.Message)
    }
    finally {
        if ($Archive) {
            $Archive.Dispose()
        }

        if ($MemoryStream) {
            $MemoryStream.Dispose()
        }
    }
}

Add-Section "SUMMARY"
$Lines.Add("Boyer packages found: $BoyerPackagesFound")

if ($BoyerPackagesFound -eq 0) {
    $Lines.Add("")
    $Lines.Add("The Boyer symbol package was not found.")
    $Lines.Add("In the production AL project, select Sandbox_NoZetadocs_UAT and run AL: Download Symbols.")
    $Lines.Add("Then rerun this script.")
}

$Lines | Set-Content -LiteralPath $OutputPath -Encoding utf8

Write-Host ""
Write-Host "============================================================"
Write-Host " Boyer symbol inspection v2 complete"
Write-Host "============================================================"
Write-Host ""
Write-Host "App packages scanned:  $($AppFiles.Count)"
Write-Host "Boyer packages found:  $BoyerPackagesFound"
Write-Host ""
Write-Host "Output:"
Write-Host "  $OutputPath"
Write-Host ""
Write-Host "Open it with:"
Write-Host "  notepad `"$OutputPath`""
Write-Host ""
Write-Host "No source files or versions were changed."
Write-Host "No RDLC files were touched."
