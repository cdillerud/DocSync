#requires -Version 7.0

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = 'C:\Users\ChadDillerud\Documents\DocSync-Zetadocs'
$ExpectedBranch = 'feature/phase-3-record-documents'
$BridgeRoot = Join-Path $RepoRoot 'bc-extension\gpi-zetadocs-pilot-bridge'
$AppJson = Join-Path $BridgeRoot 'app.json'
$TaskPath = Join-Path $BridgeRoot 'src\codeunit\GPIZetadocsAutoMigrationTask.Codeunit.al'
$PackageCache = Join-Path $BridgeRoot '.alpackages'
$ExpectedVersion = '0.1.0.20'
$TargetVersion = '0.1.0.21'
$PackagePath = Join-Path $BridgeRoot "Gamer Packaging_GPI Zetadocs Pilot Bridge_$TargetVersion.app"

function Section([string]$Name) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Name -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

function Read-Text([string]$Path) { [System.IO.File]::ReadAllText($Path) }
function Write-Text([string]$Path,[string]$Text) { [System.IO.File]::WriteAllText($Path,$Text,[System.Text.UTF8Encoding]::new($false)) }

function Get-AlCompiler {
    $Compiler = Get-ChildItem "$env:USERPROFILE\.vscode\extensions" -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like 'ms-dynamics-smb.al-*' } |
        Sort-Object LastWriteTime -Descending |
        ForEach-Object {
            $Candidate = Join-Path $_.FullName 'bin\win32\alc.exe'
            if (Test-Path -LiteralPath $Candidate) { $Candidate }
        } |
        Select-Object -First 1
    if (-not $Compiler) { throw 'AL compiler alc.exe was not found.' }
    return $Compiler
}

Section '1. SAFETY / BASELINE'

$Branch = (& git -C $RepoRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Could not determine Git branch.' }
if ($Branch -ne $ExpectedBranch) { throw "Expected branch '$ExpectedBranch', found '$Branch'." }

foreach ($Path in @($BridgeRoot,$AppJson,$TaskPath,$PackageCache)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Required path missing: $Path" }
}

$App = Get-Content -LiteralPath $AppJson -Raw | ConvertFrom-Json
if ([string]$App.version -notin @($ExpectedVersion,$TargetVersion)) {
    throw "Expected Bridge $ExpectedVersion (or $TargetVersion), found $($App.version)."
}

$BeforeTask = Read-Text $TaskPath
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$BackupRoot = Join-Path $RepoRoot ".gpi-backups\bridge-first-batch-stale-recovery-$TargetVersion-REV2-$Stamp"
New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null
Copy-Item -LiteralPath $AppJson -Destination (Join-Path $BackupRoot 'app.json') -Force
Copy-Item -LiteralPath $TaskPath -Destination (Join-Path $BackupRoot 'GPIZetadocsAutoMigrationTask.Codeunit.al') -Force

Write-Host "Bridge version : $($App.version)"
Write-Host "Backup         : $BackupRoot"
Write-Host 'Production     : NOT TOUCHED'
Write-Host 'Migration data : NOT TOUCHED'

try {
    if ([string]$App.version -eq $ExpectedVersion) {
        Section '2. PATCH RECOVERSTALE RUN - REGEX SAFE'

        foreach ($Marker in @(
            'procedure RecoverStaleRun()',
            'StaleAge: Duration;',
            'StaleThreshold: Duration;',
            'if State."Last Batch Date/Time" = 0DT then',
            'StaleAge := CurrentDateTime() - State."Last Batch Date/Time";',
            'StaleThreshold := 60 * 60 * 1000;',
            'if not IsNullGuid(State."Scheduled Task ID") then'
        )) {
            if (-not $BeforeTask.Contains($Marker)) { throw "Expected .20 source marker missing: $Marker" }
        }

        $Patched = $BeforeTask

        # Insert the two new variables immediately after StaleThreshold, independent of blank-line formatting.
        $VarPattern = '(?m)^(\s*StaleThreshold:\s*Duration;\s*)$'
        if ([regex]::Matches($Patched,$VarPattern).Count -ne 1) {
            throw 'Expected exactly one RecoverStaleRun StaleThreshold variable declaration.'
        }
        $Patched = [regex]::Replace(
            $Patched,
            $VarPattern,
            '$1' + "`r`n        StaleReferenceDateTime: DateTime;`r`n`r`n        StaleReferenceLabel: Text[50];",
            1
        )

        # Replace only the stale-age decision block, from the old zero-date guard up to (but not including) the Scheduled Task ID guard.
        $GuardPattern = '(?s)\s*if State\."Last Batch Date/Time" = 0DT then.*?if StaleAge < StaleThreshold then\s*Error\(\s*''Recovery was blocked because the last completed batch is only %1 old\. Wait until it is at least 60 minutes old and verify Scheduled Tasks before recovering\.'',\s*StaleAge\);'
        $GuardMatches = [regex]::Matches($Patched,$GuardPattern)
        if ($GuardMatches.Count -ne 1) {
            throw "Expected exactly one .20 stale-age guard block, found $($GuardMatches.Count)."
        }

        $NewGuard = @'

        if State."Last Batch Date/Time" <> 0DT then begin
            StaleReferenceDateTime := State."Last Batch Date/Time";
            StaleReferenceLabel := 'last completed batch';
        end else begin
            if State."Started Date/Time" = 0DT then
                Error(
                    'Recovery was blocked because neither Last Batch Date/Time nor Started Date/Time is available to prove the run is stale.');

            StaleReferenceDateTime := State."Started Date/Time";
            StaleReferenceLabel := 'run start';
        end;

        if CurrentDateTime() <= StaleReferenceDateTime then
            Error(
                'Recovery was blocked because the %1 time is not earlier than the current date/time.',
                StaleReferenceLabel);

        StaleAge := CurrentDateTime() - StaleReferenceDateTime;
        StaleThreshold := 60 * 60 * 1000;

        if StaleAge < StaleThreshold then
            Error(
                'Recovery was blocked because the %1 is only %2 old. Wait until it is at least 60 minutes old and verify Scheduled Tasks before recovering.',
                StaleReferenceLabel,
                StaleAge);
'@
        $Patched = [regex]::Replace($Patched,$GuardPattern,[System.Text.RegularExpressions.MatchEvaluator]{ param($m) $NewGuard },1)

        # Update only the stale-recovery audit message arguments.
        $MessagePattern = '(?s)''Stale unattended migration execution state recovered at %1\. Last completed batch was %2\. Counters, migration audit rows, links, family, and batch size were preserved\. Use Resume to continue\.'',\s*CurrentDateTime\(\),\s*State\."Last Batch Date/Time"\)'
        if ([regex]::Matches($Patched,$MessagePattern).Count -ne 1) {
            throw 'Expected exactly one .20 stale-recovery audit message.'
        }
        $MessageReplacement = @'
'Stale unattended migration execution state recovered at %1 using %2 time %3 as the stale reference. Counters, migration audit rows, links, family, and batch size were preserved. Use Resume to continue.',
                    CurrentDateTime(),
                    StaleReferenceLabel,
                    StaleReferenceDateTime)
'@
        $Patched = [regex]::Replace($Patched,$MessagePattern,[System.Text.RegularExpressions.MatchEvaluator]{ param($m) $MessageReplacement },1)

        # Validate the in-memory patch before writing anything.
        foreach ($Marker in @(
            'StaleReferenceDateTime: DateTime;',
            'StaleReferenceLabel: Text[50];',
            'if State."Last Batch Date/Time" <> 0DT then begin',
            'StaleReferenceDateTime := State."Started Date/Time";',
            "StaleReferenceLabel := 'run start';",
            'StaleAge := CurrentDateTime() - StaleReferenceDateTime;',
            'StaleThreshold := 60 * 60 * 1000;',
            'if not IsNullGuid(State."Scheduled Task ID") then'
        )) {
            if (-not $Patched.Contains($Marker)) { throw "In-memory patched source marker missing: $Marker" }
        }

        if ($Patched.Contains('Recovery was blocked because there is no Last Batch Date/Time to prove the run is stale.')) {
            throw 'Old first-batch recovery dead-end remains in patched source.'
        }

        Write-Text $TaskPath $Patched

        $RawApp = Read-Text $AppJson
        $VersionPattern = '("version"\s*:\s*")' + [regex]::Escape($ExpectedVersion) + '(")'
        if ([regex]::Matches($RawApp,$VersionPattern).Count -ne 1) { throw 'Could not identify exactly one bridge manifest version.' }
        $RawApp = [regex]::Replace($RawApp,$VersionPattern,'${1}' + $TargetVersion + '${2}',1)
        Write-Text $AppJson $RawApp
    }

    Section '3. POST-WRITE VALIDATION'

    $AfterTask = Read-Text $TaskPath
    $FinalApp = Get-Content -LiteralPath $AppJson -Raw | ConvertFrom-Json

    foreach ($Marker in @(
        'StaleReferenceDateTime: DateTime;',
        'StaleReferenceLabel: Text[50];',
        'if State."Last Batch Date/Time" <> 0DT then begin',
        'StaleReferenceDateTime := State."Started Date/Time";',
        "StaleReferenceLabel := 'run start';",
        'StaleAge := CurrentDateTime() - StaleReferenceDateTime;',
        'StaleThreshold := 60 * 60 * 1000;',
        'if not IsNullGuid(State."Scheduled Task ID") then',
        'procedure Start(',
        'procedure Resume()',
        'local procedure RunScheduledBatch(',
        'TaskScheduler.CreateTask('
    )) {
        if (-not $AfterTask.Contains($Marker)) { throw "Post-write validation marker missing: $Marker" }
    }

    if ([string]$FinalApp.version -ne $TargetVersion) { throw "Manifest version $($FinalApp.version), expected $TargetVersion." }

    Write-Host 'First-batch stale fallback : VERIFIED' -ForegroundColor Green
    Write-Host '60-minute threshold        : PRESERVED' -ForegroundColor Green
    Write-Host 'Scheduled Task ID guard    : PRESERVED' -ForegroundColor Green
    Write-Host 'Start/Resume scheduler     : PRESERVED' -ForegroundColor Green

    Section '4. COMPILE BRIDGE .21'

    $Compiler = Get-AlCompiler
    if (Test-Path -LiteralPath $PackagePath) { Remove-Item -LiteralPath $PackagePath -Force }

    & $Compiler "/project:$BridgeRoot" "/packagecachepath:$PackageCache" "/out:$PackagePath"
    if ($LASTEXITCODE -ne 0) { throw "AL compile failed with exit code $LASTEXITCODE." }
    if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf)) { throw 'Compile returned success but .21 package is missing.' }

    $Pkg = Get-Item -LiteralPath $PackagePath
    $Hash = (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash.ToUpperInvariant()

    Section '5. RESULT'
    Write-Host 'BRIDGE .21 COMPILED' -ForegroundColor Green
    Write-Host "Package : $($Pkg.FullName)"
    Write-Host "Bytes   : $($Pkg.Length)"
    Write-Host "SHA256  : $Hash"
    Write-Host 'Production: NOT TOUCHED'
}
catch {
    Write-Host ''
    Write-Host 'PATCH/COMPILE FAILED - RESTORING TARGETED FILES' -ForegroundColor Red
    Copy-Item -LiteralPath (Join-Path $BackupRoot 'app.json') -Destination $AppJson -Force
    Copy-Item -LiteralPath (Join-Path $BackupRoot 'GPIZetadocsAutoMigrationTask.Codeunit.al') -Destination $TaskPath -Force
    if (Test-Path -LiteralPath $PackagePath) { Remove-Item -LiteralPath $PackagePath -Force -ErrorAction SilentlyContinue }
    throw
}
