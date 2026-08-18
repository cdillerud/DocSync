[CmdletBinding()]
param(
    [Parameter()]
    [string]$AppPath = (Split-Path -Parent $PSScriptRoot),

    [Parameter()]
    [string]$PackageCachePath = '',

    [Parameter()]
    [string]$CompilerPath = '',

    [Parameter()]
    [string]$OutputPath = ''
)

$ErrorActionPreference = 'Stop'

function Write-Step {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

if (-not (Test-Path -LiteralPath $AppPath -PathType Container)) {
    throw "App path does not exist: $AppPath"
}

$AppPath = [System.IO.Path]::GetFullPath($AppPath)
$AppJsonPath = Join-Path $AppPath 'app.json'
$ValidatorPath = Join-Path $AppPath 'scripts\Test-GPIPackagingCatalogScaffold.ps1'

if (-not (Test-Path -LiteralPath $AppJsonPath -PathType Leaf)) {
    throw "app.json was not found: $AppJsonPath"
}

if (-not (Test-Path -LiteralPath $ValidatorPath -PathType Leaf)) {
    throw "Validator was not found: $ValidatorPath"
}

Write-Step 'Running scaffold validation'
& $ValidatorPath -AppPath $AppPath
if ($LASTEXITCODE -ne 0) {
    throw "Scaffold validation failed with exit code $LASTEXITCODE"
}

if ([string]::IsNullOrWhiteSpace($PackageCachePath)) {
    $PackageCachePath = Join-Path $AppPath '.alpackages'
}
$PackageCachePath = [System.IO.Path]::GetFullPath($PackageCachePath)

if (-not (Test-Path -LiteralPath $PackageCachePath -PathType Container)) {
    throw @"
AL symbol cache does not exist:
  $PackageCachePath

Open this project in Visual Studio Code and run:
  AL: Download Symbols from Global Sources

Then rerun this build script.
"@
}

$SymbolFiles = @(Get-ChildItem -LiteralPath $PackageCachePath -File -Filter '*.app' -ErrorAction SilentlyContinue)
if ($SymbolFiles.Count -eq 0) {
    throw @"
No AL symbol packages were found in:
  $PackageCachePath

Open this project in Visual Studio Code and run:
  AL: Download Symbols from Global Sources

Then rerun this build script.
"@
}

if ([string]::IsNullOrWhiteSpace($CompilerPath)) {
    $ExtensionsRoot = Join-Path $env:USERPROFILE '.vscode\extensions'
    if (-not (Test-Path -LiteralPath $ExtensionsRoot -PathType Container)) {
        throw "VS Code extensions folder was not found: $ExtensionsRoot"
    }

    $CompilerCandidates = @(
        Get-ChildItem -LiteralPath $ExtensionsRoot -Directory -Filter 'ms-dynamics-smb.al-*' -ErrorAction SilentlyContinue |
            ForEach-Object {
                $Candidate = Join-Path $_.FullName 'bin\win32\alc.exe'
                if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
                    Get-Item -LiteralPath $Candidate
                }
            } |
            Sort-Object LastWriteTime -Descending
    )

    if ($CompilerCandidates.Count -eq 0) {
        throw 'No AL compiler was found under the installed VS Code AL Language extensions.'
    }

    $CompilerPath = $CompilerCandidates[0].FullName
}

$CompilerPath = [System.IO.Path]::GetFullPath($CompilerPath)
if (-not (Test-Path -LiteralPath $CompilerPath -PathType Leaf)) {
    throw "AL compiler does not exist: $CompilerPath"
}

$AppJson = Get-Content -LiteralPath $AppJsonPath -Raw | ConvertFrom-Json

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $SafeName = ($AppJson.name -replace '[<>:"/\\|?*]', '_')
    $OutputPath = Join-Path $AppPath ("{0}_{1}.app" -f $SafeName, $AppJson.version)
}
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)

if (Test-Path -LiteralPath $OutputPath -PathType Leaf) {
    Remove-Item -LiteralPath $OutputPath -Force
}

Write-Step 'Compiling GPI Packaging Catalog'
Write-Host "Project  : $AppPath"
Write-Host "Compiler : $CompilerPath"
Write-Host "Symbols  : $PackageCachePath"
Write-Host "Output   : $OutputPath"
Write-Host "Packages : $($SymbolFiles.Count)"
Write-Host ''

$ProjectArg = "/project:$AppPath"
$PackageArg = "/packagecachepath:$PackageCachePath"
$OutputArg = "/out:$OutputPath"

& $CompilerPath $ProjectArg $PackageArg $OutputArg
$CompilerExitCode = $LASTEXITCODE

if ($CompilerExitCode -ne 0) {
    throw "AL compilation failed with exit code $CompilerExitCode"
}

if (-not (Test-Path -LiteralPath $OutputPath -PathType Leaf)) {
    throw 'AL compiler returned success but the expected .app file was not created.'
}

$OutputFile = Get-Item -LiteralPath $OutputPath

Write-Host ''
Write-Host 'GPI Packaging Catalog compilation PASSED.' -ForegroundColor Green
Write-Host "App      : $($OutputFile.FullName)"
Write-Host "Size     : $($OutputFile.Length) bytes"
Write-Host "Modified : $($OutputFile.LastWriteTime)"
Write-Host ''
Write-Host 'No publish or deployment was performed.' -ForegroundColor Yellow
