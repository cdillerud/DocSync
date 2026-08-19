page 71027 "GPI Route UAT API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'packagingCompareUAT';
    APIVersion = 'v1.0';
    Caption = 'routeCacheUAT';
    EntityName = 'routeCacheUAT';
    EntitySetName = 'routeCacheUAT';
    SourceTable = "GPI Route Cache";
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
                    Caption = 'Entry No.';
                    Editable = false;
                }
                field(originLatitude; Rec."Origin Latitude")
                {
                    Caption = 'Origin Latitude';
                }
                field(originLongitude; Rec."Origin Longitude")
                {
                    Caption = 'Origin Longitude';
                }
                field(destinationLatitude; Rec."Destination Latitude")
                {
                    Caption = 'Destination Latitude';
                }
                field(destinationLongitude; Rec."Destination Longitude")
                {
                    Caption = 'Destination Longitude';
                }
                field(mode; Rec.Mode)
                {
                    Caption = 'Transport Mode';
                }
                field(distanceMiles; Rec."Distance Miles")
                {
                    Caption = 'Distance Miles';
                }
                field(durationMinutes; Rec."Duration Minutes")
                {
                    Caption = 'Duration Minutes';
                }
                field(provider; Rec.Provider)
                {
                    Caption = 'Provider';
                }
                field(calculatedAt; Rec."Calculated At")
                {
                    Caption = 'Calculated At';
                }
                field(expiresAt; Rec."Expires At")
                {
                    Caption = 'Expires At';
                }
                field(providerReference; Rec."Provider Reference")
                {
                    Caption = 'Provider Reference';
                }
                field(notes; Rec.Notes)
                {
                    Caption = 'Notes';
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
            Error('The routeCacheUAT API is available only in a Business Central sandbox environment.');
    end;
}
