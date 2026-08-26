page 71122 "GPI Commercial Agent Queue"
{
    PageType = List;
    SourceTable = "GPI Commercial Agent Queue";
    ApplicationArea = All;
    UsageCategory = Administration;
    Caption = 'Commercial Agent Queue';
    Editable = false;

    layout
    {
        area(Content)
        {
            repeater(General)
            {
                field("Entry No."; Rec."Entry No.") { ApplicationArea = All; }
                field("Agent Type"; Rec."Agent Type") { ApplicationArea = All; }
                field(Status; Rec.Status) { ApplicationArea = All; }
                field(Priority; Rec.Priority) { ApplicationArea = All; }
                field("Requested At"; Rec."Requested At") { ApplicationArea = All; }
                field("Started At"; Rec."Started At") { ApplicationArea = All; }
                field("Completed At"; Rec."Completed At") { ApplicationArea = All; }
                field("Attempt Count"; Rec."Attempt Count") { ApplicationArea = All; }
                field("Max Attempts"; Rec."Max Attempts") { ApplicationArea = All; }
                field("Customer No."; Rec."Customer No.") { ApplicationArea = All; }
                field("Item No."; Rec."Item No.") { ApplicationArea = All; }
                field("Document Type"; Rec."Document Type") { ApplicationArea = All; }
                field("Document No."; Rec."Document No.") { ApplicationArea = All; }
                field("Source Type"; Rec."Source Type") { ApplicationArea = All; }
                field("Source Key"; Rec."Source Key") { ApplicationArea = All; }
                field("Exception Entry No."; Rec."Exception Entry No.") { ApplicationArea = All; }
                field("Correlation ID"; Rec."Correlation ID") { ApplicationArea = All; }
                field("Last Error"; Rec."Last Error") { ApplicationArea = All; }
            }
        }
    }
}
