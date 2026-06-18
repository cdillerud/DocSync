pageextension 70518 "GPI WH Receiving PO Ext" extends "Purchase Order"
{
    layout
    {
        addlast(General)
        {
            field(GPIWarehouseReceiptDate; Rec."GPI WH Receipt Date")
            {
                ApplicationArea = All;
                Caption = 'Warehouse Receipt Date';
                ToolTip = 'Specifies the date the warehouse should expect to receive this purchase order.';
            }
        }
    }

    actions
    {
        addfirst(Processing)
        {
            action(GPIPreviewWarehouseReceiving)
            {
                ApplicationArea = All;
                Caption = 'Preview Warehouse Receiving Notice';
                Image = Print;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;
                ToolTip = 'Previews the Gamer-owned warehouse receiving notice without creating an email or delivery record.';

                trigger OnAction()
                var
                    ReceivingEmail: Codeunit "GPI WH Receiving Email";
                    PurchaseHeader: Record "Purchase Header";
                begin
                    CurrPage.SaveRecord();
                    Commit();
                    PurchaseHeader.Get(Rec."Document Type", Rec."No.");
                    ReceivingEmail.Preview(PurchaseHeader);
                end;
            }

            action(GPIEmailWarehouseReceiving)
            {
                ApplicationArea = All;
                Caption = 'Email Warehouse Receiving Notice';
                Image = Email;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;
                ToolTip = 'Creates the warehouse receiving notice PDF and opens an email from the current Business Central user for review.';

                trigger OnAction()
                var
                    ReceivingEmail: Codeunit "GPI WH Receiving Email";
                    PurchaseHeader: Record "Purchase Header";
                begin
                    CurrPage.SaveRecord();
                    Commit();
                    PurchaseHeader.Get(Rec."Document Type", Rec."No.");
                    ReceivingEmail.OpenDraft(PurchaseHeader);
                    CurrPage.Update(false);
                end;
            }

            action(GPIWarehouseReceivingLog)
            {
                ApplicationArea = All;
                Caption = 'Receiving Notice Delivery Log';
                Image = Log;
                ToolTip = 'Shows Gamer receiving notice delivery records for this Purchase Order.';

                trigger OnAction()
                var
                    DeliveryLog: Record "GPI Document Delivery Log";
                begin
                    DeliveryLog.SetRange("Delivery Document Type", Enum::"GPI Delivery Document Type"::"Warehouse Receiving Notice");
                    DeliveryLog.SetRange("Source Table ID", Database::"Purchase Header");
                    DeliveryLog.SetRange("Source Document No.", Rec."No.");
                    Page.Run(Page::"GPI Document Delivery Log", DeliveryLog);
                end;
            }

            action(GPIWarehouseReceivingRules)
            {
                ApplicationArea = All;
                Caption = 'Receiving Notice Routing Rules';
                Image = Setup;
                RunObject = page "GPI Document Routing Rules";
                ToolTip = 'Opens location and purchase-order-specific recipient rules.';
            }

            action(GPIWarehouseReceivingHistory)
            {
                ApplicationArea = All;
                Caption = 'Receiving Notice Sent Email History';
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
