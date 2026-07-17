[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedProductionVersion = "0.27.0.2"
$ExpectedTestVersion = "0.8.0.2"
$NewProductionVersion = "0.27.0.3"
$NewTestVersion = "0.8.0.3"

$ProductionRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests"

$DocumentPolicyPath = Join-Path $ProductionRoot "src\codeunit\GPIDocumentPolicyMgt.Codeunit.al"
$InvoiceBatchPath = Join-Path $ProductionRoot "src\codeunit\GPIInvoiceBatchEmail.Codeunit.al"
$NewTestPath = Join-Path $TestRoot "src\codeunit\GPIInvoiceRecipientFallbackTests.Codeunit.al"
$ProductionAppJson = Join-Path $ProductionRoot "app.json"
$TestAppJson = Join-Path $TestRoot "app.json"
$ChangeLogPath = Join-Path $ProductionRoot "CHANGELOG.md"
$BuildScript = Join-Path $RepoRoot "scripts\Prepare-GPIALTests.ps1"

foreach ($RequiredPath in @(
    $DocumentPolicyPath,
    $InvoiceBatchPath,
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLogPath,
    $BuildScript
)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required path was not found: $RequiredPath"
    }
}

if (Test-Path -LiteralPath $NewTestPath) {
    throw "The new invoice recipient test file already exists: $NewTestPath. No files were changed."
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

function Assert-FileHash {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$ExpectedHash
    )

    $ActualHash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($ActualHash -ne $ExpectedHash.ToUpperInvariant()) {
        throw "Source file changed unexpectedly: $Path`nExpected SHA256: $ExpectedHash`nActual SHA256:   $ActualHash`nNo files were changed."
    }
}

# These files were not touched by the Gamer Documents UI fixes, so their
# captured hashes remain a reliable guard.
Assert-FileHash `
    -Path $DocumentPolicyPath `
    -ExpectedHash "7A8B758601C7206409D04582DA390B298616F63BC105135ECBB5293A624CCB24"

Assert-FileHash `
    -Path $InvoiceBatchPath `
    -ExpectedHash "8CA0D0CF91EF640D0DA5D5F394634F3B3366DD7B25BBB7AC14D97C8B7EB5F26E"

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

$OriginalDocumentPolicy = Get-Content -LiteralPath $DocumentPolicyPath -Raw
$OriginalInvoiceBatch = Get-Content -LiteralPath $InvoiceBatchPath -Raw
$OriginalProductionAppJson = Get-Content -LiteralPath $ProductionAppJson -Raw
$OriginalTestAppJson = Get-Content -LiteralPath $TestAppJson -Raw
$OriginalChangeLog = Get-Content -LiteralPath $ChangeLogPath -Raw

# Use whitespace-tolerant regular expressions so CRLF/LF differences do not
# cause a false "not found" result.
$ResolverCallPattern = @'
(?ms)if\s+ToRecipients\.Count\(\)\s*=\s*0\s+then\s+
\s*AddRecipientsFromText\(\s*
ToRecipients\s*,\s*
GetCustomerPrimaryContactEmail\(\s*
SalesInvoiceHeader\."Bill-to Customer No\."\s*
\)\s*
\)\s*;
'@

$ResolverCallReplacement = @'
if ToRecipients.Count() = 0 then
            AddRecipientsFromText(
                ToRecipients,
                GetPostedInvoiceDefaultRecipient(
                    SalesInvoiceHeader."Bill-to Customer No."));
'@

$ResolverCallMatches = [regex]::Matches(
    $OriginalDocumentPolicy,
    $ResolverCallPattern,
    [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)

if ($ResolverCallMatches.Count -ne 1) {
    throw "Expected exactly one posted-invoice default recipient call, but found $($ResolverCallMatches.Count). No files were changed."
}

$PrimaryContactProcedurePattern = @'
(?ms)^\s{4}local\s+procedure\s+GetCustomerPrimaryContactEmail\(CustomerNo:\s*Code\[20\]\):\s*Text\s*
\s{4}var\s*
\s{8}Customer:\s*Record\s+Customer;\s*
\s{8}Contact:\s*Record\s+Contact;\s*
\s{4}begin\s*
.*?
^\s{4}end;\s*
(?=\s{4}local\s+procedure\s+GetLocationEmail)
'@

$PrimaryContactProcedureReplacement = @'
    procedure GetPostedInvoiceDefaultRecipient(CustomerNo: Code[20]): Text
    var
        Customer: Record Customer;
        Contact: Record Contact;
        RecipientEmail: Text;
    begin
        if not Customer.Get(CustomerNo) then
            exit('');

        if Customer."Primary Contact No." <> '' then
            if Contact.Get(Customer."Primary Contact No.") then begin
                RecipientEmail := DelChr(Contact."E-Mail", '<>', ' ');
                if RecipientEmail <> '' then
                    exit(RecipientEmail);
            end;

        exit(DelChr(Customer."E-Mail", '<>', ' '));
    end;

'@

$PrimaryContactMatches = [regex]::Matches(
    $OriginalDocumentPolicy,
    $PrimaryContactProcedurePattern,
    [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)

if ($PrimaryContactMatches.Count -ne 1) {
    throw "Expected exactly one primary-contact recipient procedure, but found $($PrimaryContactMatches.Count). No files were changed."
}

$UpdatedDocumentPolicy = [regex]::Replace(
    $OriginalDocumentPolicy,
    $ResolverCallPattern,
    $ResolverCallReplacement,
    [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)

$UpdatedDocumentPolicy = [regex]::Replace(
    $UpdatedDocumentPolicy,
    $PrimaryContactProcedurePattern,
    $PrimaryContactProcedureReplacement,
    [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)

$OldGuidance = 'Add an email to the Customer Card primary contact or create a customer-specific Invoice routing rule.'
$NewGuidance = 'Add an email to the Customer Card primary contact, populate the Customer Card E-Mail field, or create a customer-specific Invoice routing rule.'

$GuidanceCount = ([regex]::Matches(
    $OriginalInvoiceBatch,
    [regex]::Escape($OldGuidance))).Count

if ($GuidanceCount -ne 1) {
    throw "Expected exactly one invoice missing-recipient guidance message, but found $GuidanceCount. No files were changed."
}

$UpdatedInvoiceBatch = $OriginalInvoiceBatch.Replace($OldGuidance, $NewGuidance)

$NewTestSource = @'
codeunit 70719 "GPI Invoice Recipient Tests"
{
    Subtype = Test;

    Permissions =
        tabledata Customer = rimd,
        tabledata Contact = rimd;

    [Test]
    procedure PostedInvoiceDefaultsToCustomerCardEmailWhenPrimaryContactEmailIsBlank()
    var
        Customer: Record Customer;
        DocumentPolicy: Codeunit "GPI Document Policy Mgt.";
        CustomerNo: Code[20];
    begin
        CustomerNo := NewCode('INV');

        Customer.Init();
        Customer."No." := CustomerNo;
        Customer.Name := 'Invoice Customer Card Test';
        Customer."E-Mail" := 'customer.card@example.com';
        Customer.Insert(false);

        AssertEqualText(
            'customer.card@example.com',
            DocumentPolicy.GetPostedInvoiceDefaultRecipient(CustomerNo),
            'The posted invoice recipient did not fall back to the Customer Card E-Mail field.');
    end;

    [Test]
    procedure PostedInvoicePrimaryContactEmailTakesPrecedence()
    var
        Customer: Record Customer;
        Contact: Record Contact;
        DocumentPolicy: Codeunit "GPI Document Policy Mgt.";
        CustomerNo: Code[20];
        ContactNo: Code[20];
    begin
        CustomerNo := NewCode('INV');
        ContactNo := NewCode('CON');

        Contact.Init();
        Contact."No." := ContactNo;
        Contact.Name := 'Invoice Primary Contact Test';
        Contact."E-Mail" := 'primary.contact@example.com';
        Contact.Insert(false);

        Customer.Init();
        Customer."No." := CustomerNo;
        Customer.Name := 'Invoice Primary Contact Customer';
        Customer."Primary Contact No." := ContactNo;
        Customer."E-Mail" := 'customer.card@example.com';
        Customer.Insert(false);

        AssertEqualText(
            'primary.contact@example.com',
            DocumentPolicy.GetPostedInvoiceDefaultRecipient(CustomerNo),
            'The Customer Card E-Mail field incorrectly replaced the primary-contact email.');
    end;

    local procedure NewCode(Prefix: Text): Code[20]
    begin
        exit(CopyStr(Prefix + DelChr(Format(CreateGuid()), '=', '{}-'), 1, 20));
    end;

    local procedure AssertEqualText(Expected: Text; Actual: Text; FailureMessage: Text)
    begin
        if Expected <> Actual then
            Error('%1 Expected "%2" but received "%3".', FailureMessage, Expected, Actual);
    end;
}
'@

$ProductionApp.version = $NewProductionVersion
$TestApp.version = $NewTestVersion
$MainDependency[0].version = $NewProductionVersion

$ChangeLogEntry = @"
## $NewProductionVersion

### Fixed
- Posted Sales Invoice recipient resolution now falls back to the direct Customer Card E-Mail field when the customer has no usable primary-contact email.
- Primary-contact email remains the preferred Customer Card default.
- Customer-specific and generic Invoice routing rules continue to use the existing Add and Replace behavior.
- Missing-recipient guidance now identifies both Customer Card email locations.

### Tests
- Added coverage for direct Customer Card E-Mail fallback.
- Added coverage confirming that primary-contact email still takes precedence.

### Safety
- No invoice PDF, queue filtering, sender-account, Delivery Log, SharePoint archive, report, or routing-rule behavior was otherwise changed.
- No package is published automatically.
- Publish only to Sandbox_5_5_2026 unless Chad explicitly approves another environment.

"@

if ($OriginalChangeLog -match '(?m)^# Changelog\s*$') {
    $UpdatedChangeLog = [regex]::Replace(
        $OriginalChangeLog,
        '(?m)^# Changelog\s*$',
        "# Changelog`r`n`r`n$ChangeLogEntry",
        1
    )
}
else {
    throw "The changelog header was not found. No files were changed."
}

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $RepoRoot ".gpi-backups\fix-invoice-customer-email-fallback-v2-$Timestamp"
New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

$FilesToBackup = @(
    $DocumentPolicyPath,
    $InvoiceBatchPath,
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLogPath
)

foreach ($Path in $FilesToBackup) {
    $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
    $BackupPath = Join-Path $BackupRoot $RelativePath

    New-Item -ItemType Directory -Path (Split-Path -Parent $BackupPath) -Force | Out-Null
    Copy-Item -LiteralPath $Path -Destination $BackupPath -Force
}

$ProductionPackage = Join-Path $ProductionRoot "Gamer Packaging_GPI Sales Document Email_$NewProductionVersion.app"
$TestPackage = Join-Path $TestRoot "Gamer Packaging_GPI Sales Document Email Tests_$NewTestVersion.app"

try {
    Write-Utf8NoBom -Path $DocumentPolicyPath -Content $UpdatedDocumentPolicy
    Write-Utf8NoBom -Path $InvoiceBatchPath -Content $UpdatedInvoiceBatch
    Write-Utf8NoBom -Path $NewTestPath -Content $NewTestSource
    Write-JsonNoBom -Value $ProductionApp -Path $ProductionAppJson
    Write-JsonNoBom -Value $TestApp -Path $TestAppJson
    Write-Utf8NoBom -Path $ChangeLogPath -Content $UpdatedChangeLog

    if (Test-Path -LiteralPath $ProductionPackage) {
        Remove-Item -LiteralPath $ProductionPackage -Force
    }

    if (Test-Path -LiteralPath $TestPackage) {
        Remove-Item -LiteralPath $TestPackage -Force
    }

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host " Invoice Customer Card email fallback v2" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Production version: $NewProductionVersion"
    Write-Host "Test version:       $NewTestVersion"
    Write-Host "Backup:             $BackupRoot"
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
    Write-Host "The invoice recipient correction failed. Restoring all modified files." -ForegroundColor Red

    foreach ($Path in $FilesToBackup) {
        $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
        $BackupPath = Join-Path $BackupRoot $RelativePath
        Copy-Item -LiteralPath $BackupPath -Destination $Path -Force
    }

    if (Test-Path -LiteralPath $NewTestPath) {
        Remove-Item -LiteralPath $NewTestPath -Force
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
Write-Host " Invoice Customer Card fallback build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Backup:             $BackupRoot"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish both packages only to Sandbox_5_5_2026, refresh the Testing panel, and run the complete test suite." -ForegroundColor Yellow
