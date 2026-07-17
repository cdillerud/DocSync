[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedProductionVersion = "0.27.0.18"
$ExpectedTestVersion = "0.8.0.18"
$NewProductionVersion = "0.27.0.19"
$NewTestVersion = "0.8.0.19"

$ProductionRoot = Join-Path -Path $RepoRoot -ChildPath "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path -Path $RepoRoot -ChildPath "bc-extension\zetadocs-replacement-tests"

$ProductionAppJson = Join-Path -Path $ProductionRoot -ChildPath "app.json"
$TestAppJson = Join-Path -Path $TestRoot -ChildPath "app.json"
$ChangeLog = Join-Path -Path $ProductionRoot -ChildPath "CHANGELOG.md"
$BuildScript = Join-Path -Path $RepoRoot -ChildPath "scripts\Prepare-GPIALTests.ps1"
$ReportLayoutFolder = Join-Path -Path $ProductionRoot -ChildPath "src\reportlayout"

$TargetLayoutNames = @(
    "GPIDropShipPurchaseOrderBranded.rdl",
    "GPIWarehousePurchaseOrderBranded.rdl",
    "GPIWarehouseReceivingNoticeBranded.rdl"
)

foreach ($RequiredPath in @($ProductionAppJson, $TestAppJson, $ChangeLog, $BuildScript, $ReportLayoutFolder)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required path was not found: $RequiredPath"
    }
}

$TargetLayouts = @()
foreach ($LayoutName in $TargetLayoutNames) {
    $Path = Join-Path -Path $ReportLayoutFolder -ChildPath $LayoutName
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Target layout was not found: $Path"
    }

    $TargetLayouts += $Path
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

function Get-RdlNsMgr {
    param([Parameter(Mandatory)][System.Xml.XmlDocument]$Doc)

    $NsMgr = New-Object System.Xml.XmlNamespaceManager($Doc.NameTable)
    [void]$NsMgr.AddNamespace("rdl", $Doc.DocumentElement.NamespaceURI)
    Write-Output -NoEnumerate $NsMgr
}

function Test-IsContactExpression {
    param([Parameter(Mandatory)][string]$ExpressionText)

    $Lower = $ExpressionText.ToLowerInvariant()

    if (-not $Lower.TrimStart().StartsWith("=")) {
        return $false
    }

    return (
        ($Lower -match 'gamercontact') -or
        ($Lower -match 'salespersonname') -or
        ($Lower -match 'insidesalesperson') -or
        ($Lower -match 'backupinsidesalesperson') -or
        ($Lower -match 'purchasername') -or
        ($Lower -match 'contactline') -or
        (($Lower -match 'fields!') -and ($Lower -match 'contact'))
    )
}

function Strip-LeadingLineBreakTokens {
    param([Parameter(Mandatory)][string]$Expression)

    $Expr = $Expression.Trim()

    if (-not $Expr.StartsWith("=")) {
        return $Expr
    }

    # Remove embedded label if prior patches pushed it into the expression.
    $Expr = [regex]::Replace($Expr, '^\s*=\s*"Gamer Contacts:\s*"\s*&\s*', '=', 1)
    $Expr = [regex]::Replace($Expr, '^\s*=\s*Trim\(\s*"Gamer Contacts:\s*"\s*&\s*', '=Trim(', 1)

    # Remove all leading line-break tokens from the contact expression.
    # The label run will own the single line break after "Gamer Contacts:".
    $changed = $true
    while ($changed) {
        $Old = $Expr

        $Expr = [regex]::Replace($Expr, '^\s*=\s*vbCrLf\s*&\s*', '=', 1)
        $Expr = [regex]::Replace($Expr, '^\s*=\s*vbLf\s*&\s*', '=', 1)
        $Expr = [regex]::Replace($Expr, '^\s*=\s*Chr\(\s*13\s*\)\s*&\s*Chr\(\s*10\s*\)\s*&\s*', '=', 1)
        $Expr = [regex]::Replace($Expr, '^\s*=\s*Chr\(\s*10\s*\)\s*&\s*', '=', 1)
        $Expr = [regex]::Replace($Expr, '^\s*=\s*Environment\.NewLine\s*&\s*', '=', 1)

        $changed = ($Expr -ne $Old)
    }

    return $Expr
}

function Set-ParagraphLeftAlign {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlElement]$Paragraph,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Ns = $Doc.DocumentElement.NamespaceURI
    $Style = $Paragraph.SelectSingleNode("rdl:Style", $NsMgr)

    if ($null -eq $Style) {
        $Style = $Doc.CreateElement("Style", $Ns)
        [void]$Paragraph.AppendChild($Style)
    }

    $TextAlign = $Style.SelectSingleNode("rdl:TextAlign", $NsMgr)

    if ($null -eq $TextAlign) {
        $TextAlign = $Doc.CreateElement("TextAlign", $Ns)
        [void]$Style.AppendChild($TextAlign)
    }

    $TextAlign.InnerText = "Left"
}

function Remove-TextboxPadding {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlElement]$Textbox,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Changed = 0
    $Ns = $Doc.DocumentElement.NamespaceURI
    $Style = $Textbox.SelectSingleNode("rdl:Style", $NsMgr)

    if ($null -eq $Style) {
        $Style = $Doc.CreateElement("Style", $Ns)
        [void]$Textbox.AppendChild($Style)
    }

    foreach ($ElementName in @("PaddingTop", "PaddingBottom")) {
        $Node = $Style.SelectSingleNode("rdl:$ElementName", $NsMgr)

        if ($null -eq $Node) {
            $Node = $Doc.CreateElement($ElementName, $Ns)
            [void]$Style.AppendChild($Node)
        }

        if ([string]$Node.InnerText -ne "0pt") {
            $Node.InnerText = "0pt"
            $Changed++
        }
    }

    return $Changed
}

function Fix-GamerContactGapInParagraph {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlElement]$Paragraph,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Changed = 0
    $TextRuns = @($Paragraph.SelectNodes("rdl:TextRuns/rdl:TextRun", $NsMgr))

    if ($TextRuns.Count -eq 0) {
        return 0
    }

    for ($i = 0; $i -lt $TextRuns.Count; $i++) {
        $ValueNode = $TextRuns[$i].SelectSingleNode("rdl:Value", $NsMgr)

        if ($null -eq $ValueNode) {
            continue
        }

        $ValueText = [string]$ValueNode.InnerText

        if ($ValueText.TrimStart().StartsWith("=")) {
            continue
        }

        if ($ValueText -notmatch "Gamer Contacts") {
            continue
        }

        # Normalize the label and let the label own exactly one line break.
        $NewLabelValue = '="Gamer Contacts:" & vbCrLf'

        if ($ValueText -ne $NewLabelValue) {
            $ValueNode.InnerText = $NewLabelValue
            $Changed++
        }

        # Find the first contact expression after the label and remove its leading line break.
        for ($j = $i + 1; $j -lt $TextRuns.Count; $j++) {
            $ContactValueNode = $TextRuns[$j].SelectSingleNode("rdl:Value", $NsMgr)

            if ($null -eq $ContactValueNode) {
                continue
            }

            $ContactValue = [string]$ContactValueNode.InnerText

            if (-not (Test-IsContactExpression -ExpressionText $ContactValue)) {
                continue
            }

            $NewContactValue = Strip-LeadingLineBreakTokens -Expression $ContactValue

            if ($NewContactValue -ne $ContactValue) {
                $ContactValueNode.InnerText = $NewContactValue
                $Changed++
            }

            break
        }
    }

    if ($Changed -gt 0) {
        Set-ParagraphLeftAlign -Doc $Doc -Paragraph $Paragraph -NsMgr $NsMgr
    }

    return $Changed
}

function Save-XmlDocumentUtf8NoBom {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][string]$Path
    )

    $Settings = New-Object System.Xml.XmlWriterSettings
    $Settings.Encoding = New-Object System.Text.UTF8Encoding($false)
    $Settings.Indent = $true
    $Settings.OmitXmlDeclaration = $false

    $Writer = [System.Xml.XmlWriter]::Create($Path, $Settings)
    try {
        $Doc.Save($Writer)
    }
    finally {
        $Writer.Close()
    }
}

function Update-TargetLayout {
    param([Parameter(Mandatory)][string]$LayoutPath)

    $LayoutName = [System.IO.Path]::GetFileName($LayoutPath)
    $Original = Get-Content -LiteralPath $LayoutPath -Raw

    $Doc = New-Object System.Xml.XmlDocument
    $Doc.PreserveWhitespace = $false

    try {
        $Doc.Load($LayoutPath)
    }
    catch {
        throw "The original RDL XML for $LayoutName is not valid XML before changes: $($_.Exception.Message)"
    }

    $NsMgr = Get-RdlNsMgr -Doc $Doc
    $Changes = 0

    $Textboxes = @($Doc.SelectNodes("//rdl:Textbox[not(ancestor::rdl:Tablix)]", $NsMgr))

    foreach ($TextboxNode in $Textboxes) {
        $Textbox = [System.Xml.XmlElement]$TextboxNode

        if ([string]$Textbox.InnerText -notmatch "Gamer Contacts") {
            continue
        }

        $Changes += Remove-TextboxPadding -Doc $Doc -Textbox $Textbox -NsMgr $NsMgr

        $Paragraphs = @($Textbox.SelectNodes("rdl:Paragraphs/rdl:Paragraph", $NsMgr))
        foreach ($ParagraphNode in $Paragraphs) {
            $Paragraph = [System.Xml.XmlElement]$ParagraphNode

            if ([string]$Paragraph.InnerText -match "Gamer Contacts") {
                $Changes += Fix-GamerContactGapInParagraph -Doc $Doc -Paragraph $Paragraph -NsMgr $NsMgr
            }
        }
    }

    if ($Changes -gt 0) {
        Save-XmlDocumentUtf8NoBom -Doc $Doc -Path $LayoutPath

        try {
            [xml]$XmlCheck = Get-Content -LiteralPath $LayoutPath -Raw
        }
        catch {
            throw "The updated RDL XML for $LayoutName is not valid XML after save: $($_.Exception.Message)"
        }
    }

    $Updated = Get-Content -LiteralPath $LayoutPath -Raw

    return [pscustomobject]@{
        Layout = $LayoutName
        Changes = $Changes
        Changed = ($Updated -ne $Original)
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

$FilesToBackup = @(
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLog
) + $TargetLayouts

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path -Path $RepoRoot -ChildPath ".gpi-backups\po-doc-contact-gap-0270019-$Timestamp"
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

### Fixed
- Removed the extra blank space above the first Gamer Contact name on purchase-order-related documents.
- The label now owns exactly one line break after `Gamer Contacts:`.
- The first contact expression no longer starts with its own leading line break.

### Scope
- Drop Ship Purchase Order
- Warehouse Purchase Order
- Warehouse Receiving Notice

### Safety
- No PO number formatting, report dataset fields, line-grid formatting, decimal formatting, UoM columns, footer text, routing rules, sender logic, Delivery Log, SharePoint archive, or email behavior was changed.
- No package is published automatically.
- Publish production $NewProductionVersion first, then tests only after production is installed in the sandbox.

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
    $Results = @()
    foreach ($LayoutPath in $TargetLayouts) {
        $Results += Update-TargetLayout -LayoutPath $LayoutPath
    }

    $ChangedCount = @($Results | Where-Object { $_.Changed }).Count
    $TotalChanges = 0

    foreach ($Result in $Results) {
        $TotalChanges += [int]$Result.Changes
    }

    if ($ChangedCount -eq 0) {
        throw "No target layouts were changed. No files were changed."
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
    Write-Host " GPI PO document contact gap cleanup 0.27.0.19" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Production version: $NewProductionVersion"
    Write-Host "Test version:       $NewTestVersion"
    Write-Host "Layouts changed:    $ChangedCount"
    Write-Host "Total XML changes:  $TotalChanges"
    Write-Host "Backup:             $BackupRoot"
    Write-Host ""

    foreach ($Result in $Results) {
        Write-Host ("{0}: Changes={1}" -f $Result.Layout, $Result.Changes)
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
    Write-Host "The PO document contact gap cleanup build failed. Restoring modified files." -ForegroundColor Red

    foreach ($Path in $FilesToBackup) {
        $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
        $BackupPath = Join-Path -Path $BackupRoot -ChildPath $RelativePath
        if (Test-Path -LiteralPath $BackupPath) {
            Copy-Item -LiteralPath $BackupPath -Destination $Path -Force
        }
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
Write-Host " GPI 0.27.0.19 build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Backup:             $BackupRoot"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish production $NewProductionVersion first, then tests only after production is installed in the sandbox." -ForegroundColor Yellow
