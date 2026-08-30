#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$MainPath = Join-Path $ToolRoot 'Invoke-GPIHub-V115-AP-AI-Routing-Learning-Golden.ps1'
$GeneratedPath = Join-Path $ToolRoot '.Invoke-GPIHub-V115-REV2.generated.ps1'
$ExpectedCommit = '95202888f533aca9eaf9235655ebe4c3298e07da'

if (-not (Test-Path -LiteralPath $MainPath -PathType Leaf)) {
    throw "V115 main script missing: $MainPath"
}

$script = Get-Content -LiteralPath $MainPath -Raw

# Repair 1: pin the exact currently approved AI routing feature commit.
$commitPattern = '\$ExpectedFeatureCommit = ''[0-9a-f]{40}'''
$commitReplacement = '$ExpectedFeatureCommit = ''' + $ExpectedCommit + ''''
$script = $script -replace $commitPattern, $commitReplacement

# Repair 2: avoid Windows wildcard expansion in scp. Copy the candidate directory
# as one recursive object into a dedicated remote parent, then point HOST_STAGE at
# the resulting /candidate child. This changes only temp staging mechanics.
$script = $script.Replace(
@'
rm -rf /tmp/gpi-ap-routing-v115-host
mkdir -p /tmp/gpi-ap-routing-v115-host
chmod 700 /tmp/gpi-ap-routing-v115-host
'@,
@'
rm -rf /tmp/gpi-ap-routing-v115-host /tmp/gpi-ap-routing-v115-stage
mkdir -p /tmp/gpi-ap-routing-v115-stage
chmod 700 /tmp/gpi-ap-routing-v115-stage
'@
)
$script = $script.Replace('"$CandidateRoot\*",','"$CandidateRoot",')
$script = $script.Replace('"azureuser@$SourceIp`:/tmp/gpi-ap-routing-v115-host/"','"azureuser@$SourceIp`:/tmp/gpi-ap-routing-v115-stage/"')
$script = $script.Replace("HOST_STAGE='/tmp/gpi-ap-routing-v115-host'","HOST_STAGE='/tmp/gpi-ap-routing-v115-stage/candidate'")

$expectedPinText = '$ExpectedFeatureCommit = ''' + $ExpectedCommit + ''''
if ($script.Contains('"$CandidateRoot\*",')) {
    throw 'V115 REV2 repair failed: wildcard scp source remains.'
}
if (-not $script.Contains("HOST_STAGE='/tmp/gpi-ap-routing-v115-stage/candidate'")) {
    throw 'V115 REV2 repair failed: robust remote staging path not installed.'
}
if (-not $script.Contains($expectedPinText)) {
    throw 'V115 REV2 repair failed: exact feature commit pin not installed.'
}

Set-Content -LiteralPath $GeneratedPath -Value $script -Encoding utf8 -NoNewline

try {
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($GeneratedPath,[ref]$tokens,[ref]$errors)
    if (@($errors).Count -gt 0) {
        $text = (@($errors) | ForEach-Object { $_.Message }) -join '; '
        throw "V115 REV2 generated script parse failed: $text"
    }

    Write-Host 'V115_REV2_FEATURE_COMMIT_PIN=PASS' -ForegroundColor Green
    Write-Host 'V115_REV2_SCP_DIRECTORY_STAGE=PASS' -ForegroundColor Green
    Write-Host 'V115_REV2_GENERATED_PARSE=PASS' -ForegroundColor Green

    & $GeneratedPath
    if (-not $?) {
        throw 'V115 main phase returned failure.'
    }

    Write-Host 'V115_REV2_ENTRY=PASS' -ForegroundColor Green
}
finally {
    Remove-Item -LiteralPath $GeneratedPath -Force -ErrorAction SilentlyContinue
}
