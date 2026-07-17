[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedProductionVersion = "0.27.0.20"
$ExpectedTestVersion = "0.8.0.20"
$NewProductionVersion = "0.27.0.21"
$NewTestVersion = "0.8.0.21"

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

function Get-RdlNsMgr {
    param([Parameter(Mandatory)][System.Xml.XmlDocument]$Doc)
    $NsMgr = New-Object System.Xml.XmlNamespaceManager($Doc.NameTable)
    [void]$NsMgr.AddNamespace("rdl", $Doc.DocumentElement.NamespaceURI)
    Write-Output -NoEnumerate $NsMgr
}

function Get-TextboxName {
    param([Parameter(Mandatory)][System.Xml.XmlElement]$Textbox)
    if ($Textbox.HasAttribute("Name")) { return [string]$Textbox.GetAttribute("Name") }
    return ""
}

function Get-DirectChildText {
    param(
        [Parameter(Mandatory)][System.Xml.XmlElement]$Element,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr,
        [Parameter(Mandatory)][string]$ChildName
    )
    $Node = $Element.SelectSingleNode("rdl:$ChildName", $NsMgr)
    if ($null -eq $Node) { return "" }
    return [string]$Node.InnerText
}

function ConvertTo-Inches {
    param([string]$Value, [double]$Default = 0.0)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $Default }
    $Match = [regex]::Match($Value.Trim(), '([-+]?\d+(?:\.\d+)?)\s*(in|cm|mm|pt)?', 'IgnoreCase')
    if (-not $Match.Success) { return $Default }
    $Number = [double]::Parse($Match.Groups[1].Value, [System.Globalization.CultureInfo]::InvariantCulture)
    $Unit = $Match.Groups[2].Value.ToLowerInvariant()
    switch ($Unit) {
        "cm" { return ($Number / 2.54) }
        "mm" { return ($Number / 25.4) }
        "pt" { return ($Number / 72.0) }
        default { return $Number }
    }
}

function Format-Inches {
    param([Parameter(Mandatory)][double]$Value)
    return ($Value.ToString("0.###", [System.Globalization.CultureInfo]::InvariantCulture) + "in")
}

function Set-DirectChildTextIfExists {
    param(
        [Parameter(Mandatory)][System.Xml.XmlElement]$Element,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr,
        [Parameter(Mandatory)][string]$ChildName,
        [Parameter(Mandatory)][string]$Value
    )
    $Node = $Element.SelectSingleNode("rdl:$ChildName", $NsMgr)
    if ($null -eq $Node) { return 0 }
    if ([string]$Node.InnerText -ne $Value) {
        $Node.InnerText = $Value
        return 1
    }
    return 0
}

function Set-StyleValue {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlElement]$Textbox,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr,
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Value
    )
    $Ns = $Doc.DocumentElement.NamespaceURI
    $Style = $Textbox.SelectSingleNode("rdl:Style", $NsMgr)
    if ($null -eq $Style) {
        $Style = $Doc.CreateElement("Style", $Ns)
        [void]$Textbox.AppendChild($Style)
    }
    $Node = $Style.SelectSingleNode("rdl:$Name", $NsMgr)
    if ($null -eq $Node) {
        $Node = $Doc.CreateElement($Name, $Ns)
        [void]$Style.AppendChild($Node)
    }
    if ([string]$Node.InnerText -ne $Value) {
        $Node.InnerText = $Value
        return 1
    }
    return 0
}

function Test-IsContactExpressionText {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return $false }
    $Lower = $Text.ToLowerInvariant()
    if (-not $Lower.TrimStart().StartsWith("=")) { return $false }
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

function Test-IsContactTextbox {
    param([Parameter(Mandatory)][System.Xml.XmlElement]$Textbox)
    if ([string]$Textbox.InnerText -match "Gamer Contacts") { return $false }
    $Xml = $Textbox.OuterXml.ToLowerInvariant()
    return (
        ($Xml -match 'gamercontact') -or
        ($Xml -match 'salespersonname') -or
        ($Xml -match 'insidesalesperson') -or
        ($Xml -match 'backupinsidesalesperson') -or
        ($Xml -match 'purchasername') -or
        ($Xml -match 'contactline') -or
        (($Xml -match 'fields!') -and ($Xml -match 'contact'))
    )
}

function Strip-LeadingLineBreakTokens {
    param([Parameter(Mandatory)][string]$Expression)
    $Expr = $Expression.Trim()
    if (-not $Expr.StartsWith("=")) { return $Expr }

    $Expr = [regex]::Replace($Expr, '^\s*=\s*"Gamer Contacts:\s*"\s*&\s*', '=', 1)
    $Expr = [regex]::Replace($Expr, '^\s*=\s*Trim\(\s*"Gamer Contacts:\s*"\s*&\s*', '=Trim(', 1)

    $Changed = $true
    while ($Changed) {
        $Old = $Expr
        $Expr = [regex]::Replace($Expr, '^\s*=\s*vbCrLf\s*&\s*', '=', 1)
        $Expr = [regex]::Replace($Expr, '^\s*=\s*vbLf\s*&\s*', '=', 1)
        $Expr = [regex]::Replace($Expr, '^\s*=\s*Chr\(\s*13\s*\)\s*&\s*Chr\(\s*10\s*\)\s*&\s*', '=', 1)
        $Expr = [regex]::Replace($Expr, '^\s*=\s*Chr\(\s*10\s*\)\s*&\s*', '=', 1)
        $Expr = [regex]::Replace($Expr, '^\s*=\s*Environment\.NewLine\s*&\s*', '=', 1)
        $Changed = ($Expr -ne $Old)
    }
    return $Expr
}

function Normalize-LabelTextboxRuns {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlElement]$Textbox,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Changes = 0
    $Values = @($Textbox.SelectNodes(".//rdl:TextRun/rdl:Value", $NsMgr))
    $HasContactExpression = $false

    foreach ($ValueNode in $Values) {
        if (Test-IsContactExpressionText -Text ([string]$ValueNode.InnerText)) {
            $HasContactExpression = $true
        }
    }

    $Changes += Set-StyleValue -Doc $Doc -Textbox $Textbox -NsMgr $NsMgr -Name "PaddingTop" -Value "0pt"
    $Changes += Set-StyleValue -Doc $Doc -Textbox $Textbox -NsMgr $NsMgr -Name "PaddingBottom" -Value "0pt"
    $Changes += Set-StyleValue -Doc $Doc -Textbox $Textbox -NsMgr $NsMgr -Name "VerticalAlign" -Value "Top"

    foreach ($ValueNode in $Values) {
        $ValueText = [string]$ValueNode.InnerText

        if ($ValueText -match "Gamer Contacts") {
            # If contacts are in the same textbox, label owns exactly one line break.
            # If contacts are in a separate textbox, label is plain text.
            if ($HasContactExpression) { $NewLabel = '="Gamer Contacts:" & vbCrLf' } else { $NewLabel = "Gamer Contacts:" }
            if ($ValueText -ne $NewLabel) {
                $ValueNode.InnerText = $NewLabel
                $Changes++
            }
        }
        elseif (Test-IsContactExpressionText -Text $ValueText) {
            $NewExpression = Strip-LeadingLineBreakTokens -Expression $ValueText
            if ($NewExpression -ne $ValueText) {
                $ValueNode.InnerText = $NewExpression
                $Changes++
            }
        }
    }

    return $Changes
}

function Get-ContactDiagnostics {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Rows = @()
    $Textboxes = @($Doc.SelectNodes("//rdl:Textbox[not(ancestor::rdl:Tablix)]", $NsMgr))
    foreach ($TextboxNode in $Textboxes) {
        $Textbox = [System.Xml.XmlElement]$TextboxNode
        $Xml = $Textbox.OuterXml
        $Text = ([string]$Textbox.InnerText).Replace("`r", " ").Replace("`n", " ")
        if ($Text -match "Gamer Contacts" -or $Xml -match "GamerContact|SalespersonName|InsideSalesperson|PurchaserName|ContactLine") {
            $Rows += [pscustomobject]@{
                Name = Get-TextboxName -Textbox $Textbox
                Top = Get-DirectChildText -Element $Textbox -NsMgr $NsMgr -ChildName "Top"
                Left = Get-DirectChildText -Element $Textbox -NsMgr $NsMgr -ChildName "Left"
                Height = Get-DirectChildText -Element $Textbox -NsMgr $NsMgr -ChildName "Height"
                Snippet = ($Text.Substring(0, [Math]::Min(100, $Text.Length)))
            }
        }
    }
    return @($Rows)
}

function Move-SeparateContactTextboxesUp {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlElement]$LabelTextbox,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Changes = 0
    $LabelLeft = ConvertTo-Inches -Value (Get-DirectChildText -Element $LabelTextbox -NsMgr $NsMgr -ChildName "Left") -Default -999
    $LabelTop = ConvertTo-Inches -Value (Get-DirectChildText -Element $LabelTextbox -NsMgr $NsMgr -ChildName "Top") -Default -999

    if ($LabelLeft -eq -999 -or $LabelTop -eq -999) {
        return 0
    }

    $DesiredLabelHeight = 0.14
    $Changes += Set-DirectChildTextIfExists -Element $LabelTextbox -NsMgr $NsMgr -ChildName "Height" -Value (Format-Inches -Value $DesiredLabelHeight)

    # Separate textbox case: make label plain, not a line-break expression.
    $Values = @($LabelTextbox.SelectNodes(".//rdl:TextRun/rdl:Value", $NsMgr))
    foreach ($ValueNode in $Values) {
        $ValueText = [string]$ValueNode.InnerText
        if ($ValueText -match "Gamer Contacts" -and $ValueText -ne "Gamer Contacts:") {
            $ValueNode.InnerText = "Gamer Contacts:"
            $Changes++
        }
    }

    $AllTextboxes = @($Doc.SelectNodes("//rdl:Textbox[not(ancestor::rdl:Tablix)]", $NsMgr))
    $ContactCandidates = @()

    foreach ($TextboxNode in $AllTextboxes) {
        $Textbox = [System.Xml.XmlElement]$TextboxNode
        if (-not (Test-IsContactTextbox -Textbox $Textbox)) { continue }

        $ContactLeft = ConvertTo-Inches -Value (Get-DirectChildText -Element $Textbox -NsMgr $NsMgr -ChildName "Left") -Default -999
        $ContactTop = ConvertTo-Inches -Value (Get-DirectChildText -Element $Textbox -NsMgr $NsMgr -ChildName "Top") -Default -999

        if ($ContactLeft -eq -999 -or $ContactTop -eq -999) { continue }

        $HorizontallyClose = ([Math]::Abs($ContactLeft - $LabelLeft) -le 0.45)
        $BelowLabel = ($ContactTop -gt $LabelTop)
        $NearbyVertically = ($ContactTop -lt ($LabelTop + 0.90))

        if ($HorizontallyClose -and $BelowLabel -and $NearbyVertically) {
            $ContactCandidates += $Textbox
        }
    }

    foreach ($ContactTextbox in @($ContactCandidates)) {
        $CurrentTop = ConvertTo-Inches -Value (Get-DirectChildText -Element $ContactTextbox -NsMgr $NsMgr -ChildName "Top") -Default -999
        if ($CurrentTop -eq -999) { continue }

        $DesiredTop = $LabelTop + $DesiredLabelHeight + 0.015
        if ($CurrentTop -gt ($DesiredTop + 0.01)) {
            $Changes += Set-DirectChildTextIfExists -Element $ContactTextbox -NsMgr $NsMgr -ChildName "Top" -Value (Format-Inches -Value $DesiredTop)
        }

        $Changes += Set-StyleValue -Doc $Doc -Textbox $ContactTextbox -NsMgr $NsMgr -Name "PaddingTop" -Value "0pt"
        $Changes += Set-StyleValue -Doc $Doc -Textbox $ContactTextbox -NsMgr $NsMgr -Name "PaddingBottom" -Value "0pt"
        $Changes += Set-StyleValue -Doc $Doc -Textbox $ContactTextbox -NsMgr $NsMgr -Name "VerticalAlign" -Value "Top"

        $CurrentHeight = ConvertTo-Inches -Value (Get-DirectChildText -Element $ContactTextbox -NsMgr $NsMgr -ChildName "Height") -Default 0.0
        if ($CurrentHeight -gt 0 -and $CurrentHeight -lt 0.34) {
            $Changes += Set-DirectChildTextIfExists -Element $ContactTextbox -NsMgr $NsMgr -ChildName "Height" -Value "0.34in"
        }

        $ContactValues = @($ContactTextbox.SelectNodes(".//rdl:TextRun/rdl:Value", $NsMgr))
        foreach ($ContactValueNode in $ContactValues) {
            $OldValue = [string]$ContactValueNode.InnerText
            if (Test-IsContactExpressionText -Text $OldValue) {
                $NewValue = Strip-LeadingLineBreakTokens -Expression $OldValue
                if ($NewValue -ne $OldValue) {
                    $ContactValueNode.InnerText = $NewValue
                    $Changes++
                }
            }
        }
    }

    return $Changes
}

function Save-XmlDocumentUtf8NoBom {
    param([Parameter(Mandatory)][System.Xml.XmlDocument]$Doc, [Parameter(Mandatory)][string]$Path)
    $Settings = New-Object System.Xml.XmlWriterSettings
    $Settings.Encoding = New-Object System.Text.UTF8Encoding($false)
    $Settings.Indent = $true
    $Settings.OmitXmlDeclaration = $false
    $Writer = [System.Xml.XmlWriter]::Create($Path, $Settings)
    try { $Doc.Save($Writer) } finally { $Writer.Close() }
}

function Update-LayoutContactGap {
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

    $LabelTextboxes = @(
        $Doc.SelectNodes("//rdl:Textbox[not(ancestor::rdl:Tablix)]", $NsMgr) |
            Where-Object { [string]$_.InnerText -match "Gamer Contacts" }
    )

    foreach ($LabelTextboxNode in @($LabelTextboxes)) {
        $LabelTextbox = [System.Xml.XmlElement]$LabelTextboxNode
        $Before = $Changes
        $Changes += Normalize-LabelTextboxRuns -Doc $Doc -Textbox $LabelTextbox -NsMgr $NsMgr
        $Changes += Move-SeparateContactTextboxesUp -Doc $Doc -LabelTextbox $LabelTextbox -NsMgr $NsMgr
    }

    if ($Changes -gt 0) {
        Save-XmlDocumentUtf8NoBom -Doc $Doc -Path $LayoutPath
        try { [xml]$XmlCheck = Get-Content -LiteralPath $LayoutPath -Raw } catch { throw "The updated RDL XML for $LayoutName is not valid XML after save: $($_.Exception.Message)" }
    }

    $Updated = Get-Content -LiteralPath $LayoutPath -Raw

    return [pscustomobject]@{
        Layout = $LayoutName
        LabelCount = @($LabelTextboxes).Count
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

$MainDependency = @($TestApp.dependencies | Where-Object { [string]$_.id -eq [string]$ProductionApp.id })
if ($MainDependency.Count -ne 1) {
    throw "Expected exactly one test dependency on production app $($ProductionApp.id), but found $($MainDependency.Count). No files were changed."
}

$TargetLayouts = @(
    Get-ChildItem -LiteralPath $ReportLayoutFolder -File -Filter "*.rdl" |
        Where-Object { (Get-Content -LiteralPath $_.FullName -Raw) -match "Gamer Contacts" } |
        Select-Object -ExpandProperty FullName
)

if ($TargetLayouts.Count -eq 0) {
    throw "No layouts containing Gamer Contacts were found. No files were changed."
}

$FilesToBackup = @($ProductionAppJson, $TestAppJson, $ChangeLog) + @($TargetLayouts)
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path -Path $RepoRoot -ChildPath ".gpi-backups\all-docs-gamer-contacts-gap-0270021-$Timestamp"
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
- Checked all RDLC layouts that contain Gamer Contacts.
- Removed extra vertical gap above the first Gamer Contact name where the label and names are split across textboxes.
- Removed duplicate leading line breaks from contact expressions where the label and names share one textbox.

### Scope
- All report layouts containing the visible `Gamer Contacts` label.

### Safety
- No PO number formatting, Expected-column removal, report dataset fields, line-grid formatting, decimal formatting, UoM columns, footer text, routing rules, sender logic, Delivery Log, SharePoint archive, or email behavior was changed.
- No package is published automatically.
- Publish production $NewProductionVersion first, then tests only after production is installed in the sandbox.

"@

if ($ChangeLogOriginal -match '(?m)^# Changelog\s*$') {
    $UpdatedChangeLog = [regex]::Replace($ChangeLogOriginal, '(?m)^# Changelog\s*$', "# Changelog`r`n`r`n$ChangeLogEntry", 1)
}
else {
    throw "The changelog header was not found. No files were changed."
}

$ProductionPackage = Join-Path -Path $ProductionRoot -ChildPath "Gamer Packaging_GPI Sales Document Email_$NewProductionVersion.app"
$TestPackage = Join-Path -Path $TestRoot -ChildPath "Gamer Packaging_GPI Sales Document Email Tests_$NewTestVersion.app"

try {
    $Results = @()
    foreach ($LayoutPath in @($TargetLayouts)) {
        $Results += Update-LayoutContactGap -LayoutPath $LayoutPath
    }
    $Results = @($Results)

    $ChangedCount = @($Results | Where-Object { $_.Changed }).Count
    $TotalChanges = 0
    foreach ($Result in $Results) { $TotalChanges += [int]$Result.Changes }

    if ($TotalChanges -eq 0) {
        Write-Host "Layouts containing Gamer Contacts were scanned, but no spacing changes were applied:" -ForegroundColor Yellow
        $Results | Format-Table -AutoSize
        throw "No Gamer Contacts spacing changes were applied. No files were changed."
    }

    Write-JsonNoBom -Value $ProductionApp -Path $ProductionAppJson
    Write-JsonNoBom -Value $TestApp -Path $TestAppJson
    Write-Utf8NoBom -Path $ChangeLog -Content $UpdatedChangeLog

    if (Test-Path -LiteralPath $ProductionPackage) { Remove-Item -LiteralPath $ProductionPackage -Force }
    if (Test-Path -LiteralPath $TestPackage) { Remove-Item -LiteralPath $TestPackage -Force }

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host " GPI all-doc Gamer Contacts gap cleanup 0.27.0.21" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Production version: $NewProductionVersion"
    Write-Host "Test version:       $NewTestVersion"
    Write-Host "Layouts scanned:    $($Results.Count)"
    Write-Host "Layouts changed:    $ChangedCount"
    Write-Host "Total XML changes:  $TotalChanges"
    Write-Host "Backup:             $BackupRoot"
    Write-Host ""

    $Results | Sort-Object Layout | Format-Table -AutoSize

    Write-Host ""
    Write-Host "Running production and test builds..." -ForegroundColor Cyan

    & $BuildScript

    if (-not (Test-Path -LiteralPath $ProductionPackage)) { throw "The expected production package was not created: $ProductionPackage" }
    if (-not (Test-Path -LiteralPath $TestPackage)) { throw "The expected test package was not created: $TestPackage" }
}
catch {
    Write-Host ""
    Write-Host "The all-doc Gamer Contacts gap cleanup build failed. Restoring modified files." -ForegroundColor Red
    foreach ($Path in $FilesToBackup) {
        $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
        $BackupPath = Join-Path -Path $BackupRoot -ChildPath $RelativePath
        if (Test-Path -LiteralPath $BackupPath) { Copy-Item -LiteralPath $BackupPath -Destination $Path -Force }
    }
    if (Test-Path -LiteralPath $ProductionPackage) { Remove-Item -LiteralPath $ProductionPackage -Force }
    if (Test-Path -LiteralPath $TestPackage) { Remove-Item -LiteralPath $TestPackage -Force }
    throw
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " GPI 0.27.0.21 build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Backup:             $BackupRoot"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish production $NewProductionVersion first, then tests only after production is installed in the sandbox." -ForegroundColor Yellow
