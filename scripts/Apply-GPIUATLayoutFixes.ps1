[CmdletBinding()]
param(
    [string]$ProjectRoot = (Join-Path $PSScriptRoot '..\bc-extension\zetadocs-replacement')
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$LayoutRoot = Join-Path $ProjectRoot 'src\reportlayout'
$BackupRoot = Join-Path $ProjectRoot ('.uat-layout-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$Changed = [System.Collections.Generic.List[string]]::new()

function Load-Rdl {
    param([Parameter(Mandatory)][string]$Path)

    $Xml = [System.Xml.XmlDocument]::new()
    $Xml.PreserveWhitespace = $true
    $Xml.Load($Path)

    $Ns = [System.Xml.XmlNamespaceManager]::new($Xml.NameTable)
    $Ns.AddNamespace('r', 'http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition')

    return @($Xml, $Ns)
}

function Save-Rdl {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Xml
    )

    if (-not (Test-Path $BackupRoot)) {
        New-Item -ItemType Directory -Path $BackupRoot | Out-Null
    }

    Copy-Item -LiteralPath $Path `
        -Destination (Join-Path $BackupRoot ([System.IO.Path]::GetFileName($Path))) `
        -Force

    $Settings = [System.Xml.XmlWriterSettings]::new()
    $Settings.Encoding = [System.Text.UTF8Encoding]::new($false)
    $Settings.Indent = $false

    $Writer = [System.Xml.XmlWriter]::Create($Path, $Settings)
    try {
        $Xml.Save($Writer)
    }
    finally {
        $Writer.Dispose()
    }

    $Changed.Add($Path)
}

function Set-NodeText {
    param(
        [Parameter(Mandatory)]$Node,
        [Parameter(Mandatory)][string]$XPath,
        [Parameter(Mandatory)][string]$Value,
        [Parameter(Mandatory)]$Ns
    )

    $Target = $Node.SelectSingleNode($XPath, $Ns)
    if ($null -eq $Target) {
        throw "Missing RDLC node: $XPath"
    }

    if ($Target.InnerText -eq $Value) {
        return $false
    }

    $Target.InnerText = $Value
    return $true
}

function Ensure-StyleValue {
    param(
        [Parameter(Mandatory)]$Textbox,
        [Parameter(Mandatory)][string]$ElementName,
        [Parameter(Mandatory)][string]$Value,
        [Parameter(Mandatory)]$Ns,
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Xml
    )

    $Style = $Textbox.SelectSingleNode('r:Style', $Ns)
    if ($null -eq $Style) {
        throw "Textbox $($Textbox.GetAttribute('Name')) has no outer Style node."
    }

    $Node = $Style.SelectSingleNode("r:$ElementName", $Ns)
    if ($null -eq $Node) {
        $Node = $Xml.CreateElement($ElementName, $Ns.LookupNamespace('r'))
        $Style.AppendChild($Node) | Out-Null
    }

    if ($Node.InnerText -eq $Value) {
        return $false
    }

    $Node.InnerText = $Value
    return $true
}

function Center-ContactFooter {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Xml,
        [Parameter(Mandatory)]$Ns
    )

    $Footer = $Xml.SelectSingleNode('//r:Textbox[@Name="ContactFooter"]', $Ns)
    if ($null -eq $Footer) {
        throw 'ContactFooter textbox was not found.'
    }

    $ChangedHere = Ensure-StyleValue $Footer 'TextAlign' 'Center' $Ns $Xml
    $ChangedHere = (Ensure-StyleValue $Footer 'VerticalAlign' 'Middle' $Ns $Xml) -or $ChangedHere
    return $ChangedHere
}

Write-Host '============================================================'
Write-Host ' GPI UAT RDLC Layout Fixes'
Write-Host '============================================================'
Write-Host "Project root: $ProjectRoot"
Write-Host ''

# Customer Open Order Status:
# - Give Outstanding more width.
# - Reduce the header font slightly.
# - Center the Outstanding header.
# - Center the bottom contact text.
$Path = Join-Path $LayoutRoot 'GPICustomerOpenOrderStatusBranded.rdl'
$Loaded = Load-Rdl -Path $Path
$Xml = $Loaded[0]
$Ns = $Loaded[1]
$FileChanged = $false

$Columns = $Xml.SelectNodes(
    '//r:Tablix[@Name="OpenOrderLines"]/r:TablixBody/r:TablixColumns/r:TablixColumn/r:Width',
    $Ns
)

if ($Columns.Count -ne 11) {
    throw "Expected 11 Open Order columns but found $($Columns.Count)."
}

if ($Columns[4].InnerText -ne '2.1in') {
    $Columns[4].InnerText = '2.1in'
    $FileChanged = $true
}

if ($Columns[5].InnerText -ne '0.9in') {
    $Columns[5].InnerText = '0.9in'
    $FileChanged = $true
}

$HQty = $Xml.SelectSingleNode('//r:Textbox[@Name="HQty"]', $Ns)
if ($null -eq $HQty) {
    throw 'Open Order HQty textbox was not found.'
}

$CanGrow = $HQty.SelectSingleNode('r:CanGrow', $Ns)
if ($null -eq $CanGrow) {
    $CanGrow = $Xml.CreateElement('CanGrow', $Ns.LookupNamespace('r'))
    $CanGrow.InnerText = 'false'
    $Paragraphs = $HQty.SelectSingleNode('r:Paragraphs', $Ns)
    $HQty.InsertBefore($CanGrow, $Paragraphs) | Out-Null
    $FileChanged = $true
}
elseif ($CanGrow.InnerText -ne 'false') {
    $CanGrow.InnerText = 'false'
    $FileChanged = $true
}

$RunStyle = $HQty.SelectSingleNode(
    'r:Paragraphs/r:Paragraph/r:TextRuns/r:TextRun/r:Style',
    $Ns
)

if ($null -eq $RunStyle) {
    throw 'Open Order HQty text-run Style was not found.'
}

$FontSize = $RunStyle.SelectSingleNode('r:FontSize', $Ns)
if ($null -eq $FontSize) {
    $FontSize = $Xml.CreateElement('FontSize', $Ns.LookupNamespace('r'))
    $RunStyle.AppendChild($FontSize) | Out-Null
}

if ($FontSize.InnerText -ne '7pt') {
    $FontSize.InnerText = '7pt'
    $FileChanged = $true
}

$FileChanged = (Ensure-StyleValue $HQty 'TextAlign' 'Center' $Ns $Xml) -or $FileChanged
$FileChanged = (Ensure-StyleValue $HQty 'PaddingLeft' '1pt' $Ns $Xml) -or $FileChanged
$FileChanged = (Ensure-StyleValue $HQty 'PaddingRight' '1pt' $Ns $Xml) -or $FileChanged
$FileChanged = (Center-ContactFooter $Xml $Ns) -or $FileChanged

if ($FileChanged) {
    Save-Rdl -Path $Path -Xml $Xml
    Write-Host '[UPDATED] GPICustomerOpenOrderStatusBranded.rdl'
}
else {
    Write-Host '[SKIP] GPICustomerOpenOrderStatusBranded.rdl already contains the fixes.'
}

# Keep the Sales Return Warehouse Notification title on one line.
$Path = Join-Path $LayoutRoot 'GPISalesReturnWarehouseNotificationBranded.rdl'
$Loaded = Load-Rdl -Path $Path
$Xml = $Loaded[0]
$Ns = $Loaded[1]
$FileChanged = $false

$Title = $Xml.SelectSingleNode('//r:Textbox[@Name="DocumentTitle"]', $Ns)
if ($null -eq $Title) {
    throw 'Sales Return Warehouse Notification title was not found.'
}

$FileChanged = (
    Set-NodeText $Title `
        'r:Paragraphs/r:Paragraph/r:TextRuns/r:TextRun/r:Style/r:FontSize' `
        '12pt' `
        $Ns
) -or $FileChanged

$FileChanged = (Set-NodeText $Title 'r:Left' '2.85in' $Ns) -or $FileChanged
$FileChanged = (Set-NodeText $Title 'r:Height' '0.35in' $Ns) -or $FileChanged
$FileChanged = (Set-NodeText $Title 'r:Width' '4.65in' $Ns) -or $FileChanged

if ($FileChanged) {
    Save-Rdl -Path $Path -Xml $Xml
    Write-Host '[UPDATED] GPISalesReturnWarehouseNotificationBranded.rdl'
}
else {
    Write-Host '[SKIP] GPISalesReturnWarehouseNotificationBranded.rdl already contains the fixes.'
}

# Center the existing bottom contact text on the two portrait reports that have it.
foreach ($FileName in @(
    'GPIPurchaseReturnOrderBranded.rdl',
    'GPISalesReturnAuthorizationBranded.rdl'
)) {
    $Path = Join-Path $LayoutRoot $FileName
    $Loaded = Load-Rdl -Path $Path
    $Xml = $Loaded[0]
    $Ns = $Loaded[1]

    if (Center-ContactFooter $Xml $Ns) {
        Save-Rdl -Path $Path -Xml $Xml
        Write-Host "[UPDATED] $FileName"
    }
    else {
        Write-Host "[SKIP] $FileName already contains the footer fix."
    }
}

Write-Host ''
Write-Host "Changed RDLC files: $($Changed.Count)"
if ($Changed.Count -gt 0) {
    Write-Host "Backup copies: $BackupRoot"
}
Write-Host 'No local files were discarded or committed.'
