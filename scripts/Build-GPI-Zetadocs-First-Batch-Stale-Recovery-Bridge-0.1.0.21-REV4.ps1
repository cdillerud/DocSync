#requires -Version 7.0
[CmdletBinding()] param()
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

$RepoRoot='C:\Users\ChadDillerud\Documents\DocSync-Zetadocs'
$ExpectedBranch='feature/phase-3-record-documents'
$BridgeRoot=Join-Path $RepoRoot 'bc-extension\gpi-zetadocs-pilot-bridge'
$AppJson=Join-Path $BridgeRoot 'app.json'
$TaskPath=Join-Path $BridgeRoot 'src\codeunit\GPIZetadocsAutoMigrationTask.Codeunit.al'
$PackageCache=Join-Path $BridgeRoot '.alpackages'
$TargetVersion='0.1.0.21'
$PackagePath=Join-Path $BridgeRoot "Gamer Packaging_GPI Zetadocs Pilot Bridge_$TargetVersion.app"

function Section([string]$n){Write-Host '';Write-Host ('='*120) -ForegroundColor Cyan;Write-Host $n -ForegroundColor Cyan;Write-Host ('='*120) -ForegroundColor Cyan}
function Read-Text([string]$p){[IO.File]::ReadAllText($p)}
function Write-Text([string]$p,[string]$t){[IO.File]::WriteAllText($p,$t,[Text.UTF8Encoding]::new($false))}
function Get-AlCompiler {
  $c=Get-ChildItem "$env:USERPROFILE\.vscode\extensions" -Directory -ErrorAction SilentlyContinue |
    Where-Object {$_.Name -like 'ms-dynamics-smb.al-*'} | Sort-Object LastWriteTime -Descending |
    ForEach-Object {$x=Join-Path $_.FullName 'bin\win32\alc.exe'; if(Test-Path $x){$x}} | Select-Object -First 1
  if(-not $c){throw 'AL compiler alc.exe was not found.'}; $c
}

Section '1. SAFETY / CANONICAL PROCEDURE REPLACEMENT'
$Branch=(& git -C $RepoRoot branch --show-current).Trim()
if($LASTEXITCODE -ne 0){throw 'Could not determine Git branch.'}
if($Branch -ne $ExpectedBranch){throw "Expected branch '$ExpectedBranch', found '$Branch'."}
foreach($p in @($BridgeRoot,$AppJson,$TaskPath,$PackageCache)){if(-not(Test-Path -LiteralPath $p)){throw "Required path missing: $p"}}

$App=Get-Content $AppJson -Raw|ConvertFrom-Json
if([string]$App.version -notin @('0.1.0.20','0.1.0.21')){throw "Unexpected bridge version $($App.version)."}
$Before=Read-Text $TaskPath
$Start=$Before.IndexOf('    procedure RecoverStaleRun()')
$Next=$Before.IndexOf('    procedure Resume()',$Start+1)
if($Start -lt 0 -or $Next -lt 0 -or $Next -le $Start){throw 'Could not isolate RecoverStaleRun() procedure.'}

$Stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$BackupRoot=Join-Path $RepoRoot ".gpi-backups\bridge-first-batch-stale-recovery-$TargetVersion-REV4-$Stamp"
New-Item -ItemType Directory -Path $BackupRoot -Force|Out-Null
Copy-Item $AppJson (Join-Path $BackupRoot 'app.json') -Force
Copy-Item $TaskPath (Join-Path $BackupRoot 'GPIZetadocsAutoMigrationTask.Codeunit.al') -Force
Write-Host "Bridge version : $($App.version)"
Write-Host "Backup         : $BackupRoot"
Write-Host 'Strategy       : replace only RecoverStaleRun() with canonical .21 implementation'
Write-Host 'Production     : NOT TOUCHED'

$Canonical=@'
    procedure RecoverStaleRun()
    var
        State: Record "GPI ZD Auto Migration State";
        StaleAge: Duration;
        StaleThreshold: Duration;
        StaleReferenceDateTime: DateTime;
        StaleReferenceLabel: Text[50];
    begin
        EnsureState(State);

        State.LockTable();
        State.Get(StateKey());

        if not State.Active then
            Error('Recovery is allowed only when the unattended migration is still marked Active.');

        if not State.Running then
            Error('Recovery is allowed only when the unattended migration is still marked Running.');

        if not IsNullGuid(State."Scheduled Task ID") then
            Error(
                'Recovery was blocked because Scheduled Task ID %1 is still recorded.',
                State."Scheduled Task ID");

        if State."Last Batch Date/Time" <> 0DT then begin
            StaleReferenceDateTime := State."Last Batch Date/Time";
            StaleReferenceLabel := 'last completed batch';
        end else begin
            if State."Started Date/Time" = 0DT then
                Error('Recovery was blocked because neither Last Batch Date/Time nor Started Date/Time is available to prove the run is stale.');

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

        State.Active := false;
        State.Running := false;
        State."Stop Requested" := false;
        State.Status := 'Stopped: stale run recovered';
        Clear(State."Scheduled Task ID");
        State."Last Error" :=
            CopyStr(
                StrSubstNo(
                    'Stale unattended migration execution state recovered at %1 using %2 time %3 as the stale reference. Counters, migration audit rows, links, family, and batch size were preserved. Use Resume to continue.',
                    CurrentDateTime(),
                    StaleReferenceLabel,
                    StaleReferenceDateTime),
                1,
                MaxStrLen(State."Last Error"));
        State.Modify(true);
    end;

'@

try {
  $After=$Before.Substring(0,$Start)+$Canonical+$Before.Substring($Next)
  foreach($m in @(
    'StaleReferenceDateTime: DateTime;',
    'StaleReferenceLabel: Text[50];',
    'if State."Last Batch Date/Time" <> 0DT then begin',
    'StaleReferenceDateTime := State."Started Date/Time";',
    "StaleReferenceLabel := 'run start';",
    'StaleThreshold := 60 * 60 * 1000;',
    'if not IsNullGuid(State."Scheduled Task ID") then',
    'procedure Resume()'
  )){if(-not $After.Contains($m)){throw "Canonical validation marker missing: $m"}}
  if($After.Contains('Recovery was blocked because there is no Last Batch Date/Time to prove the run is stale.')){throw 'Old recovery dead-end still present.'}

  Write-Text $TaskPath $After
  $Raw=Read-Text $AppJson
  $Raw=[regex]::Replace($Raw,'("version"\s*:\s*")0\.1\.0\.(20|21)(")','${1}0.1.0.21${3}',1)
  Write-Text $AppJson $Raw

  Section '2. COMPILE BRIDGE .21'
  $Compiler=Get-AlCompiler
  if(Test-Path $PackagePath){Remove-Item $PackagePath -Force}
  & $Compiler "/project:$BridgeRoot" "/packagecachepath:$PackageCache" "/out:$PackagePath"
  if($LASTEXITCODE -ne 0){throw "AL compile failed with exit code $LASTEXITCODE."}
  if(-not(Test-Path $PackagePath)){throw 'Compile succeeded but .21 package is missing.'}
  $Pkg=Get-Item $PackagePath
  $Hash=(Get-FileHash $PackagePath -Algorithm SHA256).Hash.ToUpperInvariant()
  Section '3. RESULT'
  Write-Host 'BRIDGE .21 COMPILED' -ForegroundColor Green
  Write-Host "Package : $($Pkg.FullName)"
  Write-Host "Bytes   : $($Pkg.Length)"
  Write-Host "SHA256  : $Hash"
  Write-Host 'Production: NOT TOUCHED'
}
catch {
  Write-Host '';Write-Host 'REV4 FAILED - RESTORING TARGETED FILES' -ForegroundColor Red
  Copy-Item (Join-Path $BackupRoot 'app.json') $AppJson -Force
  Copy-Item (Join-Path $BackupRoot 'GPIZetadocsAutoMigrationTask.Codeunit.al') $TaskPath -Force
  if(Test-Path $PackagePath){Remove-Item $PackagePath -Force -ErrorAction SilentlyContinue}
  throw
}
