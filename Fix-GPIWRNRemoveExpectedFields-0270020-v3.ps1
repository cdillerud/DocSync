[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedProductionVersion = "0.27.0.19"
$ExpectedTestVersion = "0.8.0.19"
$NewProductionVersion = "0.27.0.20"
$NewTestVersion = "0.8.0.20"

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

function Test-IsWarehouseReceivingLayoutText {
    param([Parameter(Mandatory)][string]$Text)

    return (
        $Text -match '(?i)WAREHOUSE\s+RECEIVING\s+NOTICE' -or
        $Text -match '(?i)Warehouse\s+Receiving\s+Notice' -or
        $Text -match '(?i)WarehouseReceivingNotice'
    )
}

function Test-IsExpectedXml {
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return $false
    }

    return (
        $Text -match '(?i)\bExpected\b' -or
        $Text -match '(?i)Expected\s*Receipt' -or
        $Text -match '(?i)ExpectedReceipt' -or
        $Text -match '(?i)Expected_Receipt'
    )
}

function Get-NodeNameSafe {
    param([System.Xml.XmlElement]$Element)

    if ($null -eq $Element) {
        return ""
    }

    if ($Element.HasAttribute("Name")) {
        return [string]$Element.GetAttribute("Name")
    }

    return ""
}

function Remove-NodeAtIndex {
    param(
        [Parameter(Mandatory)][System.Xml.XmlNodeList]$Nodes,
        [Parameter(Mandatory)][int]$Index
    )

    if ($Index -lt 0 -or $Index -ge $Nodes.Count) {
        return $false
    }

    $Node = $Nodes.Item($Index)
    if ($null -eq $Node -or $null -eq $Node.ParentNode) {
        return $false
    }

    [void]$Node.ParentNode.RemoveChild($Node)
    return $true
}

function Remove-ExpectedTablixColumns {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $RemovedColumns = 0
    $Tablixes = @($Doc.SelectNodes("//rdl:Tablix", $NsMgr))

    foreach ($TablixNode in $Tablixes) {
        $Tablix = [System.Xml.XmlElement]$TablixNode

        $Columns = @($Tablix.SelectNodes("rdl:TablixBody/rdl:TablixColumns/rdl:TablixColumn", $NsMgr))
        if ($Columns.Count -eq 0) {
            continue
        }

        $ColumnIndexesToRemove = New-Object System.Collections.Generic.HashSet[int]
        $Rows = @($Tablix.SelectNodes("rdl:TablixBody/rdl:TablixRows/rdl:TablixRow", $NsMgr))

        foreach ($RowNode in $Rows) {
            $Row = [System.Xml.XmlElement]$RowNode
            $Cells = @($Row.SelectNodes("rdl:TablixCells/rdl:TablixCell", $NsMgr))

            for ($Index = 0; $Index -lt $Cells.Count; $Index++) {
                $Cell = [System.Xml.XmlElement]$Cells[$Index]
                $CellXml = $Cell.OuterXml

                if (Test-IsExpectedXml -Text $CellXml) {
                    [void]$ColumnIndexesToRemove.Add($Index)
                }
            }
        }

        if ($ColumnIndexesToRemove.Count -eq 0) {
            continue
        }

        $IndexesDescending = @($ColumnIndexesToRemove | Sort-Object -Descending)

        foreach ($Index in $IndexesDescending) {
            $BodyColumns = $Tablix.SelectNodes("rdl:TablixBody/rdl:TablixColumns/rdl:TablixColumn", $NsMgr)
            if (Remove-NodeAtIndex -Nodes $BodyColumns -Index $Index) {
                $RemovedColumns++
            }

            foreach ($RowNode in @($Tablix.SelectNodes("rdl:TablixBody/rdl:TablixRows/rdl:TablixRow", $NsMgr))) {
                $Row = [System.Xml.XmlElement]$RowNode
                $Cells = $Row.SelectNodes("rdl:TablixCells/rdl:TablixCell", $NsMgr)
                [void](Remove-NodeAtIndex -Nodes $Cells -Index $Index)
            }

            $ColumnMembers = $Tablix.SelectNodes("rdl:TablixColumnHierarchy/rdl:TablixMembers/rdl:TablixMember", $NsMgr)
            [void](Remove-NodeAtIndex -Nodes $ColumnMembers -Index $Index)
        }
    }

    return $RemovedColumns
}

function Set-TextboxFirstValue {
    param(
        [Parameter(Mandatory)][System.Xml.XmlElement]$Textbox,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr,
        [Parameter(Mandatory)][string]$Value
    )

    $ValueNode = $Textbox.SelectSingleNode(".//rdl:TextRun/rdl:Value", $NsMgr)

    if ($null -eq $ValueNode) {
        return 0
    }

    if ([string]$ValueNode.InnerText -ne $Value) {
        $ValueNode.InnerText = $Value
        return 1
    }

    return 0
}

function Remove-ExpectedFromExpression {
    param([Parameter(Mandatory)][string]$Expression)

    $Expr = $Expression

    if ($Expr -notmatch '(?i)Expected') {
        return $Expr
    }

    # Remove a trailing expected line:
    # & vbCrLf & "Expected Receipt Date: " & Fields!...
    $Expr = [regex]::Replace(
        $Expr,
        '(?i)\s*&\s*vbCrLf\s*&\s*"[^"]*Expected[^"]*"\s*&\s*[^&\r\n\)]*',
        '',
        1
    )

    # Remove a leading/middle expected line followed by a line break:
    # "Expected Receipt Date: " & Fields!... & vbCrLf &
    $Expr = [regex]::Replace(
        $Expr,
        '(?i)"[^"]*Expected[^"]*"\s*&\s*[^&\r\n\)]*\s*&\s*vbCrLf\s*&\s*',
        '',
        1
    )

    # Remove a simple literal label only.
    $Expr = [regex]::Replace(
        $Expr,
        '(?i)"[^"]*Expected[^"]*"\s*&?',
        '',
        1
    )

    return $Expr
}

function Remove-ExpectedFromNonTablixTextboxes {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Changes = 0
    $Textboxes = @($Doc.SelectNodes("//rdl:Textbox[not(ancestor::rdl:Tablix)]", $NsMgr))

    foreach ($TextboxNode in $Textboxes) {
        $Textbox = [System.Xml.XmlElement]$TextboxNode
        $TextboxName = Get-NodeNameSafe -Element $Textbox
        $TextboxXml = $Textbox.OuterXml

        if (-not (Test-IsExpectedXml -Text ($TextboxName + " " + $TextboxXml))) {
            continue
        }

        $ParagraphsElement = $Textbox.SelectSingleNode("rdl:Paragraphs", $NsMgr)
        if ($null -eq $ParagraphsElement) {
            $Changes += Set-TextboxFirstValue -Textbox $Textbox -NsMgr $NsMgr -Value '=""'
            continue
        }

        $Paragraphs = @($ParagraphsElement.SelectNodes("rdl:Paragraph", $NsMgr))

        # If this textbox is only expected content, blank it.
        $HasNonExpectedParagraph = $false
        foreach ($Paragraph in $Paragraphs) {
            if (-not (Test-IsExpectedXml -Text $Paragraph.OuterXml)) {
                $HasNonExpectedParagraph = $true
            }
        }

        if (-not $HasNonExpectedParagraph) {
            $Changes += Set-TextboxFirstValue -Textbox $Textbox -NsMgr $NsMgr -Value '=""'
            continue
        }

        # If the expected content is isolated to one paragraph, remove that paragraph.
        foreach ($Paragraph in @($ParagraphsElement.SelectNodes("rdl:Paragraph", $NsMgr))) {
            if (Test-IsExpectedXml -Text $Paragraph.OuterXml) {
                [void]$ParagraphsElement.RemoveChild($Paragraph)
                $Changes++
            }
        }

        # Also clean up any text runs or expressions left behind in mixed paragraphs.
        $Values = @($Textbox.SelectNodes(".//rdl:TextRun/rdl:Value", $NsMgr))
        for ($Index = 0; $Index -lt $Values.Count; $Index++) {
            $ValueNode = $Values[$Index]
            $ValueText = [string]$ValueNode.InnerText

            if (-not (Test-IsExpectedXml -Text $ValueText)) {
                continue
            }

            if ($ValueText.TrimStart().StartsWith("=")) {
                $NewExpression = Remove-ExpectedFromExpression -Expression $ValueText

                if ($NewExpression -eq $ValueText -or $NewExpression -match '(?i)Expected') {
                    $NewExpression = '=""'
                }

                if ([string]$ValueNode.InnerText -ne $NewExpression) {
                    $ValueNode.InnerText = $NewExpression
                    $Changes++
                }
            }
            else {
                $ValueNode.InnerText = ""
                $Changes++

                # If the following run is a plain expression value tied to the expected label, blank it too.
                if (($Index + 1) -lt $Values.Count) {
                    $NextValueNode = $Values[$Index + 1]
                    $NextText = [string]$NextValueNode.InnerText

                    if ($NextText.TrimStart().StartsWith("=") -and -not (Test-IsExpectedXml -Text $NextText)) {
                        $NextValueNode.InnerText = '=""'
                        $Changes++
                    }
                }
            }
        }
    }

    return $Changes
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

function Update-WarehouseReceivingLayout {
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

    $RemovedColumns = Remove-ExpectedTablixColumns -Doc $Doc -NsMgr $NsMgr
    $NonTablixChanges = Remove-ExpectedFromNonTablixTextboxes -Doc $Doc -NsMgr $NsMgr

    $TotalChanges = $RemovedColumns + $NonTablixChanges

    if ($TotalChanges -eq 0) {
        return [pscustomobject]@{
            Layout = $LayoutName
            RemovedColumns = 0
            NonTablixChanges = 0
            Changed = $false
            HadExpectedText = ($Original -match '(?i)Expected')
        }
    }

    Save-XmlDocumentUtf8NoBom -Doc $Doc -Path $LayoutPath

    try {
        [xml]$XmlCheck = Get-Content -LiteralPath $LayoutPath -Raw
    }
    catch {
        throw "The updated RDL XML for $LayoutName is not valid XML after save: $($_.Exception.Message)"
    }

    $Updated = Get-Content -LiteralPath $LayoutPath -Raw

    return [pscustomobject]@{
        Layout = $LayoutName
        RemovedColumns = $RemovedColumns
        NonTablixChanges = $NonTablixChanges
        Changed = ($Updated -ne $Original)
        HadExpectedText = ($Original -match '(?i)Expected')
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

$CandidateLayouts = @(
    Get-ChildItem -LiteralPath $ReportLayoutFolder -File -Filter "*.rdl" |
        Where-Object {
            ($_.Name -match '(?i)Warehouse.*Receiving') -or
            (Test-IsWarehouseReceivingLayoutText -Text (Get-Content -LiteralPath $_.FullName -Raw))
        } |
        Select-Object -ExpandProperty FullName
)

if ($CandidateLayouts.Count -eq 0) {
    throw "No Warehouse Receiving Notice RDL layout candidates were found under $ReportLayoutFolder. No files were changed."
}

$FilesToBackup = @(
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLog
) + @($CandidateLayouts)

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path -Path $RepoRoot -ChildPath ".gpi-backups\wrn-remove-expected-fields-0270020-v3-$Timestamp"
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
- Warehouse Receiving Notice no longer displays Expected Receipt fields.
- Warehouse Receiving Notice item grid no longer displays the Expected column.
- This change is limited to Warehouse Receiving Notice layouts.

### Safety
- No Purchase Order layouts were changed.
- No report dataset fields, routing rules, sender logic, Delivery Log, SharePoint archive, or email behavior was changed.
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
    foreach ($LayoutPath in @($CandidateLayouts)) {
        $Results += Update-WarehouseReceivingLayout -LayoutPath $LayoutPath
    }
    $Results = @($Results)

    $ChangedCount = @($Results | Where-Object { $_.Changed }).Count
    $HadExpectedCount = @($Results | Where-Object { $_.HadExpectedText }).Count
    $RemovedColumnsTotal = 0
    $NonTablixChangesTotal = 0

    foreach ($Result in $Results) {
        $RemovedColumnsTotal += [int]$Result.RemovedColumns
        $NonTablixChangesTotal += [int]$Result.NonTablixChanges
    }

    if ($ChangedCount -eq 0) {
        Write-Host ""
        Write-Host "Warehouse Receiving Notice layout candidates found, but none contained removable Expected fields:" -ForegroundColor Yellow
        foreach ($Result in @($Results)) {
            Write-Host ("{0}: HadExpectedText={1}" -f $Result.Layout, $Result.HadExpectedText)
        }

        Write-Host ""
        Write-Host "Candidate layout files checked:" -ForegroundColor Yellow
        foreach ($LayoutPath in @($CandidateLayouts)) {
            $Raw = Get-Content -LiteralPath $LayoutPath -Raw
            Write-Host ("{0} | raw XML contains Expected={1}" -f $LayoutPath, [bool]($Raw -match '(?i)Expected'))
        }

        throw "No removable Expected / Expected Receipt fields were found. No files were changed."
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
    Write-Host " GPI Warehouse Receiving Notice remove Expected fields 0.27.0.20 v3" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Production version:       $NewProductionVersion"
    Write-Host "Test version:             $NewTestVersion"
    Write-Host "Layout candidates:        $(@($Results).Count)"
    Write-Host "Layouts changed:          $ChangedCount"
    Write-Host "Layouts had Expected text:$HadExpectedCount"
    Write-Host "Removed tablix columns:   $RemovedColumnsTotal"
    Write-Host "Non-tablix changes:       $NonTablixChangesTotal"
    Write-Host "Backup:                   $BackupRoot"
    Write-Host ""

    foreach ($Result in $Results) {
        Write-Host ("{0}: Changed={1}, RemovedColumns={2}, NonTablixChanges={3}, HadExpectedText={4}" -f $Result.Layout, $Result.Changed, $Result.RemovedColumns, $Result.NonTablixChanges, $Result.HadExpectedText)
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
    Write-Host "The Warehouse Receiving Notice Expected-field cleanup build failed. Restoring modified files." -ForegroundColor Red

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
Write-Host " GPI 0.27.0.20 build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Backup:             $BackupRoot"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish production $NewProductionVersion first, then tests only after production is installed in the sandbox." -ForegroundColor Yellow
