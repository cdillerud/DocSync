[CmdletBinding()]
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
    [string]$ExpectedBranch = 'feature/square9-parity-systemid-gate',
    [string]$ExpectedHead = '',
    [switch]$SkipSharePointSchema,
    [switch]$SkipALCompile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Section {
    param([string]$Title)
    Write-Host "`n================================================================================================================" -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host "================================================================================================================" -ForegroundColor Cyan
}

function Fail {
    param([string]$Message)
    throw "PARITY VALIDATION FAILED: $Message"
}

function Get-EnvFileValue {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Name
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    $match = Get-Content -LiteralPath $Path | Where-Object {
        $_ -match ('^\s*' + [regex]::Escape($Name) + '\s*=')
    } | Select-Object -Last 1

    if (-not $match) {
        return $null
    }

    $value = ($match -split '=', 2)[1].Trim()
    if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    return $value
}

function Get-EffectiveSetting {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$EnvFile
    )

    $processValue = [Environment]::GetEnvironmentVariable($Name, 'Process')
    if (-not [string]::IsNullOrWhiteSpace($processValue)) {
        return $processValue.Trim()
    }

    return Get-EnvFileValue -Path $EnvFile -Name $Name
}

function Assert-TrueSetting {
    param(
        [string]$Name,
        [string]$EnvFile
    )

    $effective = Get-EffectiveSetting -Name $Name -EnvFile $EnvFile

    if ([string]::IsNullOrWhiteSpace($effective)) {
        Write-Host "$Name : not explicitly set; application default must remain fail-closed" -ForegroundColor Yellow
        return
    }

    if ($effective.Trim().ToLowerInvariant() -notin @('1', 'true', 'yes', 'on')) {
        Fail "$Name must be true for UAT validation. Effective value was '$effective'."
    }

    Write-Host "$Name : TRUE" -ForegroundColor Green
}

function Find-Python {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return [pscustomobject]@{
            Command = $python.Source
            PrefixArgs = @()
        }
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return [pscustomobject]@{
            Command = $py.Source
            PrefixArgs = @('-3')
        }
    }

    Fail 'Python 3 was not found in PATH.'
}

function Find-ALCompiler {
    $roots = @(
        (Join-Path $env:USERPROFILE '.vscode\extensions'),
        (Join-Path $env:USERPROFILE '.vscode-insiders\extensions')
    ) | Where-Object { Test-Path -LiteralPath $_ }

    $candidates = foreach ($root in $roots) {
        Get-ChildItem -LiteralPath $root -Directory -Filter 'ms-dynamics-smb.al-*' -ErrorAction SilentlyContinue | ForEach-Object {
            $extensionDir = $_.FullName
            $exe = Join-Path $extensionDir 'bin\win32\alc.exe'
            $dll = Join-Path $extensionDir 'bin\alc.dll'
            if (Test-Path -LiteralPath $exe) {
                [pscustomobject]@{
                    Type = 'exe'
                    Path = $exe
                    Version = $_.Name.Substring('ms-dynamics-smb.al-'.Length)
                }
            }
            elseif (Test-Path -LiteralPath $dll) {
                [pscustomobject]@{
                    Type = 'dll'
                    Path = $dll
                    Version = $_.Name.Substring('ms-dynamics-smb.al-'.Length)
                }
            }
        }
    }

    $selected = $candidates | Sort-Object {
        try { [version]($_.Version -replace '-.*$', '') } catch { [version]'0.0' }
    } -Descending | Select-Object -First 1

    if (-not $selected) {
        Fail 'Microsoft AL Language compiler was not found. Install/enable the Microsoft AL Language extension in VS Code.'
    }

    return $selected
}

Write-Section '1. REPOSITORY SAFETY CHECK'

$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$BackendRoot = Join-Path $RepoRoot 'backend'
$BCExtensionRoot = Join-Path $RepoRoot 'bc-extension'
$EnvFile = Join-Path $BackendRoot '.env'

if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot '.git'))) {
    Fail "RepoRoot is not a Git working tree: $RepoRoot"
}

Push-Location $RepoRoot
try {
    $branch = (& git rev-parse --abbrev-ref HEAD).Trim()
    $head = (& git rev-parse HEAD).Trim()
    $dirty = & git status --porcelain

    Write-Host "Repo   : $RepoRoot"
    Write-Host "Branch : $branch"
    Write-Host "HEAD   : $head"

    if ($branch -ne $ExpectedBranch) {
        Fail "Expected branch '$ExpectedBranch' but current branch is '$branch'."
    }

    if (-not [string]::IsNullOrWhiteSpace($ExpectedHead) -and $head -ne $ExpectedHead) {
        Fail "Expected evidence head '$ExpectedHead' but current HEAD is '$head'. Pull/review the intended head or omit -ExpectedHead to validate the checked-out clean branch."
    }

    if ($dirty) {
        Fail 'Working tree is not clean. Commit/stash changes before generating parity evidence.'
    }
}
finally {
    Pop-Location
}

Write-Host 'Repository checkpoint verified.' -ForegroundColor Green

Write-Section '2. PRODUCTION WRITE INTERLOCKS'
Assert-TrueSetting -Name 'BC_BLOCK_PRODUCTION_WRITES' -EnvFile $EnvFile
Assert-TrueSetting -Name 'SHAREPOINT_BLOCK_PRODUCTION_WRITES' -EnvFile $EnvFile

$sharePointTarget = Get-EffectiveSetting -Name 'SHAREPOINT_TARGET' -EnvFile $EnvFile
$sharePointPath = Get-EffectiveSetting -Name 'SHAREPOINT_SITE_PATH' -EnvFile $EnvFile
$bcWriteEnvironment = Get-EffectiveSetting -Name 'BC_WRITE_ENVIRONMENT' -EnvFile $EnvFile

if ($sharePointTarget -and $sharePointTarget.Trim().ToLowerInvariant() -eq 'production') {
    Fail 'SHAREPOINT_TARGET=production is not allowed in this UAT evidence harness.'
}
if ($sharePointPath -and $sharePointPath.Trim().TrimEnd('/') -ieq '/sites/GamerAccounting') {
    Fail 'SHAREPOINT_SITE_PATH points to GamerAccounting Production. UAT validation aborted.'
}
if ($bcWriteEnvironment -and $bcWriteEnvironment -match '(?i)^production$') {
    Fail 'BC_WRITE_ENVIRONMENT=Production is not allowed in this UAT evidence harness.'
}

Write-Host "SharePoint target      : $(if ($sharePointTarget) { $sharePointTarget } else { '<default test>' })"
Write-Host "SharePoint site path   : $(if ($sharePointPath) { $sharePointPath } else { '<default /sites/GPI-DocumentHub-Test>' })"
Write-Host "BC write environment   : $(if ($bcWriteEnvironment) { $bcWriteEnvironment } else { '<application default>' })"
Write-Host 'Production write boundaries verified.' -ForegroundColor Green

if (-not $SkipSharePointSchema) {
    Write-Section '3. LIVE SHAREPOINT PARITY SCHEMA PREFLIGHT'

    $python = Find-Python
    $script = Join-Path $BackendRoot 'scripts\validate_sharepoint_parity_schema.py'
    if (-not (Test-Path -LiteralPath $script)) {
        Fail "SharePoint schema diagnostic not found: $script"
    }

    Push-Location $BackendRoot
    try {
        $pythonArgs = @($python.PrefixArgs) + @($script)
        & $python.Command @pythonArgs
        if ($LASTEXITCODE -ne 0) {
            Fail "Live SharePoint schema preflight returned exit code $LASTEXITCODE. Review missing/incompatible GPI columns above."
        }
    }
    finally {
        Pop-Location
    }

    Write-Host 'Live SharePoint metadata schema: READY.' -ForegroundColor Green
}
else {
    Write-Section '3. LIVE SHAREPOINT PARITY SCHEMA PREFLIGHT'
    Write-Host 'SKIPPED by explicit switch. This remains an unproven parity risk.' -ForegroundColor Yellow
}

if (-not $SkipALCompile) {
    Write-Section '4. TRUE AL COMPILATION'

    $appJson = Join-Path $BCExtensionRoot 'app.json'
    $symbolPath = Join-Path $BCExtensionRoot '.alpackages'
    $outputPath = Join-Path $BCExtensionRoot '.uat-parity-build'

    if (-not (Test-Path -LiteralPath $appJson)) {
        Fail "Business Central app.json not found: $appJson"
    }
    if (-not (Test-Path -LiteralPath $symbolPath)) {
        Fail "BC symbol cache not found: $symbolPath. In VS Code, open bc-extension and run 'AL: Download Symbols' against Sandbox_NoZetadocs_UAT first."
    }
    if (-not (Get-ChildItem -LiteralPath $symbolPath -Filter '*.app' -File -ErrorAction SilentlyContinue)) {
        Fail "$symbolPath contains no .app symbols. Run 'AL: Download Symbols' against Sandbox_NoZetadocs_UAT first."
    }

    $compiler = Find-ALCompiler
    Write-Host "AL compiler : $($compiler.Path)"
    Write-Host "AL version  : $($compiler.Version)"
    Write-Host "Symbols     : $symbolPath"

    if (Test-Path -LiteralPath $outputPath) {
        Remove-Item -LiteralPath $outputPath -Recurse -Force
    }
    New-Item -ItemType Directory -Path $outputPath | Out-Null

    $outFile = Join-Path $outputPath 'GPI_Hub_Integration_UAT_Parity.app'
    $errorLog = Join-Path $outputPath 'alc-errors.txt'

    $arguments = @(
        "/project:$BCExtensionRoot",
        "/packagecachepath:$symbolPath",
        "/out:$outFile",
        "/errorlog:$errorLog"
    )

    if ($compiler.Type -eq 'exe') {
        & $compiler.Path @arguments
    }
    else {
        $dotnet = Get-Command dotnet -ErrorAction SilentlyContinue
        if (-not $dotnet) {
            Fail "AL compiler is a DLL but dotnet was not found: $($compiler.Path)"
        }
        & $dotnet.Source $compiler.Path @arguments
    }

    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $outFile)) {
        if (Test-Path -LiteralPath $errorLog) {
            Write-Host "`nAL compiler errors:" -ForegroundColor Red
            Get-Content -LiteralPath $errorLog | Write-Host
        }
        Fail "AL compilation failed with exit code $LASTEXITCODE. No publish was attempted."
    }

    Write-Host "Compiled app: $outFile" -ForegroundColor Green
    Write-Host 'AL compilation: PASS. No publish was attempted.' -ForegroundColor Green
}
else {
    Write-Section '4. TRUE AL COMPILATION'
    Write-Host 'SKIPPED by explicit switch. Compiler proof remains an unproven parity risk.' -ForegroundColor Yellow
}

Write-Section '5. RESULT'
Write-Host 'PASS: fail-closed UAT preflight completed.' -ForegroundColor Green
Write-Host 'This script performs no Business Central publish and no intentional SharePoint/BC document writes.'
Write-Host 'Next evidence step is controlled UAT publish + representative AP/Warehouse end-to-end validation.'
