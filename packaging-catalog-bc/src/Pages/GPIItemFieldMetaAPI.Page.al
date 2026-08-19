page 71029 "GPI Item Field API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'catalogDiscovery';
    APIVersion = 'v1.0';
    Caption = 'bcItemFields';
    EntityName = 'bcItemField';
    EntitySetName = 'bcItemFields';
    SourceTable = "GPI Item Field Meta";
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
                field(length; Rec.Length)
                {
                    Caption = 'Length';
                    Editable = false;
                }
                field(fieldClass; Rec."Field Class")
                {
                    Caption = 'Field Class';
                    Editable = false;
                }
                field(enabled; Rec.Enabled)
                {
                    Caption = 'Enabled';
                    Editable = false;
                }
                field(typeName; Rec."Type Name")
                {
                    Caption = 'Type Name';
                    Editable = false;
                }
                field(externalName; Rec."External Name")
                {
                    Caption = 'External Name';
                    Editable = false;
                }
                field(relationTableNo; Rec."Relation Table No.")
                {
                    Caption = 'Relation Table No.';
                    Editable = false;
                }
                field(relationFieldNo; Rec."Relation Field No.")
                {
                    Caption = 'Relation Field No.';
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
