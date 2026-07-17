[CmdletBinding()]
param(
    [Parameter()]
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProdRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests"
$ProdSrc = Join-Path $ProdRoot "src"
$RecordDocsFile = Join-Path $ProdSrc "pageextension\GPISalesOrderRecordDocuments.PageExt.al"
$ProdAppJson = Join-Path $ProdRoot "app.json"
$TestAppJson = Join-Path $TestRoot "app.json"
$ChangeLog = Join-Path $ProdRoot "CHANGELOG.md"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $RepoRoot ".sales-order-factbox-backup-$Stamp"

foreach ($RequiredPath in @(
    $ProdSrc,
    $RecordDocsFile,
    $ProdAppJson,
    $TestAppJson,
    $ChangeLog
)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required path was not found: $RequiredPath"
    }
}

New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

function Copy-ToBackup {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
    $BackupPath = Join-Path $BackupRoot $RelativePath
    $BackupDirectory = Split-Path $BackupPath -Parent

    New-Item -ItemType Directory -Path $BackupDirectory -Force | Out-Null
    Copy-Item -LiteralPath $Path -Destination $BackupPath -Force
}

function Get-MatchingBraceIndex {
    param(
        [Parameter(Mandatory)]
        [string]$Text,

        [Parameter(Mandatory)]
        [int]$OpenBraceIndex
    )

    $Depth = 0
    $InString = $false
    $InLineComment = $false
    $InBlockComment = $false

    for ($Index = $OpenBraceIndex; $Index -lt $Text.Length; $Index++) {
        $Char = $Text[$Index]
        $NextChar = if (($Index + 1) -lt $Text.Length) {
            $Text[$Index + 1]
        }
        else {
            [char]0
        }

        if ($InLineComment) {
            if ($Char -eq "`n") {
                $InLineComment = $false
            }
            continue
        }

        if ($InBlockComment) {
            if ($Char -eq '*' -and $NextChar -eq '/') {
                $InBlockComment = $false
                $Index++
            }
            continue
        }

        if (-not $InString -and $Char -eq '/' -and $NextChar -eq '/') {
            $InLineComment = $true
            $Index++
            continue
        }

        if (-not $InString -and $Char -eq '/' -and $NextChar -eq '*') {
            $InBlockComment = $true
            $Index++
            continue
        }

        if ($Char -eq "'") {
            if ($InString -and $NextChar -eq "'") {
                $Index++
                continue
            }

            $InString = -not $InString
            continue
        }

        if ($InString) {
            continue
        }

        if ($Char -eq '{') {
            $Depth++
        }
        elseif ($Char -eq '}') {
            $Depth--
            if ($Depth -eq 0) {
                return $Index
            }
        }
    }

    throw "A matching closing brace could not be found."
}

function Get-NextFourPartVersion {
    param(
        [Parameter(Mandatory)]
        [string]$Version
    )

    $Parts = $Version -split '\.'
    if ($Parts.Count -ne 4) {
        throw "Version is not a valid four-part version: $Version"
    }

    $Parts[3] = ([int]$Parts[3] + 1).ToString()
    return ($Parts -join '.')
}

# Identify page objects whose names or captions describe a Documents Sent FactBox.
$DocumentsSentPageNames = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::OrdinalIgnoreCase
)

foreach ($PageFile in (
    Get-ChildItem -LiteralPath $ProdSrc -File -Filter "*.al" -Recurse |
        Sort-Object FullName
)) {
    $Text = Get-Content -LiteralPath $PageFile.FullName -Raw

    $PageObjectMatch = [regex]::Match(
        $Text,
        '(?im)^\s*page\s+\d+\s+(?<name>"[^"]+"|[A-Za-z_][A-Za-z0-9_]*)'
    )

    if (-not $PageObjectMatch.Success) {
        continue
    }

    $RawPageName = $PageObjectMatch.Groups["name"].Value
    $PageName = $RawPageName.Trim('"')

    $HasDocumentsSentName = $PageName -match '(?i)Documents?\s*Sent|Documents?Sent'
    $HasDocumentsSentCaption = $Text -match "(?im)^\s*Caption\s*=\s*'[^']*Documents?\s+Sent[^']*'\s*;"

    if ($HasDocumentsSentName -or $HasDocumentsSentCaption) {
        [void]$DocumentsSentPageNames.Add($PageName)
    }
}

# Find candidate factbox parts on page extensions that extend Sales Order.
$Candidates = [System.Collections.Generic.List[object]]::new()

foreach ($PageExtFile in (
    Get-ChildItem -LiteralPath $ProdSrc -File -Filter "*.al" -Recurse |
        Sort-Object FullName
)) {
    if ($PageExtFile.FullName -eq $RecordDocsFile) {
        continue
    }

    $Text = Get-Content -LiteralPath $PageExtFile.FullName -Raw

    if ($Text -notmatch '(?im)^\s*pageextension\s+\d+\s+.+?\s+extends\s+"Sales Order"\s*$') {
        continue
    }

    $PartPattern = [regex]::new(
        '(?im)^\s*part\s*\(\s*(?<control>"[^"]+"|[A-Za-z_][A-Za-z0-9_]*)\s*;\s*(?<page>"[^"]+"|[A-Za-z_][A-Za-z0-9_:]*)\s*\)\s*\{'
    )

    foreach ($PartMatch in @($PartPattern.Matches($Text))) {
        $OpenBrace = $Text.IndexOf('{', $PartMatch.Index)
        $CloseBrace = Get-MatchingBraceIndex -Text $Text -OpenBraceIndex $OpenBrace
        $Block = $Text.Substring(
            $PartMatch.Index,
            $CloseBrace - $PartMatch.Index + 1
        )

        $RawControl = $PartMatch.Groups["control"].Value
        $RawPage = $PartMatch.Groups["page"].Value
        $ControlName = $RawControl.Trim('"')
        $PageName = $RawPage.Trim('"')

        $CaptionMatch = [regex]::Match(
            $Block,
            "(?im)^\s*Caption\s*=\s*'(?<caption>[^']+)'\s*;"
        )
        $Caption = if ($CaptionMatch.Success) {
            $CaptionMatch.Groups["caption"].Value
        }
        else {
            ""
        }

        $IsDocumentsSent =
            ($ControlName -match '(?i)Documents?\s*Sent|Documents?Sent') -or
            ($PageName -match '(?i)Documents?\s*Sent|Documents?Sent') -or
            ($Caption -match '(?i)Documents?\s+Sent') -or
            $DocumentsSentPageNames.Contains($PageName)

        $IsRecordDocuments =
            ($ControlName -eq "GPIRecordDocuments") -or
            ($PageName -match '(?i)Record Documents FactBox')

        if ($IsDocumentsSent -and -not $IsRecordDocuments) {
            $Score = 0

            if ($Caption -match '(?i)^Sales Order Documents Sent$') {
                $Score += 100
            }
            elseif ($Caption -match '(?i)Documents?\s+Sent') {
                $Score += 70
            }

            if ($ControlName -match '(?i)SalesOrder.*Documents?Sent|Documents?Sent') {
                $Score += 50
            }

            if ($PageName -match '(?i)Sales Order Documents Sent') {
                $Score += 40
            }
            elseif ($DocumentsSentPageNames.Contains($PageName)) {
                $Score += 25
            }

            $Candidates.Add([pscustomobject]@{
                File = $PageExtFile.FullName
                RawControl = $RawControl
                ControlName = $ControlName
                PageName = $PageName
                Caption = $Caption
                Score = $Score
            })
        }
    }
}

if ($Candidates.Count -eq 0) {
    throw @"
No Sales Order Documents Sent FactBox control could be identified automatically.

Run this read-only command and paste the results:
Get-ChildItem "$ProdSrc" -Recurse -Filter *.al |
    Select-String -Pattern "Documents Sent|DocumentsSent" -Context 8,8
"@
}

$TopScore = ($Candidates | Measure-Object -Property Score -Maximum).Maximum
$TopCandidates = @($Candidates | Where-Object Score -eq $TopScore)

if ($TopCandidates.Count -ne 1) {
    $CandidateText = ($Candidates |
        Sort-Object Score -Descending |
        ForEach-Object {
            "File=$($_.File); Control=$($_.RawControl); Page=$($_.PageName); Caption=$($_.Caption); Score=$($_.Score)"
        }) -join [Environment]::NewLine

    throw "More than one possible Documents Sent FactBox was found:`r`n$CandidateText"
}

$Anchor = $TopCandidates[0]
$AnchorControl = $Anchor.RawControl

$RecordDocsText = Get-Content -LiteralPath $RecordDocsFile -Raw

$InsertionPattern = '(?im)\b(addlast|addfirst|addafter|addbefore)\s*\(\s*[^)]+\s*\)\s*(?=\{[\s\S]*?part\s*\(\s*GPIRecordDocuments\s*;)'
$InsertionMatches = @([regex]::Matches($RecordDocsText, $InsertionPattern))

if ($InsertionMatches.Count -ne 1) {
    throw "Expected exactly one insertion block for GPIRecordDocuments, but found $($InsertionMatches.Count)."
}

$NewInsertion = "addafter($AnchorControl)"
$UpdatedRecordDocsText = [regex]::Replace(
    $RecordDocsText,
    $InsertionPattern,
    [System.Text.RegularExpressions.MatchEvaluator]{
        param($Match)
        return $NewInsertion
    },
    1
)

if ($UpdatedRecordDocsText -eq $RecordDocsText) {
    throw "The Sales Order record-documents page extension was not changed."
}

Copy-ToBackup -Path $RecordDocsFile
Copy-ToBackup -Path $ProdAppJson
Copy-ToBackup -Path $TestAppJson
Copy-ToBackup -Path $ChangeLog

Set-Content -LiteralPath $RecordDocsFile -Value $UpdatedRecordDocsText -Encoding utf8

$ProdApp = Get-Content -LiteralPath $ProdAppJson -Raw | ConvertFrom-Json
$OldProdVersion = [string]$ProdApp.version
$NewProdVersion = Get-NextFourPartVersion -Version $OldProdVersion
$ProdApp.version = $NewProdVersion

$ProdApp |
    ConvertTo-Json -Depth 50 -Compress |
    Set-Content -LiteralPath $ProdAppJson -Encoding utf8

$TestApp = Get-Content -LiteralPath $TestAppJson -Raw | ConvertFrom-Json
$OldTestVersion = [string]$TestApp.version
$NewTestVersion = Get-NextFourPartVersion -Version $OldTestVersion
$TestApp.version = $NewTestVersion

$DependencyUpdated = $false
foreach ($Dependency in @($TestApp.dependencies)) {
    if ([string]$Dependency.id -eq [string]$ProdApp.id) {
        $Dependency.version = $NewProdVersion
        $DependencyUpdated = $true
    }
}

if (-not $DependencyUpdated) {
    throw "The test extension dependency on the production extension was not found."
}

$TestApp |
    ConvertTo-Json -Depth 50 -Compress |
    Set-Content -LiteralPath $TestAppJson -Encoding utf8

$ExistingChangeLog = Get-Content -LiteralPath $ChangeLog -Raw
$NewEntry = @"
## $NewProdVersion

### Changed
- Moved the Sales Order Documents drag-and-drop FactBox directly below the Sales Order Documents Sent FactBox.
- Kept the record-specific SharePoint document list and drop zone behavior unchanged.

### Safety
- No RDLC or report layout files were changed.
- No document upload, routing, delivery, archive, or SharePoint logic was changed.

"@

$UpdatedChangeLog = [regex]::Replace(
    $ExistingChangeLog,
    '^# Changelog\s*\r?\n',
    "# Changelog`r`n`r`n$NewEntry",
    1
)

Set-Content -LiteralPath $ChangeLog -Value $UpdatedChangeLog -Encoding utf8

Write-Host ""
Write-Host "============================================================"
Write-Host " Sales Order Documents FactBox moved"
Write-Host "============================================================"
Write-Host ""
Write-Host "Anchor file:        $($Anchor.File)"
Write-Host "Anchor control:     $($Anchor.RawControl)"
Write-Host "Anchor page:        $($Anchor.PageName)"
Write-Host "Anchor caption:     $($Anchor.Caption)"
Write-Host ""
Write-Host "Changed file:       $RecordDocsFile"
Write-Host "New placement:      $NewInsertion"
Write-Host ""
Write-Host "Production version: $OldProdVersion -> $NewProdVersion"
Write-Host "Test version:       $OldTestVersion -> $NewTestVersion"
Write-Host "Backup folder:      $BackupRoot"
Write-Host ""
Write-Host "No RDLC files were touched."
