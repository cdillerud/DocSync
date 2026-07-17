[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedProductionVersion = "0.27.0.6"
$ExpectedTestVersion = "0.8.0.6"
$NewProductionVersion = "0.27.0.7"
$NewTestVersion = "0.8.0.7"

$FooterAddressLine = "Gamer Packaging, Inc. | 100 S 5th Street, Suite 1900, Minneapolis, MN 55402"

$ProductionRoot = Join-Path -Path $RepoRoot -ChildPath "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path -Path $RepoRoot -ChildPath "bc-extension\zetadocs-replacement-tests"

$ProductionAppJson = Join-Path -Path $ProductionRoot -ChildPath "app.json"
$TestAppJson = Join-Path -Path $TestRoot -ChildPath "app.json"
$ChangeLog = Join-Path -Path $ProductionRoot -ChildPath "CHANGELOG.md"
$BuildScript = Join-Path -Path $RepoRoot -ChildPath "scripts\Prepare-GPIALTests.ps1"
$ReportLayoutFolder = Join-Path -Path $ProductionRoot -ChildPath "src\reportlayout"

$RequiredPaths = @(
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLog,
    $BuildScript,
    $ReportLayoutFolder
)

foreach ($RequiredPath in $RequiredPaths) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required path was not found: $RequiredPath"
    }
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )

    $Encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $Encoding)
}

function Write-JsonNoBom {
    param(
        [Parameter(Mandatory)][object]$Value,
        [Parameter(Mandatory)][string]$Path
    )

    $Json = $Value | ConvertTo-Json -Depth 100
    Write-Utf8NoBom -Path $Path -Content ($Json + [Environment]::NewLine)
}

function Get-LineEnding {
    param([Parameter(Mandatory)][string]$Content)

    if ($Content.Contains("`r`n")) {
        return "`r`n"
    }

    return "`n"
}

function Replace-ReportPageFooter {
    param(
        [Parameter(Mandatory)][string]$Content,
        [Parameter(Mandatory)][string]$FooterAddressLine,
        [Parameter(Mandatory)][string]$LayoutName
    )

    $LineEnding = Get-LineEnding -Content $Content
    $FooterXml = @"
      <PageFooter>
        <Height>0.24in</Height>
        <PrintOnFirstPage>true</PrintOnFirstPage>
        <PrintOnLastPage>true</PrintOnLastPage>
        <ReportItems>
          <Textbox Name="GPIStandardAddressFooter">
            <CanGrow>false</CanGrow>
            <KeepTogether>true</KeepTogether>
            <Paragraphs>
              <Paragraph>
                <TextRuns>
                  <TextRun>
                    <Value>$FooterAddressLine</Value>
                    <Style>
                      <FontFamily>Arial</FontFamily>
                      <FontSize>7pt</FontSize>
                      <Color>#666666</Color>
                    </Style>
                  </TextRun>
                </TextRuns>
                <Style>
                  <TextAlign>Center</TextAlign>
                </Style>
              </Paragraph>
            </Paragraphs>
            <Top>0.02in</Top>
            <Left>0in</Left>
            <Height>0.18in</Height>
            <Width>7.8in</Width>
            <Style>
              <Border>
                <Style>None</Style>
              </Border>
              <PaddingTop>1pt</PaddingTop>
            </Style>
          </Textbox>
        </ReportItems>
        <Style>
          <Border>
            <Style>None</Style>
          </Border>
        </Style>
      </PageFooter>
"@

    $FooterXml = ($FooterXml -replace "`r?`n", $LineEnding)

    if ($Content -match '(?s)<PageFooter>.*?</PageFooter>') {
        $Updated = [regex]::Replace($Content, '(?s)\s*<PageFooter>.*?</PageFooter>', $LineEnding + $FooterXml, 1)
    }
    elseif ($Content -match '</Body>\s*</ReportSection>') {
        $Updated = [regex]::Replace($Content, '</Body>\s*</ReportSection>', "</Body>$LineEnding$FooterXml$LineEnding    </ReportSection>", 1)
    }
    else {
        throw "Could not find a safe place to insert PageFooter in $LayoutName."
    }

    try {
        [xml]$XmlCheck = $Updated
    }
    catch {
        throw "The updated RDL XML for $LayoutName is not valid XML: $($_.Exception.Message)"
    }

    if ($Updated -notmatch '<PageFooter>' -or $Updated -notmatch [regex]::Escape($FooterAddressLine)) {
        throw "Footer standardization did not apply correctly to $LayoutName."
    }

    return $Updated
}

$ProductionApp = Get-Content -LiteralPath $ProductionAppJson -Raw | ConvertFrom-Json
$TestApp = Get-Content -LiteralPath $TestAppJson -Raw | ConvertFrom-Json

if ([string]$ProductionApp.version -ne $ExpectedProductionVersion) {
    throw "Expected production version $ExpectedProductionVersion, but found $($ProductionApp.version). No files were changed."
}

if ([string]$TestApp.version -ne $ExpectedTestVersion) {
    throw "Expected test version $ExpectedTestVersion, but found $($TestApp.version). No files were changed."
}

$MainDependency = @(
    $TestApp.dependencies |
        Where-Object { [string]$_.id -eq [string]$ProductionApp.id }
)

if ($MainDependency.Count -ne 1) {
    throw "Expected exactly one test dependency on production app $($ProductionApp.id), but found $($MainDependency.Count). No files were changed."
}

$LayoutFiles = @(
    "GPIBlanketSalesOrderBranded.rdl",
    "GPICustomerOpenOrderStatusBranded.rdl",
    "GPICustomerStatementBranded.rdl",
    "GPIDropShipPurchaseOrderBranded.rdl",
    "GPIPickTicket.rdl",
    "GPIPrepaymentNotice.rdl",
    "GPIPurchaseCreditMemoBranded.rdl",
    "GPIPurchaseReturnOrderBranded.rdl",
    "GPIPurchaseReturnPickTicketBranded.rdl",
    "GPISalesCreditMemoBranded.rdl",
    "GPISalesInvoiceBranded.rdl",
    "GPISalesOrderConfirmationBranded.rdl",
    "GPISalesReturnAuthorizationBranded.rdl",
    "GPISalesReturnWarehouseNotificationBranded.rdl",
    "GPITransferPickListBranded.rdl",
    "GPITransferReceiptNotificationBranded.rdl",
    "GPIWarehousePurchaseOrderBranded.rdl",
    "GPIWarehouseReceivingNoticeBranded.rdl"
) | ForEach-Object { Join-Path -Path $ReportLayoutFolder -ChildPath $_ }

foreach ($LayoutFile in $LayoutFiles) {
    if (-not (Test-Path -LiteralPath $LayoutFile)) {
        throw "Layout file was not found: $LayoutFile"
    }
}

$FilesToBackup = @(
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLog
) + $LayoutFiles

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path -Path $RepoRoot -ChildPath ".gpi-backups\footer-address-only-027007-$Timestamp"
New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

foreach ($Path in $FilesToBackup) {
    $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
    $BackupPath = Join-Path -Path $BackupRoot -ChildPath $RelativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $BackupPath) -Force | Out-Null
    Copy-Item -LiteralPath $Path -Destination $BackupPath -Force
}

$UpdatedLayouts = @{}
foreach ($LayoutFile in $LayoutFiles) {
    $LayoutContent = Get-Content -LiteralPath $LayoutFile -Raw
    $UpdatedLayouts[$LayoutFile] = Replace-ReportPageFooter `
        -Content $LayoutContent `
        -FooterAddressLine $FooterAddressLine `
        -LayoutName ([System.IO.Path]::GetFileName($LayoutFile))
}

$ProductionApp.version = $NewProductionVersion
$TestApp.version = $NewTestVersion
$MainDependency[0].version = $NewProductionVersion

$ChangeLogOriginal = Get-Content -LiteralPath $ChangeLog -Raw
$ChangeLogEntry = @"
## $NewProductionVersion

### Changed
- Standardized Gamer document footers across report layouts.
- Footers now render as a true page footer at the bottom of each page.
- Footer text is limited to the Gamer address line:
  `$FooterAddressLine

### Safety
- No line, extended-text, recipient, sender, routing-rule, Delivery Log, SharePoint archive, or email behavior was changed.
- No package is published automatically.
- Publish only to Sandbox_NoZetadocs_UAT or Sandbox_5_5_2026 unless Chad explicitly approves another environment.

"@

if ($ChangeLogOriginal -match '(?m)^# Changelog\s*$') {
    $UpdatedChangeLog = [regex]::Replace(
        $ChangeLogOriginal,
        '(?m)^# Changelog\s*$',
        "# Changelog`r`n`r`n$ChangeLogEntry",
        1
    )
}
else {
    throw "The changelog header was not found. No files were changed."
}

$ProductionPackage = Join-Path -Path $ProductionRoot -ChildPath "Gamer Packaging_GPI Sales Document Email_$NewProductionVersion.app"
$TestPackage = Join-Path -Path $TestRoot -ChildPath "Gamer Packaging_GPI Sales Document Email Tests_$NewTestVersion.app"

try {
    foreach ($LayoutFile in $LayoutFiles) {
        Write-Utf8NoBom -Path $LayoutFile -Content $UpdatedLayouts[$LayoutFile]
    }

    Write-JsonNoBom -Value $ProductionApp -Path $ProductionAppJson
    Write-JsonNoBom -Value $TestApp -Path $TestAppJson
    Write-Utf8NoBom -Path $ChangeLog -Content $UpdatedChangeLog

    if (Test-Path -LiteralPath $ProductionPackage) {
        Remove-Item -LiteralPath $ProductionPackage -Force
    }

    if (Test-Path -LiteralPath $TestPackage) {
        Remove-Item -LiteralPath $TestPackage -Force
    }

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host " GPI footer address-only layout pass 0.27.0.7" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Production version: $NewProductionVersion"
    Write-Host "Test version:       $NewTestVersion"
    Write-Host "Footer line:        $FooterAddressLine"
    Write-Host "Layouts updated:    $($LayoutFiles.Count)"
    Write-Host "Backup:             $BackupRoot"
    Write-Host ""
    Write-Host "Running production and test builds..." -ForegroundColor Cyan

    & $BuildScript

    if (-not (Test-Path -LiteralPath $ProductionPackage)) {
        throw "The expected production package was not created: $ProductionPackage"
    }

    if (-not (Test-Path -LiteralPath $TestPackage)) {
        throw "The expected test package was not created: $TestPackage"
    }
}
catch {
    Write-Host ""
    Write-Host "The footer address-only build failed. Restoring modified files." -ForegroundColor Red

    foreach ($Path in $FilesToBackup) {
        $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
        $BackupPath = Join-Path -Path $BackupRoot -ChildPath $RelativePath
        Copy-Item -LiteralPath $BackupPath -Destination $Path -Force
    }

    if (Test-Path -LiteralPath $ProductionPackage) {
        Remove-Item -LiteralPath $ProductionPackage -Force
    }

    if (Test-Path -LiteralPath $TestPackage) {
        Remove-Item -LiteralPath $TestPackage -Force
    }

    throw
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " GPI 0.27.0.7 build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Backup:             $BackupRoot"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish both packages only to the active UAT sandbox and run the complete test suite." -ForegroundColor Yellow
