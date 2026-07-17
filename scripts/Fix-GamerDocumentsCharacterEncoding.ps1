[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedProductionVersion = "0.27.0.1"
$ExpectedTestVersion = "0.8.0.1"
$NewProductionVersion = "0.27.0.2"
$NewTestVersion = "0.8.0.2"

$ProductionRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests"
$JavaScriptPath = Join-Path $ProductionRoot "src\controladdin\recorddocuments\recordDocuments.js"
$ProductionAppJson = Join-Path $ProductionRoot "app.json"
$TestAppJson = Join-Path $TestRoot "app.json"
$ChangeLog = Join-Path $ProductionRoot "CHANGELOG.md"
$BuildScript = Join-Path $RepoRoot "scripts\Prepare-GPIALTests.ps1"

foreach ($RequiredPath in @(
    $JavaScriptPath,
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLog,
    $BuildScript
)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required path was not found: $RequiredPath"
    }
}

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Read-Utf8 {
    param([Parameter(Mandatory)][string]$Path)

    return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )

    [System.IO.File]::WriteAllText($Path, $Content, $script:Utf8NoBom)
}

function Write-JsonNoBom {
    param(
        [Parameter(Mandatory)][object]$Value,
        [Parameter(Mandatory)][string]$Path
    )

    $Json = $Value | ConvertTo-Json -Depth 100
    Write-Utf8NoBom -Path $Path -Content ($Json + [Environment]::NewLine)
}

$ProductionApp = Get-Content -LiteralPath $ProductionAppJson -Raw | ConvertFrom-Json
$TestApp = Get-Content -LiteralPath $TestAppJson -Raw | ConvertFrom-Json

if ([string]$ProductionApp.version -ne $ExpectedProductionVersion) {
    throw "Expected production version $ExpectedProductionVersion, but found $($ProductionApp.version). No files were changed."
}

if ([string]$TestApp.version -ne $ExpectedTestVersion) {
    throw "Expected test version $ExpectedTestVersion, but found $($TestApp.version). No files were changed."
}

$MainDependency = @(
    $TestApp.dependencies |
        Where-Object { [string]$_.id -eq [string]$ProductionApp.id }
)

if ($MainDependency.Count -ne 1) {
    throw "Expected exactly one test dependency on production app $($ProductionApp.id), but found $($MainDependency.Count). No files were changed."
}

$OriginalJavaScript = Read-Utf8 -Path $JavaScriptPath
$OriginalProductionAppJson = Get-Content -LiteralPath $ProductionAppJson -Raw
$OriginalTestAppJson = Get-Content -LiteralPath $TestAppJson -Raw
$OriginalChangeLog = Get-Content -LiteralPath $ChangeLog -Raw

$Arrow = [string][char]0x21E9
$Bullet = [string][char]0x2022

# Also support a file that already contains UTF-8 mojibake text.
$Windows1252 = [System.Text.Encoding]::GetEncoding(1252)
$MojibakeArrow = $Windows1252.GetString([System.Text.Encoding]::UTF8.GetBytes($Arrow))
$MojibakeBullet = $Windows1252.GetString([System.Text.Encoding]::UTF8.GetBytes($Bullet))

$UpdatedJavaScript = $OriginalJavaScript
$ReplacementCount = 0

foreach ($Candidate in @($Arrow, $MojibakeArrow)) {
    $Count = ([regex]::Matches($UpdatedJavaScript, [regex]::Escape($Candidate))).Count
    if ($Count -gt 0) {
        $UpdatedJavaScript = $UpdatedJavaScript.Replace($Candidate, '\u21E9')
        $ReplacementCount += $Count
    }
}

foreach ($Candidate in @($Bullet, $MojibakeBullet)) {
    $Count = ([regex]::Matches($UpdatedJavaScript, [regex]::Escape($Candidate))).Count
    if ($Count -gt 0) {
        $UpdatedJavaScript = $UpdatedJavaScript.Replace($Candidate, '\u2022')
        $ReplacementCount += $Count
    }
}

if ($ReplacementCount -lt 2) {
    throw "Expected to replace at least the drop-arrow and metadata bullet characters, but replaced only $ReplacementCount character(s). No files were changed."
}

if ($ReplacementCount -gt 6) {
    throw "The encoding patch found $ReplacementCount replacement candidates, which is more than expected. No files were changed."
}

if ($UpdatedJavaScript -notmatch '\\u21E9') {
    throw "The JavaScript does not contain the ASCII-safe drop-arrow escape after patching. No files were changed."
}

if ($UpdatedJavaScript -notmatch '\\u2022') {
    throw "The JavaScript does not contain the ASCII-safe bullet escape after patching. No files were changed."
}

$ProductionApp.version = $NewProductionVersion
$TestApp.version = $NewTestVersion
$MainDependency[0].version = $NewProductionVersion

$ChangeLogEntry = @"
## $NewProductionVersion

### Fixed
- Replaced literal Unicode characters in the Gamer Documents control-add-in JavaScript with ASCII-safe Unicode escape sequences.
- The drop-zone arrow now renders as the intended symbol instead of mojibake such as â‡©.
- Document metadata separators now render as bullets instead of mojibake such as â€¢.

### Safety
- No Gamer Documents click, upload, Delivery Log, SharePoint archive, email, routing, report, or stored-PDF behavior was changed.
- No package is published automatically.
- Publish only to Sandbox_5_5_2026 unless Chad explicitly approves another environment.

"@

if ($OriginalChangeLog -match '(?m)^# Changelog\s*$') {
    $UpdatedChangeLog = [regex]::Replace(
        $OriginalChangeLog,
        '(?m)^# Changelog\s*$',
        "# Changelog`r`n`r`n$ChangeLogEntry",
        1
    )
}
else {
    throw "The changelog header was not found. No files were changed."
}

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $RepoRoot ".gpi-backups\fix-gamer-documents-encoding-$Timestamp"
New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

$FilesToBackup = @(
    $JavaScriptPath,
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLog
)

foreach ($Path in $FilesToBackup) {
    $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
    $BackupPath = Join-Path $BackupRoot $RelativePath

    New-Item -ItemType Directory -Path (Split-Path -Parent $BackupPath) -Force | Out-Null
    Copy-Item -LiteralPath $Path -Destination $BackupPath -Force
}

$ProductionPackage = Join-Path $ProductionRoot "Gamer Packaging_GPI Sales Document Email_$NewProductionVersion.app"
$TestPackage = Join-Path $TestRoot "Gamer Packaging_GPI Sales Document Email Tests_$NewTestVersion.app"

try {
    Write-Utf8NoBom -Path $JavaScriptPath -Content $UpdatedJavaScript
    Write-JsonNoBom -Value $ProductionApp -Path $ProductionAppJson
    Write-JsonNoBom -Value $TestApp -Path $TestAppJson
    Write-Utf8NoBom -Path $ChangeLog -Content $UpdatedChangeLog

    if (Test-Path -LiteralPath $ProductionPackage) {
        Remove-Item -LiteralPath $ProductionPackage -Force
    }

    if (Test-Path -LiteralPath $TestPackage) {
        Remove-Item -LiteralPath $TestPackage -Force
    }

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host " Gamer Documents character-encoding correction" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Characters replaced: $ReplacementCount"
    Write-Host "Production version:  $NewProductionVersion"
    Write-Host "Test version:        $NewTestVersion"
    Write-Host "Backup:              $BackupRoot"
    Write-Host ""
    Write-Host "Running production and test builds..." -ForegroundColor Cyan

    & $BuildScript

    if (-not (Test-Path -LiteralPath $ProductionPackage)) {
        throw "The expected production package was not created: $ProductionPackage"
    }

    if (-not (Test-Path -LiteralPath $TestPackage)) {
        throw "The expected test package was not created: $TestPackage"
    }
}
catch {
    Write-Host ""
    Write-Host "The character-encoding correction failed. Restoring all modified files." -ForegroundColor Red

    foreach ($Path in $FilesToBackup) {
        $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
        $BackupPath = Join-Path $BackupRoot $RelativePath
        Copy-Item -LiteralPath $BackupPath -Destination $Path -Force
    }

    if (Test-Path -LiteralPath $ProductionPackage) {
        Remove-Item -LiteralPath $ProductionPackage -Force
    }

    if (Test-Path -LiteralPath $TestPackage) {
        Remove-Item -LiteralPath $TestPackage -Force
    }

    throw
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " Gamer Documents encoding build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Backup:             $BackupRoot"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish both packages only to Sandbox_5_5_2026 and fully reload the Business Central browser tab." -ForegroundColor Yellow
