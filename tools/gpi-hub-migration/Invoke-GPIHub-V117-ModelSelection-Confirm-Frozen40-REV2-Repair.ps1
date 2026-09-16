#requires -Version 7.0
[CmdletBinding()]
param(
    [int]$PilotSize = 24,
    [int]$ValidationSize = 100,
    [int]$ConcurrencyPerModel = 2
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$StatePath = Join-Path $ToolRoot 'state.json'
$BrokenCommit = 'd96611db1778c13a78255d5c889114a7c6cac16c'
$BrokenRepoPath = 'tools/gpi-hub-migration/Invoke-GPIHub-V117-ModelSelection-Confirm-Frozen40-REV1.ps1'
$ExpectedBrokenBlob = '3e4ef132c2643a0cdee623186e3f500fb24febbb'

function Require {
    param([bool]$Condition,[string]$Message)
    if (-not $Condition) { throw $Message }
}

function Get-GitText {
    param([string]$Repo,[string]$Ref,[string]$RepoPath)
    $spec = "{0}:{1}" -f $Ref,$RepoPath
    $lines = & git.exe -C $Repo show $spec
    $code = $LASTEXITCODE
    Require ($code -eq 0) "Could not read $RepoPath from $Ref."
    return ((@($lines) | ForEach-Object { [string]$_ }) -join "`n") -replace "`r",''
}

function Replace-NestedHereStringAssignmentWithBase64 {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$AssignmentMarker,
        [Parameter(Mandatory)][string]$FollowingMarker,
        [Parameter(Mandatory)][string]$VariableName
    )

    $start = $Text.IndexOf($AssignmentMarker,[StringComparison]::Ordinal)
    Require ($start -ge 0) "Missing nested here-string start marker for $VariableName."

    $bodyStart = $start + $AssignmentMarker.Length
    if ($Text.Substring($bodyStart).StartsWith("`n")) { $bodyStart++ }

    $follow = $Text.IndexOf($FollowingMarker,$bodyStart,[StringComparison]::Ordinal)
    Require ($follow -gt $bodyStart) "Missing following marker for $VariableName."

    $terminator = $Text.LastIndexOf("'@",$follow,[StringComparison]::Ordinal)
    Require ($terminator -gt $bodyStart) "Missing nested here-string terminator for $VariableName."

    $body = $Text.Substring($bodyStart,$terminator-$bodyStart)
    if ($body.EndsWith("`n")) { $body = $body.Substring(0,$body.Length-1) }

    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($body))
    $replacement = '$' + $VariableName + " = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + $b64 + "'))"

    return $Text.Substring(0,$start) + $replacement + $Text.Substring($terminator+2)
}

Require (Test-Path -LiteralPath $StatePath -PathType Leaf) "Repair state missing: $StatePath"
Require ($null -ne (Get-Command git.exe -ErrorAction SilentlyContinue)) 'git.exe unavailable.'
Require ($null -ne (Get-Command pwsh.exe -ErrorAction SilentlyContinue)) 'pwsh.exe unavailable.'

$State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 80
$OperationalRoot = [string]$State.local.operational_root
Require (Test-Path -LiteralPath $OperationalRoot -PathType Container) "Operational repo missing: $OperationalRoot"

$brokenSpec = "{0}:{1}" -f $BrokenCommit,$BrokenRepoPath
$brokenBlob = (& git.exe -C $OperationalRoot rev-parse $brokenSpec).Trim()
Require ($LASTEXITCODE -eq 0) 'Could not resolve broken confirmation controller blob.'
Require ($brokenBlob -ceq $ExpectedBrokenBlob) "Broken controller blob drift: $brokenBlob"

$Raw = Get-GitText -Repo $OperationalRoot -Ref $BrokenCommit -RepoPath $BrokenRepoPath

# The original REV1 confirmation controller contains two nested single-quoted
# here-string assignments. PowerShell terminates the outer string when it sees
# the first inner '@ terminator. Convert the inner assignment first, then the
# outer assignment, so each generated layer receives ordinary decoded text.
$Raw = Replace-NestedHereStringAssignmentWithBase64 `
    -Text $Raw `
    -AssignmentMarker '$InnerInvokeNew = @''' `
    -FollowingMarker 'Require ($ConfirmWrapperRaw.Contains($InnerInvokeOld))' `
    -VariableName 'InnerInvokeNew'

$Raw = Replace-NestedHereStringAssignmentWithBase64 `
    -Text $Raw `
    -AssignmentMarker '$InvokeNew = @''' `
    -FollowingMarker 'Require ($Raw.Contains($InvokeOld))' `
    -VariableName 'InvokeNew'

$GeneratedController = Join-Path $ToolRoot 'Invoke-GPIHub-V117-ModelSelection-Confirm-Frozen40-REV2-Generated.ps1'
Set-Content -LiteralPath $GeneratedController -Value $Raw -Encoding utf8 -NoNewline

$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($GeneratedController,[ref]$tokens,[ref]$errors)
if (@($errors).Count -gt 0) {
    $text = (@($errors) | ForEach-Object { "line=$($_.Extent.StartLineNumber): $($_.Message)" }) -join '; '
    throw "Frozen-40 REV2 repaired controller parse failed: $text"
}

Write-Host 'V117_CONFIRM_REV2_BROKEN_CONTROLLER_BLOB=3e4ef132c2643a0cdee623186e3f500fb24febbb' -ForegroundColor Green
Write-Host 'V117_CONFIRM_REV2_INNER_HERESTRING_BASE64_REPAIR=PASS' -ForegroundColor Green
Write-Host 'V117_CONFIRM_REV2_OUTER_HERESTRING_BASE64_REPAIR=PASS' -ForegroundColor Green
Write-Host 'V117_CONFIRM_REV2_REPAIRED_CONTROLLER_PARSE=PASS' -ForegroundColor Green
Write-Host 'V117_CONFIRM_REV2_SELECTION_LOGIC=UNCHANGED' -ForegroundColor Green
Write-Host 'V117_CONFIRM_REV2_FROZEN40_EXCLUSION_LOGIC=UNCHANGED' -ForegroundColor Green
Write-Host 'V117_CONFIRM_REV2_AUTHORITY_THRESHOLDS=UNCHANGED' -ForegroundColor Green
Write-Host 'V117_CONFIRM_REV2_PRODUCTION_MUTATION=NONE' -ForegroundColor Green
Write-Host "V117_CONFIRM_REV2_GENERATED_CONTROLLER=$GeneratedController"

& pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $GeneratedController `
    -PilotSize $PilotSize `
    -ValidationSize $ValidationSize `
    -ConcurrencyPerModel $ConcurrencyPerModel
exit $LASTEXITCODE
