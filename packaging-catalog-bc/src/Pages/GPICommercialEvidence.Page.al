page 71121 "GPI Comm Evidence"
{
    PageType = ListPart;
    SourceTable = "GPI Comm Evidence";
    ApplicationArea = All;
    Caption = 'Commercial Evidence';
    Editable = false;

    layout
    {
        area(Content)
        {
            repeater(General)
            {
                field("Evidence Type"; Rec."Evidence Type") { ApplicationArea = All; }
                field("Source System"; Rec."Source System") { ApplicationArea = All; }
                field(Metric; Rec.Metric) { ApplicationArea = All; }
                field("Current Value"; Rec."Current Value") { ApplicationArea = All; }
                field("Comparison Value"; Rec."Comparison Value") { ApplicationArea = All; }
                field(Variance; Rec.Variance) { ApplicationArea = All; }
                field(Unit; Rec.Unit) { ApplicationArea = All; }
                field(Weight; Rec.Weight) { ApplicationArea = All; }
                field(Explanation; Rec.Explanation) { ApplicationArea = All; }
                field(Provenance; Rec.Provenance) { ApplicationArea = All; }
                field("Captured At"; Rec."Captured At") { ApplicationArea = All; }
            }
        }
    }
}
