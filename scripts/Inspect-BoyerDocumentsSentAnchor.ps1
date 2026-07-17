[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.IO.Compression.FileSystem

$ProdRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement"
$PurchaseFile = Join-Path $ProdRoot "src\pageextension\GPIPurchaseOrderRecordDocuments.PageExt.al"
$SalesFile = Join-Path $ProdRoot "src\pageextension\GPISalesOrderRecordDocuments.PageExt.al"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Boyer Documents Sent anchor inspection" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "This script does not modify project files."
Write-Host ""

foreach ($File in @($SalesFile, $PurchaseFile)) {
    Write-Host "------------------------------------------------------------"
    Write-Host $File -ForegroundColor Yellow
    Write-Host "------------------------------------------------------------"

    if (Test-Path -LiteralPath $File) {
        Get-Content -LiteralPath $File
    }
    else {
        Write-Host "NOT FOUND"
    }

    Write-Host ""
}

$PackageRoots = @(
    (Join-Path $ProdRoot ".alpackages"),
    (Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests\.alpackages")
) | Where-Object { Test-Path -LiteralPath $_ }

$Packages = @(
    foreach ($PackageRoot in $PackageRoots) {
        Get-ChildItem -LiteralPath $PackageRoot -Filter *.app -File
    }
) | Sort-Object FullName -Unique

if ($Packages.Count -eq 0) {
    throw "No .app symbol packages were found under the production or test .alpackages folders."
}

$Candidates = New-Object System.Collections.Generic.List[object]

foreach ($Package in $Packages) {
    $Zip = $null
    try {
        $Zip = [System.IO.Compression.ZipFile]::OpenRead($Package.FullName)
        $SymbolEntry = $Zip.Entries |
            Where-Object { $_.FullName -match '(^|/)SymbolReference\.json$' } |
            Select-Object -First 1

        if ($null -eq $SymbolEntry) {
            continue
        }

        $Reader = New-Object System.IO.StreamReader($SymbolEntry.Open())
        try {
            $Raw = $Reader.ReadToEnd()
        }
        finally {
            $Reader.Dispose()
        }

        if (
            ($Raw -match '(?i)Documents Sent') -or
            ($Package.Name -match '(?i)Boyer|Document')
        ) {
            $Candidates.Add([pscustomobject]@{
                Package = $Package
                Raw = $Raw
            })
        }
    }
    catch {
        Write-Warning "Could not inspect package $($Package.FullName): $($_.Exception.Message)"
    }
    finally {
        if ($null -ne $Zip) {
            $Zip.Dispose()
        }
    }
}

if ($Candidates.Count -eq 0) {
    throw "No symbol package containing 'Documents Sent' was found."
}

foreach ($Candidate in $Candidates) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "PACKAGE: $($Candidate.Package.FullName)" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green

    $Raw = [string]$Candidate.Raw
    $Matches = @([regex]::Matches($Raw, '(?i)Documents Sent'))

    if ($Matches.Count -eq 0) {
        Write-Host "Package name looked relevant, but SymbolReference.json had no Documents Sent occurrence."
        continue
    }

    Write-Host "Documents Sent occurrences: $($Matches.Count)"
    Write-Host ""

    for ($i = 0; $i -lt $Matches.Count; $i++) {
        $Match = $Matches[$i]
        $Start = [Math]::Max(0, $Match.Index - 2500)
        $Length = [Math]::Min(5000, $Raw.Length - $Start)
        $Snippet = $Raw.Substring($Start, $Length)

        # Make minified JSON much easier to inspect in the terminal.
        $Snippet = $Snippet `
            -replace '\},\{', "},`r`n{" `
            -replace '\],', "],`r`n" `
            -replace '\},', "},`r`n"

        Write-Host "---------------- OCCURRENCE $($i + 1) ----------------" -ForegroundColor Magenta
        Write-Host $Snippet
        Write-Host ""
    }

    Write-Host "---------------- STRUCTURED ANCESTOR REPORT ----------------" -ForegroundColor Magenta

    try {
        $Json = $Raw | ConvertFrom-Json
    }
    catch {
        Write-Warning "ConvertFrom-Json failed for this package: $($_.Exception.Message)"
        continue
    }

    function Get-ScalarSummary {
        param([object]$Node)

        if ($null -eq $Node) {
            return ""
        }

        $Pairs = New-Object System.Collections.Generic.List[string]

        foreach ($Property in $Node.PSObject.Properties) {
            $Value = $Property.Value

            if (
                $null -eq $Value -or
                $Value -is [System.Collections.IEnumerable] -and
                $Value -isnot [string]
            ) {
                continue
            }

            $Text = [string]$Value
            if ($Text.Length -gt 250) {
                $Text = $Text.Substring(0, 250) + "..."
            }

            if (
                $Property.Name -match '^(Name|Id|Caption|Value|Kind|Type|Target|TargetObject|TargetObjectType|SourceTable|PageId|PageName)$' -or
                $Text -match '(?i)Documents Sent|Purchase Order|Sales Order'
            ) {
                $Pairs.Add("$($Property.Name)=$Text")
            }
        }

        return ($Pairs -join '; ')
    }

    function Walk-JsonNode {
        param(
            [object]$Node,
            [string]$Path,
            [object[]]$Ancestors
        )

        if ($null -eq $Node) {
            return
        }

        if ($Node -is [string]) {
            if ($Node -match '(?i)Documents Sent') {
                Write-Host "MATCH PATH: $Path" -ForegroundColor Yellow
                $StartIndex = [Math]::Max(0, $Ancestors.Count - 8)

                for ($a = $StartIndex; $a -lt $Ancestors.Count; $a++) {
                    $Summary = Get-ScalarSummary -Node $Ancestors[$a]
                    if ($Summary) {
                        Write-Host "  ancestor[$a]: $Summary"
                    }
                }

                Write-Host "  value: $Node"
                Write-Host ""
            }
            return
        }

        if ($Node -is [System.Collections.IDictionary]) {
            foreach ($Key in $Node.Keys) {
                Walk-JsonNode `
                    -Node $Node[$Key] `
                    -Path "$Path.$Key" `
                    -Ancestors ($Ancestors + @($Node))
            }
            return
        }

        if (
            $Node -is [System.Collections.IEnumerable] -and
            $Node -isnot [string] -and
            $Node -isnot [pscustomobject]
        ) {
            $Index = 0
            foreach ($Item in $Node) {
                Walk-JsonNode `
                    -Node $Item `
                    -Path "$Path[$Index]" `
                    -Ancestors $Ancestors
                $Index++
            }
            return
        }

        foreach ($Property in $Node.PSObject.Properties) {
            Walk-JsonNode `
                -Node $Property.Value `
                -Path "$Path.$($Property.Name)" `
                -Ancestors ($Ancestors + @($Node))
        }
    }

    Walk-JsonNode -Node $Json -Path '$' -Ancestors @()
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Inspection complete. No project files were changed." -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
