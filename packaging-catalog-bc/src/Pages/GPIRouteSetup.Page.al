page 71025 "GPI Route Setup"
{
    PageType = Card;
    SourceTable = "GPI Route Setup";
    ApplicationArea = All;
    Caption = 'Packaging Route Setup';
    InsertAllowed = false;
    DeleteAllowed = false;

    layout
    {
        area(Content)
        {
            group(General)
            {
                field(Enabled; Rec.Enabled)
                {
                    ApplicationArea = All;
                }
                field(Provider; Rec.Provider)
                {
                    ApplicationArea = All;
                }
                field(Endpoint; Rec.Endpoint)
                {
                    ApplicationArea = All;
                }
                field("Cache Days"; Rec."Cache Days")
                {
                    ApplicationArea = All;
                }
                field(ApiKeyConfigured; ApiKeyConfigured)
                {
                    ApplicationArea = All;
                    Caption = 'Azure Maps API Key Configured';
                    Editable = false;
                }
                field(AzureMapsApiKey; ApiKeyInput)
                {
                    ApplicationArea = All;
                    Caption = 'Set Azure Maps API Key';
                    ExtendedDatatype = Masked;
                    ToolTip = 'Enter a new Azure Maps subscription key. The key is stored encrypted in extension isolated storage and is not written to a Business Central table.';

                    trigger OnValidate()
                    var
                        RouteMgt: Codeunit "GPI Pack Route Mgt";
                    begin
                        if ApiKeyInput = '' then
                            exit;

                        RouteMgt.SetAzureMapsKey(ApiKeyInput);
                        Clear(ApiKeyInput);
                        ApiKeyConfigured := RouteMgt.HasAzureMapsKey();
                    end;
                }
            }
        }
    }

    actions
    {
        area(Processing)
        {
            action(ClearAzureMapsKey)
            {
                ApplicationArea = All;
                Caption = 'Clear Azure Maps API Key';
                Image = Delete;

                trigger OnAction()
                var
                    RouteMgt: Codeunit "GPI Pack Route Mgt";
                begin
                    RouteMgt.ClearAzureMapsKey();
                    ApiKeyConfigured := false;
                    Clear(ApiKeyInput);
                end;
            }
            action(RouteCache)
            {
                ApplicationArea = All;
                Caption = 'Route Cache';
                RunObject = page "GPI Route Cache";
            }
        }
    }

    trigger OnOpenPage()
    var
        RouteMgt: Codeunit "GPI Pack Route Mgt";
    begin
        RouteMgt.EnsureSetup(Rec);
        Rec.SetRange("Primary Key", 'SETUP');
        Rec.FindFirst();
        ApiKeyConfigured := RouteMgt.HasAzureMapsKey();
    end;

    var
        ApiKeyInput: Text[215];
        ApiKeyConfigured: Boolean;
}
