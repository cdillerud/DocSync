pageextension 70580 "GPI Customer Open Orders" extends "Customer Card"
{
    actions
    {
        addlast(Processing)
        {
            group(GPIOpenOrderStatus)
            {
                Caption = 'Gamer Open Orders';
                Image = Documents;

                action(GPIEmailOpenOrderStatus)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Email Open Order Status';
                    Image = Email;
                    Promoted = true;
                    PromotedCategory = Process;
                    PromotedIsBig = true;
                    ToolTip = 'Creates the current Customer Open Order Status PDF and opens an email from the current Business Central user.';

                    trigger OnAction()
                    var
                        OpenOrderEmail: Codeunit "GPI Customer Open Order Email";
                        Customer: Record Customer;
                    begin
                        CurrPage.SaveRecord();
                        CommitPageChanges();
                        Customer.Get(Rec."No.");
                        OpenOrderEmail.OpenOpenOrderDraft(Customer);
                        CurrPage.Update(false);
                    end;
                }

                action(GPIPreviewOpenOrderStatus)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Preview Open Order Status';
                    Image = Print;
                    ToolTip = 'Previews the Customer Open Order Status without creating an email or Delivery Log entry.';

                    trigger OnAction()
                    var
                        OpenOrderEmail: Codeunit "GPI Customer Open Order Email";
                        Customer: Record Customer;
                    begin
                        CurrPage.SaveRecord();
                        CommitPageChanges();
                        Customer.Get(Rec."No.");
                        OpenOrderEmail.PreviewOpenOrderStatus(Customer);
                    end;
                }

                action(GPIViewOpenOrderDeliveryLog)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Open Order Delivery Log';
                    Image = Log;
                    ToolTip = 'Shows Customer Open Order Status delivery records for this customer.';

                    trigger OnAction()
                    var
                        DeliveryLog: Record "GPI Document Delivery Log";
                    begin
                        DeliveryLog.SetRange("Delivery Document Type", DeliveryLog."Delivery Document Type"::"Customer Open Order Status");
                        DeliveryLog.SetRange("Source Table ID", Database::Customer);
                        DeliveryLog.SetRange("Source Document No.", Rec."No.");
                        Page.Run(Page::"GPI Document Delivery Log", DeliveryLog);
                    end;
                }

                action(GPIViewOpenOrderRoutingRules)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Open Order Routing Rules';
                    Image = Setup;
                    RunObject = page "GPI Document Routing Rules";
                    ToolTip = 'Opens customer-specific and generic Customer Open Order Status routing rules.';
                }

                action(GPIViewOpenOrderSentEmails)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Open Order Sent Emails';
                    Image = Email;
                    ToolTip = 'Shows native Business Central sent emails related to this customer.';

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

    local procedure CommitPageChanges()
    var
        DeliveryTransportMgt: Codeunit "GPI Delivery Transport Mgt.";
    begin
        DeliveryTransportMgt.CommitChanges();
    end;
}
