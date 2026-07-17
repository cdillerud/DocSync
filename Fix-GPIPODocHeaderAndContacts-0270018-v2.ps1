[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedProductionVersion = "0.27.0.17"
$ExpectedTestVersion = "0.8.0.17"
$NewProductionVersion = "0.27.0.18"
$NewTestVersion = "0.8.0.18"

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

    # XmlNamespaceManager can enumerate internally in PowerShell pipeline binding.
    # Return it as one object so typed parameters receive the manager, not Object[].
    Write-Output -NoEnumerate $NsMgr
}

function Get-TextboxName {
    param([Parameter(Mandatory)][System.Xml.XmlElement]$Textbox)

    if ($Textbox.HasAttribute("Name")) {
        return [string]$Textbox.GetAttribute("Name")
    }

    return ""
}

function Get-FirstTextboxExpression {
    param(
        [Parameter(Mandatory)][System.Xml.XmlElement]$Textbox,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Values = @($Textbox.SelectNodes(".//rdl:TextRun/rdl:Value", $NsMgr))
    foreach ($Value in $Values) {
        $Text = ([string]$Value.InnerText).Trim()
        if ($Text.StartsWith("=") -and ($Text -match "Fields!")) {
            return $Text
        }
    }

    foreach ($Value in $Values) {
        $Text = ([string]$Value.InnerText).Trim()
        if ($Text.StartsWith("=")) {
            return $Text
        }
    }

    return ""
}

function New-CleanPOExpression {
    param([Parameter(Mandatory)][string]$OriginalExpression)

    $Expr = $OriginalExpression.Trim()

    if (-not $Expr.StartsWith("=")) {
        $Escaped = $Expr.Replace('"', '""')
        return ('="PO: " & Trim(Replace(Replace(Replace(Replace(Replace(Replace("' + $Escaped + '", "PO #: #", ""), "PO #:#", ""), "PO##", ""), "PO #: ", ""), "PO #:", ""), "#", ""))')
    }

    $Body = $Expr.Substring(1).Trim()

    # The existing expression already knows which PO field to use. This wraps its rendered output.
    # It removes the old PO # label variants and strips hash marks from the number, then applies one clean label.
    return ('="PO: " & Trim(Replace(Replace(Replace(Replace(Replace(Replace(Replace(Replace(CStr(' + $Body + '), "PO #: #", ""), "PO #:#", ""), "PO##", ""), "PO #: ", ""), "PO #:", ""), "PO: ", ""), "PO:", ""), "#", ""))')
}

function Set-TextboxFirstValue {
    param(
        [Parameter(Mandatory)][System.Xml.XmlElement]$Textbox,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr,
        [Parameter(Mandatory)][string]$NewValue
    )

    $ValueNode = $Textbox.SelectSingleNode(".//rdl:TextRun/rdl:Value", $NsMgr)
    if ($null -eq $ValueNode) {
        return $false
    }

    if ([string]$ValueNode.InnerText -ne $NewValue) {
        $ValueNode.InnerText = $NewValue
        return $true
    }

    return $false
}

function Upsert-StyleValue {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlElement]$Textbox,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr,
        [Parameter(Mandatory)][string]$ElementName,
        [Parameter(Mandatory)][string]$ElementValue
    )

    $Ns = $Doc.DocumentElement.NamespaceURI
    $Style = $Textbox.SelectSingleNode("rdl:Style", $NsMgr)
    if ($null -eq $Style) {
        $Style = $Doc.CreateElement("Style", $Ns)
        [void]$Textbox.AppendChild($Style)
    }

    $Existing = $Style.SelectSingleNode("rdl:$ElementName", $NsMgr)
    if ($null -eq $Existing) {
        $Existing = $Doc.CreateElement($ElementName, $Ns)
        [void]$Style.AppendChild($Existing)
    }

    if ([string]$Existing.InnerText -ne $ElementValue) {
        $Existing.InnerText = $ElementValue
        return $true
    }

    return $false
}

function Collapse-ExtraContactLineBreaks {
    param([Parameter(Mandatory)][string]$Expression)

    $Updated = $Expression

    # Collapse repeated leading line breaks added in earlier contact alignment attempts.
    for ($i = 0; $i -lt 6; $i++) {
        $Updated = [regex]::Replace($Updated, '=\s*vbCrLf\s*&\s*vbCrLf\s*&\s*', '=vbCrLf & ', 1)
        $Updated = [regex]::Replace($Updated, 'vbCrLf\s*&\s*vbCrLf\s*&\s*', 'vbCrLf & ', 1)
    }

    return $Updated
}

function Update-GamerContactsSpacing {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Changed = 0
    $Textboxes = @($Doc.SelectNodes("//rdl:Textbox[not(ancestor::rdl:Tablix)]", $NsMgr))

    foreach ($TextboxNode in $Textboxes) {
        $Textbox = [System.Xml.XmlElement]$TextboxNode
        $Text = [string]$Textbox.InnerText

        if ($Text -notmatch "Gamer Contacts") {
            continue
        }

        if (Upsert-StyleValue -Doc $Doc -Textbox $Textbox -NsMgr $NsMgr -ElementName "PaddingTop" -ElementValue "0pt") {
            $Changed++
        }

        if (Upsert-StyleValue -Doc $Doc -Textbox $Textbox -NsMgr $NsMgr -ElementName "PaddingBottom" -ElementValue "0pt") {
            $Changed++
        }

        $Values = @($Textbox.SelectNodes(".//rdl:TextRun/rdl:Value", $NsMgr))
        foreach ($ValueNode in $Values) {
            $OldValue = [string]$ValueNode.InnerText

            if ($OldValue.TrimStart().StartsWith("=")) {
                $NewValue = Collapse-ExtraContactLineBreaks -Expression $OldValue
                if ($NewValue -ne $OldValue) {
                    $ValueNode.InnerText = $NewValue
                    $Changed++
                }
            }
            elseif ($OldValue -match "Gamer Contacts") {
                if ($OldValue -ne "Gamer Contacts:") {
                    $ValueNode.InnerText = "Gamer Contacts:"
                    $Changed++
                }
            }
        }
    }

    return $Changed
}

function Update-POHeaderNumber {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Changed = 0

    $CandidateTextboxes = @($Doc.SelectNodes("//rdl:Textbox[not(ancestor::rdl:Tablix)]", $NsMgr)) |
        Where-Object {
            $Name = Get-TextboxName -Textbox ([System.Xml.XmlElement]$_)
            $Text = [string]$_.InnerText

            (
                $Name -eq "GPIHeaderDocumentNumber" -or
                $Name -eq "PONo" -or
                $Name -eq "PONumber" -or
                (($Text -match "PO") -and ($Text -match "Fields!") -and ($Text -match "#"))
            )
        }

    if ($CandidateTextboxes.Count -eq 0) {
        throw "Could not find a PO header number textbox in this layout."
    }

    $Primary = $null

    foreach ($Textbox in $CandidateTextboxes) {
        $Name = Get-TextboxName -Textbox ([System.Xml.XmlElement]$Textbox)
        $Expr = Get-FirstTextboxExpression -Textbox ([System.Xml.XmlElement]$Textbox) -NsMgr $NsMgr

        if (($Name -eq "GPIHeaderDocumentNumber") -and ($Expr -ne "")) {
            $Primary = [System.Xml.XmlElement]$Textbox
            break
        }
    }

    if ($null -eq $Primary) {
        foreach ($Textbox in $CandidateTextboxes) {
            $Expr = Get-FirstTextboxExpression -Textbox ([System.Xml.XmlElement]$Textbox) -NsMgr $NsMgr
            if ($Expr -match "Fields!") {
                $Primary = [System.Xml.XmlElement]$Textbox
                break
            }
        }
    }

    if ($null -eq $Primary) {
        $Primary = [System.Xml.XmlElement]$CandidateTextboxes[0]
    }

    $SourceExpression = Get-FirstTextboxExpression -Textbox $Primary -NsMgr $NsMgr

    if ($SourceExpression -eq "") {
        foreach ($Textbox in $CandidateTextboxes) {
            $CandidateExpression = Get-FirstTextboxExpression -Textbox ([System.Xml.XmlElement]$Textbox) -NsMgr $NsMgr
            if ($CandidateExpression -match "Fields!") {
                $SourceExpression = $CandidateExpression
                break
            }
        }
    }

    if ($SourceExpression -eq "") {
        throw "Could not determine the PO number source expression."
    }

    $CleanExpression = New-CleanPOExpression -OriginalExpression $SourceExpression

    if (Set-TextboxFirstValue -Textbox $Primary -NsMgr $NsMgr -NewValue $CleanExpression) {
        $Changed++
    }

    # Blank duplicate PO number textboxes so the old # value cannot visually overlap the corrected value.
    foreach ($Textbox in $CandidateTextboxes) {
        $TextboxElement = [System.Xml.XmlElement]$Textbox
        if ([object]::ReferenceEquals($TextboxElement, $Primary)) {
            continue
        }

        $Name = Get-TextboxName -Textbox $TextboxElement

        if ($Name -eq "PONo" -or $Name -eq "PONumber") {
            if (Set-TextboxFirstValue -Textbox $TextboxElement -NsMgr $NsMgr -NewValue '=""') {
                $Changed++
            }
        }
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

    $POChanges = Update-POHeaderNumber -Doc $Doc -NsMgr $NsMgr
    $ContactChanges = Update-GamerContactsSpacing -Doc $Doc -NsMgr $NsMgr

    if (($POChanges + $ContactChanges) -gt 0) {
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
        POHeaderChanges = $POChanges
        ContactSpacingChanges = $ContactChanges
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
$BackupRoot = Join-Path -Path $RepoRoot -ChildPath ".gpi-backups\po-doc-header-and-contacts-0270018-v2-$Timestamp"
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
- Purchase-order-related document headers now display the upper-right PO number as `PO: xxxxxxxx`.
- Removed the extra hash-mark formatting from the upper-right PO number.
- Suppressed duplicate old PO number textboxes where they could overlap the new header number.
- Tightened Gamer Contacts spacing on purchase-order-related documents without moving the detail fields.

### Scope
- Drop Ship Purchase Order
- Warehouse Purchase Order
- Warehouse Receiving Notice

### Safety
- No report dataset fields, line-grid formatting, decimal formatting, UoM columns, footer text, routing rules, sender logic, Delivery Log, SharePoint archive, or email behavior was changed.
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
    $POHeaderChangeCount = 0
    $ContactSpacingChangeCount = 0

    foreach ($Result in $Results) {
        $POHeaderChangeCount += [int]$Result.POHeaderChanges
        $ContactSpacingChangeCount += [int]$Result.ContactSpacingChanges
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
    Write-Host " GPI PO document header/contact cleanup 0.27.0.18 v2" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Production version:       $NewProductionVersion"
    Write-Host "Test version:             $NewTestVersion"
    Write-Host "Layouts changed:          $ChangedCount"
    Write-Host "PO header changes:        $POHeaderChangeCount"
    Write-Host "Contact spacing changes:  $ContactSpacingChangeCount"
    Write-Host "Backup:                   $BackupRoot"
    Write-Host ""

    foreach ($Result in $Results) {
        Write-Host ("{0}: POHeaderChanges={1}, ContactSpacingChanges={2}" -f $Result.Layout, $Result.POHeaderChanges, $Result.ContactSpacingChanges)
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
    Write-Host "The PO document header/contact cleanup build failed. Restoring modified files." -ForegroundColor Red

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
Write-Host " GPI 0.27.0.18 build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Backup:             $BackupRoot"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish production $NewProductionVersion first, then tests only after production is installed in the sandbox." -ForegroundColor Yellow
