page 71132 "GPI Agent Setup API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'commercialAgents';
    APIVersion = 'v1.0';
    Caption = 'commercialAgentSetup';
    EntityName = 'commercialAgentSetup';
    EntitySetName = 'commercialAgentSetups';
    SourceTable = "GPI Agent Setup";
    ODataKeyFields = SystemId;
    InsertAllowed = true;
    ModifyAllowed = true;
    DeleteAllowed = false;
    Extensible = false;

    layout
    {
        area(Content)
        {
            repeater(General)
            {
                field(id; Rec.SystemId) { Caption = 'Id'; Editable = false; }
                field(primaryKey; Rec."Primary Key") { Caption = 'Primary Key'; }
                field(lowMarginEnabled; Rec."Low Margin Enabled") { Caption = 'Low Margin Enabled'; }
                field(lowMarginFloorPct; Rec."Low Margin Floor %") { Caption = 'Low Margin Floor %'; }
                field(marginVariancePts; Rec."Margin Variance Pts") { Caption = 'Margin Variance Pts'; }
                field(costChangeEnabled; Rec."Cost Change Enabled") { Caption = 'Cost Change Enabled'; }
                field(costChangeMinPct; Rec."Cost Change Min %") { Caption = 'Cost Change Min %'; }
                field(incorrectItemEnabled; Rec."Incorrect Item Enabled") { Caption = 'Incorrect Item Enabled'; }
                field(similarityThresholdPct; Rec."Similarity Threshold %") { Caption = 'Similarity Threshold %'; }
                field(lastModifiedAt; Rec."Last Modified At") { Caption = 'Last Modified At'; Editable = false; }
                field(lastModifiedBy; Rec."Last Modified By") { Caption = 'Last Modified By'; Editable = false; }
            }
        }
    }
}
