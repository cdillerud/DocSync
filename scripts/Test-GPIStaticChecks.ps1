param(
    [Parameter()]
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$extensionPath = Join-Path $RepoRoot "bc-extension\zetadocs-replacement"
$sourcePath = Join-Path $extensionPath "src"
$appJsonPath = Join-Path $extensionPath "app.json"
$changeLogPath = Join-Path $extensionPath "CHANGELOG.md"
$launchJsonPath = Join-Path $extensionPath ".vscode\launch.json"

$errors = [System.Collections.Generic.List[string]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()

function Add-CheckError {
    param([Parameter(Mandatory)][string]$Message)
    $script:errors.Add($Message)
}

function Add-CheckWarning {
    param([Parameter(Mandatory)][string]$Message)
    $script:warnings.Add($Message)
}

function Write-Check {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "[CHECK] $Message"
}

Write-Host ""
Write-Host "============================================================"
Write-Host " GPI Sales Document Email - Static Checks"
Write-Host "============================================================"
Write-Host ""
Write-Host "Repository: $RepoRoot"
Write-Host "Extension:  $extensionPath"
Write-Host ""

Write-Check "Validating required paths"

foreach ($requiredPath in @(
    $RepoRoot,
    $extensionPath,
    $sourcePath,
    $appJsonPath,
    $changeLogPath
)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        Add-CheckError "Required path was not found: $requiredPath"
    }
}

if ($errors.Count -gt 0) {
    Write-Host ""
    Write-Host "Static checks failed before analysis could begin." -ForegroundColor Red

    foreach ($errorMessage in $errors) {
        Write-Host "  [ERROR] $errorMessage" -ForegroundColor Red
    }

    exit 1
}

Write-Check "Reading app.json"

$app = $null

try {
    $appJsonRaw = Get-Content -LiteralPath $appJsonPath -Raw
    $app = $appJsonRaw | ConvertFrom-Json
}
catch {
    Add-CheckError "app.json could not be parsed: $($_.Exception.Message)"
}

if ($null -ne $app) {
    if ([string]::IsNullOrWhiteSpace([string]$app.version)) {
        Add-CheckError "app.json does not contain a version."
    }
    elseif ([string]$app.version -notmatch '^\d+\.\d+\.\d+\.\d+$') {
        Add-CheckError "The extension version is not a valid four-part version: $($app.version)"
    }

    if ($null -eq $app.idRanges -or @($app.idRanges).Count -eq 0) {
        Add-CheckError "app.json does not contain any idRanges."
    }
}

Write-Check "Checking CHANGELOG.md version entry"

try {
    $changeLog = Get-Content -LiteralPath $changeLogPath -Raw

    if (
        $null -ne $app -and
        -not [string]::IsNullOrWhiteSpace([string]$app.version)
    ) {
        $expectedHeading = "## $($app.version)"

        if ($changeLog -notmatch [regex]::Escape($expectedHeading)) {
            Add-CheckError "CHANGELOG.md does not contain the heading '$expectedHeading'."
        }
    }
}
catch {
    Add-CheckError "CHANGELOG.md could not be read: $($_.Exception.Message)"
}

Write-Check "Finding AL and RDLC source files"

$alFiles = @(
    Get-ChildItem -LiteralPath $sourcePath -Recurse -File -Filter "*.al"
)

$rdlFiles = @(
    Get-ChildItem -LiteralPath $sourcePath -Recurse -File -Filter "*.rdl"
)

if ($alFiles.Count -eq 0) {
    Add-CheckError "No AL files were found under $sourcePath."
}

Write-Host "        AL files:   $($alFiles.Count)"
Write-Host "        RDLC files: $($rdlFiles.Count)"

Write-Check "Validating RDLC XML"

foreach ($rdlFile in $rdlFiles) {
    try {
        $rdlContent = Get-Content -LiteralPath $rdlFile.FullName -Raw
        [xml]$rdlXml = $rdlContent

        if ($null -eq $rdlXml.DocumentElement) {
            Add-CheckError "RDLC has no XML document element: $($rdlFile.FullName)"
        }
    }
    catch {
        Add-CheckError "Invalid RDLC XML in '$($rdlFile.FullName)': $($_.Exception.Message)"
    }
}

Write-Check "Checking report LayoutFile references"

$layoutReferencePattern = [regex]::new(
    "LayoutFile\s*=\s*'([^']+)'",
    [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
)

foreach ($alFile in $alFiles) {
    $alContent = Get-Content -LiteralPath $alFile.FullName -Raw
    $layoutMatches = $layoutReferencePattern.Matches($alContent)

    foreach ($layoutMatch in $layoutMatches) {
        $relativeLayoutPath = $layoutMatch.Groups[1].Value
        $normalizedLayoutPath = $relativeLayoutPath.Replace("/", "\")
        $fullLayoutPath = Join-Path $extensionPath $normalizedLayoutPath

        if (-not (Test-Path -LiteralPath $fullLayoutPath)) {
            Add-CheckError "Missing LayoutFile '$relativeLayoutPath', referenced by '$($alFile.FullName)'."
        }
    }
}

Write-Check "Checking AL object IDs and object ranges"

$objectPattern = [regex]::new(
    '^\s*(tableextension|pageextension|reportextension|enumextension|permissionsetextension|table|page|report|codeunit|enum|interface|xmlport|query|controladdin|profile|permissionset)\s+(\d+)\s+("[^"]+"|[A-Za-z0-9_.]+)',
    (
        [System.Text.RegularExpressions.RegexOptions]::IgnoreCase -bor
        [System.Text.RegularExpressions.RegexOptions]::Multiline
    )
)

$objects = [System.Collections.Generic.List[object]]::new()

foreach ($alFile in $alFiles) {
    $alContent = Get-Content -LiteralPath $alFile.FullName -Raw
    $objectMatches = $objectPattern.Matches($alContent)

    foreach ($objectMatch in $objectMatches) {
        $objects.Add(
            [pscustomobject]@{
                Type = $objectMatch.Groups[1].Value.ToLowerInvariant()
                Id   = [int]$objectMatch.Groups[2].Value
                Name = $objectMatch.Groups[3].Value
                File = $alFile.FullName
            }
        )
    }
}

Write-Host "        AL objects found: $($objects.Count)"

$duplicateGroups = @(
    $objects |
        Group-Object Type, Id |
        Where-Object Count -gt 1
)

foreach ($duplicateGroup in $duplicateGroups) {
    $duplicateDetails = (
        $duplicateGroup.Group |
            ForEach-Object {
                "$($_.Type) $($_.Id) $($_.Name) [$($_.File)]"
            }
    ) -join [Environment]::NewLine

    Add-CheckError "Duplicate AL object ID within the same object type:`n$duplicateDetails"
}

if ($null -ne $app -and $null -ne $app.idRanges) {
    foreach ($object in $objects) {
        $insideApprovedRange = $false

        foreach ($range in @($app.idRanges)) {
            $rangeStart = [int]$range.from
            $rangeEnd = [int]$range.to

            if (
                $object.Id -ge $rangeStart -and
                $object.Id -le $rangeEnd
            ) {
                $insideApprovedRange = $true
                break
            }
        }

        if (-not $insideApprovedRange) {
            Add-CheckError "Object $($object.Type) $($object.Id) $($object.Name) is outside the app.json ID ranges. File: $($object.File)"
        }
    }
}

Write-Check "Checking EmptyGuid compatibility"

foreach ($alFile in $alFiles) {
    $alContent = Get-Content -LiteralPath $alFile.FullName -Raw

    $containsEmptyGuid = (
        $alContent -match '\bEmptyGuid\s*\(\s*\)'
    )

    if (-not $containsEmptyGuid) {
        continue
    }

    $definesEmptyGuidHelper = (
        $alContent -match '(?im)^\s*(local\s+)?procedure\s+EmptyGuid\s*\(\s*\)\s*:\s*Guid'
    )

    if (-not $definesEmptyGuidHelper) {
        Add-CheckError "EmptyGuid() is used without a local helper definition: $($alFile.FullName)"
    }
}

Write-Check "Checking Email Recipient Type enum syntax"

$unquotedRecipientPattern = [regex]::new(
    'Enum::"Email Recipient Type"::(To|Cc|Bcc)\b',
    [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
)

foreach ($alFile in $alFiles) {
    $alContent = Get-Content -LiteralPath $alFile.FullName -Raw

    if ($unquotedRecipientPattern.IsMatch($alContent)) {
        Add-CheckError "Unquoted Email Recipient Type enum member found in '$($alFile.FullName)'. Use quoted To, Cc, or Bcc values."
    }
}

Write-Check "Checking for an accidental Production launch target"

if (Test-Path -LiteralPath $launchJsonPath) {
    $launchContent = Get-Content -LiteralPath $launchJsonPath -Raw

    if ($launchContent -match '(?i)"environmentName"\s*:\s*"Production"') {
        Add-CheckError "The AL launch configuration targets environmentName Production: $launchJsonPath"
    }

    if ($launchContent -match '(?i)"environmentType"\s*:\s*"Production"') {
        Add-CheckError "The AL launch configuration targets environmentType Production: $launchJsonPath"
    }
}

Write-Check "Checking for tracked generated .app packages"

$gitCommand = Get-Command git -ErrorAction SilentlyContinue

if ($null -eq $gitCommand) {
    Add-CheckWarning "Git is not available in PATH, so tracked .app packages could not be checked."
}
else {
    $locationPushed = $false

    try {
        Push-Location $RepoRoot
        $locationPushed = $true

        $trackedAppFiles = @(
            git ls-files "*.app" 2>$null
        )

        if ($trackedAppFiles.Count -gt 0) {
            Add-CheckError "Generated .app files are tracked by Git:`n$($trackedAppFiles -join [Environment]::NewLine)"
        }
    }
    catch {
        Add-CheckWarning "Git tracked-file check could not be completed: $($_.Exception.Message)"
    }
    finally {
        if ($locationPushed) {
            Pop-Location
        }
    }
}

Write-Host ""
Write-Host "============================================================"

if ($warnings.Count -gt 0) {
    Write-Host " Warnings" -ForegroundColor Yellow
    Write-Host "============================================================"

    foreach ($warningMessage in $warnings) {
        Write-Host "  [WARNING] $warningMessage" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "============================================================"
}

if ($errors.Count -gt 0) {
    Write-Host " Static checks failed" -ForegroundColor Red
    Write-Host "============================================================"

    foreach ($errorMessage in $errors) {
        Write-Host ""
        Write-Host "  [ERROR] $errorMessage" -ForegroundColor Red
    }

    Write-Host ""
    Write-Host "Total errors: $($errors.Count)" -ForegroundColor Red
    exit 1
}

Write-Host " Static checks passed" -ForegroundColor Green
Write-Host "============================================================"
Write-Host ""
Write-Host "Extension name:    $($app.name)"
Write-Host "Extension version: $($app.version)"
Write-Host "AL files:          $($alFiles.Count)"
Write-Host "AL objects:        $($objects.Count)"
Write-Host "RDLC files:        $($rdlFiles.Count)"
Write-Host ""
exit 0
