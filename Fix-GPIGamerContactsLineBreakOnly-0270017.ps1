[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedProductionVersion = "0.27.0.16"
$ExpectedTestVersion = "0.8.0.16"
$NewProductionVersion = "0.27.0.17"
$NewTestVersion = "0.8.0.17"

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

function Remove-GamerContactsLiteralFromExpression {
    param([Parameter(Mandatory)][string]$Expression)

    $Expr = $Expression.Trim()

    # Remove literal label from expressions such as:
    # ="Gamer Contacts: " & SomeContactExpression
    # =Trim("Gamer Contacts: " & SomeContactExpression)
    $Expr = [regex]::Replace($Expr, '^\s*=\s*"Gamer Contacts:\s*"\s*&\s*', '=', 1)
    $Expr = [regex]::Replace($Expr, '^\s*=\s*Trim\(\s*"Gamer Contacts:\s*"\s*&\s*', '=Trim(', 1)

    return $Expr
}

function Add-LeadingLineBreakToExpression {
    param([Parameter(Mandatory)][string]$Expression)

    $Expr = Remove-GamerContactsLiteralFromExpression -Expression $Expression

    if (-not $Expr.TrimStart().StartsWith("=")) {
        return $Expr
    }

    if ($Expr -match '^\s*=\s*vbCrLf\s*&') {
        return $Expr
    }

    $Body = $Expr.TrimStart().Substring(1).TrimStart()
    if ([string]::IsNullOrWhiteSpace($Body)) {
        return $Expr
    }

    return ("=vbCrLf & " + $Body)
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

function Update-GamerContactsParagraph {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlElement]$Paragraph,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Changed = $false
    $Values = @($Paragraph.SelectNodes(".//rdl:TextRun/rdl:Value", $NsMgr))

    foreach ($ValueNode in $Values) {
        $ValueText = [string]$ValueNode.InnerText

        if (-not $ValueText.TrimStart().StartsWith("=") -and ($ValueText -match 'Gamer Contacts')) {
            if ($ValueText -ne "Gamer Contacts:") {
                $ValueNode.InnerText = "Gamer Contacts:"
                $Changed = $true
            }
        }
    }

    $ContactValueNodes = @()
    foreach ($ValueNode in $Values) {
        $ValueText = [string]$ValueNode.InnerText
        if (Test-IsContactExpression -ExpressionText $ValueText) {
            $ContactValueNodes += $ValueNode
        }
    }

    if ($ContactValueNodes.Count -gt 0) {
        # Only add the line break before the first contact expression.
        # Leave subsequent expressions alone so existing vbCrLf logic between contacts is preserved.
        $FirstContactValue = $ContactValueNodes[0]
        $OldExpression = [string]$FirstContactValue.InnerText
        $NewExpression = Add-LeadingLineBreakToExpression -Expression $OldExpression

        if ($NewExpression -ne $OldExpression) {
            $FirstContactValue.InnerText = $NewExpression
            $Changed = $true
        }

        # Remove embedded labels from any other contact expression, but do not add more line breaks.
        for ($Index = 1; $Index -lt $ContactValueNodes.Count; $Index++) {
            $ValueNode = $ContactValueNodes[$Index]
            $Old = [string]$ValueNode.InnerText
            $New = Remove-GamerContactsLiteralFromExpression -Expression $Old
            if ($New -ne $Old) {
                $ValueNode.InnerText = $New
                $Changed = $true
            }
        }
    }

    Set-ParagraphLeftAlign -Doc $Doc -Paragraph $Paragraph -NsMgr $NsMgr

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

function Update-LayoutGamerContactsLineBreak {
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

    $NsMgr = New-Object System.Xml.XmlNamespaceManager($Doc.NameTable)
    [void]$NsMgr.AddNamespace("rdl", $Doc.DocumentElement.NamespaceURI)

    $ChangedParagraphs = 0
    $Paragraphs = @($Doc.SelectNodes("//rdl:Textbox[not(ancestor::rdl:Tablix)]/rdl:Paragraphs/rdl:Paragraph", $NsMgr))

    foreach ($ParagraphNode in $Paragraphs) {
        $Paragraph = [System.Xml.XmlElement]$ParagraphNode
        $ParagraphText = [string]$Paragraph.InnerText

        if ($ParagraphText -notmatch 'Gamer Contacts') {
            continue
        }

        if (Update-GamerContactsParagraph -Doc $Doc -Paragraph $Paragraph -NsMgr $NsMgr) {
            $ChangedParagraphs++
        }
    }

    if ($ChangedParagraphs -gt 0) {
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
        ParagraphsFixed = $ChangedParagraphs
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

# Only touch layouts that currently contain the label. No document fields or positions are changed.
$LayoutFiles = Get-ChildItem -LiteralPath $ReportLayoutFolder -File -Filter "*.rdl" |
    Where-Object { (Get-Content -LiteralPath $_.FullName -Raw) -match 'Gamer Contacts' } |
    Select-Object -ExpandProperty FullName

if ($LayoutFiles.Count -eq 0) {
    throw "No RDL layouts containing 'Gamer Contacts' were found. No files were changed."
}

$FilesToBackup = @(
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLog
) + $LayoutFiles

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path -Path $RepoRoot -ChildPath ".gpi-backups\gamer-contacts-linebreak-only-0270017-$Timestamp"
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
- Improved Gamer Contacts alignment without moving any fields.
- The existing Gamer Contacts paragraph now starts the first contact name on the next line after the label.
- Existing internal line-break logic between contact names is preserved.

### Safety
- No field positions, header/detail blocks, line-grid formatting, decimal formatting, UoM columns, footer text, dataset fields, routing rules, sender logic, Delivery Log, SharePoint archive, or email behavior was changed.
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
    foreach ($LayoutFile in $LayoutFiles) {
        $Results += Update-LayoutGamerContactsLineBreak -LayoutPath $LayoutFile
    }

    $ChangedCount = @($Results | Where-Object { $_.Changed }).Count
    $ParagraphCount = 0
    foreach ($Result in $Results) {
        $ParagraphCount += [int]$Result.ParagraphsFixed
    }

    if ($ParagraphCount -eq 0) {
        throw "No Gamer Contacts paragraphs were changed. No files were changed."
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
    Write-Host " GPI Gamer Contacts line-break-only pass 0.27.0.17" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Production version: $NewProductionVersion"
    Write-Host "Test version:       $NewTestVersion"
    Write-Host "Layouts scanned:    $($Results.Count)"
    Write-Host "Layouts changed:    $ChangedCount"
    Write-Host "Paragraphs fixed:   $ParagraphCount"
    Write-Host "Backup:             $BackupRoot"
    Write-Host ""

    foreach ($Result in $Results) {
        if ($Result.ParagraphsFixed -gt 0) {
            Write-Host ("{0}: Gamer Contacts paragraphs fixed={1}" -f $Result.Layout, $Result.ParagraphsFixed)
        }
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
    Write-Host "The Gamer Contacts line-break-only build failed. Restoring modified files." -ForegroundColor Red

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
Write-Host " GPI 0.27.0.17 build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Backup:             $BackupRoot"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish production $NewProductionVersion first, then tests only after production is installed in the sandbox." -ForegroundColor Yellow
