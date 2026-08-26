page 71128 "GPI Agent Evid API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'commercialAgentWrite';
    APIVersion = 'v1.0';
    Caption = 'commercialAgentEvidenceWrite';
    EntityName = 'commercialAgentEvidenceWrite';
    EntitySetName = 'commercialAgentEvidenceWrites';
    SourceTable = "GPI Comm Evidence";
    ODataKeyFields = SystemId;
    InsertAllowed = true;
    ModifyAllowed = false;
    DeleteAllowed = false;
    DelayedInsert = true;
    Extensible = false;

    layout
    {
        area(Content)
        {
            repeater(General)
            {
                field(id; Rec.SystemId) { Caption = 'Id'; Editable = false; }
                field(entryNo; Rec."Entry No.") { Caption = 'Entry No.'; Editable = false; }
                field(exceptionEntryNo; Rec."Exception Entry No.") { Caption = 'Exception Entry No.'; }
                field(evidenceType; Rec."Evidence Type") { Caption = 'Evidence Type'; }
                field(sourceSystem; Rec."Source System") { Caption = 'Source System'; }
                field(sourceRecordType; Rec."Source Record Type") { Caption = 'Source Record Type'; }
                field(sourceSystemId; Rec."Source SystemId") { Caption = 'Source SystemId'; }
                field(metric; Rec.Metric) { Caption = 'Metric'; }
                field(currentValue; Rec."Current Value") { Caption = 'Current Value'; }
                field(comparisonValue; Rec."Comparison Value") { Caption = 'Comparison Value'; }
                field(variance; Rec.Variance) { Caption = 'Variance'; }
                field(unit; Rec.Unit) { Caption = 'Unit'; }
                field(weight; Rec.Weight) { Caption = 'Weight'; }
                field(explanation; Rec.Explanation) { Caption = 'Explanation'; }
                field(provenance; Rec.Provenance) { Caption = 'Provenance'; }
                field(capturedAt; Rec."Captured At") { Caption = 'Captured At'; }
            }
        }
    }
}
