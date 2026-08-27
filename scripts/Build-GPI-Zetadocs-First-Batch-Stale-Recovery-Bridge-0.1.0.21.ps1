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

function Read-Text([string]$Path) {
    [System.IO.File]::ReadAllText($Path)
}

function Write-Text([string]$Path,[string]$Text) {
    [System.IO.File]::WriteAllText($Path,$Text,[System.Text.UTF8Encoding]::new($false))
}

function Backup-One([string]$Path,[string]$BackupRoot) {
    $Relative = [System.IO.Path]::GetRelativePath($RepoRoot,$Path)
    $Dest = Join-Path $BackupRoot $Relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $Dest) -Force | Out-Null
    Copy-Item -LiteralPath $Path -Destination $Dest -Force
}

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

Section '1. SAFETY / SOURCE BASELINE'

$Branch = (& git -C $RepoRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Could not determine Git branch.' }
if ($Branch -ne $ExpectedBranch) {
    throw "Expected branch '$ExpectedBranch', found '$Branch'."
}

foreach ($Path in @($BridgeRoot,$AppJson,$TaskPath,$PackageCache)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Required path missing: $Path" }
}

$App = Get-Content -LiteralPath $AppJson -Raw | ConvertFrom-Json
if ([string]$App.version -notin @($ExpectedVersion,$TargetVersion)) {
    throw "Expected Bridge $ExpectedVersion (or already-patched $TargetVersion), found $($App.version)."
}

$BeforeTask = Read-Text $TaskPath

foreach ($Marker in @(
    'procedure RecoverStaleRun()',
    'StaleAge: Duration;',
    'StaleThreshold: Duration;',
    'if State."Last Batch Date/Time" = 0DT then',
    'Recovery was blocked because there is no Last Batch Date/Time to prove the run is stale.',
    'StaleAge := CurrentDateTime() - State."Last Batch Date/Time";',
    'StaleThreshold := 60 * 60 * 1000;',
    'if not IsNullGuid(State."Scheduled Task ID") then'
)) {
    if (-not $BeforeTask.Contains($Marker) -and [string]$App.version -eq $ExpectedVersion) {
        throw "Expected .20 stale-recovery marker missing: $Marker"
    }
}

Write-Host "Bridge version : $($App.version)"
Write-Host 'Problem        : first scheduled batch can hang before Last Batch Date/Time is ever populated'
Write-Host 'Repair         : use Started Date/Time as stale reference only when no completed batch exists'
Write-Host 'Threshold      : unchanged at 60 minutes'
Write-Host 'Task-ID guard  : unchanged; recovery still requires Scheduled Task ID to be clear'
Write-Host 'Migration data : NOT TOUCHED BY THIS BUILD SCRIPT'
Write-Host 'Production     : NOT TOUCHED'

$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$BackupRoot = Join-Path $RepoRoot ".gpi-backups\bridge-first-batch-stale-recovery-$TargetVersion-$Stamp"
New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null
Backup-One $AppJson $BackupRoot
Backup-One $TaskPath $BackupRoot
Write-Host "Backup         : $BackupRoot"

try {
    if ([string]$App.version -eq $ExpectedVersion) {
        Section '2. PATCH RECOVERSTALE RUN REFERENCE TIME'

        $OldVar = @'
        StaleAge: Duration;

        StaleThreshold: Duration;
'@

        $NewVar = @'
        StaleAge: Duration;

        StaleThreshold: Duration;

        StaleReferenceDateTime: DateTime;

        StaleReferenceLabel: Text[50];
'@

        if (-not $BeforeTask.Contains($OldVar)) {
            throw 'Could not locate RecoverStaleRun variable block.'
        }

        $Patched = $BeforeTask.Replace($OldVar,$NewVar)

        $OldGuard = @'
        if State."Last Batch Date/Time" = 0DT then

            Error(

                'Recovery was blocked because there is no Last Batch Date/Time to prove the run is stale.');



        if CurrentDateTime() <= State."Last Batch Date/Time" then

            Error(

                'Recovery was blocked because Last Batch Date/Time is not earlier than the current date/time.');



        StaleAge := CurrentDateTime() - State."Last Batch Date/Time";

        StaleThreshold := 60 * 60 * 1000;



        if StaleAge < StaleThreshold then

            Error(

                'Recovery was blocked because the last completed batch is only %1 old. Wait until it is at least 60 minutes old and verify Scheduled Tasks before recovering.',

                StaleAge);
'@

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

        if (-not $Patched.Contains($OldGuard)) {
            throw 'Could not locate exact .20 stale-age guard block. No source written.'
        }

        $Patched = $Patched.Replace($OldGuard,$NewGuard)

        $OldMessage = @'
                    'Stale unattended migration execution state recovered at %1. Last completed batch was %2. Counters, migration audit rows, links, family, and batch size were preserved. Use Resume to continue.',

                    CurrentDateTime(),

                    State."Last Batch Date/Time"),
'@

        $NewMessage = @'
                    'Stale unattended migration execution state recovered at %1 using %2 time %3 as the stale reference. Counters, migration audit rows, links, family, and batch size were preserved. Use Resume to continue.',

                    CurrentDateTime(),

                    StaleReferenceLabel,

                    StaleReferenceDateTime),
'@

        if (-not $Patched.Contains($OldMessage)) {
            throw 'Could not locate exact stale-recovery audit message.'
        }

        $Patched = $Patched.Replace($OldMessage,$NewMessage)
        Write-Text $TaskPath $Patched

        $RawApp = Read-Text $AppJson
        $Pattern = '("version"\s*:\s*")' + [regex]::Escape($ExpectedVersion) + '("\s*[},])'
        if (([regex]::Matches($RawApp,$Pattern)).Count -ne 1) {
            throw 'Could not identify exactly one bridge manifest version field.'
        }
        $RawApp = [regex]::Replace($RawApp,$Pattern,'${1}' + $TargetVersion + '${2}',1)
        Write-Text $AppJson $RawApp
    }

    Section '3. STATIC SAFETY VALIDATION'

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
        'neither Last Batch Date/Time nor Started Date/Time is available'
    )) {
        if (-not $AfterTask.Contains($Marker)) {
            throw "Post-patch validation marker missing: $Marker"
        }
    }

    if ($AfterTask.Contains('Recovery was blocked because there is no Last Batch Date/Time to prove the run is stale.')) {
        throw 'Old first-batch recovery dead-end is still present.'
    }

    if ([string]$FinalApp.version -ne $TargetVersion) {
        throw "Bridge manifest version is $($FinalApp.version), expected $TargetVersion."
    }

    # Scope guard: only RecoverStaleRun semantics and manifest version are intended.
    if (-not $AfterTask.Contains('procedure Start(') -or
        -not $AfterTask.Contains('procedure Resume()') -or
        -not $AfterTask.Contains('local procedure RunScheduledBatch(') -or
        -not $AfterTask.Contains('TaskScheduler.CreateTask(')) {
        throw 'Migration orchestration baseline marker missing after patch.'
    }

    Write-Host 'First-batch stale reference fallback : VERIFIED' -ForegroundColor Green
    Write-Host '60-minute safety threshold           : PRESERVED' -ForegroundColor Green
    Write-Host 'Scheduled Task ID guard              : PRESERVED' -ForegroundColor Green
    Write-Host 'Counters / links / audit data         : UNCHANGED' -ForegroundColor Green
    Write-Host 'Start / Resume scheduling             : UNCHANGED' -ForegroundColor Green

    Section '4. COMPILE BRIDGE .21'

    $Compiler = Get-AlCompiler
    if (Test-Path -LiteralPath $PackagePath) { Remove-Item -LiteralPath $PackagePath -Force }

    & $Compiler `
        "/project:$BridgeRoot" `
        "/packagecachepath:$PackageCache" `
        "/out:$PackagePath"

    if ($LASTEXITCODE -ne 0) { throw "AL compile failed with exit code $LASTEXITCODE." }
    if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf)) { throw 'Compile succeeded but .21 package was not created.' }

    $Pkg = Get-Item -LiteralPath $PackagePath
    $Hash = (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash

    Section '5. RESULT'
    Write-Host 'BRIDGE FIRST-BATCH STALE RECOVERY FIX COMPILED' -ForegroundColor Green
    Write-Host ''
    Write-Host "Version : $TargetVersion"
    Write-Host "Package : $($Pkg.FullName)"
    Write-Host "Bytes   : $($Pkg.Length)"
    Write-Host "SHA256  : $Hash"
    Write-Host ''
    Write-Host 'PARITY CLASSIFICATION:'
    Write-Host '  Before: PARITY RISK - a hang during the first unattended batch could not satisfy Recover Stale Run because Last Batch Date/Time was 0DT.'
    Write-Host '  Fix:    first-batch recovery uses Started Date/Time only when no completed-batch timestamp exists.'
    Write-Host ''
    Write-Host 'NOT DONE:'
    Write-Host '  No publish'
    Write-Host '  No Production changes'
    Write-Host '  No migration data changes'
    Write-Host '  No routing changes'
    Write-Host '  No Git reset/clean/checkout'
}
catch {
    Write-Host ''
    Write-Host 'PATCH/COMPILE FAILED - RESTORING TARGETED FILES' -ForegroundColor Red

    foreach ($Path in @($AppJson,$TaskPath)) {
        $Relative = [System.IO.Path]::GetRelativePath($RepoRoot,$Path)
        $Backup = Join-Path $BackupRoot $Relative
        if (Test-Path -LiteralPath $Backup) {
            Copy-Item -LiteralPath $Backup -Destination $Path -Force
        }
    }

    if (Test-Path -LiteralPath $PackagePath) {
        Remove-Item -LiteralPath $PackagePath -Force -ErrorAction SilentlyContinue
    }

    throw
}
