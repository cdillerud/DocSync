[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedProductionVersion = "0.27.0.9"
$ExpectedTestVersion = "0.8.0.9"
$NewProductionVersion = "0.27.0.10"
$NewTestVersion = "0.8.0.10"

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

function Convert-InchTextToDecimal {
    param([string]$ValueText)

    if ([string]::IsNullOrWhiteSpace($ValueText)) {
        return 0.0
    }

    $Clean = $ValueText.Trim().Replace("in", "")
    $Value = 0.0
    [void][double]::TryParse(
        $Clean,
        [System.Globalization.NumberStyles]::Float,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [ref]$Value)

    return $Value
}

function Format-Inches {
    param([double]$Value)

    return ($Value.ToString("0.###", [System.Globalization.CultureInfo]::InvariantCulture) + "in")
}

function Get-TagInches {
    param(
        [Parameter(Mandatory)][string]$Xml,
        [Parameter(Mandatory)][string]$TagName
    )

    $Match = [regex]::Match($Xml, "(?s)<$TagName>([0-9.]+)in</$TagName>")
    if (-not $Match.Success) {
        return 0.0
    }

    return Convert-InchTextToDecimal $Match.Groups[1].Value
}

function Set-SimpleTagValue {
    param(
        [Parameter(Mandatory)][string]$Xml,
        [Parameter(Mandatory)][string]$TagName,
        [Parameter(Mandatory)][string]$Value
    )

    if ($Xml -match "(?s)<$TagName>.*?</$TagName>") {
        return [regex]::Replace($Xml, "(?s)<$TagName>.*?</$TagName>", "<$TagName>$Value</$TagName>", 1)
    }

    if ($Xml -match "(?s)</Paragraphs>") {
        return [regex]::Replace($Xml, "(?s)</Paragraphs>", "</Paragraphs>`r`n            <$TagName>$Value</$TagName>", 1)
    }

    return [regex]::Replace($Xml, "(?s)</Textbox>", "            <$TagName>$Value</$TagName>`r`n          </Textbox>", 1)
}

function Set-TextboxBold {
    param([Parameter(Mandatory)][string]$Xml)

    if ($Xml -match "(?s)<FontWeight>.*?</FontWeight>") {
        $Xml = [regex]::Replace($Xml, "(?s)<FontWeight>.*?</FontWeight>", "<FontWeight>Bold</FontWeight>")
    }
    else {
        $TextRunStyleMatch = [regex]::Match($Xml, "(?s)(<TextRun>.*?<Style>)(.*?)(</Style>)")
        if ($TextRunStyleMatch.Success) {
            $Xml = $Xml.Substring(0, $TextRunStyleMatch.Groups[3].Index) +
                "                      <FontWeight>Bold</FontWeight>`r`n" +
                $Xml.Substring($TextRunStyleMatch.Groups[3].Index)
        }
        else {
            $Xml = [regex]::Replace(
                $Xml,
                "(?s)(</TextRun>)",
                "                    <Style><FontWeight>Bold</FontWeight></Style>`r`n                  `$1",
                1)
        }
    }

    return $Xml
}

function Set-TextboxRightAligned {
    param([Parameter(Mandatory)][string]$Xml)

    if ($Xml -match "(?s)<TextAlign>.*?</TextAlign>") {
        return [regex]::Replace($Xml, "(?s)<TextAlign>.*?</TextAlign>", "<TextAlign>Right</TextAlign>", 1)
    }

    $ParagraphStyleMatch = [regex]::Match($Xml, "(?s)(<Paragraph>.*?<Style>)(.*?)(</Style>)")
    if ($ParagraphStyleMatch.Success) {
        return $Xml.Substring(0, $ParagraphStyleMatch.Groups[3].Index) +
            "                  <TextAlign>Right</TextAlign>`r`n" +
            $Xml.Substring($ParagraphStyleMatch.Groups[3].Index)
    }

    return [regex]::Replace(
        $Xml,
        "(?s)(</Paragraph>)",
        "                <Style><TextAlign>Right</TextAlign></Style>`r`n              `$1",
        1)
}

function Get-TextboxName {
    param([Parameter(Mandatory)][string]$Xml)

    $Match = [regex]::Match($Xml, '<Textbox\s+Name="([^"]+)"')
    if ($Match.Success) {
        return $Match.Groups[1].Value
    }

    return ""
}

function Get-BodyWidth {
    param([Parameter(Mandatory)][string]$Content)

    $Match = [regex]::Match($Content, '(?s)<Body\b[^>]*>.*?<Width>([0-9.]+)in</Width>')
    if ($Match.Success) {
        return Convert-InchTextToDecimal $Match.Groups[1].Value
    }

    return 7.8
}

function Get-TextboxBlocks {
    param([Parameter(Mandatory)][string]$Content)

    return @([regex]::Matches($Content, '(?s)<Textbox\b[^>]*>.*?</Textbox>'))
}

function Find-TitleTextbox {
    param([Parameter(Mandatory)][string]$Content)

    $Blocks = Get-TextboxBlocks -Content $Content
    $BodyWidth = Get-BodyWidth -Content $Content

    foreach ($BlockMatch in $Blocks) {
        $Block = $BlockMatch.Value
        $Name = (Get-TextboxName -Xml $Block).ToLowerInvariant()
        if (($Name -eq "title") -or ($Name -eq "documenttitle") -or ($Name -eq "reporttitle")) {
            if (($Block -match '<Top>') -and ($Block -match '<Left>')) {
                return $BlockMatch
            }
        }
    }

    foreach ($BlockMatch in $Blocks) {
        $Block = $BlockMatch.Value
        if (($Block -notmatch '<Top>') -or ($Block -notmatch '<Left>') -or ($Block -notmatch '<Width>')) {
            continue
        }

        $Top = Get-TagInches -Xml $Block -TagName "Top"
        $Left = Get-TagInches -Xml $Block -TagName "Left"
        $Text = $Block.ToLowerInvariant()

        if (($Top -le 0.9) -and ($Left -ge ($BodyWidth / 2)) -and
            (($Text.Contains("order")) -or
             ($Text.Contains("invoice")) -or
             ($Text.Contains("memo")) -or
             ($Text.Contains("notice")) -or
             ($Text.Contains("ticket")) -or
             ($Text.Contains("receipt")) -or
             ($Text.Contains("transfer")))) {
            return $BlockMatch
        }
    }

    return $null
}

function Find-DocumentNumberTextbox {
    param(
        [Parameter(Mandatory)][string]$Content,
        [Parameter(Mandatory)][string]$FieldName
    )

    $Blocks = Get-TextboxBlocks -Content $Content
    $BodyWidth = Get-BodyWidth -Content $Content
    $BestMatch = $null
    $BestScore = -9999

    foreach ($BlockMatch in $Blocks) {
        $Block = $BlockMatch.Value

        if ($Block -notlike "*Fields!$FieldName.Value*") {
            continue
        }

        if (($Block -notmatch '<Top>') -or ($Block -notmatch '<Left>')) {
            continue
        }

        $Name = (Get-TextboxName -Xml $Block).ToLowerInvariant()
        $Top = Get-TagInches -Xml $Block -TagName "Top"
        $Left = Get-TagInches -Xml $Block -TagName "Left"
        $Text = $Block.ToLowerInvariant()

        $Score = 0
        if ($Top -le 2.2) { $Score += 30 }
        if ($Top -le 1.2) { $Score += 30 }
        if ($Left -ge ($BodyWidth / 2)) { $Score += 30 }
        if ($Name -match '(no|num|number|order|invoice|memo|return|transfer|po|document)') { $Score += 40 }
        if ($Text -match '(order|invoice|memo|return|transfer|po|#|no)') { $Score += 10 }

        if ($Score -gt $BestScore) {
            $BestScore = $Score
            $BestMatch = $BlockMatch
        }
    }

    return $BestMatch
}

function Move-ExistingDocumentNumber {
    param(
        [Parameter(Mandatory)][string]$LayoutPath,
        [Parameter(Mandatory)][string]$FieldName
    )

    $LayoutName = [System.IO.Path]::GetFileName($LayoutPath)
    $Content = Get-Content -LiteralPath $LayoutPath -Raw

    $TitleMatch = Find-TitleTextbox -Content $Content
    $NumberMatch = Find-DocumentNumberTextbox -Content $Content -FieldName $FieldName

    if ($null -eq $NumberMatch) {
        throw "Could not find an existing positioned textbox that uses Fields!$FieldName.Value in $LayoutName. No files were changed."
    }

    $BodyWidth = Get-BodyWidth -Content $Content
    $Width = 2.75
    $Left = [Math]::Max(0, $BodyWidth - $Width)
    $Top = 0.72

    if ($null -ne $TitleMatch) {
        $TitleBlock = $TitleMatch.Value
        $TitleTop = Get-TagInches -Xml $TitleBlock -TagName "Top"
        $TitleHeight = Get-TagInches -Xml $TitleBlock -TagName "Height"
        $TitleLeft = Get-TagInches -Xml $TitleBlock -TagName "Left"
        $TitleWidth = Get-TagInches -Xml $TitleBlock -TagName "Width"

        if ($TitleWidth -gt 0) {
            $Width = $TitleWidth
        }

        if ($TitleLeft -gt 0) {
            $Left = $TitleLeft
        }

        if (($TitleTop + $TitleHeight) -gt 0) {
            $Top = $TitleTop + $TitleHeight + 0.03
        }
    }

    $OldBlock = $NumberMatch.Value
    $NewBlock = $OldBlock

    $NewBlock = Set-SimpleTagValue -Xml $NewBlock -TagName "Top" -Value (Format-Inches $Top)
    $NewBlock = Set-SimpleTagValue -Xml $NewBlock -TagName "Left" -Value (Format-Inches $Left)
    $NewBlock = Set-SimpleTagValue -Xml $NewBlock -TagName "Width" -Value (Format-Inches $Width)
    $NewBlock = Set-SimpleTagValue -Xml $NewBlock -TagName "Height" -Value "0.22in"
    $NewBlock = Set-TextboxBold -Xml $NewBlock
    $NewBlock = Set-TextboxRightAligned -Xml $NewBlock

    if ($NewBlock -notmatch '<FontWeight>Bold</FontWeight>') {
        throw "Failed to apply bold formatting in $LayoutName."
    }

    if ($NewBlock -notmatch '<TextAlign>Right</TextAlign>') {
        throw "Failed to apply right alignment in $LayoutName."
    }

    $Updated = $Content.Substring(0, $NumberMatch.Index) + $NewBlock + $Content.Substring($NumberMatch.Index + $NumberMatch.Length)

    try {
        [xml]$XmlCheck = $Updated
    }
    catch {
        throw "The updated RDL XML for $LayoutName is not valid XML: $($_.Exception.Message)"
    }

    Write-Utf8NoBom -Path $LayoutPath -Content $Updated

    return [pscustomobject]@{
        Layout = $LayoutName
        Field = $FieldName
        OldTop = (Format-Inches (Get-TagInches -Xml $OldBlock -TagName "Top"))
        NewTop = (Format-Inches $Top)
    }
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

$LayoutMap = @(
    @{ File = "GPISalesOrderConfirmationBranded.rdl"; Field = "OrderNo" },
    @{ File = "GPIPrepaymentNotice.rdl"; Field = "OrderNo" },
    @{ File = "GPIPickTicket.rdl"; Field = "OrderNo" },
    @{ File = "GPIBlanketSalesOrderBranded.rdl"; Field = "BlanketOrderNo" },

    @{ File = "GPIDropShipPurchaseOrderBranded.rdl"; Field = "PurchaseOrderNo" },
    @{ File = "GPIWarehousePurchaseOrderBranded.rdl"; Field = "PurchaseOrderNo" },
    @{ File = "GPIWarehouseReceivingNoticeBranded.rdl"; Field = "PurchaseOrderNo" },

    @{ File = "GPISalesInvoiceBranded.rdl"; Field = "InvoiceNo" },
    @{ File = "GPISalesCreditMemoBranded.rdl"; Field = "InvoiceNo" },
    @{ File = "GPIPurchaseCreditMemoBranded.rdl"; Field = "InvoiceNo" },

    @{ File = "GPISalesReturnAuthorizationBranded.rdl"; Field = "ReturnOrderNo" },
    @{ File = "GPISalesReturnWarehouseNotificationBranded.rdl"; Field = "ReturnOrderNo" },
    @{ File = "GPIPurchaseReturnOrderBranded.rdl"; Field = "ReturnOrderNo" },
    @{ File = "GPIPurchaseReturnPickTicketBranded.rdl"; Field = "ReturnOrderNo" },

    @{ File = "GPITransferPickListBranded.rdl"; Field = "TransferOrderNo" },
    @{ File = "GPITransferReceiptNotificationBranded.rdl"; Field = "TransferOrderNo" }
)

$LayoutPaths = @()
foreach ($Map in $LayoutMap) {
    $LayoutPath = Join-Path -Path $ReportLayoutFolder -ChildPath $Map.File
    if (-not (Test-Path -LiteralPath $LayoutPath)) {
        throw "Layout file was not found: $LayoutPath"
    }
    $LayoutPaths += $LayoutPath
}

$FilesToBackup = @(
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLog
) + $LayoutPaths

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path -Path $RepoRoot -ChildPath ".gpi-backups\header-document-number-0270010-v2-$Timestamp"
New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

foreach ($Path in $FilesToBackup) {
    $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
    $BackupPath = Join-Path -Path $BackupRoot -ChildPath $RelativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $BackupPath) -Force | Out-Null
    Copy-Item -LiteralPath $Path -Destination $BackupPath -Force
}

$ProductionApp.version = $NewProductionVersion
$TestApp.version = $NewTestVersion
$MainDependency[0].version = $NewProductionVersion

$ChangeLogOriginal = Get-Content -LiteralPath $ChangeLog -Raw
$ChangeLogEntry = @"
## $NewProductionVersion

### Changed
- Moved existing document-number textboxes to the upper-right header area directly below the document title.
- Document numbers are right-aligned and bolded.
- This v2 patch preserves each report's existing document-number expression instead of creating new RDLC expressions.

### Safety
- No line, extended-text, footer, recipient, sender, routing-rule, Delivery Log, SharePoint archive, or email behavior was changed.
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
    $MoveResults = @()
    foreach ($Map in $LayoutMap) {
        $LayoutPath = Join-Path -Path $ReportLayoutFolder -ChildPath $Map.File
        $MoveResults += Move-ExistingDocumentNumber `
            -LayoutPath $LayoutPath `
            -FieldName $Map.Field
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
    Write-Host " GPI header document number layout pass 0.27.0.10 v2" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Production version: $NewProductionVersion"
    Write-Host "Test version:       $NewTestVersion"
    Write-Host "Layouts updated:    $($MoveResults.Count)"
    Write-Host "Backup:             $BackupRoot"
    Write-Host ""

    foreach ($Result in $MoveResults) {
        Write-Host ("{0}: {1} {2} -> {3}" -f $Result.Layout, $Result.Field, $Result.OldTop, $Result.NewTop)
    }

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
    Write-Host "The header document-number build failed. Restoring modified files." -ForegroundColor Red

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
Write-Host " GPI 0.27.0.10 build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Backup:             $BackupRoot"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish production first, then tests only after production 0.27.0.10 is installed in the sandbox." -ForegroundColor Yellow
