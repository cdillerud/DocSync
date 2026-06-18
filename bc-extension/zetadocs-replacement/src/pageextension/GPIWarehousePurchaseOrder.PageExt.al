pageextension 70516 "GPI Warehouse PO Ext" extends "Purchase Order"
{
    actions
    {
        addfirst(Processing)
        {
            action(GPIPreviewWarehousePO)
            {
                ApplicationArea = All;
                Caption = 'Preview Warehouse Purchase Order';
                Image = Print;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;
                ToolTip = 'Previews the Gamer-owned warehouse Purchase Order without creating an email or delivery record.';

                trigger OnAction()
                var
                    WarehousePOEmail: Codeunit "GPI Warehouse PO Email";
                    PurchaseHeader: Record "Purchase Header";
                begin
                    CurrPage.SaveRecord();
                    Commit();
                    PurchaseHeader.Get(Rec."Document Type", Rec."No.");
                    WarehousePOEmail.Preview(PurchaseHeader);
                end;
            }

            action(GPIEmailWarehousePO)
            {
                ApplicationArea = All;
                Caption = 'Email Warehouse Purchase Order';
                Image = Email;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;
                ToolTip = 'Creates the Gamer-owned warehouse Purchase Order PDF and opens an email from the current Business Central user for review.';

                trigger OnAction()
                var
                    WarehousePOEmail: Codeunit "GPI Warehouse PO Email";
                    PurchaseHeader: Record "Purchase Header";
                begin
                    CurrPage.SaveRecord();
                    Commit();
                    PurchaseHeader.Get(Rec."Document Type", Rec."No.");
                    WarehousePOEmail.OpenDraft(PurchaseHeader);
                    CurrPage.Update(false);
                end;
            }

            action(GPIWarehousePODeliveryLog)
            {
                ApplicationArea = All;
                Caption = 'Warehouse PO Delivery Log';
                Image = Log;
                ToolTip = 'Shows Gamer document delivery records for this Purchase Order.';

                trigger OnAction()
                var
                    DeliveryLog: Record "GPI Document Delivery Log";
                begin
                    DeliveryLog.SetRange("Source Table ID", Database::"Purchase Header");
                    DeliveryLog.SetRange("Source Document Type", Format(Rec."Document Type"));
                    DeliveryLog.SetRange("Source Document No.", Rec."No.");
                    Page.Run(Page::"GPI Document Delivery Log", DeliveryLog);
                end;
            }

            action(GPIWarehousePORoutingRules)
            {
                ApplicationArea = All;
                Caption = 'Warehouse PO Routing Rules';
                Image = Setup;
                RunObject = page "GPI Document Routing Rules";
                ToolTip = 'Opens vendor, location, and document-specific recipient rules.';
            }

            action(GPIWarehousePOSentHistory)
            {
                ApplicationArea = All;
                Caption = 'Warehouse PO Sent Email History';
                Image = Email;
                ToolTip = 'Shows native Business Central sent emails related to this Purchase Order.';

                trigger OnAction()
                var
                    Email: Codeunit Email;
                begin
                    Email.OpenSentEmails(Rec);
                end;
            }
        }
    }
}
