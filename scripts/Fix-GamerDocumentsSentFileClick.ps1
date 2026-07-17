[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedProductionVersion = "0.27.0.0"
$ExpectedTestVersion = "0.8.0.0"
$NewProductionVersion = "0.27.0.1"
$NewTestVersion = "0.8.0.1"

$ProductionRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests"
$ProductionAppJson = Join-Path $ProductionRoot "app.json"
$TestAppJson = Join-Path $TestRoot "app.json"
$ChangeLog = Join-Path $ProductionRoot "CHANGELOG.md"
$ControlAddInRoot = Join-Path $ProductionRoot "src\controladdin\recorddocuments"
$BuildScript = Join-Path $RepoRoot "scripts\Prepare-GPIALTests.ps1"

foreach ($RequiredPath in @(
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLog,
    $ControlAddInRoot,
    $BuildScript
)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required path was not found: $RequiredPath"
    }
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )

    $Encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $Encoding)
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

$JavaScriptFiles = @(
    Get-ChildItem -LiteralPath $ControlAddInRoot -Recurse -File |
        Where-Object { $_.Extension -in @(".js", ".mjs") }
)

if ($JavaScriptFiles.Count -eq 0) {
    throw "No JavaScript files were found beneath $ControlAddInRoot. No files were changed."
}

$CandidateFiles = New-Object 'System.Collections.Generic.List[System.IO.FileInfo]'

foreach ($JavaScriptFile in $JavaScriptFiles) {
    $Text = Get-Content -LiteralPath $JavaScriptFile.FullName -Raw

    if (
        ($Text -match 'DocumentSelected') -and
        ($Text -match 'entryNo')
    ) {
        $CandidateFiles.Add($JavaScriptFile)
    }
}

if ($CandidateFiles.Count -eq 0) {
    Write-Host "JavaScript files inspected:" -ForegroundColor Yellow
    $JavaScriptFiles.FullName | ForEach-Object { Write-Host "  $_" }

    throw "No JavaScript file contained both DocumentSelected and entryNo. No files were changed."
}

$PatchedFiles = New-Object 'System.Collections.Generic.List[object]'
$TotalReplacementCount = 0

$GuardPatterns = @(
    @{
        Name = "greater than zero"
        Pattern = '(?<value>\b(?:[A-Za-z_$][\w$]*\.)*entryNo)\s*>\s*0'
        Replacement = '${value} !== 0'
    },
    @{
        Name = "greater than or equal to one"
        Pattern = '(?<value>\b(?:[A-Za-z_$][\w$]*\.)*entryNo)\s*>=\s*1'
        Replacement = '${value} !== 0'
    },
    @{
        Name = "less than or equal to zero"
        Pattern = '(?<value>\b(?:[A-Za-z_$][\w$]*\.)*entryNo)\s*<=\s*0'
        Replacement = '${value} === 0'
    },
    @{
        Name = "less than one"
        Pattern = '(?<value>\b(?:[A-Za-z_$][\w$]*\.)*entryNo)\s*<\s*1'
        Replacement = '${value} === 0'
    }
)

foreach ($CandidateFile in $CandidateFiles) {
    $OriginalContent = Get-Content -LiteralPath $CandidateFile.FullName -Raw
    $PatchedContent = $OriginalContent
    $FileReplacementCount = 0

    foreach ($GuardPattern in $GuardPatterns) {
        $Matches = [regex]::Matches(
            $PatchedContent,
            $GuardPattern.Pattern,
            [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)

        if ($Matches.Count -gt 0) {
            $PatchedContent = [regex]::Replace(
                $PatchedContent,
                $GuardPattern.Pattern,
                $GuardPattern.Replacement,
                [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)

            $FileReplacementCount += $Matches.Count
        }
    }

    if ($FileReplacementCount -gt 0) {
        $PatchedFiles.Add([pscustomobject]@{
            Path = $CandidateFile.FullName
            OriginalContent = $OriginalContent
            PatchedContent = $PatchedContent
            ReplacementCount = $FileReplacementCount
        })

        $TotalReplacementCount += $FileReplacementCount
    }
}

if ($TotalReplacementCount -eq 0) {
    Write-Host ""
    Write-Host "The sent-document selection handler was found, but no positive-only entryNo guard matched." -ForegroundColor Yellow
    Write-Host "Relevant source context:" -ForegroundColor Yellow

    foreach ($CandidateFile in $CandidateFiles) {
        Write-Host ""
        Write-Host "FILE: $($CandidateFile.FullName)" -ForegroundColor Cyan
        Select-String `
            -LiteralPath $CandidateFile.FullName `
            -Pattern 'DocumentSelected|entryNo' `
            -Context 4,4 |
            ForEach-Object {
                Write-Host $_.ToString()
            }
    }

    throw "No JavaScript was changed. Send the source context above back for a targeted correction."
}

if ($TotalReplacementCount -gt 8) {
    throw "The patch found $TotalReplacementCount positive-only entryNo guards, which is more than expected. No files were changed."
}

$OriginalProductionAppJson = Get-Content -LiteralPath $ProductionAppJson -Raw
$OriginalTestAppJson = Get-Content -LiteralPath $TestAppJson -Raw
$OriginalChangeLog = Get-Content -LiteralPath $ChangeLog -Raw

$ProductionApp.version = $NewProductionVersion
$TestApp.version = $NewTestVersion
$MainDependency[0].version = $NewProductionVersion

$ChangeLogEntry = @"
## $NewProductionVersion

### Fixed
- Sent documents in the Gamer Documents FactBox are now selectable and openable.
- The control add-in now treats negative sent-document references as valid document references instead of allowing only positive uploaded-document entry numbers.

### Safety
- Entry number 0 remains nonselectable.
- Uploaded-document click behavior is unchanged.
- No delivery-log, SharePoint archive, email, routing, report, or stored-PDF behavior was changed.
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
$BackupRoot = Join-Path $RepoRoot ".gpi-backups\fix-gamer-documents-sent-click-$Timestamp"
New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

$FilesToBackup = @(
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLog
) + @($PatchedFiles | ForEach-Object { $_.Path })

foreach ($Path in $FilesToBackup) {
    $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
    $BackupPath = Join-Path $BackupRoot $RelativePath

    New-Item -ItemType Directory -Path (Split-Path -Parent $BackupPath) -Force | Out-Null
    Copy-Item -LiteralPath $Path -Destination $BackupPath -Force
}

$ProductionPackage = Join-Path $ProductionRoot "Gamer Packaging_GPI Sales Document Email_$NewProductionVersion.app"
$TestPackage = Join-Path $TestRoot "Gamer Packaging_GPI Sales Document Email Tests_$NewTestVersion.app"

try {
    foreach ($PatchedFile in $PatchedFiles) {
        Write-Utf8NoBom -Path $PatchedFile.Path -Content $PatchedFile.PatchedContent
    }

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
    Write-Host " Gamer Documents sent-file click correction" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan

    foreach ($PatchedFile in $PatchedFiles) {
        Write-Host "Patched: $($PatchedFile.Path)"
        Write-Host "Guards corrected: $($PatchedFile.ReplacementCount)"
    }

    Write-Host "Production version: $NewProductionVersion"
    Write-Host "Test version:       $NewTestVersion"
    Write-Host "Backup:             $BackupRoot"
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
    Write-Host "The sent-file click correction failed. Restoring all modified files." -ForegroundColor Red

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
Write-Host " Gamer Documents sent-file click build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Backup:             $BackupRoot"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish both packages only to Sandbox_5_5_2026 and retest clicking both sent and uploaded files." -ForegroundColor Yellow
