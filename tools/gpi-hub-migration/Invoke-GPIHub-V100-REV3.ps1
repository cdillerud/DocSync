#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$StatePath = Join-Path $ToolRoot 'state.json'
$InnerScript = Join-Path $ToolRoot 'Invoke-GPIHub-V100-REV2.ps1'
$RunLog = Join-Path $ToolRoot 'last-v100-run.log'
$ErrorLog = Join-Path $ToolRoot 'last-v100-error.txt'

function Require([bool]$Condition,[string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Show-LatestV100DiagnosticTail {
    param([string]$OperationalRoot)

    if ([string]::IsNullOrWhiteSpace($OperationalRoot)) { return }
    $diagRoot = Join-Path $OperationalRoot '.gpi-diagnostics\migration-v100-target-runtime'
    if (-not (Test-Path -LiteralPath $diagRoot -PathType Container)) { return }

    $candidate = Get-ChildItem -LiteralPath $diagRoot -Filter 'Invoke-GPIHub-V100.txt' -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if ($null -eq $candidate) { return }

    Write-Host ''
    Write-Host 'Latest V100 diagnostic transcript tail:' -ForegroundColor Yellow
    Write-Host "  $($candidate.FullName)" -ForegroundColor DarkYellow
    Write-Host ('-' * 96) -ForegroundColor DarkGray
    Get-Content -LiteralPath $candidate.FullName -Tail 80 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
    Write-Host ('-' * 96) -ForegroundColor DarkGray
}

$State = $null
try {
    Require (Test-Path -LiteralPath $StatePath -PathType Leaf) "Migration state file missing: $StatePath"
    Require (Test-Path -LiteralPath $InnerScript -PathType Leaf) "V100 REV2 script missing: $InnerScript"

    $State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 50
    $OperationalRoot = [string]$State.local.operational_root

    Remove-Item -LiteralPath $RunLog,$ErrorLog -Force -ErrorAction SilentlyContinue

    Write-Host ''
    Write-Host ('=' * 104) -ForegroundColor Cyan
    Write-Host 'V100 REV3 — CAPTURED EXECUTION' -ForegroundColor Cyan
    Write-Host ('=' * 104) -ForegroundColor Cyan
    Write-Host "Inner phase : $InnerScript"
    Write-Host "Run log     : $RunLog"
    Write-Host 'V100_REV3_CAPTURE_WRAPPER=PASS' -ForegroundColor Green
    Write-Host ''

    $allOutput = & pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $InnerScript 2>&1
    $exitCode = $LASTEXITCODE

    $text = (@($allOutput) | ForEach-Object { [string]$_ }) -join "`r`n"
    Set-Content -LiteralPath $RunLog -Value $text -Encoding utf8
    if (-not [string]::IsNullOrWhiteSpace($text)) {
        Write-Host $text
    }

    if ($exitCode -ne 0) {
        throw "V100 REV2 exited with code $exitCode."
    }

    Write-Host ''
    Write-Host 'V100_REV3_INNER_PHASE=PASS' -ForegroundColor Green
    exit 0
}
catch {
    $message = $_ | Out-String
    Set-Content -LiteralPath $ErrorLog -Value $message -Encoding utf8

    Write-Host ''
    Write-Host ('=' * 104) -ForegroundColor Red
    Write-Host 'V100 REV3 FAILED — WINDOW WILL REMAIN OPEN' -ForegroundColor Red
    Write-Host ('=' * 104) -ForegroundColor Red
    Write-Host $message -ForegroundColor Red
    Write-Host ''
    Write-Host "Full captured run log : $RunLog" -ForegroundColor Yellow
    Write-Host "Error file            : $ErrorLog" -ForegroundColor Yellow

    if ($null -ne $State) {
        Show-LatestV100DiagnosticTail -OperationalRoot ([string]$State.local.operational_root)
    }

    Write-Host ''
    Write-Host 'Nothing in this error handler stops the source VM, changes traffic, or enables Production writes.' -ForegroundColor Yellow
    Write-Host 'Copy the visible error back to ChatGPT, or just tell me the window is still open.' -ForegroundColor Cyan
    [void](Read-Host 'Press Enter when you are ready to close this window')
    exit 1
}
