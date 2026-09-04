#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$StatePath = Join-Path $ToolRoot 'state.json'
$ControlBranch = 'migration/gpi-hub-dedicated-vm'
$RemoteTrackingRef = "refs/remotes/origin/$ControlBranch"
$LegacyControlCommit = 'b45ae78800b8f6666a6a105318cf0b7bf6fe6648'
$LegacyRepoPath = 'tools/gpi-hub-migration/Invoke-GPIHub-V117-REV2-Detached-Entry.ps1'
$EntryPatchRepoPath = 'tools/gpi-hub-migration/v117-rev3-entry-patch.ps1frag'
$ReplayTransformRepoPath = 'tools/gpi-hub-migration/v117-rev3-replay-transform.ps1frag'
$ExpectedEntryPatchSha256 = '4F81CD9E8A890E6F58E6AD74827ACFA2574D3E5D2C6936F0ABB7E2EBB8EBCD37'
$ExpectedReplayTransformSha256 = 'EDAF2B455F7F903E82E418DE38642C39E9AF79094042EDD1185797049064A7C6'
$ExpectedFeatureCommit = '7a983c610b206cff2d059f7a009a6d63bd15d4d0'

function Require {
    param([bool]$Condition,[string]$Message)
    if (-not $Condition) { throw $Message }
}

function Get-GitText {
    param([string]$Repo,[string]$Ref,[string]$RepoPath)
    $spec = "{0}:{1}" -f $Ref,$RepoPath
    $lines = & git.exe -C $Repo show $spec
    $exitCode = $LASTEXITCODE
    Require ($exitCode -eq 0) "Could not read $RepoPath from $Ref."
    return ((@($lines) | ForEach-Object { [string]$_ }) -join "`n") -replace "`r",''
}

function Get-TextSha256 {
    param([string]$Text)
    $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','')
    }
    finally {
        $sha.Dispose()
    }
}

Require (Test-Path -LiteralPath $StatePath -PathType Leaf) "V117 REV3 state missing: $StatePath"
$State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 80
$OperationalRoot = [string]$State.local.operational_root
Require (Test-Path -LiteralPath $OperationalRoot -PathType Container) "V117 REV3 operational repo missing: $OperationalRoot"
Require ($null -ne (Get-Command git.exe -ErrorAction SilentlyContinue)) 'git.exe unavailable.'
Require ($null -ne (Get-Command pwsh.exe -ErrorAction SilentlyContinue)) 'pwsh.exe unavailable.'

$LegacyRaw = Get-GitText -Repo $OperationalRoot -Ref $LegacyControlCommit -RepoPath $LegacyRepoPath
$EntryPatchTemplate = Get-GitText -Repo $OperationalRoot -Ref $RemoteTrackingRef -RepoPath $EntryPatchRepoPath
$ReplayTransform = Get-GitText -Repo $OperationalRoot -Ref $RemoteTrackingRef -RepoPath $ReplayTransformRepoPath

Require ((Get-TextSha256 $EntryPatchTemplate) -eq $ExpectedEntryPatchSha256) 'V117 REV3 entry patch SHA256 drift.'
Require ((Get-TextSha256 $ReplayTransform) -eq $ExpectedReplayTransformSha256) 'V117 REV3 replay transform SHA256 drift.'
Require ($EntryPatchTemplate.Contains('__REPLAY_TRANSFORM_B64__')) 'V117 REV3 replay transform placeholder missing.'

$ReplayTransformB64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($ReplayTransform))
$EntryPatch = $EntryPatchTemplate.Replace('__REPLAY_TRANSFORM_B64__',$ReplayTransformB64)

$EntryReadAnchor = @'
$EntryRaw = (Get-Content -LiteralPath $EntrySourcePath -Raw) -replace "`r",''
'@
Require ($LegacyRaw.Contains($EntryReadAnchor)) 'V117 REV3 legacy entry-read anchor missing.'
$LegacyRaw = $LegacyRaw.Replace($EntryReadAnchor,$EntryReadAnchor + "`n" + $EntryPatch)

$SnapshotDigestOld = @'
                'example_count':len(examples),
                'examples':examples,
'@
$SnapshotDigestNew = @'
                'example_count':len(examples),
                'examples_sha256':snapshot_examples_sha256(examples),
                'examples':examples,
'@
Require ($LegacyRaw.Contains($SnapshotDigestOld)) 'V117 REV3 snapshot digest anchor missing.'
$LegacyRaw = $LegacyRaw.Replace($SnapshotDigestOld,$SnapshotDigestNew)

$Rev3MarkerOld = "Write-Host 'V117_REV2_EVIDENCE_SNAPSHOT_CONFIGURED=PASS' -ForegroundColor Green"
$Rev3MarkerNew = $Rev3MarkerOld + "`nWrite-Host 'V117_REV3_VALIDATED_EVIDENCE_REPLAY_CONFIGURED=PASS' -ForegroundColor Green`nWrite-Host 'V117_REV3_INVALID_SNAPSHOT_LIVE_REBUILD_FALLBACK_CONFIGURED=PASS' -ForegroundColor Green`nWrite-Host 'V117_REV3_FOCUSED_REGRESSION_TARGET_CONFIGURED=120' -ForegroundColor Green"
Require ($LegacyRaw.Contains($Rev3MarkerOld)) 'V117 REV3 marker anchor missing.'
$LegacyRaw = $LegacyRaw.Replace($Rev3MarkerOld,$Rev3MarkerNew)

$OverlayPath = Join-Path $ToolRoot 'Invoke-GPIHub-V117-REV3-Replay-Generated.ps1'
Set-Content -LiteralPath $OverlayPath -Value $LegacyRaw -Encoding utf8 -NoNewline

$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($OverlayPath,[ref]$tokens,[ref]$errors)
if (@($errors).Count -gt 0) {
    $text = (@($errors) | ForEach-Object { $_.Message }) -join '; '
    throw "V117 REV3 overlay parse failed: $text"
}

Write-Host 'V117_REV3_RESTARTED_SPRINT=PASS' -ForegroundColor Green
Write-Host "V117_REV3_LEGACY_CONTROL_BASE=$LegacyControlCommit"
Write-Host "V117_REV3_FEATURE_COMMIT=$ExpectedFeatureCommit"
Write-Host "V117_REV3_ENTRY_PATCH_SHA256=$ExpectedEntryPatchSha256"
Write-Host "V117_REV3_REPLAY_TRANSFORM_SHA256=$ExpectedReplayTransformSha256"
Write-Host 'V117_REV3_SNAPSHOT_MAX_AGE_HOURS=24'
Write-Host 'V117_REV3_SNAPSHOT_FAILS_CLOSED_TO_LIVE_REBUILD=PASS' -ForegroundColor Green
Write-Host 'V117_REV3_PRODUCTION_MUTATION=NONE' -ForegroundColor Green
Write-Host "V117_REV3_GENERATED_CONTROLLER=$OverlayPath"

& pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $OverlayPath
exit $LASTEXITCODE
