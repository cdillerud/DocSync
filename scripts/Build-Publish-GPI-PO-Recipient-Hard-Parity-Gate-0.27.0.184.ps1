#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$BuildOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot       = 'C:\Users\ChadDillerud\Documents\DocSync-Zetadocs'
$ExpectedBranch = 'feature/phase-3-record-documents'
$AppRoot        = Join-Path $RepoRoot 'bc-extension\zetadocs-replacement'
$SrcRoot        = Join-Path $AppRoot 'src'
$AppJson        = Join-Path $AppRoot 'app.json'
$AuditPage      = Join-Path $SrcRoot 'page\GPIPOBucketEvidenceAudit.Page.al'
$AuditCodeunit  = Join-Path $SrcRoot 'codeunit\GPIPOBucketEvidenceAuditMgt.Codeunit.al'
$AuditTable     = Join-Path $SrcRoot 'table\GPIPOBucketAuditBuffer.Table.al'
$PackageCache   = Join-Path $AppRoot '.alpackages'
$SourceVersion  = '0.27.0.183'
$TargetVersion  = '0.27.0.184'
$TenantId       = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$Environment    = 'Sandbox_08142026_GamerDocs'
$AppId          = 'b6eb6cc8-d984-4ab0-bb15-d3569db41171'
$AppName        = 'GPI Sales Document Email'
$AdminApiVersion= 'v2.29'
$PackagePath    = Join-Path $AppRoot "Gamer Packaging_GPI Sales Document Email_$TargetVersion.app"
$BackupRoot     = Join-Path $RepoRoot ('.gpi-backups\po-recipient-hard-parity-gate-' + $TargetVersion + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))

function Section([string]$Name) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Name -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

function Read-Text([string]$Path) { [System.IO.File]::ReadAllText($Path) }
function Write-Text([string]$Path,[string]$Text) { [System.IO.File]::WriteAllText($Path,$Text,[System.Text.UTF8Encoding]::new($false)) }
function Backup-One([string]$Path) {
    $Relative = [System.IO.Path]::GetRelativePath($RepoRoot,$Path)
    $Dest = Join-Path $BackupRoot $Relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $Dest) -Force | Out-Null
    Copy-Item -LiteralPath $Path -Destination $Dest -Force
}
function Restore-One([string]$Path) {
    $Relative = [System.IO.Path]::GetRelativePath($RepoRoot,$Path)
    $Source = Join-Path $BackupRoot $Relative
    if (Test-Path -LiteralPath $Source) { Copy-Item -LiteralPath $Source -Destination $Path -Force }
}
function Get-AlCompiler {
    $Compiler = Get-ChildItem "$env:USERPROFILE\.vscode\extensions" -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like 'ms-dynamics-smb.al-*' } |
        Sort-Object LastWriteTime -Descending |
        ForEach-Object {
            $Candidate = Join-Path $_.FullName 'bin\win32\alc.exe'
            if (Test-Path -LiteralPath $Candidate) { $Candidate }
        } | Select-Object -First 1
    if (-not $Compiler) { throw 'AL compiler alc.exe was not found.' }
    return $Compiler
}
function Convert-TokenToString($TokenValue) {
    if ($null -eq $TokenValue) { return $null }
    if ($TokenValue -is [string]) { return $TokenValue }
    if ($TokenValue -is [Security.SecureString]) { return [System.Net.NetworkCredential]::new('', $TokenValue).Password }
    return [string]$TokenValue
}
function Get-BcToken {
    if (-not (Get-Module -ListAvailable -Name Az.Accounts)) { throw 'Az.Accounts is not installed.' }
    Import-Module Az.Accounts -ErrorAction Stop
    $Ctx = Get-AzContext -ErrorAction SilentlyContinue
    if (($null -eq $Ctx) -or ($null -eq $Ctx.Account) -or ([string]$Ctx.Tenant.Id -ne $TenantId)) {
        Connect-AzAccount -Tenant $TenantId -AuthScope 'https://api.businesscentral.dynamics.com' | Out-Null
    }
    $TokenResult = Get-AzAccessToken -TenantId $TenantId -ResourceUrl 'https://api.businesscentral.dynamics.com' -ErrorAction Stop
    $Token = Convert-TokenToString $TokenResult.Token
    if ([string]::IsNullOrWhiteSpace($Token)) { throw 'Business Central access token was empty.' }
    return $Token
}
function Get-AdminAppRecord([string]$Token) {
    $EnvironmentEncoded = [uri]::EscapeDataString($Environment)
    $Uri = "https://api.businesscentral.dynamics.com/admin/$AdminApiVersion/applications/BusinessCentral/environments/$EnvironmentEncoded/apps"
    $Response = Invoke-RestMethod -Method Get -Uri $Uri -Headers @{ Authorization = "Bearer $Token"; Accept = 'application/json' } -ErrorAction Stop
    $Matches = @($Response.value | Where-Object { ([string]$_.id -eq $AppId) -or ([string]$_.name -eq $AppName) })
    if ($Matches.Count -ne 1) { throw "Expected exactly one installed $AppName record. Found $($Matches.Count)." }
    return $Matches[0]
}

Section '1. HARD SAFETY / CURRENT SOURCE PRECHECK'
if ($Environment -ne 'Sandbox_08142026_GamerDocs') { throw 'SAFETY STOP: environment must be exactly Sandbox_08142026_GamerDocs.' }
if ($Environment -match '(?i)prod|production') { throw 'SAFETY STOP: Production-like environment detected.' }
foreach ($Path in @($RepoRoot,$AppRoot,$AppJson,$AuditPage,$AuditCodeunit,$AuditTable,$PackageCache)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Required path missing: $Path" }
}
$Branch = (& git -C $RepoRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Could not determine current Git branch.' }
if ($Branch -ne $ExpectedBranch) { throw "Expected branch '$ExpectedBranch', found '$Branch'." }
$App = Get-Content -LiteralPath $AppJson -Raw | ConvertFrom-Json
if ([string]$App.id -ne $AppId) { throw "Unexpected app ID: $($App.id)" }
if ([string]$App.version -notin @($SourceVersion,$TargetVersion)) { throw "Expected local source $SourceVersion (or already-patched $TargetVersion), found $($App.version)." }
$PageBefore = Read-Text $AuditPage
$MgtBefore = Read-Text $AuditCodeunit
$TableBefore = Read-Text $AuditTable
foreach ($Marker in @('"GPI PO Bucket Evidence Audit"','SourceTableTemporary = true;','action(RefreshAudit)','AuditMgt.BuildAudit(Rec);')) {
    if (-not $PageBefore.Contains($Marker)) { throw "Existing audit page marker missing: $Marker" }
}
foreach ($Marker in @('procedure BuildAudit(var TempAudit: Record "GPI PO Bucket Audit Buffer" temporary)',"TempAudit.Result := 'MATCH';","TempAudit.Result := 'PARITY BLOCKER';","TempAudit.Result := 'SOURCE NOT FOUND';",'WarehouseEmail.ResolveDraftRecipients(','DropShipEmail.ResolveDraftRecipients(')) {
    if (-not $MgtBefore.Contains($Marker)) { throw "Existing exact-evidence audit marker missing: $Marker" }
}
foreach ($Marker in @('field(5; "Source Found"; Boolean)','field(19; Result; Text[30])','field(20; Detail; Text[2048])')) {
    if (-not $TableBefore.Contains($Marker)) { throw "Existing audit buffer marker missing: $Marker" }
}

Section '2. TARGETED BACKUP'
New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null
foreach ($Path in @($AppJson,$AuditPage)) { Backup-One $Path }

try {
    if ([string]$App.version -eq $SourceVersion) {
        Section '3. ADD HARD PARITY GATE ACTION'
        if ($PageBefore.Contains('action(RunHardParityGate)')) { throw 'RunHardParityGate unexpectedly already exists in .183 source.' }
        $TriggerIndex = $PageBefore.IndexOf('    trigger OnOpenPage()')
        if ($TriggerIndex -lt 0) { throw 'Could not locate OnOpenPage trigger.' }
        $BeforeTrigger = $PageBefore.Substring(0,$TriggerIndex)
        $ActionsClose = $BeforeTrigger.LastIndexOf('    }')
        if ($ActionsClose -lt 0) { throw 'Could not locate actions block closing brace.' }
        $ActionInsert = @'
            action(RunHardParityGate)
            {
                ApplicationArea = All;
                Caption = 'Run Hard Parity Gate';
                Image = TestReport;
                ToolTip = 'Rebuilds exact retained Production PO recipient evidence and fails if any available sandbox Purchase Header resolves to different To/CC/BCC buckets. Missing sandbox source records are reported separately as fixture risks.';

                trigger OnAction()
                var
                    AuditMgt: Codeunit "GPI PO Bucket Audit Mgt";
                    MatchCount: Integer;
                    FixtureRiskCount: Integer;
                    BlockerCount: Integer;
                    BlockerDetail: Text;
                begin
                    AuditMgt.BuildAudit(Rec);
                    MatchCount := 0;
                    FixtureRiskCount := 0;
                    BlockerCount := 0;
                    Clear(BlockerDetail);
                    Rec.Reset();
                    if Rec.FindSet() then
                        repeat
                            case Rec.Result of
                                'MATCH': MatchCount += 1;
                                'SOURCE NOT FOUND': FixtureRiskCount += 1;
                                else begin
                                    BlockerCount += 1;
                                    if BlockerDetail = '' then
                                        BlockerDetail := CopyStr(StrSubstNo('%1 %2: %3',Rec."PO No.",Rec."Vendor No.",Rec.Result),1,MaxStrLen(BlockerDetail));
                                end;
                            end;
                        until Rec.Next() = 0;
                    CurrPage.Update(false);
                    if BlockerCount > 0 then
                        Error('PO RECIPIENT PARITY BLOCKER: %1 source-found audit row(s) failed exact Production To/CC/BCC comparison. First failure: %2. Exact matches: %3. Missing sandbox fixtures: %4.',BlockerCount,BlockerDetail,MatchCount,FixtureRiskCount);
                    Message('PO RECIPIENT PARITY GATE PASS. Exact source-found resolver matches: %1. Missing sandbox fixtures (risk only): %2. No source-found To/CC/BCC mismatches.',MatchCount,FixtureRiskCount);
                end;
            }

'@
        $PageText = $PageBefore.Substring(0,$ActionsClose) + $ActionInsert + $PageBefore.Substring($ActionsClose)
        Write-Text $AuditPage $PageText
        Section '4. BUMP MAIN APP TO 0.27.0.184'
        $RawApp = Read-Text $AppJson
        $Pattern = '("version"\s*:\s*")' + [regex]::Escape($SourceVersion) + '(")'
        if (([regex]::Matches($RawApp,$Pattern)).Count -ne 1) { throw 'Expected exactly one manifest version field.' }
        $RawApp = [regex]::Replace($RawApp,$Pattern,'${1}' + $TargetVersion + '${2}',1)
        Write-Text $AppJson $RawApp
    }

    Section '5. STATIC PARITY / SAFETY VALIDATION'
    $PageAfter = Read-Text $AuditPage
    $MgtAfter = Read-Text $AuditCodeunit
    $TableAfter = Read-Text $AuditTable
    $FinalApp = Get-Content -LiteralPath $AppJson -Raw | ConvertFrom-Json
    foreach ($Marker in @('action(RunHardParityGate)','case Rec.Result of',"'MATCH':","'SOURCE NOT FOUND':",'BlockerCount += 1;','PO RECIPIENT PARITY BLOCKER:','PO RECIPIENT PARITY GATE PASS.')) {
        if (-not $PageAfter.Contains($Marker)) { throw "Hard-gate source validation failed. Missing: $Marker" }
    }
    if ([string]$FinalApp.version -ne $TargetVersion) { throw "Manifest version validation failed. Found $($FinalApp.version)." }
    if ($MgtAfter -ne $MgtBefore) { throw 'SAFETY STOP: exact-evidence audit management codeunit changed unexpectedly.' }
    if ($TableAfter -ne $TableBefore) { throw 'SAFETY STOP: audit buffer table changed unexpectedly.' }
    foreach ($Forbidden in @('RoutingRule.Modify','RoutingRule.Insert','RoutingRule.Delete','Email.Send','ApplyParity(','ModifyAll(')) {
        if ($PageAfter.Contains($Forbidden)) { throw "SAFETY STOP: forbidden operation found in hard-gate page: $Forbidden" }
    }

    Section '6. COMPILE MAIN APP'
    $Compiler = Get-AlCompiler
    if (Test-Path -LiteralPath $PackagePath) { Remove-Item -LiteralPath $PackagePath -Force }
    & $Compiler "/project:$AppRoot" "/packagecachepath:$PackageCache" "/out:$PackagePath"
    if ($LASTEXITCODE -ne 0) { throw "AL compile failed with exit code $LASTEXITCODE." }
    if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf)) { throw 'Compiler returned success but .184 package was not created.' }
    $PackageItem = Get-Item -LiteralPath $PackagePath
    $Hash = (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash.ToUpperInvariant()
    Write-Host "COMPILE SUCCESS $TargetVersion SHA256=$Hash" -ForegroundColor Green
    if ($BuildOnly) { exit 0 }

    Section '7. VERIFY CURRENT SANDBOX DEV SCOPE'
    $Token = Get-BcToken
    $Current = Get-AdminAppRecord -Token $Token
    if ([string]$Current.state -notmatch '(?i)^installed$') { throw "SAFETY STOP: current app state is '$($Current.state)'." }
    if ([string]$Current.appType -notmatch '(?i)^dev$') { throw "SAFETY STOP: current app type is '$($Current.appType)', expected DEV." }
    if ([version]([string]$Current.version) -gt [version]$TargetVersion) { throw "SAFETY STOP: sandbox has newer version $($Current.version)." }
    if ([string]$Current.version -eq $TargetVersion) { exit 0 }
    if ([string]$Current.version -notin @('0.27.0.182','0.27.0.183')) { throw "SAFETY STOP: expected installed .182 or .183 before .184, found $($Current.version)." }

    Section '8. PUBLISH .184 TO SAME DEV SCOPE'
    $Token = Get-BcToken
    $TenantEncoded = [uri]::EscapeDataString($TenantId)
    $EnvironmentEncoded = [uri]::EscapeDataString($Environment)
    $DevBase = "https://api.businesscentral.dynamics.com/v2.0/$TenantEncoded/$EnvironmentEncoded/dev/apps"
    $PublishUri = "$DevBase?SchemaUpdateMode=synchronize&DependencyPublishingOption=ignore"
    Invoke-RestMethod -Method Post -Uri $PublishUri -Headers @{ Authorization = "Bearer $Token"; Accept = 'application/json' } -Form @{ file = $PackageItem } -ErrorAction Stop | Out-Null

    Section '9. VERIFY INSTALLED VERSION'
    $Deadline = (Get-Date).AddMinutes(10)
    $Verified = $false
    while ((Get-Date) -lt $Deadline) {
        Start-Sleep -Seconds 8
        $Token = Get-BcToken
        $Observed = Get-AdminAppRecord -Token $Token
        if (([string]$Observed.version -eq $TargetVersion) -and ([string]$Observed.appType -match '(?i)^dev$') -and ([string]$Observed.state -match '(?i)^installed$')) {
            $Verified = $true
            break
        }
    }
    if (-not $Verified) { throw "Publish accepted but $TargetVersion was not verified installed." }
    Section '10. RESULT'
    Write-Host "PO RECIPIENT HARD PARITY GATE DEPLOYED $TargetVersion SHA256=$Hash" -ForegroundColor Green
}
catch {
    try {
        if ((Test-Path -LiteralPath $BackupRoot) -and ([string]$App.version -eq $SourceVersion)) {
            Restore-One $AppJson
            Restore-One $AuditPage
        }
    } catch {}
    if (Test-Path -LiteralPath $PackagePath) { Remove-Item -LiteralPath $PackagePath -Force -ErrorAction SilentlyContinue }
    throw
}
