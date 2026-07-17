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
        [datetime]$LastWriteTime
    )

    if (-not (Test-Path -LiteralPath $LayoutPath)) {
        return [pscustomobject]@{
            Label = $Label
            LastWriteTime = $LastWriteTime
            LayoutExists = $false
            ProductionVersion = ""
            TestVersion = ""
            HasOrderDate = $false
            HasRequestedReceiveBy = $false
            HasGamerContacts = $false
            HasCustomerNo = $false
            HasTerms = $false
            HasShippingMethod = $false
            HasFOB = $false
            HasVbCrLfNearContacts = $false
            HasContactName1Name2Fields = $false
            HasBadNoSeparatorPattern = $false
            Score = -999
            BackupPath = ""
        }
    }

    $Content = Get-Content -LiteralPath $LayoutPath -Raw
    $Lower = $Content.ToLowerInvariant()

    $ContactsIndex = $Lower.IndexOf("gamer contacts")
    $ContactWindow = ""
    if ($ContactsIndex -ge 0) {
        $Start = [Math]::Max(0, $ContactsIndex - 500)
        $Length = [Math]::Min(2500, $Content.Length - $Start)
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
    $HasContactName1Name2Fields = ($Lower.Contains("gamercontactname1") -and $Lower.Contains("gamercontactname2"))
    $HasBadNoSeparatorPattern =
        ($ContactWindow -match 'GamerContactName1.*GamerContactName2' -and $ContactWindow -notmatch 'vbCrLf') -or
        ($ContactWindow -match 'SalespersonName.*InsideSalespersonName' -and $ContactWindow -notmatch 'vbCrLf')

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
        Label = $Label
        LastWriteTime = $LastWriteTime
        LayoutExists = $true
        ProductionVersion = ""
        TestVersion = ""
        HasOrderDate = $HasOrderDate
        HasRequestedReceiveBy = $HasRequestedReceiveBy
        HasGamerContacts = $HasGamerContacts
        HasCustomerNo = $HasCustomerNo
        HasTerms = $HasTerms
        HasShippingMethod = $HasShippingMethod
        HasFOB = $HasFOB
        HasVbCrLfNearContacts = $HasVbCrLfNearContacts
        HasContactName1Name2Fields = $HasContactName1Name2Fields
        HasBadNoSeparatorPattern = $HasBadNoSeparatorPattern
        Score = $Score
        BackupPath = ""
    }
}

$Rows = New-Object System.Collections.Generic.List[object]

$CurrentFacts = Get-LayoutFacts -LayoutPath $CurrentSalesOrderLayout -Label "CURRENT SOURCE" -LastWriteTime (Get-Date)
$CurrentFacts.ProductionVersion = Get-AppVersionSafe -Path $CurrentProductionAppJson
$CurrentFacts.TestVersion = Get-AppVersionSafe -Path $CurrentTestAppJson
$CurrentFacts.BackupPath = "(current repo)"
[void]$Rows.Add($CurrentFacts)

if (Test-Path -LiteralPath $BackupBase) {
    $BackupDirs = Get-ChildItem -LiteralPath $BackupBase -Directory | Sort-Object LastWriteTime -Descending

    foreach ($Dir in $BackupDirs) {
        $LayoutPath = Join-Path -Path $Dir.FullName -ChildPath "bc-extension\zetadocs-replacement\src\reportlayout\GPISalesOrderConfirmationBranded.rdl"
        $ProdAppJson = Join-Path -Path $Dir.FullName -ChildPath "bc-extension\zetadocs-replacement\app.json"
        $TestAppJson = Join-Path -Path $Dir.FullName -ChildPath "bc-extension\zetadocs-replacement-tests\app.json"

        $Facts = Get-LayoutFacts -LayoutPath $LayoutPath -Label $Dir.Name -LastWriteTime $Dir.LastWriteTime
        $Facts.ProductionVersion = Get-AppVersionSafe -Path $ProdAppJson
        $Facts.TestVersion = Get-AppVersionSafe -Path $TestAppJson
        $Facts.BackupPath = $Dir.FullName
        [void]$Rows.Add($Facts)
    }
}

$Rows |
    Sort-Object Score -Descending, LastWriteTime -Descending |
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
Write-Host "Copy/paste the top 10 lines of this output back to ChatGPT." -ForegroundColor Yellow
Write-Host "Do not run another restore or layout patch until we identify the actual good backup." -ForegroundColor Yellow
