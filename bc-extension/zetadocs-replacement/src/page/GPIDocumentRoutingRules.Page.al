page 70512 "GPI Document Routing Rules"
{
    Caption = 'GPI Document Routing Rules';
    PageType = List;
    SourceTable = "GPI Document Routing Rule";
    SourceTableView = sorting(Enabled, "Delivery Document Type", Priority, "Entry No.") order(ascending);
    ApplicationArea = All;
    UsageCategory = Administration;

    layout
    {
        area(Content)
        {
            repeater(Rules)
            {
                field(Enabled; Rec.Enabled)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies whether this routing rule can be applied.';
                }

                field(Priority; Rec.Priority)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the order in which matching rules are applied. Lower numbers are applied first.';
                }

                field("Rule Name"; Rec."Rule Name")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies a descriptive name for the rule.';
                }

                field("Delivery Document Type"; Rec."Delivery Document Type")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies which Gamer document type the rule applies to.';
                }

                field("Customer No."; Rec."Customer No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the customer the rule applies to. Leave blank to match every customer.';
                }

                field("Vendor No."; Rec."Vendor No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the vendor the rule applies to. Leave blank to match every vendor.';
                }

                field("Location Code"; Rec."Location Code")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the location the rule applies to. Leave blank to match every location.';
                }

                field(Action; Rec.Action)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies whether the rule adds recipients to the defaults or replaces all defaults.';
                }

                field("To Addresses"; Rec."To Addresses")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies one or more To addresses separated by semicolons.';
                }

                field("CC Addresses"; Rec."CC Addresses")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies one or more CC addresses separated by semicolons.';
                }

                field("BCC Addresses"; Rec."BCC Addresses")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies one or more BCC addresses separated by semicolons.';
                }

                field("Effective Start Date"; Rec."Effective Start Date")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the first date on which the rule is active. Leave blank for no start limit.';
                }

                field("Effective End Date"; Rec."Effective End Date")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the last date on which the rule is active. Leave blank for no end limit.';
                }

                field(Notes; Rec.Notes)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies administrative notes about the routing exception.';
                }
            }
        }
    }
}
