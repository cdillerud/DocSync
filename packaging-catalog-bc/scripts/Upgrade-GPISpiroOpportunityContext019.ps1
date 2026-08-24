[CmdletBinding()]
param(
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Step {
    param([Parameter(Mandatory)][string]$Text)
    Write-Host "`n== $Text ==" -ForegroundColor Cyan
}

function Backup-File {
    param([Parameter(Mandatory)][string]$Path)
    $backup = "$Path.pre-0.19.bak"
    Copy-Item -LiteralPath $Path -Destination $backup -Force
    return $backup
}

function Replace-Once {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$Old,
        [Parameter(Mandatory)][string]$New,
        [Parameter(Mandatory)][string]$Label
    )

    $first = $Text.IndexOf($Old, [System.StringComparison]::Ordinal)
    if ($first -lt 0) {
        throw "Patch anchor not found: $Label"
    }
    $second = $Text.IndexOf($Old, $first + $Old.Length, [System.StringComparison]::Ordinal)
    if ($second -ge 0) {
        throw "Patch anchor is not unique: $Label"
    }
    return $Text.Substring(0, $first) + $New + $Text.Substring($first + $Old.Length)
}

function Save-PatchedFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )
    Backup-File -Path $Path | Out-Null
    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Patched: $Path" -ForegroundColor Green
}

$appJson = Join-Path $ProjectPath 'app.json'
$cacheTable = Join-Path $ProjectPath 'src\Tables\GPISpiroOpportunityCache.Table.al'
$oppApi = Join-Path $ProjectPath 'src\Pages\GPISpiroOpportunityAPI.Page.al'
$oppLookup = Join-Path $ProjectPath 'src\Pages\GPISpiroOpportunityLookup.Page.al'
$quoteTableExt = Join-Path $ProjectPath 'src\TableExtensions\GPISpiroQuote.TableExt.al'
$quotePageExt = Join-Path $ProjectPath 'src\PageExtensions\GPISpiroQuoteCard.PageExt.al'
$linkMgt = Join-Path $ProjectPath 'src\Codeunits\GPISpiroLinkMgt.Codeunit.al'
$refreshScript = Join-Path $ProjectPath 'scripts\Refresh-GPISpiroOpportunityCacheUAT.ps1'

$required = @($appJson, $cacheTable, $oppApi, $oppLookup, $quoteTableExt, $quotePageExt, $linkMgt, $refreshScript)
foreach ($file in $required) {
    if (-not (Test-Path -LiteralPath $file)) {
        throw "Required file not found: $file"
    }
}

Write-Step 'PRECHECK'
$app = Get-Content -LiteralPath $appJson -Raw | ConvertFrom-Json
if ([string]$app.version -ne '0.18.0.0') {
    throw "Expected app version 0.18.0.0 before this upgrade. Found $($app.version)."
}

foreach ($file in @($cacheTable, $oppApi, $oppLookup, $quoteTableExt, $quotePageExt, $linkMgt, $refreshScript)) {
    $raw = Get-Content -LiteralPath $file -Raw
    if ($raw -match 'GPI Spiro Assigned ISR|assignedIsr|Estimated Annual Volume') {
        throw "0.19 context fields already appear to be present in $file"
    }
}
Write-Host '0.18 source precheck passed.' -ForegroundColor Green

Write-Step 'BUMP APP VERSION TO 0.19.0.0'
$appRaw = Get-Content -LiteralPath $appJson -Raw
$appRaw = Replace-Once -Text $appRaw -Old '"version": "0.18.0.0"' -New '"version": "0.19.0.0"' -Label 'app version'
Save-PatchedFile -Path $appJson -Content $appRaw

Write-Step 'EXTEND SPIRO OPPORTUNITY CACHE TABLE'
$text = Get-Content -LiteralPath $cacheTable -Raw
$anchor = @'
        field(9; "Refreshed By"; Text[100])
        {
            Caption = 'Refreshed By';
        }
'@
$replacement = $anchor + @'
        field(10; "Assigned ISR"; Text[100])
        {
            Caption = 'Assigned ISR';
        }
        field(11; Probability; Decimal)
        {
            Caption = 'Probability';
            DecimalPlaces = 0 : 5;
        }
        field(12; "Estimated Annual Volume"; Decimal)
        {
            Caption = 'Estimated Annual Volume';
            DecimalPlaces = 0 : 5;
        }
        field(13; "Close Date"; Date)
        {
            Caption = 'Close Date';
        }
        field(14; Rating; Text[50])
        {
            Caption = 'Rating';
        }
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'cache metadata field block'
Save-PatchedFile -Path $cacheTable -Content $text

Write-Step 'EXPOSE NEW CACHE FIELDS THROUGH BC API'
$text = Get-Content -LiteralPath $oppApi -Raw
$anchor = @'
                field(owner; Rec.Owner)
                {
                    Caption = 'Owner';
                }
'@
$replacement = $anchor + @'
                field(assignedIsr; Rec."Assigned ISR")
                {
                    Caption = 'Assigned ISR';
                }
                field(probability; Rec.Probability)
                {
                    Caption = 'Probability';
                }
                field(estimatedAnnualVolume; Rec."Estimated Annual Volume")
                {
                    Caption = 'Estimated Annual Volume';
                }
                field(closeDate; Rec."Close Date")
                {
                    Caption = 'Close Date';
                }
                field(rating; Rec.Rating)
                {
                    Caption = 'Rating';
                }
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'opportunity API owner field'
Save-PatchedFile -Path $oppApi -Content $text

Write-Step 'EXTEND OPPORTUNITY LOOKUP'
$text = Get-Content -LiteralPath $oppLookup -Raw
$anchor = @'
                field(Owner; Rec.Owner)
                {
                    ApplicationArea = All;
                }
'@
$replacement = $anchor + @'
                field("Assigned ISR"; Rec."Assigned ISR")
                {
                    ApplicationArea = All;
                }
                field(Probability; Rec.Probability)
                {
                    ApplicationArea = All;
                    Caption = 'Probability %';
                }
                field("Estimated Annual Volume"; Rec."Estimated Annual Volume")
                {
                    ApplicationArea = All;
                }
                field("Close Date"; Rec."Close Date")
                {
                    ApplicationArea = All;
                }
                field(Rating; Rec.Rating)
                {
                    ApplicationArea = All;
                }
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'lookup Owner field'
Save-PatchedFile -Path $oppLookup -Content $text

Write-Step 'ADD READ-ONLY SPIRO SNAPSHOT FIELDS TO PACKAGING QUOTE'
$text = Get-Content -LiteralPath $quoteTableExt -Raw
$anchor = @'
        field(71130; "GPI Spiro Synced By"; Text[100])
        {
            Caption = 'Spiro Last Synced By';
        }
'@
$replacement = $anchor + @'
        field(71131; "GPI Spiro Assigned ISR"; Text[100])
        {
            Caption = 'Spiro Assigned ISR';
        }
        field(71132; "GPI Spiro Probability"; Decimal)
        {
            Caption = 'Spiro Probability';
            DecimalPlaces = 0 : 5;
        }
        field(71133; "GPI Spiro Est. Annual Volume"; Decimal)
        {
            Caption = 'Spiro Estimated Annual Volume';
            DecimalPlaces = 0 : 5;
        }
        field(71134; "GPI Spiro Close Date"; Date)
        {
            Caption = 'Spiro Close Date';
        }
        field(71135; "GPI Spiro Rating"; Text[50])
        {
            Caption = 'Spiro Rating';
        }
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'quote Spiro synced-by field'
Save-PatchedFile -Path $quoteTableExt -Content $text

Write-Step 'SHOW SPIRO SALES CONTEXT ON QUOTE CARD'
$text = Get-Content -LiteralPath $quotePageExt -Raw
$anchor = @'
                field("GPI Spiro Owner"; Rec."GPI Spiro Owner")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
'@
$replacement = $anchor + @'
                field("GPI Spiro Assigned ISR"; Rec."GPI Spiro Assigned ISR")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("GPI Spiro Probability"; Rec."GPI Spiro Probability")
                {
                    ApplicationArea = All;
                    Editable = false;
                    Caption = 'Spiro Probability %';
                }
                field("GPI Spiro Est. Annual Volume"; Rec."GPI Spiro Est. Annual Volume")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("GPI Spiro Close Date"; Rec."GPI Spiro Close Date")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("GPI Spiro Rating"; Rec."GPI Spiro Rating")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'quote card Spiro owner field'
Save-PatchedFile -Path $quotePageExt -Content $text

Write-Step 'COPY CACHED SALES CONTEXT WHEN LINKING AN OPPORTUNITY'
$text = Get-Content -LiteralPath $linkMgt -Raw
$anchor = @'
        Quote."GPI Spiro Stage" := Opportunity.Stage;
        Quote."GPI Spiro Owner" := Opportunity.Owner;
        Quote."GPI Spiro Opp. URL" := Opportunity."Browser URL";
'@
$replacement = @'
        Quote."GPI Spiro Stage" := Opportunity.Stage;
        Quote."GPI Spiro Owner" := Opportunity.Owner;
        Quote."GPI Spiro Assigned ISR" := Opportunity."Assigned ISR";
        Quote."GPI Spiro Probability" := Opportunity.Probability;
        Quote."GPI Spiro Est. Annual Volume" := Opportunity."Estimated Annual Volume";
        Quote."GPI Spiro Close Date" := Opportunity."Close Date";
        Quote."GPI Spiro Rating" := Opportunity.Rating;
        Quote."GPI Spiro Opp. URL" := Opportunity."Browser URL";
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'link opportunity field assignments'
Save-PatchedFile -Path $linkMgt -Content $text

Write-Step 'ENRICH CACHE REFRESH WITH SPIRO SALES CONTEXT'
$text = Get-Content -LiteralPath $refreshScript -Raw

$anchor = @'
function Get-SpiroRecordId {
'@
$helpers = @'
function Get-SpiroCustomAttribute {
    param(
        [AllowNull()]$Record,
        [Parameter(Mandatory)][string[]]$Names
    )

    if ($null -eq $Record) {
        return $null
    }

    $attributes = Get-PropertyValue -Object $Record -Names @('attributes')
    if ($null -ne $attributes) {
        $custom = Get-PropertyValue -Object $attributes -Names @('custom', 'custom_fields', 'customFields')
        if ($null -ne $custom) {
            $value = Get-PropertyValue -Object $custom -Names $Names
            if ($null -ne $value) {
                return $value
            }
        }
    }

    return Get-SpiroAttribute -Record $Record -Names $Names
}

function Convert-ToDecimalOrZero {
    param([AllowNull()]$Value)

    if ($null -eq $Value) { return [decimal]0 }
    $text = ([string]$Value).Trim().Replace(',', '')
    if ([string]::IsNullOrWhiteSpace($text)) { return [decimal]0 }

    $parsed = [decimal]0
    if ([decimal]::TryParse(
        $text,
        [System.Globalization.NumberStyles]::Any,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [ref]$parsed
    )) {
        return $parsed
    }

    return [decimal]0
}

function Convert-ToBcDateText {
    param([AllowNull()]$Value)

    if ($null -eq $Value) { return '' }
    $text = ([string]$Value).Trim()
    if ([string]::IsNullOrWhiteSpace($text)) { return '' }

    $parsed = [datetime]::MinValue
    if ([datetime]::TryParse(
        $text,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::AllowWhiteSpaces,
        [ref]$parsed
    )) {
        return $parsed.ToString('yyyy-MM-dd', [System.Globalization.CultureInfo]::InvariantCulture)
    }

    return ''
}

function Get-SpiroRecordId {
'@
$text = Replace-Once -Text $text -Old $anchor -New $helpers -Label 'Spiro record id helper anchor'

$anchor = @'
        $stageName = Get-StageName -StageId $stageId -PipelineId $pipelineId -AccessToken $spiroAccessToken -Cache $stageCache
        $ownerName = Get-OwnerDisplayName -OpportunityResponse $detailResponse -OwnerUserId $ownerId
        $opportunityName = Get-SpiroDisplayName -Record $detail
'@
$replacement = @'
        $stageName = Get-StageName -StageId $stageId -PipelineId $pipelineId -AccessToken $spiroAccessToken -Cache $stageCache
        $ownerName = Get-OwnerDisplayName -OpportunityResponse $detailResponse -OwnerUserId $ownerId
        $assignedIsr = [string](Get-SpiroCustomAttribute -Record $detail -Names @('assigned_isr', 'assignedISR', 'assignedIsr', 'assigned_isr_name', 'assignedISRName', 'isr', 'isr_name'))
        $probability = Convert-ToDecimalOrZero -Value (Get-SpiroCustomAttribute -Record $detail -Names @('probability', 'win_probability', 'winProbability'))
        $estimatedAnnualVolume = Convert-ToDecimalOrZero -Value (Get-SpiroCustomAttribute -Record $detail -Names @('estimated_annual_volume', 'est_annual_volume', 'annual_volume', 'estimatedAnnualVolume', 'estAnnualVolume'))
        $closeDate = Convert-ToBcDateText -Value (Get-SpiroCustomAttribute -Record $detail -Names @('close_date', 'closeDate', 'expected_close_date', 'expectedCloseDate'))
        $rating = [string](Get-SpiroCustomAttribute -Record $detail -Names @('rating', 'opportunity_rating', 'opportunityRating', 'temperature'))
        $opportunityName = Get-SpiroDisplayName -Record $detail
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'Spiro enrichment calculations'

$anchor = @'
            Stage = $stageName
            Owner = $ownerName
            BrowserUrl = $browserUrl
'@
$replacement = @'
            Stage = $stageName
            Owner = $ownerName
            AssignedIsr = $assignedIsr
            Probability = $probability
            EstimatedAnnualVolume = $estimatedAnnualVolume
            CloseDate = $closeDate
            Rating = $rating
            BrowserUrl = $browserUrl
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'live candidate object'

$anchor = @'
    Select-Object OpportunityId, CompanyName, OpportunityName, Stage, Owner |
'@
$replacement = @'
    Select-Object OpportunityId, CompanyName, OpportunityName, Stage, Owner, AssignedIsr, Probability, EstimatedAnnualVolume, CloseDate, Rating |
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'candidate console output'

$anchor = @'
            @{ Label = 'Stage'; Current = $existing.stage; Desired = $live.Stage },
            @{ Label = 'Owner'; Current = $existing.owner; Desired = $live.Owner },
            @{ Label = 'Browser URL'; Current = $existing.browserUrl; Desired = $live.BrowserUrl }
'@
$replacement = @'
            @{ Label = 'Stage'; Current = $existing.stage; Desired = $live.Stage },
            @{ Label = 'Owner'; Current = $existing.owner; Desired = $live.Owner },
            @{ Label = 'Assigned ISR'; Current = $existing.assignedIsr; Desired = $live.AssignedIsr },
            @{ Label = 'Probability'; Current = $existing.probability; Desired = $live.Probability },
            @{ Label = 'Estimated Annual Volume'; Current = $existing.estimatedAnnualVolume; Desired = $live.EstimatedAnnualVolume },
            @{ Label = 'Close Date'; Current = $existing.closeDate; Desired = $live.CloseDate },
            @{ Label = 'Rating'; Current = $existing.rating; Desired = $live.Rating },
            @{ Label = 'Browser URL'; Current = $existing.browserUrl; Desired = $live.BrowserUrl }
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'cache comparisons'

$anchor = @'
        Stage = $live.Stage
        Owner = $live.Owner
        BrowserUrl = $live.BrowserUrl
'@
$replacement = @'
        Stage = $live.Stage
        Owner = $live.Owner
        AssignedIsr = $live.AssignedIsr
        Probability = $live.Probability
        EstimatedAnnualVolume = $live.EstimatedAnnualVolume
        CloseDate = $live.CloseDate
        Rating = $live.Rating
        BrowserUrl = $live.BrowserUrl
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'plan live fields'

$anchor = @'
            Stage = [string]$existing.stage
            Owner = [string]$existing.owner
            BrowserUrl = [string]$existing.browserUrl
'@
$replacement = @'
            Stage = [string]$existing.stage
            Owner = [string]$existing.owner
            AssignedIsr = [string]$existing.assignedIsr
            Probability = Convert-ToDecimalOrZero -Value $existing.probability
            EstimatedAnnualVolume = Convert-ToDecimalOrZero -Value $existing.estimatedAnnualVolume
            CloseDate = [string]$existing.closeDate
            Rating = [string]$existing.rating
            BrowserUrl = [string]$existing.browserUrl
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'plan removed fields'

$anchor = @'
        stage = $item.Stage
        owner = $item.Owner
        browserUrl = $item.BrowserUrl
'@
$replacement = @'
        stage = $item.Stage
        owner = $item.Owner
        assignedIsr = $item.AssignedIsr
        probability = $item.Probability
        estimatedAnnualVolume = $item.EstimatedAnnualVolume
        closeDate = $item.CloseDate
        rating = $item.Rating
        browserUrl = $item.BrowserUrl
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'BC cache write body'

$anchor = @'
    if (-not (Test-TextEqual $verified.owner $live.Owner)) {
        $verificationFailures.Add("Owner mismatch for $($live.OpportunityId)")
    }
    if (-not (Test-TextEqual $verified.browserUrl $live.BrowserUrl)) {
'@
$replacement = @'
    if (-not (Test-TextEqual $verified.owner $live.Owner)) {
        $verificationFailures.Add("Owner mismatch for $($live.OpportunityId)")
    }
    if (-not (Test-TextEqual $verified.assignedIsr $live.AssignedIsr)) {
        $verificationFailures.Add("Assigned ISR mismatch for $($live.OpportunityId)")
    }
    if (-not (Test-TextEqual $verified.probability $live.Probability)) {
        $verificationFailures.Add("Probability mismatch for $($live.OpportunityId)")
    }
    if (-not (Test-TextEqual $verified.estimatedAnnualVolume $live.EstimatedAnnualVolume)) {
        $verificationFailures.Add("Estimated annual volume mismatch for $($live.OpportunityId)")
    }
    if (-not (Test-TextEqual $verified.closeDate $live.CloseDate)) {
        $verificationFailures.Add("Close date mismatch for $($live.OpportunityId)")
    }
    if (-not (Test-TextEqual $verified.rating $live.Rating)) {
        $verificationFailures.Add("Rating mismatch for $($live.OpportunityId)")
    }
    if (-not (Test-TextEqual $verified.browserUrl $live.BrowserUrl)) {
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'cache verification fields'

Save-PatchedFile -Path $refreshScript -Content $text

Write-Step 'VALIDATE PATCH'
$checks = @(
    @{ Path = $appJson; Pattern = '"version": "0.19.0.0"'; Label = '0.19 app version' },
    @{ Path = $cacheTable; Pattern = 'field\(10; "Assigned ISR"'; Label = 'cache Assigned ISR' },
    @{ Path = $oppApi; Pattern = 'field\(assignedIsr;'; Label = 'API assignedIsr' },
    @{ Path = $oppLookup; Pattern = 'Estimated Annual Volume'; Label = 'lookup annual volume' },
    @{ Path = $quoteTableExt; Pattern = '71135; "GPI Spiro Rating"'; Label = 'quote Spiro rating' },
    @{ Path = $quotePageExt; Pattern = 'Spiro Probability %'; Label = 'quote probability UI' },
    @{ Path = $linkMgt; Pattern = 'GPI Spiro Est\. Annual Volume'; Label = 'linker annual volume' },
    @{ Path = $refreshScript; Pattern = 'assignedIsr = \$item\.AssignedIsr'; Label = 'refresh API payload' }
)

foreach ($check in $checks) {
    $raw = Get-Content -LiteralPath $check.Path -Raw
    if ($raw -notmatch $check.Pattern) {
        throw "Validation failed: $($check.Label)"
    }
    Write-Host "PASS: $($check.Label)" -ForegroundColor Green
}

Write-Host "`n0.19 Spiro opportunity context patch applied successfully." -ForegroundColor Green
Write-Host 'No publish or deployment was performed.' -ForegroundColor Yellow
Write-Host 'Next: run the normal GPI Packaging Catalog build, publish 0.19 to UAT, then refresh WAT in dry-run mode.' -ForegroundColor Cyan
