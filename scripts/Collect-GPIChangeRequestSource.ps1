[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProductionRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests"

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$OutFile = Join-Path $RepoRoot "GPI-ChangeRequestSource-$Timestamp.txt"

$Patterns = @(
    "app.json",
    "CHANGELOG.md",

    "src\pageextension\*Sales*Order*.al",
    "src\pageextension\*Purchase*Order*.al",
    "src\pageextension\*Posted*Sales*Invoice*.al",
    "src\pageextension\*Posted*Sales*Order*.al",
    "src\pageextension\*Customer*.al",
    "src\pageextension\*Vendor*.al",

    "src\page\*Invoice*Batch*.al",
    "src\page\*Document*Routing*.al",
    "src\page\*Record*Document*.al",

    "src\table\*Invoice*.al",
    "src\table\*Document*Routing*.al",
    "src\table\*Record*Document*.al",

    "src\codeunit\*Invoice*.al",
    "src\codeunit\*Document*Policy*.al",
    "src\codeunit\*Routing*.al",
    "src\codeunit\*Purchase*.al",
    "src\codeunit\*Sales*.al",
    "src\codeunit\*Record*Document*.al",
    "src\codeunit\*Delivery*.al",
    "src\codeunit\*Email*.al",

    "src\controladdin\*.al",
    "src\controladdin\recorddocuments\*.js",
    "src\controladdin\recorddocuments\*.css",

    "src\permissionset\*.al",

    "tests\src\codeunit\*Invoice*.al",
    "tests\src\codeunit\*Routing*.al",
    "tests\src\codeunit\*Record*Document*.al",
    "tests\src\codeunit\*Delivery*.al",
    "tests\src\codeunit\*Purchase*.al",
    "tests\src\codeunit\*Sales*.al"
)

$Files = New-Object "System.Collections.Generic.List[string]"

foreach ($Root in @($ProductionRoot, $TestRoot)) {
    foreach ($Pattern in $Patterns) {
        $SearchPath = Join-Path $Root (Split-Path $Pattern -Parent)
        $Filter = Split-Path $Pattern -Leaf

        if (Test-Path -LiteralPath $SearchPath) {
            Get-ChildItem -LiteralPath $SearchPath -Filter $Filter -Recurse -File -ErrorAction SilentlyContinue |
                ForEach-Object {
                    if (-not $Files.Contains($_.FullName)) {
                        $Files.Add($_.FullName)
                    }
                }
        }
    }
}

$Files = $Files | Sort-Object

"Generated: $(Get-Date -Format o)" | Set-Content -LiteralPath $OutFile -Encoding UTF8
"RepoRoot: $RepoRoot" | Add-Content -LiteralPath $OutFile -Encoding UTF8
"" | Add-Content -LiteralPath $OutFile -Encoding UTF8

"================================================================================" | Add-Content -LiteralPath $OutFile -Encoding UTF8
"GIT STATUS" | Add-Content -LiteralPath $OutFile -Encoding UTF8
"================================================================================" | Add-Content -LiteralPath $OutFile -Encoding UTF8
try {
    Push-Location $RepoRoot
    git status --short | Add-Content -LiteralPath $OutFile -Encoding UTF8
}
catch {
    "git status failed: $($_.Exception.Message)" | Add-Content -LiteralPath $OutFile -Encoding UTF8
}
finally {
    Pop-Location
}

"" | Add-Content -LiteralPath $OutFile -Encoding UTF8
"================================================================================" | Add-Content -LiteralPath $OutFile -Encoding UTF8
"FILES INCLUDED: $($Files.Count)" | Add-Content -LiteralPath $OutFile -Encoding UTF8
"================================================================================" | Add-Content -LiteralPath $OutFile -Encoding UTF8

foreach ($File in $Files) {
    $Relative = $File.Substring($RepoRoot.Length).TrimStart('\')
    $Hash = (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash

    "" | Add-Content -LiteralPath $OutFile -Encoding UTF8
    "========================================================================================================================" | Add-Content -LiteralPath $OutFile -Encoding UTF8
    "FILE: $Relative" | Add-Content -LiteralPath $OutFile -Encoding UTF8
    "SHA256: $Hash" | Add-Content -LiteralPath $OutFile -Encoding UTF8
    "========================================================================================================================" | Add-Content -LiteralPath $OutFile -Encoding UTF8
    Get-Content -LiteralPath $File -Raw | Add-Content -LiteralPath $OutFile -Encoding UTF8
}

Write-Host "Created: $OutFile" -ForegroundColor Green
