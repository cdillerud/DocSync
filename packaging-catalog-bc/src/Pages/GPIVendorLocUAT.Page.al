page 71024 "GPI Vendor Loc UAT"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'packagingCompareUAT';
    APIVersion = 'v1.0';
    Caption = 'vendorLocationsUAT';
    EntityName = 'vendorLocationUAT';
    EntitySetName = 'vendorLocationsUAT';
    SourceTable = "GPI Pack Vendor Loc";
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
                field(vendorNo; Rec."Vendor No.")
                {
                    Caption = 'Vendor No.';
                }
                field(locationCode; Rec.Code)
                {
                    Caption = 'Location Code';
                }
                field(description; Rec.Description)
                {
                    Caption = 'Description';
                }
                field(city; Rec.City)
                {
                    Caption = 'City';
                }
                field(stateProvince; Rec."State/Province")
                {
                    Caption = 'State/Province';
                }
                field(latitude; Rec.Latitude)
                {
                    Caption = 'Latitude';
                }
                field(longitude; Rec.Longitude)
                {
                    Caption = 'Longitude';
                }
                field(defaultFob; Rec."Default FOB")
                {
                    Caption = 'Default FOB';
                }
                field(blocked; Rec.Blocked)
                {
                    Caption = 'Blocked';
                }
            }
        }
    }

    trigger OnOpenPage()
    begin
        EnsureSandbox();
    end;

    trigger OnInsertRecord(BelowxRec: Boolean): Boolean
    begin
        EnsureSandbox();
        exit(true);
    end;

    trigger OnModifyRecord(): Boolean
    begin
        EnsureSandbox();
        exit(true);
    end;

    trigger OnDeleteRecord(): Boolean
    begin
        EnsureSandbox();
        exit(true);
    end;

    local procedure EnsureSandbox()
    var
        EnvironmentInformation: Codeunit "Environment Information";
    begin
        if not EnvironmentInformation.IsSandbox() then
            Error('The vendorLocationsUAT API is available only in a Business Central sandbox environment.');
    end;
}
