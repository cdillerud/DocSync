page 71020 "GPI Pack Compare API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'packagingComparisons';
    APIVersion = 'v1.0';
    Caption = 'packagingComparisons';
    EntityName = 'packagingComparison';
    EntitySetName = 'packagingComparisons';
    SourceTable = "GPI Pack Compare";
    ODataKeyFields = SystemId;
    InsertAllowed = true;
    ModifyAllowed = true;
    DeleteAllowed = true;
    DelayedInsert = true;
    Extensible = false;

    layout
    {
        area(Content)
        {
            repeater(General)
            {
                field(id; Rec.SystemId)
                {
                    Caption = 'Id';
                    Editable = false;
                }
                field(entryNo; Rec."Entry No.")
                {
                    Caption = 'Comparison No.';
                    Editable = false;
                }
                field(comparisonDate; Rec."Comparison Date")
                {
                    Caption = 'Comparison Date';
                }
                field(description; Rec.Description)
                {
                    Caption = 'Description';
                }
                field(referenceProductNo; Rec."Reference Product No.")
                {
                    Caption = 'Reference Gamer ID';
                }
                field(destinationState; Rec."Destination State")
                {
                    Caption = 'Destination State';
                }
                field(targetGrossMarginPct; Rec."Target Gross Margin %")
                {
                    Caption = 'Target Gross Margin %';
                }
                field(palletCostPerPallet; Rec."Pallet Cost per Pallet")
                {
                    Caption = 'Default Pallet Cost per Pallet';
                }
                field(tariffPct; Rec."Tariff %")
                {
                    Caption = 'Default Tariff %';
                }
                field(internationalFreightTotal; Rec."Intl Freight Total")
                {
                    Caption = 'Default International Freight Total';
                }
                field(customsTotal; Rec."Customs Total")
                {
                    Caption = 'Default Customs Total';
                }
                field(deliveryTotal; Rec."Delivery Total")
                {
                    Caption = 'Default Delivery Charge Total';
                }
                field(candidateCount; Rec."Candidate Count")
                {
                    Caption = 'Candidate Count';
                    Editable = false;
                }
                field(rankedCount; Rec."Ranked Count")
                {
                    Caption = 'Ranked Count';
                    Editable = false;
                }
                field(lastCalculatedAt; Rec."Last Calculated At")
                {
                    Caption = 'Last Calculated At';
                    Editable = false;
                }
                field(lastCalculatedBy; Rec."Last Calculated By")
                {
                    Caption = 'Last Calculated By';
                    Editable = false;
                }
                field(notes; Rec.Notes)
                {
                    Caption = 'Notes';
                }
            }
        }
    }

    [ServiceEnabled]
    procedure addMatchingCandidates(var ActionContext: WebServiceActionContext)
    var
        CompareMgt: Codeunit "GPI Pack Compare Mgt";
    begin
        CompareMgt.AddMatchingCandidates(Rec);
        SetActionResponse(ActionContext);
    end;

    [ServiceEnabled]
    procedure applyHeaderDefaults(var ActionContext: WebServiceActionContext)
    var
        CompareMgt: Codeunit "GPI Pack Compare Mgt";
    begin
        CompareMgt.ApplyHeaderDefaults(Rec);
        SetActionResponse(ActionContext);
    end;

    [ServiceEnabled]
    procedure calculate(var ActionContext: WebServiceActionContext)
    var
        CompareMgt: Codeunit "GPI Pack Compare Mgt";
    begin
        CompareMgt.CalculateComparison(Rec);
        SetActionResponse(ActionContext);
    end;

    local procedure SetActionResponse(var ActionContext: WebServiceActionContext)
    begin
        ActionContext.SetObjectType(ObjectType::Page);
        ActionContext.SetObjectId(Page::"GPI Pack Compare API");
        ActionContext.AddEntityKey(Rec.FieldNo(SystemId), Rec.SystemId);
        ActionContext.SetResultCode(WebServiceActionResultCode::Updated);
    end;
}
