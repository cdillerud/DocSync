[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs",
    [switch]$SkipBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedProdVersion = "0.26.0.4"
$ExpectedTestVersion = "0.7.1.6"
$NewProdVersion = "0.26.0.5"
$NewTestVersion = "0.7.1.7"

$ProdRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests"
$ProdAppJson = Join-Path $ProdRoot "app.json"
$TestAppJson = Join-Path $TestRoot "app.json"
$ChangeLog = Join-Path $ProdRoot "CHANGELOG.md"
$ArchivePage = Join-Path $ProdRoot "src\page\GPISharePointArchiveSetup.Page.al"
$ArchiveCodeunit = Join-Path $ProdRoot "src\codeunit\GPISharePointArchive.Codeunit.al"
$PurchaseOrderFactBox = Join-Path $ProdRoot "src\pageextension\GPIPurchaseOrderRecordDocuments.PageExt.al"
$BuildScript = Join-Path $RepoRoot "scripts\Prepare-GPIALTests.ps1"

$RequiredFiles = @(
    $ProdAppJson,
    $TestAppJson,
    $ChangeLog,
    $ArchivePage,
    $ArchiveCodeunit,
    $PurchaseOrderFactBox
)

foreach ($Path in $RequiredFiles) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Required file was not found: $Path"
    }
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )

    $Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $Content, $Utf8NoBom)
}

function Get-RegexMatches {
    param(
        [Parameter(Mandatory)][string]$Content,
        [Parameter(Mandatory)][string]$Pattern
    )

    return [regex]::Matches(
        $Content,
        $Pattern,
        [System.Text.RegularExpressions.RegexOptions]::Multiline -bor
        [System.Text.RegularExpressions.RegexOptions]::Singleline
    )
}

function Replace-One {
    param(
        [Parameter(Mandatory)][string]$Content,
        [Parameter(Mandatory)][string]$Pattern,
        [Parameter(Mandatory)][string]$Replacement,
        [Parameter(Mandatory)][string]$Description
    )

    $Matches = @(Get-RegexMatches -Content $Content -Pattern $Pattern)
    if ($Matches.Count -ne 1) {
        throw "Expected exactly one $Description match, but found $($Matches.Count). No files were changed."
    }

    return [regex]::Replace(
        $Content,
        $Pattern,
        [System.Text.RegularExpressions.MatchEvaluator]{
            param($Match)
            return $Replacement
        },
        [System.Text.RegularExpressions.RegexOptions]::Multiline -bor
        [System.Text.RegularExpressions.RegexOptions]::Singleline
    )
}

function Write-JsonNoBom {
    param(
        [Parameter(Mandatory)][object]$Value,
        [Parameter(Mandatory)][string]$Path
    )

    $Json = $Value | ConvertTo-Json -Depth 100
    Write-Utf8NoBom -Path $Path -Content ($Json + [Environment]::NewLine)
}

$ProdApp = Get-Content -LiteralPath $ProdAppJson -Raw | ConvertFrom-Json
$TestApp = Get-Content -LiteralPath $TestAppJson -Raw | ConvertFrom-Json

if ([string]$ProdApp.version -ne $ExpectedProdVersion) {
    throw "Expected production version $ExpectedProdVersion, but found $($ProdApp.version). No files were changed."
}

if ([string]$TestApp.version -ne $ExpectedTestVersion) {
    throw "Expected test version $ExpectedTestVersion, but found $($TestApp.version). No files were changed."
}

$MainAppId = [string]$ProdApp.id
$MainDependency = @($TestApp.dependencies | Where-Object { [string]$_.id -eq $MainAppId })
if ($MainDependency.Count -ne 1) {
    throw "Expected exactly one test dependency on the production app, but found $($MainDependency.Count). No files were changed."
}

$ArchivePageText = Get-Content -LiteralPath $ArchivePage -Raw
$ArchiveCodeunitText = Get-Content -LiteralPath $ArchiveCodeunit -Raw
$PurchaseOrderFactBoxText = Get-Content -LiteralPath $PurchaseOrderFactBox -Raw
$ChangeLogText = Get-Content -LiteralPath $ChangeLog -Raw

# -----------------------------------------------------------------------------
# Replace the complete TestConnection procedure instead of matching a fragile
# internal block. This tolerates local differences in the current 0.26.0.4 code.
# -----------------------------------------------------------------------------

$TestConnectionPattern = '(?ms)^    procedure TestConnection\(\)\s*\r?\n.*?(?=^    procedure ArchivePendingDocuments\()'

$NewTestConnection = @'
    procedure TestConnection()
    var
        Setup: Record "GPI SharePoint Archive Setup";
        AccountName: Text;
        ErrorText: Text;
    begin
        GetSetup(Setup);
        Setup."Last Connection Test" := CurrentDateTime;
        ClearLastError();

        if TryConnection(Setup, AccountName) then begin
            Setup."Last Connection Result" :=
                CopyStr(
                    StrSubstNo(
                        'Success. %1 can access the configured SharePoint archive.',
                        AccountName),
                    1,
                    MaxStrLen(Setup."Last Connection Result"));
            Setup.Modify(true);
            Message('%1', Setup."Last Connection Result");
            exit;
        end;

        ErrorText := GetLastErrorText();
        if ErrorText = '' then
            ErrorText := 'The SharePoint archive connection test failed.';

        if IsDisabledAccountError(ErrorText) then begin
            if AccountName = '' then
                AccountName := 'GPI Document Archive';

            ErrorText :=
                StrSubstNo(
                    'The External File Account "%1" is disabled. Open External File Accounts, open the account, turn off Disabled, and then test the connection again.',
                    AccountName);
        end;

        Setup."Last Connection Result" :=
            CopyStr(ErrorText, 1, MaxStrLen(Setup."Last Connection Result"));
        Setup.Modify(true);
        Commit();
        Error('%1', ErrorText);
    end;

'@

$UpdatedArchiveCodeunitText = Replace-One `
    -Content $ArchiveCodeunitText `
    -Pattern $TestConnectionPattern `
    -Replacement $NewTestConnection `
    -Description "complete TestConnection procedure"

# -----------------------------------------------------------------------------
# Insert account-health helpers immediately before GetSetup.
# -----------------------------------------------------------------------------

if ($UpdatedArchiveCodeunitText -match '(?m)^    procedure GetArchiveAccountHealth\(') {
    throw "GetArchiveAccountHealth already exists. No files were changed."
}

$GetSetupMarkerPattern = '(?m)^    procedure GetSetup\('
$GetSetupMatches = @(Get-RegexMatches -Content $UpdatedArchiveCodeunitText -Pattern $GetSetupMarkerPattern)
if ($GetSetupMatches.Count -ne 1) {
    throw "Expected exactly one GetSetup marker, but found $($GetSetupMatches.Count). No files were changed."
}

$ArchiveHealthMethods = @'
    procedure GetArchiveAccountHealth(
        var AccountName: Text;
        var ConnectorName: Text;
        var AccountStatus: Text[50];
        var AccountStyle: Text): Boolean
    var
        FileScenario: Codeunit "File Scenario";
        TempAccount: Record "File Account" temporary;
        IsDisabled: Boolean;
    begin
        Clear(AccountName);
        Clear(ConnectorName);
        AccountStatus := 'Not configured';
        AccountStyle := 'Unfavorable';

        if not FileScenario.GetSpecificFileAccount(
            Enum::"File Scenario"::"GPI Document Archive",
            TempAccount)
        then
            exit(false);

        AccountName := TempAccount.Name;
        ConnectorName := Format(TempAccount.Connector);

        if TryGetSharePointAccountDisabled(
            TempAccount."Account Id",
            IsDisabled)
        then
            if IsDisabled then begin
                AccountStatus := 'Disabled';
                AccountStyle := 'Unfavorable';
                exit(false);
            end;

        AccountStatus := 'Configured';
        AccountStyle := 'Favorable';
        exit(true);
    end;

    [TryFunction]
    local procedure TryGetSharePointAccountDisabled(
        AccountId: Guid;
        var IsDisabled: Boolean)
    var
        AccountRecordRef: RecordRef;
        AccountIdFieldRef: FieldRef;
        DisabledFieldRef: FieldRef;
    begin
        IsDisabled := false;

        AccountRecordRef.Open(4580);
        AccountIdFieldRef := AccountRecordRef.Field(1);
        AccountIdFieldRef.SetRange(AccountId);

        if not AccountRecordRef.FindFirst() then begin
            AccountRecordRef.Close();
            exit;
        end;

        DisabledFieldRef := AccountRecordRef.Field(9);
        Evaluate(IsDisabled, Format(DisabledFieldRef.Value));
        AccountRecordRef.Close();
    end;

    local procedure IsDisabledAccountError(ErrorText: Text): Boolean
    var
        NormalizedError: Text;
    begin
        NormalizedError := LowerCase(ErrorText);

        exit(
            (StrPos(NormalizedError, 'account') > 0) and
            (StrPos(NormalizedError, 'disabled') > 0));
    end;

'@

$UpdatedArchiveCodeunitText = [regex]::Replace(
    $UpdatedArchiveCodeunitText,
    $GetSetupMarkerPattern,
    [System.Text.RegularExpressions.MatchEvaluator]{
        param($Match)
        return $ArchiveHealthMethods + $Match.Value
    },
    [System.Text.RegularExpressions.RegexOptions]::Multiline
)

# -----------------------------------------------------------------------------
# Replace the complete RefreshAccountStatus procedure.
# -----------------------------------------------------------------------------

$RefreshStatusPattern = '(?ms)^    local procedure RefreshAccountStatus\(\)\s*\r?\n.*?(?=^    var\s*\r?\n)'

$NewRefreshStatus = @'
    local procedure RefreshAccountStatus()
    var
        ArchiveMgt: Codeunit "GPI SharePoint Archive";
    begin
        ArchiveMgt.GetArchiveAccountHealth(
            ArchiveAccountName,
            ArchiveConnectorName,
            ArchiveAccountStatus,
            ArchiveAccountStyle);
    end;

'@

$UpdatedArchivePageText = Replace-One `
    -Content $ArchivePageText `
    -Pattern $RefreshStatusPattern `
    -Replacement $NewRefreshStatus `
    -Description "complete RefreshAccountStatus procedure"

# -----------------------------------------------------------------------------
# Move Purchase Order Documents below Boyer's Documents Sent FactBox.
# -----------------------------------------------------------------------------

if ($PurchaseOrderFactBoxText -match '(?im)\baddafter\s*\(\s*Page50005\s*\)') {
    throw "The Purchase Order Documents FactBox is already placed after Page50005. No files were changed."
}

$PurchasePlacementPattern = '(?im)\baddlast\s*\(\s*FactBoxes\s*\)(?=\s*\{\s*part\s*\(\s*GPIRecordDocuments\s*;)'

$UpdatedPurchaseOrderFactBoxText = Replace-One `
    -Content $PurchaseOrderFactBoxText `
    -Pattern $PurchasePlacementPattern `
    -Replacement 'addafter(Page50005)' `
    -Description "Purchase Order GPIRecordDocuments placement"

# -----------------------------------------------------------------------------
# Version and changelog.
# -----------------------------------------------------------------------------

$ProdApp.version = $NewProdVersion
$TestApp.version = $NewTestVersion
$MainDependency[0].version = $NewProdVersion

$ChangeLogEntry = @"
## $NewProdVersion

### Fixed
- Archive Account Status now reports Disabled when the assigned SharePoint External File Account is disabled.
- Test Connection now replaces the raw connector error with instructions to open External File Accounts and turn off Disabled.
- Failed connection-test details are committed before the error is shown, preventing a stale Success result from remaining on the setup page.

### Changed
- Moved the Purchase Order Documents FactBox directly below the Boyer Documents Sent FactBox.
- Anchored the Purchase Order GPI Documents FactBox after Boyer control Page50005, matching the Sales Order placement pattern.

### Safety
- No account is enabled automatically.
- No RDLC or report layout files were changed.
- No document routing, archive-path, upload-path, file-content, or email logic was changed.
- Publish only to Sandbox_5_5_2026 unless Chad explicitly approves another environment.

"@

if ($ChangeLogText -match '(?m)^# Changelog\s*$') {
    $UpdatedChangeLogText = [regex]::Replace(
        $ChangeLogText,
        '(?m)^# Changelog\s*$',
        "# Changelog`r`n`r`n$ChangeLogEntry",
        1
    )
}
else {
    $UpdatedChangeLogText = "$ChangeLogEntry`r`n$ChangeLogText"
}

# -----------------------------------------------------------------------------
# All validations passed. Back up, write, and build.
# -----------------------------------------------------------------------------

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $RepoRoot ".gpi-backups\archive-status-po-factbox-v2-$Timestamp"

foreach ($Path in $RequiredFiles) {
    $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
    $BackupPath = Join-Path $BackupRoot $RelativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $BackupPath) -Force | Out-Null
    Copy-Item -LiteralPath $Path -Destination $BackupPath -Force
}

Write-Utf8NoBom -Path $ArchiveCodeunit -Content $UpdatedArchiveCodeunitText
Write-Utf8NoBom -Path $ArchivePage -Content $UpdatedArchivePageText
Write-Utf8NoBom -Path $PurchaseOrderFactBox -Content $UpdatedPurchaseOrderFactBoxText
Write-Utf8NoBom -Path $ChangeLog -Content $UpdatedChangeLogText
Write-JsonNoBom -Value $ProdApp -Path $ProdAppJson
Write-JsonNoBom -Value $TestApp -Path $TestAppJson

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " Archive status and Purchase Order FactBox fix applied" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production version: $NewProdVersion"
Write-Host "Test version:       $NewTestVersion"
Write-Host "Backup:             $BackupRoot"

if (-not $SkipBuild) {
    if (-not (Test-Path -LiteralPath $BuildScript)) {
        throw "Fix was applied, but the build script was not found: $BuildScript"
    }

    Write-Host ""
    Write-Host "Running production and test builds..." -ForegroundColor Cyan
    & $BuildScript

    if ($LASTEXITCODE -ne 0) {
        throw "The fix was applied, but the build returned exit code $LASTEXITCODE. Restore from $BackupRoot if needed."
    }
}
else {
    Write-Host ""
    Write-Host "Build skipped. Run this next:"
    Write-Host "& `"$BuildScript`""
}

Write-Host ""
Write-Host "Do not publish to Production." -ForegroundColor Yellow
Write-Host "Publish both packages only to Sandbox_5_5_2026, refresh the Testing panel, and run the complete suite." -ForegroundColor Yellow
