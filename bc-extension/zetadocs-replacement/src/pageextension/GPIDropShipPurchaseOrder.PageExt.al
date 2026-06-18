pageextension 70514 "GPI Drop Ship Purchase Order Ext" extends "Purchase Order"
{
    actions
    {
        addlast(Processing)
        {
            group(GPIDropShipDocuments)
            {
                Caption = 'Gamer Documents';
                Image = Documents;
                Visible = IsDropShipPurchaseOrder;

                action(GPIEmailDropShipPurchaseOrder)
                {
                    ApplicationArea = All;
                    Caption = 'Email Drop Ship Purchase Order';
                    Image = Email;
                    Promoted = true;
                    PromotedCategory = Process;
                    PromotedIsBig = true;
                    ToolTip = 'Creates the Gamer-owned drop-ship Purchase Order PDF and opens an email from the current Business Central user for review.';

                    trigger OnAction()
                    var
                        DropShipPOEmail: Codeunit "GPI Drop Ship PO Email";
                        PurchaseHeader: Record "Purchase Header";
                    begin
                        CurrPage.SaveRecord();
                        PurchaseHeader.Get(Rec."Document Type", Rec."No.");
                        DropShipPOEmail.OpenDraft(PurchaseHeader);
                        CurrPage.Update(false);
                    end;
                }

                action(GPIPreviewDropShipPurchaseOrder)
                {
                    ApplicationArea = All;
                    Caption = 'Preview Drop Ship Purchase Order';
                    Image = Print;
                    Promoted = true;
                    PromotedCategory = Process;
                    ToolTip = 'Previews the Gamer-owned drop-ship Purchase Order without creating an email or delivery record.';

                    trigger OnAction()
                    var
                        DropShipPOEmail: Codeunit "GPI Drop Ship PO Email";
                        PurchaseHeader: Record "Purchase Header";
                    begin
                        CurrPage.SaveRecord();
                        PurchaseHeader.Get(Rec."Document Type", Rec."No.");
                        DropShipPOEmail.Preview(PurchaseHeader);
                    end;
                }

                action(GPIDropShipPODeliveryLog)
                {
                    ApplicationArea = All;
                    Caption = 'Document Delivery Log';
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

                action(GPIDropShipPORoutingRules)
                {
                    ApplicationArea = All;
                    Caption = 'Document Routing Rules';
                    Image = Setup;
                    RunObject = page "GPI Document Routing Rules";
                    ToolTip = 'Opens vendor, location, and document-specific recipient rules.';
                }

                action(GPIDropShipPOSentEmailHistory)
                {
                    ApplicationArea = All;
                    Caption = 'Sent Email History';
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

    trigger OnAfterGetRecord()
    begin
        IsDropShipPurchaseOrder := Rec."Location Code" = '00';
    end;

    var
        IsDropShipPurchaseOrder: Boolean;
}
