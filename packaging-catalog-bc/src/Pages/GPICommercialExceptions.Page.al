page 71120 "GPI Comm Exceptions"
{
    PageType = List;
    SourceTable = "GPI Comm Exception";
    ApplicationArea = All;
    UsageCategory = Lists;
    Caption = 'Commercial Exceptions';
    Editable = true;

    layout
    {
        area(Content)
        {
            repeater(General)
            {
                field("Entry No."; Rec."Entry No.") { ApplicationArea = All; Editable = false; }
                field("Agent Type"; Rec."Agent Type") { ApplicationArea = All; }
                field("Detected At"; Rec."Detected At") { ApplicationArea = All; Editable = false; }
                field(Status; Rec.Status) { ApplicationArea = All; }
                field(Severity; Rec.Severity) { ApplicationArea = All; }
                field("Risk Score"; Rec."Risk Score") { ApplicationArea = All; }
                field("Confidence Score"; Rec."Confidence Score") { ApplicationArea = All; }
                field("Customer No."; Rec."Customer No.") { ApplicationArea = All; }
                field("Item No."; Rec."Item No.") { ApplicationArea = All; }
                field("Document Type"; Rec."Document Type") { ApplicationArea = All; }
                field("Document No."; Rec."Document No.") { ApplicationArea = All; }
                field(Summary; Rec.Summary) { ApplicationArea = All; }
                field("Assigned To"; Rec."Assigned To") { ApplicationArea = All; }
                field(Disposition; Rec.Disposition) { ApplicationArea = All; }
                field("False Positive"; Rec."False Positive") { ApplicationArea = All; }
                field("Reviewed By"; Rec."Reviewed By") { ApplicationArea = All; Editable = false; }
                field("Reviewed At"; Rec."Reviewed At") { ApplicationArea = All; Editable = false; }
            }
        }
        area(FactBoxes)
        {
            part(Evidence; "GPI Comm Evidence")
            {
                ApplicationArea = All;
                SubPageLink = "Exception Entry No." = field("Entry No.");
            }
        }
    }
}
