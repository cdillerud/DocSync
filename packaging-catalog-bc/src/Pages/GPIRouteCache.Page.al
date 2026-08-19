page 71026 "GPI Route Cache"
{
    PageType = List;
    SourceTable = "GPI Route Cache";
    ApplicationArea = All;
    Caption = 'Packaging Route Cache';
    UsageCategory = Lists;
    InsertAllowed = false;
    ModifyAllowed = false;

    layout
    {
        area(Content)
        {
            repeater(General)
            {
                field("Entry No."; Rec."Entry No.")
                {
                    ApplicationArea = All;
                }
                field("Origin Latitude"; Rec."Origin Latitude")
                {
                    ApplicationArea = All;
                }
                field("Origin Longitude"; Rec."Origin Longitude")
                {
                    ApplicationArea = All;
                }
                field("Destination Latitude"; Rec."Destination Latitude")
                {
                    ApplicationArea = All;
                }
                field("Destination Longitude"; Rec."Destination Longitude")
                {
                    ApplicationArea = All;
                }
                field(Mode; Rec.Mode)
                {
                    ApplicationArea = All;
                }
                field("Distance Miles"; Rec."Distance Miles")
                {
                    ApplicationArea = All;
                }
                field("Duration Minutes"; Rec."Duration Minutes")
                {
                    ApplicationArea = All;
                }
                field(Provider; Rec.Provider)
                {
                    ApplicationArea = All;
                }
                field("Calculated At"; Rec."Calculated At")
                {
                    ApplicationArea = All;
                }
                field("Expires At"; Rec."Expires At")
                {
                    ApplicationArea = All;
                }
                field("Provider Reference"; Rec."Provider Reference")
                {
                    ApplicationArea = All;
                }
                field(Notes; Rec.Notes)
                {
                    ApplicationArea = All;
                }
            }
        }
    }
}
