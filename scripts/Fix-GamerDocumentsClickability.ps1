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

$OriginalJavaScript = Get-Content -LiteralPath $JavaScriptPath -Raw
$OriginalProductionAppJson = Get-Content -LiteralPath $ProductionAppJson -Raw
$OriginalTestAppJson = Get-Content -LiteralPath $TestAppJson -Raw
$OriginalChangeLog = Get-Content -LiteralPath $ChangeLog -Raw

$OldState = @'
    var state = {
        root: null,
        contextAvailable: false,
        maxFileSizeMB: 25,
        documents: [],
        queueBusy: false
    };
'@

$NewState = @'
    var state = {
        root: null,
        contextAvailable: false,
        captionText: "Gamer Documents",
        maxFileSizeMB: 25,
        documents: [],
        queueBusy: false
    };
'@

$OldHeader = @'
        var header = makeElement("div", "gpi-rd-header");
        header.appendChild(makeElement("div", "gpi-rd-title", "Documents"));
'@

$NewHeader = @'
        var header = makeElement("div", "gpi-rd-header");
        header.appendChild(
            makeElement("div", "gpi-rd-title", state.captionText || "Gamer Documents")
        );
'@

$OldRow = @'
            state.documents.forEach(function (documentItem) {
                var row = makeElement(
                    "button",
                    "gpi-rd-document" +
                        (documentItem.status === "Uploaded" ? "" : " unavailable")
                );
                row.type = "button";
                row.disabled = documentItem.status !== "Uploaded";
                row.addEventListener("click", function () {
                    invoke("DocumentOpenRequested", [documentItem.entryNo]);
                });
'@

$NewRow = @'
            state.documents.forEach(function (documentItem) {
                var entryNo = Number(documentItem.entryNo);
                var statusText = documentItem.status || "";
                var isSentDocument = statusText.indexOf("Sent") === 0;
                var isOpenable =
                    entryNo !== 0 &&
                    (statusText === "Uploaded" || isSentDocument);

                var row = makeElement(
                    "button",
                    "gpi-rd-document" + (isOpenable ? "" : " unavailable")
                );
                row.type = "button";
                row.disabled = !isOpenable;
                row.addEventListener("click", function () {
                    if (isOpenable) {
                        invoke("DocumentOpenRequested", [entryNo]);
                    }
                });
'@

$OldInitialize = @'
    window.InitializeRecordDocuments = function (captionText, maxFileSizeMB) {
        state.maxFileSizeMB = maxFileSizeMB || 25;
        render();
    };
'@

$NewInitialize = @'
    window.InitializeRecordDocuments = function (captionText, maxFileSizeMB) {
        state.captionText = captionText || "Gamer Documents";
        state.maxFileSizeMB = maxFileSizeMB || 25;
        render();
    };
'@

$ExpectedBlocks = @(
    @{ Name = "state block"; Old = $OldState },
    @{ Name = "header block"; Old = $OldHeader },
    @{ Name = "document-row block"; Old = $OldRow },
    @{ Name = "initialize block"; Old = $OldInitialize }
)

foreach ($ExpectedBlock in $ExpectedBlocks) {
    $MatchCount = ([regex]::Matches(
        $OriginalJavaScript,
        [regex]::Escape($ExpectedBlock.Old))).Count

    if ($MatchCount -ne 1) {
        throw "Expected exactly one $($ExpectedBlock.Name), but found $MatchCount. No files were changed."
    }
}

$UpdatedJavaScript = $OriginalJavaScript
$UpdatedJavaScript = $UpdatedJavaScript.Replace($OldState, $NewState)
$UpdatedJavaScript = $UpdatedJavaScript.Replace($OldHeader, $NewHeader)
$UpdatedJavaScript = $UpdatedJavaScript.Replace($OldRow, $NewRow)
$UpdatedJavaScript = $UpdatedJavaScript.Replace($OldInitialize, $NewInitialize)

$ProductionApp.version = $NewProductionVersion
$TestApp.version = $NewTestVersion
$MainDependency[0].version = $NewProductionVersion

$ChangeLogEntry = @"
## $NewProductionVersion

### Fixed
- Successfully sent files in Gamer Documents are now enabled and clickable.
- Negative synthetic references used for sent Delivery Log PDFs are now passed to the existing AL open handler.
- The inner control-add-in heading now uses the Gamer Documents caption supplied by AL instead of the hard-coded Documents label.

### Safety
- Entry number 0 remains nonselectable.
- Uploaded-document click behavior remains unchanged.
- Drafts, previews, discarded messages, and failed sends remain excluded.
- No Delivery Log, SharePoint archive, email, routing, report, or stored-PDF behavior was changed.
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
$BackupRoot = Join-Path $RepoRoot ".gpi-backups\fix-gamer-documents-clickability-$Timestamp"
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
    Write-Host " Gamer Documents clickability correction" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "JavaScript:         $JavaScriptPath"
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
    Write-Host "The clickability correction failed. Restoring all modified files." -ForegroundColor Red

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
Write-Host " Gamer Documents clickability build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Backup:             $BackupRoot"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish both packages only to Sandbox_5_5_2026 and retest clicking sent and uploaded files." -ForegroundColor Yellow
