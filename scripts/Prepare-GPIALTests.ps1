param(
    [Parameter()]
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs",

    [Parameter()]
    [switch]$OpenInCode
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$productionProject = Join-Path $RepoRoot "bc-extension\zetadocs-replacement"
$testProject = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests"
$productionPackageCache = Join-Path $productionProject ".alpackages"
$testPackageCache = Join-Path $testProject ".alpackages"

foreach ($requiredPath in @($productionProject, $testProject, $productionPackageCache)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required path was not found: $requiredPath"
    }
}

$alExtensionsRoot = Join-Path $env:USERPROFILE ".vscode\extensions"
$alExtension = Get-ChildItem `
    -LiteralPath $alExtensionsRoot `
    -Directory `
    -Filter "ms-dynamics-smb.al-*" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if ($null -eq $alExtension) {
    throw "The Microsoft AL Language VS Code extension was not found under $alExtensionsRoot."
}

$compiler = Get-ChildItem `
    -LiteralPath $alExtension.FullName `
    -Recurse `
    -File `
    -Filter "alc.exe" |
    Select-Object -First 1

if ($null -eq $compiler) {
    throw "alc.exe was not found under $($alExtension.FullName)."
}

$productionApp = Get-Content `
    -LiteralPath (Join-Path $productionProject "app.json") `
    -Raw |
    ConvertFrom-Json

$testApp = Get-Content `
    -LiteralPath (Join-Path $testProject "app.json") `
    -Raw |
    ConvertFrom-Json

$productionOutput = Join-Path `
    $productionProject `
    ("{0}_{1}_{2}.app" -f $productionApp.publisher, $productionApp.name, $productionApp.version)

$testOutput = Join-Path `
    $testProject `
    ("{0}_{1}_{2}.app" -f $testApp.publisher, $testApp.name, $testApp.version)

Write-Host ""
Write-Host "============================================================"
Write-Host " GPI AL Production and Test Build"
Write-Host "============================================================"
Write-Host "Compiler:           $($compiler.FullName)"
Write-Host "Production project: $productionProject"
Write-Host "Test project:       $testProject"
Write-Host ""

if (Test-Path -LiteralPath $productionOutput) {
    Remove-Item -LiteralPath $productionOutput -Force
}

Write-Host "[BUILD] Production extension $($productionApp.version)"
& $compiler.FullName `
    "/project:$productionProject" `
    "/packagecachepath:$productionPackageCache" `
    "/out:$productionOutput"

if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $productionOutput)) {
    throw "The production extension build failed. The test extension was not prepared."
}

New-Item `
    -Path $testPackageCache `
    -ItemType Directory `
    -Force | Out-Null

Get-ChildItem `
    -LiteralPath $testPackageCache `
    -File `
    -Filter "*.app" `
    -ErrorAction SilentlyContinue |
    Remove-Item -Force

Write-Host "[COPY] Microsoft symbol packages"
Get-ChildItem `
    -LiteralPath $productionPackageCache `
    -File `
    -Filter "*.app" |
    Copy-Item `
        -Destination $testPackageCache `
        -Force

Write-Host "[COPY] Production extension dependency"
Copy-Item `
    -LiteralPath $productionOutput `
    -Destination $testPackageCache `
    -Force

if (Test-Path -LiteralPath $testOutput) {
    Remove-Item -LiteralPath $testOutput -Force
}

Write-Host "[BUILD] Test extension $($testApp.version)"
& $compiler.FullName `
    "/project:$testProject" `
    "/packagecachepath:$testPackageCache" `
    "/out:$testOutput"

if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $testOutput)) {
    throw "The test extension build failed. Review the compiler output above."
}

Write-Host ""
Write-Host "============================================================"
Write-Host " Production and test builds passed" -ForegroundColor Green
Write-Host "============================================================"
Write-Host "Production package: $productionOutput"
Write-Host "Test package:       $testOutput"
Write-Host ""
Write-Host "Publish both packages only to Sandbox_5_5_2026."
Write-Host "Then refresh the VS Code Testing panel and run the complete test suite."
Write-Host ""

if ($OpenInCode) {
    $codeCommand = Get-Command code -ErrorAction SilentlyContinue
    if ($null -eq $codeCommand) {
        Write-Warning "The code command is not available in PATH."
    }
    else {
        & code $testProject
    }
}
