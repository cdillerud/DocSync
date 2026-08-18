page 71007 "GPI Pricing Guards"
{
    PageType = List;
    SourceTable = "GPI Pricing Guard";
    ApplicationArea = All;
    UsageCategory = Administration;
    Caption = 'GPI Pricing Guardrails';

    layout
    {
        area(Content)
        {
            repeater(General)
            {
                field(Enabled; Rec.Enabled)
                {
                    ApplicationArea = All;
                }
                field("Customer No."; Rec."Customer No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the customer protected by this rule. Leave blank to apply to all customers.';
                }
                field("Item No."; Rec."Item No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the item protected by this rule. Leave blank to apply to all items.';
                }
                field("Rule Type"; Rec."Rule Type")
                {
                    ApplicationArea = All;
                }
                field("Locked Sell Price"; Rec."Locked Sell Price")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the protected sell price for Fixed Price rules. Leave zero for Special Pricing rules.';
                }
                field("Effective From"; Rec."Effective From")
                {
                    ApplicationArea = All;
                }
                field("Effective To"; Rec."Effective To")
                {
                    ApplicationArea = All;
                }
                field(Approver; Rec.Approver)
                {
                    ApplicationArea = All;
                }
                field(Notes; Rec.Notes)
                {
                    ApplicationArea = All;
                }
                field("Entry No."; Rec."Entry No.")
                {
                    ApplicationArea = All;
                    Editable = false;
                    Visible = false;
                }
            }
        }
    }
}
