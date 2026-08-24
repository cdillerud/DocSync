page 71108 "GPI Spiro Opp API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'spiroIntegration';
    APIVersion = 'v1.0';
    Caption = 'spiroOpportunityCandidates';
    EntityName = 'spiroOpportunityCandidate';
    EntitySetName = 'spiroOpportunityCandidates';
    SourceTable = "GPI Spiro Opp Cache";
    ODataKeyFields = SystemId;
    DelayedInsert = true;
    InsertAllowed = true;
    ModifyAllowed = true;
    DeleteAllowed = true;
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
                field(spiroOpportunityId; Rec."Spiro Opportunity ID")
                {
                    Caption = 'Spiro Opportunity ID';
                }
                field(spiroCompanyId; Rec."Spiro Company ID")
                {
                    Caption = 'Spiro Company ID';
                }
                field(spiroCompanyName; Rec."Spiro Company Name")
                {
                    Caption = 'Spiro Company Name';
                }
                field(opportunityName; Rec."Opportunity Name")
                {
                    Caption = 'Opportunity Name';
                }
                field(stage; Rec.Stage)
                {
                    Caption = 'Stage';
                }
                field(owner; Rec.Owner)
                {
                    Caption = 'Owner';
                }
                field(browserUrl; Rec."Browser URL")
                {
                    Caption = 'Browser URL';
                }
                field(refreshedAt; Rec."Refreshed At")
                {
                    Caption = 'Refreshed At';
                }
                field(refreshedBy; Rec."Refreshed By")
                {
                    Caption = 'Refreshed By';
                }
            }
        }
    }
}
