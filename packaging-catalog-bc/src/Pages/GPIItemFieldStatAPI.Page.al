page 71030 "GPI Item Stat API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'catalogDiscovery';
    APIVersion = 'v1.0';
    Caption = 'bcItemFieldProfiles';
    EntityName = 'bcItemFieldProfile';
    EntitySetName = 'bcItemFieldProfiles';
    SourceTable = "GPI Item Field Stat";
    ODataKeyFields = SystemId;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;
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
                field(fieldNo; Rec."Field No.")
                {
                    Caption = 'Field No.';
                    Editable = false;
                }
                field(fieldName; Rec."Field Name")
                {
                    Caption = 'Field Name';
                    Editable = false;
                }
                field(fieldCaption; Rec."Field Caption")
                {
                    Caption = 'Field Caption';
                    Editable = false;
                }
                field(dataType; Rec."Data Type")
                {
                    Caption = 'Data Type';
                    Editable = false;
                }
                field(totalItemCount; Rec."Total Item Count")
                {
                    Caption = 'Total Item Count';
                    Editable = false;
                }
                field(nondefaultCount; Rec."Nondefault Count")
                {
                    Caption = 'Nondefault Count';
                    Editable = false;
                }
                field(nondefaultPercent; Rec."Nondefault Percent")
                {
                    Caption = 'Nondefault Percent';
                    Editable = false;
                }
                field(sampleValues; Rec."Sample Values")
                {
                    Caption = 'Sample Values';
                    Editable = false;
                }
                field(sampleItemNos; Rec."Sample Item Nos.")
                {
                    Caption = 'Sample Item Nos.';
                    Editable = false;
                }
                field(packagingRelevant; Rec."Packaging Relevant")
                {
                    Caption = 'Packaging Relevant';
                    Editable = false;
                }
                field(matchedKeyword; Rec."Matched Keyword")
                {
                    Caption = 'Matched Keyword';
                    Editable = false;
                }
                field(scannedAt; Rec."Scanned At")
                {
                    Caption = 'Scanned At';
                    Editable = false;
                }
            }
        }
    }
}
