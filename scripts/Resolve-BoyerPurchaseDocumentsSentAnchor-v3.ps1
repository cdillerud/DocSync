[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$ExpectedProdVersion = "0.26.0.5"
$ExpectedTestVersion = "0.7.1.7"
$NavxPrefixLength = 40

$ProdRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests"
$ProdAppJson = Join-Path $ProdRoot "app.json"
$TestAppJson = Join-Path $TestRoot "app.json"
$PurchaseFile = Join-Path $ProdRoot "src\pageextension\GPIPurchaseOrderRecordDocuments.PageExt.al"
$ChangeLog = Join-Path $ProdRoot "CHANGELOG.md"
$BuildScript = Join-Path $RepoRoot "scripts\Prepare-GPIALTests.ps1"
$PackageRoot = Join-Path $ProdRoot ".alpackages"

foreach ($Path in @(
    $ProdAppJson,
    $TestAppJson,
    $PurchaseFile,
    $ChangeLog,
    $BuildScript,
    $PackageRoot
)) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Required path was not found: $Path"
    }
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )

    $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $Utf8NoBom)
}

function Format-AlIdentifier {
    param([Parameter(Mandatory)][string]$Name)

    if ($Name -match '^[A-Za-z_][A-Za-z0-9_]*$') {
        return $Name
    }

    return '"' + $Name.Replace('"', '""') + '"'
}

function Add-Candidate {
    param(
        [Parameter(Mandatory)][AllowEmptyCollection()][System.Collections.Generic.List[object]]$List,
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][int]$Priority,
        [Parameter(Mandatory)][string]$Source
    )

    $Trimmed = $Name.Trim()

    if ([string]::IsNullOrWhiteSpace($Trimmed)) {
        return
    }

    $Rejected = @(
        'Caption',
        'ToolTip',
        'ApplicationArea',
        'Visible',
        'Enabled',
        'Editable',
        'SourceTable',
        'SubPageLink',
        'Purchase Order',
        'Sales Order',
        'FactBoxes',
        'Documents Sent',
        'Name',
        'Value',
        'Type',
        'Kind',
        'Part',
        'Page',
        'PageExtension',
        'Properties',
        'Controls',
        'ControlAddIns'
    )

    if ($Rejected -contains $Trimmed) {
        return
    }

    foreach ($Existing in $List) {
        if ([string]::Equals(
            [string]$Existing.Name,
            $Trimmed,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            if ($Priority -lt [int]$Existing.Priority) {
                $Existing.Priority = $Priority
                $Existing.Source = $Source
            }
            return
        }
    }

    $List.Add([pscustomobject]@{
        Name = $Trimmed
        Priority = $Priority
        Source = $Source
    })
}

$ProdApp = Get-Content -LiteralPath $ProdAppJson -Raw | ConvertFrom-Json
$TestApp = Get-Content -LiteralPath $TestAppJson -Raw | ConvertFrom-Json

if ([string]$ProdApp.version -ne $ExpectedProdVersion) {
    throw "Expected production version $ExpectedProdVersion, but found $($ProdApp.version). No files were changed."
}

if ([string]$TestApp.version -ne $ExpectedTestVersion) {
    throw "Expected test version $ExpectedTestVersion, but found $($TestApp.version). No files were changed."
}

$BoyerFiles = @(
    Get-ChildItem -LiteralPath $PackageRoot -File -Filter "*.app" |
        Where-Object { $_.FullName -match "(?i)Boyer" }
)

if ($BoyerFiles.Count -ne 1) {
    throw "Expected exactly one Boyer .app package in $PackageRoot, but found $($BoyerFiles.Count)."
}

$BoyerPath = [string]$BoyerFiles[0].FullName
$Bytes = [System.IO.File]::ReadAllBytes($BoyerPath)

if ($Bytes.Length -le $NavxPrefixLength) {
    throw "The Boyer package is too small to be a valid NAVX package."
}

if (
    $Bytes[0] -ne [byte][char]'N' -or
    $Bytes[1] -ne [byte][char]'A' -or
    $Bytes[2] -ne [byte][char]'V' -or
    $Bytes[3] -ne [byte][char]'X'
) {
    throw "The Boyer package does not begin with the expected NAVX header."
}

$ZipStream = New-Object System.IO.MemoryStream(
    $Bytes,
    $NavxPrefixLength,
    ($Bytes.Length - $NavxPrefixLength),
    $false
)

$Archive = New-Object System.IO.Compression.ZipArchive(
    $ZipStream,
    [System.IO.Compression.ZipArchiveMode]::Read,
    $false
)

try {
    $SymbolEntry = $null

    foreach ($Entry in $Archive.Entries) {
        if (
            [string]::Equals(
                [string]$Entry.FullName,
                "SymbolReference.json",
                [System.StringComparison]::OrdinalIgnoreCase
            )
        ) {
            $SymbolEntry = $Entry
            break
        }
    }

    if ($null -eq $SymbolEntry) {
        $EntryNames = @(
            foreach ($Entry in $Archive.Entries) {
                [string]$Entry.FullName
            }
        )

        throw "SymbolReference.json was not found after removing the NAVX prefix. Entries: $($EntryNames -join ', ')"
    }

    $Reader = New-Object System.IO.StreamReader($SymbolEntry.Open())

    try {
        $RawSymbols = $Reader.ReadToEnd()
    }
    finally {
        $Reader.Dispose()
    }
}
finally {
    $Archive.Dispose()
    $ZipStream.Dispose()
}

$Candidates = New-Object 'System.Collections.Generic.List[object]'

# -------------------------------------------------------------------------
# Structured JSON search. For every scalar value equal to "Documents Sent",
# walk outward through its ancestor objects and collect nearby Name and
# ControlName values. Purchase Order context receives the highest priority.
# -------------------------------------------------------------------------

$SymbolRoot = $RawSymbols | ConvertFrom-Json

function Find-DocumentsSentValues {
    param(
        [AllowNull()][object]$Node,
        [object[]]$Ancestors,
        [string]$Path
    )

    if ($null -eq $Node) {
        return
    }

    if ($Node -is [string]) {
        if ([string]::Equals(
            [string]$Node,
            "Documents Sent",
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            [pscustomobject]@{
                Path = $Path
                Ancestors = @($Ancestors)
            }
        }
        return
    }

    if ($Node -is [System.Management.Automation.PSCustomObject]) {
        $NextAncestors = @($Ancestors + @($Node))

        foreach ($Property in @($Node.PSObject.Properties)) {
            Find-DocumentsSentValues `
                -Node $Property.Value `
                -Ancestors $NextAncestors `
                -Path ($Path + "." + $Property.Name)
        }
        return
    }

    if (
        $Node -is [System.Collections.IEnumerable] -and
        $Node -isnot [string]
    ) {
        $Index = 0

        foreach ($Item in $Node) {
            Find-DocumentsSentValues `
                -Node $Item `
                -Ancestors $Ancestors `
                -Path ($Path + "[" + $Index + "]")
            $Index++
        }
    }
}

$StructuredMatches = @(
    Find-DocumentsSentValues `
        -Node $SymbolRoot `
        -Ancestors @() `
        -Path '$'
)

foreach ($Match in $StructuredMatches) {
    $ContextParts = New-Object 'System.Collections.Generic.List[string]'

    foreach ($Ancestor in @($Match.Ancestors)) {
        foreach ($Property in @($Ancestor.PSObject.Properties)) {
            $Value = $Property.Value

            if (
                $null -ne $Value -and
                (
                    $Value -is [string] -or
                    $Value -is [int] -or
                    $Value -is [long] -or
                    $Value -is [bool]
                )
            ) {
                $ContextParts.Add(
                    ([string]$Property.Name + "=" + [string]$Value)
                )
            }
        }
    }

    $Context = $ContextParts -join '; '
    $IsPurchaseContext = $Context -match '(?i)Purchase Order'
    $BasePriority = if ($IsPurchaseContext) { 0 } else { 100 }

    for (
        $AncestorIndex = $Match.Ancestors.Count - 1;
        $AncestorIndex -ge 0;
        $AncestorIndex--
    ) {
        $Ancestor = $Match.Ancestors[$AncestorIndex]
        $Distance = ($Match.Ancestors.Count - 1) - $AncestorIndex

        foreach ($PropertyName in @('ControlName', 'Name')) {
            $Property = $Ancestor.PSObject.Properties[$PropertyName]

            if (
                $null -ne $Property -and
                $Property.Value -is [string]
            ) {
                Add-Candidate `
                    -List $Candidates `
                    -Name ([string]$Property.Value) `
                    -Priority ($BasePriority + $Distance) `
                    -Source ("Structured: " + $Match.Path)
            }
        }
    }
}

# -------------------------------------------------------------------------
# Raw JSON fallback. This protects against symbol schema differences by
# collecting Name or ControlName values close to every Documents Sent caption.
# -------------------------------------------------------------------------

$Needle = "Documents Sent"
$SearchStart = 0

while ($true) {
    $Position = $RawSymbols.IndexOf(
        $Needle,
        $SearchStart,
        [System.StringComparison]::OrdinalIgnoreCase
    )

    if ($Position -lt 0) {
        break
    }

    $WindowStart = [Math]::Max(0, $Position - 8000)
    $WindowLength = [Math]::Min(
        12000,
        $RawSymbols.Length - $WindowStart
    )
    $Window = $RawSymbols.Substring($WindowStart, $WindowLength)
    $IsPurchaseWindow = $Window -match '(?i)Purchase Order'
    $RawPriority = if ($IsPurchaseWindow) { 200 } else { 300 }

    $RegexMatches = @(
        [regex]::Matches(
            $Window,
            '"(?:ControlName|Name)"\s*:\s*"([^"]+)"',
            [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
        )
    )

    for ($i = $RegexMatches.Count - 1; $i -ge 0; $i--) {
        Add-Candidate `
            -List $Candidates `
            -Name ([string]$RegexMatches[$i].Groups[1].Value) `
            -Priority ($RawPriority + ($RegexMatches.Count - 1 - $i)) `
            -Source "Raw symbol window"
    }

    $SearchStart = $Position + $Needle.Length
}

if ($Candidates.Count -eq 0) {
    throw "Documents Sent was found in the Boyer symbols, but no usable control-name candidates could be derived."
}

$OrderedCandidates = @(
    $Candidates |
        Sort-Object Priority, Name
)

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Boyer Purchase Order anchor candidates" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

foreach ($Candidate in $OrderedCandidates) {
    Write-Host (
        "  {0,-45} Priority {1,-4} {2}" -f
        $Candidate.Name,
        $Candidate.Priority,
        $Candidate.Source
    )
}

$OriginalPurchase = Get-Content -LiteralPath $PurchaseFile -Raw

$PlacementPattern =
    '(?is)\b(?:addafter|addbefore|addfirst|addlast)\s*\(\s*[^)]*\s*\)' +
    '(?=\s*\{\s*part\s*\(\s*GPIRecordDocuments\s*;)'

$PlacementMatches = @(
    [regex]::Matches($OriginalPurchase, $PlacementPattern)
)

if ($PlacementMatches.Count -ne 1) {
    throw "Expected exactly one placement operation for GPIRecordDocuments, but found $($PlacementMatches.Count)."
}

# The current file may contain a trial anchor from an interrupted prior run.
# Build every candidate from the last known compilable placement and restore
# that safe placement if no candidate is accepted.
$SafePurchase = [regex]::Replace(
    $OriginalPurchase,
    $PlacementPattern,
    [System.Text.RegularExpressions.MatchEvaluator]{
        param($Match)
        return 'addlast(FactBoxes)'
    },
    1
)

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $RepoRoot ".gpi-backups\resolve-boyer-anchor-$Timestamp"
$BackupPurchase = Join-Path $BackupRoot (
    $PurchaseFile.Substring($RepoRoot.Length).TrimStart('\')
)
$BackupChangeLog = Join-Path $BackupRoot (
    $ChangeLog.Substring($RepoRoot.Length).TrimStart('\')
)

New-Item -ItemType Directory -Path (Split-Path -Parent $BackupPurchase) -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path -Parent $BackupChangeLog) -Force | Out-Null
Copy-Item -LiteralPath $PurchaseFile -Destination $BackupPurchase -Force
Copy-Item -LiteralPath $ChangeLog -Destination $BackupChangeLog -Force

$SuccessfulCandidate = $null
$SuccessfulAnchor = $null
$LastBuildLog = $null

foreach ($Candidate in $OrderedCandidates) {
    $Anchor = Format-AlIdentifier -Name ([string]$Candidate.Name)
    $Replacement = "addafter($Anchor)"

    $TrialPurchase = [regex]::Replace(
        $SafePurchase,
        $PlacementPattern,
        [System.Text.RegularExpressions.MatchEvaluator]{
            param($Match)
            return $Replacement
        },
        1
    )

    Write-Utf8NoBom -Path $PurchaseFile -Content $TrialPurchase

    $AttemptSafeName = (
        [string]$Candidate.Name -replace '[^A-Za-z0-9_.-]', '_'
    )
    $BuildLog = Join-Path $env:TEMP (
        "GPI-BoyerAnchor-" + $AttemptSafeName + "-" +
        (Get-Date -Format "yyyyMMddHHmmssfff") + ".log"
    )

    Write-Host ""
    Write-Host "Testing anchor: $Replacement" -ForegroundColor Yellow

    $StdOutLog = $BuildLog + ".stdout"
    $StdErrLog = $BuildLog + ".stderr"

    $Process = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @(
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            ('"' + $BuildScript + '"')
        ) `
        -Wait `
        -PassThru `
        -RedirectStandardOutput $StdOutLog `
        -RedirectStandardError $StdErrLog

    $BuildExitCode = $Process.ExitCode

    $StdOutText = if (Test-Path -LiteralPath $StdOutLog) {
        Get-Content -LiteralPath $StdOutLog -Raw
    }
    else {
        ''
    }

    $StdErrText = if (Test-Path -LiteralPath $StdErrLog) {
        Get-Content -LiteralPath $StdErrLog -Raw
    }
    else {
        ''
    }

    $BuildText = $StdOutText

    if (-not [string]::IsNullOrWhiteSpace($StdErrText)) {
        if (-not [string]::IsNullOrWhiteSpace($BuildText)) {
            $BuildText += [Environment]::NewLine
        }

        $BuildText += $StdErrText
    }

    Write-Utf8NoBom -Path $BuildLog -Content $BuildText
    $LastBuildLog = $BuildLog

    if ($BuildExitCode -eq 0) {
        $SuccessfulCandidate = $Candidate
        $SuccessfulAnchor = $Anchor

        Write-Host "Compiler accepted anchor: $Replacement" -ForegroundColor Green
        Write-Host ""
        Write-Host $BuildText
        break
    }

    if (
        $BuildText -match 'AL0270' -and
        $BuildText -match '(?i)control .* is not found in the target .*Purchase Order'
    ) {
        Write-Host "Rejected by compiler." -ForegroundColor DarkYellow
        continue
    }

    # The anchor was not rejected. A different production or test error was
    # reached, so retain this candidate and surface the real build output.
    $SuccessfulCandidate = $Candidate
    $SuccessfulAnchor = $Anchor

    Write-Host ""
    Write-Host "The compiler moved past the anchor and reached a different error." -ForegroundColor Red
    Write-Host $BuildText
    throw "The Purchase Order anchor was resolved as $Replacement, but the build has another error. The selected anchor has been retained."
}

if ($null -eq $SuccessfulCandidate) {
    Write-Utf8NoBom -Path $PurchaseFile -Content $SafePurchase

    Write-Host ""
    Write-Host "No candidate compiled. The safe addlast(FactBoxes) placement was restored." -ForegroundColor Red

    if ($null -ne $LastBuildLog) {
        Write-Host "Last build log: $LastBuildLog"
    }

    throw "Unable to resolve the Boyer Documents Sent control from the symbol package."
}

$ChangeLogText = Get-Content -LiteralPath $ChangeLog -Raw
$ChangeLogText = $ChangeLogText.Replace(
    'after Boyer control Page50005',
    ('after Boyer control ' + [string]$SuccessfulCandidate.Name)
)
Write-Utf8NoBom -Path $ChangeLog -Content $ChangeLogText

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " Purchase Order Documents FactBox anchor resolved" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Boyer package:      $BoyerPath"
Write-Host "Selected control:   $($SuccessfulCandidate.Name)"
Write-Host "AL anchor:          $SuccessfulAnchor"
Write-Host "Production version: $ExpectedProdVersion"
Write-Host "Test version:       $ExpectedTestVersion"
Write-Host "Backup:             $BackupRoot"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "After confirming the successful build above, publish only to Sandbox_5_5_2026." -ForegroundColor Yellow
