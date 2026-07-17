[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedProductionVersion = "0.27.0.7"
$ExpectedTestVersion = "0.8.0.7"
$NewProductionVersion = "0.27.0.8"
$NewTestVersion = "0.8.0.8"
$FooterAddressLine = "Gamer Packaging, Inc. | 100 S 5th Street, Suite 1900, Minneapolis, MN 55402"

$ProductionRoot = Join-Path -Path $RepoRoot -ChildPath "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path -Path $RepoRoot -ChildPath "bc-extension\zetadocs-replacement-tests"
$ProductionAppJson = Join-Path -Path $ProductionRoot -ChildPath "app.json"
$TestAppJson = Join-Path -Path $TestRoot -ChildPath "app.json"
$ChangeLog = Join-Path -Path $ProductionRoot -ChildPath "CHANGELOG.md"
$BuildScript = Join-Path -Path $RepoRoot -ChildPath "scripts\Prepare-GPIALTests.ps1"
$ReportLayoutFolder = Join-Path -Path $ProductionRoot -ChildPath "src\reportlayout"

foreach ($RequiredPath in @($ProductionAppJson, $TestAppJson, $ChangeLog, $BuildScript, $ReportLayoutFolder)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required path was not found: $RequiredPath"
    }
}

function Write-Utf8NoBom {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Content)
    $Encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $Encoding)
}

function Write-JsonNoBom {
    param([Parameter(Mandatory)][object]$Value, [Parameter(Mandatory)][string]$Path)
    $Json = $Value | ConvertTo-Json -Depth 100
    Write-Utf8NoBom -Path $Path -Content ($Json + [Environment]::NewLine)
}

function Get-LineEnding {
    param([Parameter(Mandatory)][string]$Content)
    if ($Content.Contains("`r`n")) { return "`r`n" }
    return "`n"
}

function Get-ReportSectionWidth {
    param([Parameter(Mandatory)][string]$Content)
    $Match = [regex]::Match($Content, '(?s)</Body>\s*<Width>([^<]+)</Width>')
    if ($Match.Success) { return $Match.Groups[1].Value }
    return "7.8in"
}

function Set-ReportPageFooter {
    param([Parameter(Mandatory)][string]$Content, [Parameter(Mandatory)][string]$FooterAddressLine, [Parameter(Mandatory)][string]$LayoutName)
    $LineEnding = Get-LineEnding -Content $Content
    $FooterWidth = Get-ReportSectionWidth -Content $Content
    $FooterXml = @"
      <PageFooter>
        <Height>0.24in</Height>
        <PrintOnFirstPage>true</PrintOnFirstPage>
        <PrintOnLastPage>true</PrintOnLastPage>
        <ReportItems>
          <Textbox Name="GPIStandardAddressFooter">
            <CanGrow>false</CanGrow>
            <KeepTogether>true</KeepTogether>
            <Paragraphs><Paragraph><TextRuns><TextRun><Value>$FooterAddressLine</Value><Style><FontFamily>Arial</FontFamily><FontSize>7pt</FontSize><Color>#666666</Color></Style></TextRun></TextRuns><Style><TextAlign>Center</TextAlign></Style></Paragraph></Paragraphs>
            <Top>0.02in</Top><Left>0in</Left><Height>0.18in</Height><Width>$FooterWidth</Width>
            <Style><Border><Style>None</Style></Border><PaddingTop>1pt</PaddingTop></Style>
          </Textbox>
        </ReportItems>
        <Style><Border><Style>None</Style></Border></Style>
      </PageFooter>
"@
    $FooterXml = ($FooterXml -replace "`r?`n", $LineEnding)
    if ($Content -match '(?s)<PageFooter>.*?</PageFooter>') {
        $Updated = [regex]::Replace($Content, '(?s)\s*<PageFooter>.*?</PageFooter>', $LineEnding + $FooterXml, 1)
    } elseif ($Content -match '<Page>\s*') {
        $Updated = [regex]::Replace($Content, '<Page>\s*', '<Page>' + $LineEnding + $FooterXml + $LineEnding, 1)
    } else {
        throw "Could not find a Page element or existing PageFooter in $LayoutName."
    }
    if (([regex]::Matches($Updated, '<PageFooter>')).Count -ne 1) { throw "Expected exactly one PageFooter in $LayoutName after update." }
    return $Updated
}

function Get-TopInches {
    param([Parameter(Mandatory)][string]$TextboxXml)
    $TopMatch = [regex]::Match($TextboxXml, '<Top>([0-9.]+)in</Top>')
    if (-not $TopMatch.Success) { return -1 }
    $Value = 0.0
    if ([double]::TryParse($TopMatch.Groups[1].Value, [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$Value)) { return $Value }
    return -1
}

function Test-LegacyBodyFooterTextbox {
    param([Parameter(Mandatory)][string]$TextboxXml)
    $Lower = $TextboxXml.ToLowerInvariant()
    $Top = Get-TopInches -TextboxXml $TextboxXml
    $DirectFooterMarkers = @(
        'fields!contactline.value', 'please contact', 'questions? contact',
        'standard terms and conditions', 'terms-conditions-customer-sales',
        'please reference', 'upon receipt and inspection', 'damage or discrepancy',
        'bill of lading', 'available at www.gamerpackaging.com',
        'www.gamerpackaging.com/terms', 'https://www.gamerpackaging.com/terms',
        'payment with any questions', 'regarding this invoice', 'regarding this credit memo',
        'regarding this purchase order', 'regarding this blanket sales order',
        'regarding this statement', 'with any questions'
    )
    foreach ($Marker in $DirectFooterMarkers) { if ($Lower.Contains($Marker)) { return $true } }
    if ($Top -ge 5.5) {
        $BottomCompanyMarkers = @(
            'fields!companyname.value', 'fields!companyaddress.value', 'fields!companycity.value',
            'fields!companystate.value', 'fields!companypostcode.value', 'fields!companyphone.value',
            'fields!companyhomepage.value', 'gamer packaging', 'gamerpackaging.com', '100 s 5th', 'minneapolis'
        )
        foreach ($Marker in $BottomCompanyMarkers) { if ($Lower.Contains($Marker)) { return $true } }
    }
    return $false
}

function Remove-LegacyBodyFooterTextboxes {
    param([Parameter(Mandatory)][string]$Content, [Parameter(Mandatory)][string]$LayoutName, [ref]$RemovedCount)
    $BodyMatch = [regex]::Match($Content, '(?s)(<Body\b[^>]*>)(.*?)(</Body>)')
    if (-not $BodyMatch.Success) { throw "Could not find Body element in $LayoutName." }
    $BodyOpen = $BodyMatch.Groups[1].Value
    $BodyContent = $BodyMatch.Groups[2].Value
    $BodyClose = $BodyMatch.Groups[3].Value
    $LocalRemoved = 0
    $NewBodyContent = [regex]::Replace($BodyContent, '(?s)\s*<Textbox\b[^>]*>.*?</Textbox>', {
        param($Match)
        $TextboxXml = $Match.Value
        if (Test-LegacyBodyFooterTextbox -TextboxXml $TextboxXml) {
            $script:__GpiLegacyFooterRemoved += 1
            return ''
        }
        return $TextboxXml
    })
    $LocalRemoved = $script:__GpiLegacyFooterRemoved
    $script:__GpiLegacyFooterRemoved = 0
    $RemovedCount.Value += $LocalRemoved
    $Updated = $Content.Substring(0, $BodyMatch.Index) + $BodyOpen + $NewBodyContent + $BodyClose + $Content.Substring($BodyMatch.Index + $BodyMatch.Length)
    $UpdatedBodyMatch = [regex]::Match($Updated, '(?s)(<Body\b[^>]*>)(.*?)(</Body>)')
    $UpdatedBody = $UpdatedBodyMatch.Groups[2].Value
    foreach ($Marker in @('Fields!ContactLine.Value','Please contact','Questions? Contact','Standard Terms and Conditions','terms-conditions-customer-sales','Please reference','upon receipt and inspection','damage or discrepancy','bill of lading')) {
        if ($UpdatedBody.Contains($Marker)) { throw "Legacy footer marker '$Marker' still exists inside the Body of $LayoutName after cleanup." }
    }
    return $Updated
}

$ProductionApp = Get-Content -LiteralPath $ProductionAppJson -Raw | ConvertFrom-Json
$TestApp = Get-Content -LiteralPath $TestAppJson -Raw | ConvertFrom-Json
if ([string]$ProductionApp.version -ne $ExpectedProductionVersion) { throw "Expected production version $ExpectedProductionVersion, but found $($ProductionApp.version). No files were changed." }
if ([string]$TestApp.version -ne $ExpectedTestVersion) { throw "Expected test version $ExpectedTestVersion, but found $($TestApp.version). No files were changed." }
$MainDependency = @($TestApp.dependencies | Where-Object { [string]$_.id -eq [string]$ProductionApp.id })
if ($MainDependency.Count -ne 1) { throw "Expected exactly one test dependency on production app $($ProductionApp.id), but found $($MainDependency.Count). No files were changed." }

$LayoutFiles = @(
    "GPIBlanketSalesOrderBranded.rdl", "GPICustomerOpenOrderStatusBranded.rdl", "GPICustomerStatementBranded.rdl",
    "GPIDropShipPurchaseOrderBranded.rdl", "GPIPickTicket.rdl", "GPIPrepaymentNotice.rdl",
    "GPIPurchaseCreditMemoBranded.rdl", "GPIPurchaseReturnOrderBranded.rdl", "GPIPurchaseReturnPickTicketBranded.rdl",
    "GPISalesCreditMemoBranded.rdl", "GPISalesInvoiceBranded.rdl", "GPISalesOrderConfirmationBranded.rdl",
    "GPISalesReturnAuthorizationBranded.rdl", "GPISalesReturnWarehouseNotificationBranded.rdl", "GPITransferPickListBranded.rdl",
    "GPITransferReceiptNotificationBranded.rdl", "GPIWarehousePurchaseOrderBranded.rdl", "GPIWarehouseReceivingNoticeBranded.rdl"
) | ForEach-Object { Join-Path -Path $ReportLayoutFolder -ChildPath $_ }
foreach ($LayoutFile in $LayoutFiles) { if (-not (Test-Path -LiteralPath $LayoutFile)) { throw "Layout file was not found: $LayoutFile" } }

$FilesToBackup = @($ProductionAppJson, $TestAppJson, $ChangeLog) + $LayoutFiles
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path -Path $RepoRoot -ChildPath ".gpi-backups\footer-body-cleanup-027008-$Timestamp"
New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null
foreach ($Path in $FilesToBackup) {
    $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
    $BackupPath = Join-Path -Path $BackupRoot -ChildPath $RelativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $BackupPath) -Force | Out-Null
    Copy-Item -LiteralPath $Path -Destination $BackupPath -Force
}

$UpdatedLayouts = @{}
$TotalRemovedCount = 0
$script:__GpiLegacyFooterRemoved = 0
foreach ($LayoutFile in $LayoutFiles) {
    $LayoutName = [System.IO.Path]::GetFileName($LayoutFile)
    $LayoutContent = Get-Content -LiteralPath $LayoutFile -Raw
    $LayoutContent = Set-ReportPageFooter -Content $LayoutContent -FooterAddressLine $FooterAddressLine -LayoutName $LayoutName
    $RemovedForThisLayout = 0
    $LayoutContent = Remove-LegacyBodyFooterTextboxes -Content $LayoutContent -LayoutName $LayoutName -RemovedCount ([ref]$RemovedForThisLayout)
    $TotalRemovedCount += $RemovedForThisLayout
    try { [xml]$XmlCheck = $LayoutContent } catch { throw "The updated RDL XML for $LayoutName is not valid XML: $($_.Exception.Message)" }
    if ($LayoutContent -notmatch '<PageFooter>' -or $LayoutContent -notmatch [regex]::Escape($FooterAddressLine)) { throw "PageFooter address line missing from $LayoutName." }
    $UpdatedLayouts[$LayoutFile] = $LayoutContent
}
if ($TotalRemovedCount -eq 0) { throw "No legacy body-footer textboxes were removed. No files were changed." }

$ProductionApp.version = $NewProductionVersion
$TestApp.version = $NewTestVersion
$MainDependency[0].version = $NewProductionVersion
$ChangeLogOriginal = Get-Content -LiteralPath $ChangeLog -Raw
$ChangeLogEntry = @"
## $NewProductionVersion

### Fixed
- Removed legacy body-level footer text blocks from Gamer report layouts.
- The only footer remaining is the RDLC PageFooter address line at the bottom of the page:
  $FooterAddressLine

### Safety
- No line, extended-text, recipient, sender, routing-rule, Delivery Log, SharePoint archive, or email behavior was changed.
- No package is published automatically.
- Publish only to Sandbox_NoZetadocs_UAT or Sandbox_5_5_2026 unless Chad explicitly approves another environment.

"@
if ($ChangeLogOriginal -match '(?m)^# Changelog\s*$') {
    $UpdatedChangeLog = [regex]::Replace($ChangeLogOriginal, '(?m)^# Changelog\s*$', "# Changelog`r`n`r`n$ChangeLogEntry", 1)
} else { throw "The changelog header was not found. No files were changed." }

$ProductionPackage = Join-Path -Path $ProductionRoot -ChildPath "Gamer Packaging_GPI Sales Document Email_$NewProductionVersion.app"
$TestPackage = Join-Path -Path $TestRoot -ChildPath "Gamer Packaging_GPI Sales Document Email Tests_$NewTestVersion.app"
try {
    foreach ($LayoutFile in $LayoutFiles) { Write-Utf8NoBom -Path $LayoutFile -Content $UpdatedLayouts[$LayoutFile] }
    Write-JsonNoBom -Value $ProductionApp -Path $ProductionAppJson
    Write-JsonNoBom -Value $TestApp -Path $TestAppJson
    Write-Utf8NoBom -Path $ChangeLog -Content $UpdatedChangeLog
    if (Test-Path -LiteralPath $ProductionPackage) { Remove-Item -LiteralPath $ProductionPackage -Force }
    if (Test-Path -LiteralPath $TestPackage) { Remove-Item -LiteralPath $TestPackage -Force }
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host " GPI footer body cleanup 0.27.0.8" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Production version:       $NewProductionVersion"
    Write-Host "Test version:             $NewTestVersion"
    Write-Host "Footer line:              $FooterAddressLine"
    Write-Host "Layouts updated:          $($LayoutFiles.Count)"
    Write-Host "Legacy footer boxes cut:  $TotalRemovedCount"
    Write-Host "Backup:                   $BackupRoot"
    Write-Host ""
    Write-Host "Running production and test builds..." -ForegroundColor Cyan
    & $BuildScript
    if (-not (Test-Path -LiteralPath $ProductionPackage)) { throw "The expected production package was not created: $ProductionPackage" }
    if (-not (Test-Path -LiteralPath $TestPackage)) { throw "The expected test package was not created: $TestPackage" }
} catch {
    Write-Host ""
    Write-Host "The footer body cleanup build failed. Restoring modified files." -ForegroundColor Red
    foreach ($Path in $FilesToBackup) {
        $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
        $BackupPath = Join-Path -Path $BackupRoot -ChildPath $RelativePath
        Copy-Item -LiteralPath $BackupPath -Destination $Path -Force
    }
    if (Test-Path -LiteralPath $ProductionPackage) { Remove-Item -LiteralPath $ProductionPackage -Force }
    if (Test-Path -LiteralPath $TestPackage) { Remove-Item -LiteralPath $TestPackage -Force }
    throw
}
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " GPI 0.27.0.8 build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Backup:             $BackupRoot"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish production first, then tests only after production 0.27.0.8 is installed in the sandbox." -ForegroundColor Yellow
