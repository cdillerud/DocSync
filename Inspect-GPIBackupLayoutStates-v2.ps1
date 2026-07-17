[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$BackupBase = Join-Path -Path $RepoRoot -ChildPath ".gpi-backups"
$CurrentSalesOrderLayout = Join-Path -Path $RepoRoot -ChildPath "bc-extension\zetadocs-replacement\src\reportlayout\GPISalesOrderConfirmationBranded.rdl"
$CurrentProductionAppJson = Join-Path -Path $RepoRoot -ChildPath "bc-extension\zetadocs-replacement\app.json"
$CurrentTestAppJson = Join-Path -Path $RepoRoot -ChildPath "bc-extension\zetadocs-replacement-tests\app.json"

function Get-AppVersionSafe {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return ""
    }

    try {
        $App = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
        return [string]$App.version
    }
    catch {
        return "Unreadable"
    }
}

function Get-LayoutFacts {
    param(
        [string]$LayoutPath,
        [string]$Label,
        [datetime]$LastWriteTime,
        [string]$ProductionVersion,
        [string]$TestVersion,
        [string]$BackupPath
    )

    if (-not (Test-Path -LiteralPath $LayoutPath)) {
        return [pscustomobject]@{
            Score = -999
            LastWriteTime = $LastWriteTime
            Label = $Label
            ProductionVersion = $ProductionVersion
            TestVersion = $TestVersion
            HasOrderDate = $false
            HasRequestedReceiveBy = $false
            HasGamerContacts = $false
            HasVbCrLfNearContacts = $false
            HasBadNoSeparatorPattern = $false
            HasCustomerNo = $false
            HasTerms = $false
            HasShippingMethod = $false
            HasFOB = $false
            BackupPath = $BackupPath
        }
    }

    $Content = Get-Content -LiteralPath $LayoutPath -Raw
    $Lower = $Content.ToLowerInvariant()

    $ContactsIndex = $Lower.IndexOf("gamer contacts")
    $ContactWindow = ""
    if ($ContactsIndex -ge 0) {
        $Start = [Math]::Max(0, $ContactsIndex - 700)
        $Length = [Math]::Min(3500, $Content.Length - $Start)
        $ContactWindow = $Content.Substring($Start, $Length)
    }

    $HasOrderDate = $Lower.Contains("order date")
    $HasRequestedReceiveBy = $Lower.Contains("requested receive by")
    $HasGamerContacts = $Lower.Contains("gamer contacts")
    $HasCustomerNo = $Lower.Contains("customer no")
    $HasTerms = $Lower.Contains("terms")
    $HasShippingMethod = $Lower.Contains("shipping method")
    $HasFOB = $Lower.Contains("fob")
    $HasVbCrLfNearContacts = $ContactWindow.ToLowerInvariant().Contains("vbcrlf")

    $HasBadNoSeparatorPattern = $false
    if ($ContactWindow -match 'Kissel LeeAngie|Maggie HallJenny|GamerContactName1.*GamerContactName2|SalespersonName.*InsideSalespersonName') {
        if ($ContactWindow -notmatch 'vbCrLf') {
            $HasBadNoSeparatorPattern = $true
        }
    }

    $Score = 0
    if ($HasCustomerNo) { $Score += 5 }
    if ($HasTerms) { $Score += 5 }
    if ($HasShippingMethod) { $Score += 5 }
    if ($HasFOB) { $Score += 5 }
    if ($HasOrderDate) { $Score += 20 }
    if ($HasRequestedReceiveBy) { $Score += 20 }
    if ($HasGamerContacts) { $Score += 20 }
    if ($HasVbCrLfNearContacts) { $Score += 20 }
    if ($HasBadNoSeparatorPattern) { $Score -= 50 }

    return [pscustomobject]@{
        Score = $Score
        LastWriteTime = $LastWriteTime
        Label = $Label
        ProductionVersion = $ProductionVersion
        TestVersion = $TestVersion
        HasOrderDate = $HasOrderDate
        HasRequestedReceiveBy = $HasRequestedReceiveBy
        HasGamerContacts = $HasGamerContacts
        HasVbCrLfNearContacts = $HasVbCrLfNearContacts
        HasBadNoSeparatorPattern = $HasBadNoSeparatorPattern
        HasCustomerNo = $HasCustomerNo
        HasTerms = $HasTerms
        HasShippingMethod = $HasShippingMethod
        HasFOB = $HasFOB
        BackupPath = $BackupPath
    }
}

$Rows = @()

$Rows += Get-LayoutFacts `
    -LayoutPath $CurrentSalesOrderLayout `
    -Label "CURRENT SOURCE" `
    -LastWriteTime (Get-Date) `
    -ProductionVersion (Get-AppVersionSafe -Path $CurrentProductionAppJson) `
    -TestVersion (Get-AppVersionSafe -Path $CurrentTestAppJson) `
    -BackupPath "(current repo)"

if (Test-Path -LiteralPath $BackupBase) {
    $BackupDirs = Get-ChildItem -LiteralPath $BackupBase -Directory

    foreach ($Dir in $BackupDirs) {
        $LayoutPath = Join-Path -Path $Dir.FullName -ChildPath "bc-extension\zetadocs-replacement\src\reportlayout\GPISalesOrderConfirmationBranded.rdl"
        $ProdAppJson = Join-Path -Path $Dir.FullName -ChildPath "bc-extension\zetadocs-replacement\app.json"
        $TestAppJson = Join-Path -Path $Dir.FullName -ChildPath "bc-extension\zetadocs-replacement-tests\app.json"

        $Rows += Get-LayoutFacts `
            -LayoutPath $LayoutPath `
            -Label $Dir.Name `
            -LastWriteTime $Dir.LastWriteTime `
            -ProductionVersion (Get-AppVersionSafe -Path $ProdAppJson) `
            -TestVersion (Get-AppVersionSafe -Path $TestAppJson) `
            -BackupPath $Dir.FullName
    }
}

$SortedRows = $Rows | Sort-Object `
    @{ Expression = { $_.Score }; Descending = $true }, `
    @{ Expression = { $_.LastWriteTime }; Descending = $true }

$SortedRows |
    Select-Object `
        Score,
        Label,
        ProductionVersion,
        TestVersion,
        HasOrderDate,
        HasRequestedReceiveBy,
        HasGamerContacts,
        HasVbCrLfNearContacts,
        HasBadNoSeparatorPattern,
        BackupPath |
    Format-Table -AutoSize

Write-Host ""
Write-Host "Copy/paste the top 10 result rows back to ChatGPT." -ForegroundColor Yellow
Write-Host "This script is read-only. It does not change source files, build packages, or publish anything." -ForegroundColor Yellow
