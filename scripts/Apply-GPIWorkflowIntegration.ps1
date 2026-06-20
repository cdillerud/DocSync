[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Read-Utf8File {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Required file was not found: $Path"
    }

    return [System.IO.File]::ReadAllText($Path)
}

function Write-Utf8File {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )

    $Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $Content, $Utf8NoBom)
}

function Replace-ExactOnce {
    param(
        [Parameter(Mandatory)][string]$Content,
        [Parameter(Mandatory)][string]$OldText,
        [Parameter(Mandatory)][string]$NewText,
        [Parameter(Mandatory)][string]$Description
    )

    $First = $Content.IndexOf($OldText, [System.StringComparison]::Ordinal)
    if ($First -lt 0) {
        throw "Could not find the expected text for: $Description"
    }

    $Second = $Content.IndexOf($OldText, $First + $OldText.Length, [System.StringComparison]::Ordinal)
    if ($Second -ge 0) {
        throw "Found the expected text more than once for: $Description"
    }

    return $Content.Substring(0, $First) + $NewText + $Content.Substring($First + $OldText.Length)
}

function Replace-RegexOnce {
    param(
        [Parameter(Mandatory)][string]$Content,
        [Parameter(Mandatory)][string]$Pattern,
        [Parameter(Mandatory)][string]$Replacement,
        [Parameter(Mandatory)][string]$Description
    )

    $Regex = [regex]::new($Pattern, [System.Text.RegularExpressions.RegexOptions]::Singleline)
    $Matches = $Regex.Matches($Content)
    if ($Matches.Count -ne 1) {
        throw "Expected exactly one match for '$Description' but found $($Matches.Count)."
    }

    return $Regex.Replace($Content, $Replacement, 1)
}

function Update-JsonVersion {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Version,
        [string]$DependencyVersion
    )

    $Json = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    $Json.version = $Version

    if ($DependencyVersion) {
        $Dependency = $Json.dependencies | Where-Object {
            $_.id -eq 'b6eb6cc8-d984-4ab0-bb15-d3569db41171'
        }
        if (-not $Dependency) {
            throw "The production extension dependency was not found in $Path"
        }
        $Dependency.version = $DependencyVersion
    }

    Write-Utf8File -Path $Path -Content ($Json | ConvertTo-Json -Depth 30)
}

$ProductionRoot = Join-Path $RepoRoot 'bc-extension\zetadocs-replacement'
$TestRoot = Join-Path $RepoRoot 'bc-extension\zetadocs-replacement-tests'
$CodeunitRoot = Join-Path $ProductionRoot 'src\codeunit'

$SalesReturnPath = Join-Path $CodeunitRoot 'GPISalesReturnEmail.Codeunit.al'
$PurchaseReturnPath = Join-Path $CodeunitRoot 'GPIPurchaseReturnEmail.Codeunit.al'
$TransferPath = Join-Path $CodeunitRoot 'GPITransferEmail.Codeunit.al'
$OpenOrderPath = Join-Path $CodeunitRoot 'GPICustomerOpenOrderEmail.Codeunit.al'

$NewLine = "`r`n"

# -----------------------------------------------------------------------------
# Sales Return workflow
# -----------------------------------------------------------------------------
$Content = Read-Utf8File $SalesReturnPath

$Content = Replace-ExactOnce $Content `
    ('        LineVisibilityMgt: Codeunit "GPI Line Visibility Mgt.";' + $NewLine + '        TempBlob: Codeunit "Temp Blob";') `
    ('        LineVisibilityMgt: Codeunit "GPI Line Visibility Mgt.";' + $NewLine + '        DeliveryTransportMgt: Codeunit "GPI Delivery Transport Mgt.";' + $NewLine + '        TempBlob: Codeunit "Temp Blob";') `
    'Sales Return transport variable'

$Content = Replace-RegexOnce $Content `
    '        Commit\(\);\r?\n        if not TryOpenEmailEditor\(EmailMessage, SenderEmailAccount, EmailAction\) then begin\r?\n            EmailErrorText := GetLastErrorText\(\);\r?\n            if EmailErrorText = '''' then\r?\n                EmailErrorText := ''The Business Central email editor returned an unexpected error\. '';?' `
    '__NEVER_MATCH__' `
    'placeholder'
