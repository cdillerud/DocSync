page 71009 "GPI Pack Quotes"
{
    PageType = List;
    SourceTable = "GPI Pack Quote";
    ApplicationArea = All;
    UsageCategory = Lists;
    Caption = 'GPI Packaging Quotes';
    CardPageId = "GPI Pack Quote Card";

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
                field("Quote Date"; Rec."Quote Date")
                {
                    ApplicationArea = All;
                }
                field("Customer No."; Rec."Customer No.")
                {
                    ApplicationArea = All;
                }
                field("Customer Name"; Rec."Customer Name")
                {
                    ApplicationArea = All;
                }
                field(Description; Rec.Description)
                {
                    ApplicationArea = All;
                }
                field(Status; Rec.Status)
                {
                    ApplicationArea = All;
                }
                field("Line Count"; Rec."Line Count")
                {
                    ApplicationArea = All;
                }
                field("Approval Line Count"; Rec."Approval Line Count")
                {
                    ApplicationArea = All;
                }
                field("Expiration Date"; Rec."Expiration Date")
                {
                    ApplicationArea = All;
                }
                field("Last Evaluated At"; Rec."Last Evaluated At")
                {
                    ApplicationArea = All;
                }
            }
        }
    }
}
