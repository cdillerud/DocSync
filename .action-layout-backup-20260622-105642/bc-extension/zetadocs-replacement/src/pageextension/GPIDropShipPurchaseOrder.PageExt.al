pageextension 70514 "GPI Purchase Order Docs Ext" extends "Purchase Order"
{
    actions
    {
        addfirst(Processing)
        {
            group(GPIGamerDocuments)
            {
                Caption = 'Gamer Documents';

                group(GPIDropShipDocuments)
                {
                    Caption = 'Drop Ship Purchase Order';
                    Enabled = IsDropShipPurchaseOrder;

                    action(GPIPreviewDropShipPO)
                    {
                        ApplicationArea = All;
                        Caption = 'Gamer Preview Drop Ship PO';
                        Image = Print;
                        ToolTip = 'Previews the Gamer-owned drop-ship Purchase Order without creating an email or delivery record.';

                        trigger OnAction()
                        var
                            DropShipPOEmail: Codeunit "GPI Drop Ship PO Email";
                            PurchaseHeader: Record "Purchase Header";
                        begin
                            CurrPage.SaveRecord();
                            Commit();
                            PurchaseHeader.Get(Rec."Document Type", Rec."No.");
                            DropShipPOEmail.Preview(PurchaseHeader);
                        end;
                    }

                    action(GPIEmailDropShipPO)
                    {
                        ApplicationArea = All;
                        Caption = 'Gamer Email Drop Ship PO';
                        Image = Email;
                        ToolTip = 'Creates the Gamer-owned drop-ship Purchase Order PDF and opens an email from the current Business Central user for review.';

                        trigger OnAction()
                        var
                            DropShipPOEmail: Codeunit "GPI Drop Ship PO Email";
                            PurchaseHeader: Record "Purchase Header";
                        begin
                            CurrPage.SaveRecord();
                            Commit();
                            PurchaseHeader.Get(Rec."Document Type", Rec."No.");
                            DropShipPOEmail.OpenDraft(PurchaseHeader);
                            CurrPage.Update(false);
                        end;
                    }
                }

                group(GPIWarehousePurchaseDocuments)
                {
                    Caption = 'Warehouse Purchase Order';
                    Enabled = IsWarehousePurchaseOrder;

                    action(GPIPreviewWarehousePO)
                    {
                        ApplicationArea = All;
                        Caption = 'Gamer Preview Warehouse PO';
                        Image = Print;
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
                        Caption = 'Gamer Email Warehouse PO';
                        Image = Email;
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
                }

                group(GPIWarehouseReceivingDocuments)
                {
                    Caption = 'Warehouse Receiving Notice';
                    Enabled = IsWarehousePurchaseOrder;

                    action(GPIPreviewWarehouseReceiving)
                    {
                        ApplicationArea = All;
                        Caption = 'Gamer Preview WRN';
                        Image = Print;
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
                        Caption = 'Gamer Email WRN';
                        Image = Email;
                        ToolTip = 'Creates the Gamer-owned warehouse receiving notice PDF and opens an email from the current Business Central user for review.';

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
                }

                group(GPIDocumentHistoryAndSetup)
                {
                    Caption = 'History and Setup';

                    action(GPIPurchaseOrderDeliveryLog)
                    {
                        ApplicationArea = All;
                        Caption = 'Gamer Document Delivery Log';
                        Image = Log;
                        ToolTip = 'Shows all Gamer document delivery records for this Purchase Order.';

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

                    action(GPIPurchaseOrderRoutingRules)
                    {
                        ApplicationArea = All;
                        Caption = 'Gamer Document Routing Rules';
                        Image = Setup;
                        RunObject = page "GPI Document Routing Rules";
                        ToolTip = 'Opens vendor, location, and document-specific recipient rules.';
                    }

                    action(GPIPurchaseOrderSentHistory)
                    {
                        ApplicationArea = All;
                        Caption = 'Gamer Sent Email History';
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
    }

    trigger OnAfterGetRecord()
    begin
        SetDocumentActionState();
    end;

    trigger OnAfterGetCurrRecord()
    begin
        SetDocumentActionState();
    end;

    local procedure SetDocumentActionState()
    begin
        IsDropShipPurchaseOrder := Rec."Location Code" = '00';
        IsWarehousePurchaseOrder := (Rec."Location Code" <> '') and (Rec."Location Code" <> '00');
    end;

    var
        IsDropShipPurchaseOrder: Boolean;
        IsWarehousePurchaseOrder: Boolean;
}
