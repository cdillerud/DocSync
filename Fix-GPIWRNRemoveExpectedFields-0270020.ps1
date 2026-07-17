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
$WarehouseReceivingLayout = Join-Path -Path $ProductionRoot -ChildPath "src\reportlayout\GPIWarehouseReceivingNoticeBranded.rdl"

foreach ($RequiredPath in @($ProductionAppJson, $TestAppJson, $ChangeLog, $BuildScript, $WarehouseReceivingLayout)) {
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

function Test-IsExpectedText {
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return $false
    }

    return ($Text -match '(?i)\bExpected\b' -or $Text -match '(?i)Expected\s+Receipt')
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
                $CellText = [string]$Cell.InnerText

                if (Test-IsExpectedText -Text $CellText) {
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

function Remove-ExpectedNonTablixParagraphs {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $RemovedParagraphs = 0
    $BlankedRuns = 0

    $Textboxes = @($Doc.SelectNodes("//rdl:Textbox[not(ancestor::rdl:Tablix)]", $NsMgr))

    foreach ($TextboxNode in $Textboxes) {
        $Textbox = [System.Xml.XmlElement]$TextboxNode
        $TextboxText = [string]$Textbox.InnerText

        if (-not (Test-IsExpectedText -Text $TextboxText)) {
            continue
        }

        $ParagraphsElement = $Textbox.SelectSingleNode("rdl:Paragraphs", $NsMgr)
        if ($null -eq $ParagraphsElement) {
            continue
        }

        $Paragraphs = @($ParagraphsElement.SelectNodes("rdl:Paragraph", $NsMgr))
        $ParagraphsToRemove = @()

        foreach ($Paragraph in $Paragraphs) {
            if (Test-IsExpectedText -Text ([string]$Paragraph.InnerText)) {
                $ParagraphsToRemove += $Paragraph
            }
        }

        # If the textbox has other paragraphs, remove only the Expected paragraph.
        # If the textbox is only Expected content, blank its first value to avoid leaving text visible.
        if ($ParagraphsToRemove.Count -gt 0 -and $ParagraphsToRemove.Count -lt $Paragraphs.Count) {
            foreach ($Paragraph in $ParagraphsToRemove) {
                [void]$ParagraphsElement.RemoveChild($Paragraph)
                $RemovedParagraphs++
            }
        }
        elseif ($ParagraphsToRemove.Count -eq $Paragraphs.Count) {
            $FirstValue = $Textbox.SelectSingleNode(".//rdl:TextRun/rdl:Value", $NsMgr)
            if ($null -ne $FirstValue) {
                $FirstValue.InnerText = '=""'
                $BlankedRuns++
            }
        }
    }

    return [pscustomobject]@{
        RemovedParagraphs = $RemovedParagraphs
        BlankedRuns = $BlankedRuns
    }
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

    $Original = Get-Content -LiteralPath $LayoutPath -Raw

    $Doc = New-Object System.Xml.XmlDocument
    $Doc.PreserveWhitespace = $false

    try {
        $Doc.Load($LayoutPath)
    }
    catch {
        throw "The original RDL XML is not valid XML before changes: $($_.Exception.Message)"
    }

    $NsMgr = Get-RdlNsMgr -Doc $Doc

    $RemovedColumns = Remove-ExpectedTablixColumns -Doc $Doc -NsMgr $NsMgr
    $NonTablixResult = Remove-ExpectedNonTablixParagraphs -Doc $Doc -NsMgr $NsMgr

    $TotalChanges = $RemovedColumns + [int]$NonTablixResult.RemovedParagraphs + [int]$NonTablixResult.BlankedRuns

    if ($TotalChanges -eq 0) {
        throw "No Expected or Expected Receipt fields were found to remove in the Warehouse Receiving Notice layout."
    }

    Save-XmlDocumentUtf8NoBom -Doc $Doc -Path $LayoutPath

    try {
        [xml]$XmlCheck = Get-Content -LiteralPath $LayoutPath -Raw
    }
    catch {
        throw "The updated RDL XML is not valid XML after save: $($_.Exception.Message)"
    }

    $Updated = Get-Content -LiteralPath $LayoutPath -Raw

    if ($Updated -notmatch 'Warehouse Receiving Notice' -and $Updated -notmatch 'WAREHOUSE') {
        throw "Warehouse Receiving Notice layout validation failed after update."
    }

    return [pscustomobject]@{
        RemovedColumns = $RemovedColumns
        RemovedParagraphs = [int]$NonTablixResult.RemovedParagraphs
        BlankedRuns = [int]$NonTablixResult.BlankedRuns
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
    $ChangeLog,
    $WarehouseReceivingLayout
)

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path -Path $RepoRoot -ChildPath ".gpi-backups\wrn-remove-expected-fields-0270020-$Timestamp"
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
- This change is limited to the Warehouse Receiving Notice layout.

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
    $Result = Update-WarehouseReceivingLayout -LayoutPath $WarehouseReceivingLayout

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
    Write-Host " GPI Warehouse Receiving Notice remove Expected fields 0.27.0.20" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Production version:      $NewProductionVersion"
    Write-Host "Test version:            $NewTestVersion"
    Write-Host "Removed tablix columns:  $($Result.RemovedColumns)"
    Write-Host "Removed paragraphs:      $($Result.RemovedParagraphs)"
    Write-Host "Blanked text runs:       $($Result.BlankedRuns)"
    Write-Host "Backup:                  $BackupRoot"
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
