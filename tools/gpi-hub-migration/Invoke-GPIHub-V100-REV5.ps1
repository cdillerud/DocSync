#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$BaseScript = Join-Path $ToolRoot 'Invoke-GPIHub-V100.ps1'
$Rev4Script = Join-Path $ToolRoot 'Invoke-GPIHub-V100-REV4.ps1'
$PatchedBase = Join-Path $ToolRoot 'Invoke-GPIHub-V100-REV5-base.generated.ps1'
$PatchedRunner = Join-Path $ToolRoot 'Invoke-GPIHub-V100-REV5-runner.generated.ps1'

function Require([bool]$Condition,[string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Replace-ExactOnce {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$Old,
        [Parameter(Mandatory)][string]$New,
        [Parameter(Mandatory)][string]$Label
    )
    $first = $Text.IndexOf($Old,[System.StringComparison]::Ordinal)
    Require ($first -ge 0) "REV5 patch anchor missing: $Label"
    $second = $Text.IndexOf($Old,$first + $Old.Length,[System.StringComparison]::Ordinal)
    Require ($second -lt 0) "REV5 patch anchor not unique: $Label"
    return $Text.Substring(0,$first) + $New + $Text.Substring($first + $Old.Length)
}

Require (Test-Path -LiteralPath $BaseScript -PathType Leaf) "Base V100 script missing: $BaseScript"
Require (Test-Path -LiteralPath $Rev4Script -PathType Leaf) "REV4 script missing: $Rev4Script"

$base = (Get-Content -LiteralPath $BaseScript -Raw) -replace "`r`n","`n"

$base = Replace-ExactOnce -Text $base `
    -Old '            $serviceCfg[$Name] = [ordered]@{ Environment = $false; Port = $null; Volumes = @() }' `
    -New '            $serviceCfg[$Name] = [ordered]@{ Environment = $false; Port = $null; Volumes = @(); Image = $null }' `
    -Label 'service config image property'

$oldServiceInit = @'
    Ensure-ServiceCfg $backend.Service
    Ensure-ServiceCfg $frontend.Service
    Ensure-ServiceCfg $mongo.Service
    $serviceCfg[$backend.Service].Environment = $true
'@
$newServiceInit = @'
    Ensure-ServiceCfg $backend.Service
    Ensure-ServiceCfg $frontend.Service
    Ensure-ServiceCfg $mongo.Service

    foreach ($c in $containers) {
        Ensure-ServiceCfg $c.Service
        Require (-not [string]::IsNullOrWhiteSpace([string]$c.Image)) "Source image reference missing for service '$($c.Service)'."
        Require ([string]$c.Image -notmatch '[\r\n"]') "Unsafe source image reference for service '$($c.Service)': $($c.Image)"
        $serviceCfg[$c.Service].Image = [string]$c.Image
    }

    $serviceCfg[$backend.Service].Environment = $true
'@
$base = Replace-ExactOnce -Text $base -Old $oldServiceInit -New $newServiceInit -Label 'service image assignment'

$oldYaml = @'
        $cfg = $serviceCfg[$serviceName]
        $yaml.Add("  ${serviceName}:")
        if ($cfg.Environment) {
'@
$newYaml = @'
        $cfg = $serviceCfg[$serviceName]
        $yaml.Add("  ${serviceName}:")
        if (-not [string]::IsNullOrWhiteSpace([string]$cfg.Image)) {
            $yaml.Add(('    image: "{0}"' -f $cfg.Image))
        }
        if ($cfg.Environment) {
'@
$base = Replace-ExactOnce -Text $base -Old $oldYaml -New $newYaml -Label 'compose image pin'

$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseInput($base,[ref]$tokens,[ref]$errors)
if ($errors.Count -gt 0) {
    $detail = ($errors | ForEach-Object { "Line $($_.Extent.StartLineNumber): $($_.Message)" }) -join "`n"
    throw "REV5 patched base failed parser validation:`n$detail"
}
Set-Content -LiteralPath $PatchedBase -Value $base -Encoding utf8 -NoNewline

$runner = (Get-Content -LiteralPath $Rev4Script -Raw) -replace "`r`n","`n"
$runner = Replace-ExactOnce -Text $runner `
    -Old '$BaseScript = Join-Path $ToolRoot ''Invoke-GPIHub-V100.ps1''' `
    -New '$BaseScript = Join-Path $ToolRoot ''Invoke-GPIHub-V100-REV5-base.generated.ps1''' `
    -Label 'REV4 base path'
$runner = Replace-ExactOnce -Text $runner `
    -Old '$GeneratedScript = Join-Path $ToolRoot ''Invoke-GPIHub-V100-REV4.generated.ps1''' `
    -New '$GeneratedScript = Join-Path $ToolRoot ''Invoke-GPIHub-V100-REV5.generated.ps1''' `
    -Label 'REV4 generated path'
$runner = $runner.Replace('V100 REV4 - CONFIGDB-GATED CAPTURED EXECUTION','V100 REV5 - EXACT-IMAGE-PIN RESUMABLE EXECUTION')
$runner = $runner.Replace('V100_REV4_PATCH_ANCHORS=PASS','V100_REV5_PATCH_ANCHORS=PASS')
$runner = $runner.Replace('V100_REV4_GENERATED_PARSER=PASS','V100_REV5_GENERATED_PARSER=PASS')
$runner = $runner.Replace('V100_REV4_CAPTURE_WRAPPER=PASS','V100_REV5_CAPTURE_WRAPPER=PASS')
$runner = $runner.Replace('V100_REV4_INNER_PHASE=PASS','V100_REV5_INNER_PHASE=PASS')
$runner = $runner.Replace('V100 REV4 FAILED - WINDOW WILL REMAIN OPEN','V100 REV5 FAILED - WINDOW WILL REMAIN OPEN')
$runner = $runner.Replace('V100 REV4 generated phase exited with code','V100 REV5 generated phase exited with code')

$oldCapture = @'
    $allOutput = & pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $GeneratedScript 2>&1
    $exitCode = $LASTEXITCODE
    $text = (@($allOutput) | ForEach-Object { [string]$_ }) -join "`r`n"
    Set-Content -LiteralPath $RunLog -Value $text -Encoding utf8
    if (-not [string]::IsNullOrWhiteSpace($text)) { Write-Host $text }

    if ($exitCode -ne 0) { throw "V100 REV5 generated phase exited with code $exitCode." }
'@
$newCapture = @'
    & pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $GeneratedScript 2>&1 |
        Tee-Object -FilePath $RunLog |
        ForEach-Object { Write-Host ([string]$_) }
    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0) { throw "V100 REV5 generated phase exited with code $exitCode." }
'@
$runner = Replace-ExactOnce -Text $runner -Old $oldCapture -New $newCapture -Label 'live output capture'

$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseInput($runner,[ref]$tokens,[ref]$errors)
if ($errors.Count -gt 0) {
    $detail = ($errors | ForEach-Object { "Line $($_.Extent.StartLineNumber): $($_.Message)" }) -join "`n"
    throw "REV5 runner failed parser validation:`n$detail"
}
Set-Content -LiteralPath $PatchedRunner -Value $runner -Encoding utf8 -NoNewline

Write-Host 'V100_REV5_EXACT_SOURCE_IMAGE_PIN=PASS' -ForegroundColor Green
Write-Host 'V100_REV5_RESUME_EXISTING_MONGO_RESTORE=ENABLED' -ForegroundColor Green
Write-Host 'V100_REV5_LIVE_OUTPUT=PASS' -ForegroundColor Green

& pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $PatchedRunner
exit $LASTEXITCODE
