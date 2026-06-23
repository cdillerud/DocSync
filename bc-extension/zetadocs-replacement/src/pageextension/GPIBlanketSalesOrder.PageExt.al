pageextension 70512 "GPI Blanket Sales Order Ext" extends "Blanket Sales Order"
{
    actions
    {
        addlast(Processing)
        {
            group(GPIDocuments)
            {
                Caption = 'Gamer Documents';
                Image = Documents;

                action(GPIEmailBlanketSalesOrder)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Email Blanket Sales Order';
                    Image = Email;
                    Promoted = true;
                    PromotedCategory = Process;
                    PromotedIsBig = true;
                    ToolTip = 'Creates the Gamer-owned Blanket Sales Order PDF and opens an email from the current Business Central user for review.';

                    trigger OnAction()
                    var
                        BlanketSalesOrderEmail: Codeunit "GPI Blanket Sales Order Email";
                        SalesHeader: Record "Sales Header";
                    begin
                        CurrPage.SaveRecord();
                        SalesHeader.Get(Rec."Document Type", Rec."No.");
                        BlanketSalesOrderEmail.OpenDraft(SalesHeader);
                        CurrPage.Update(false);
                    end;
                }

                action(GPIPreviewBlanketSalesOrder)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Preview Blanket Sales Order';
                    Image = Print;
                    Promoted = true;
                    PromotedCategory = Process;
                    ToolTip = 'Previews the Gamer-owned Blanket Sales Order without creating an email or delivery record.';

                    trigger OnAction()
                    var
                        BlanketSalesOrderEmail: Codeunit "GPI Blanket Sales Order Email";
                        SalesHeader: Record "Sales Header";
                    begin
                        CurrPage.SaveRecord();
                        SalesHeader.Get(Rec."Document Type", Rec."No.");
                        BlanketSalesOrderEmail.Preview(SalesHeader);
                    end;
                }

                action(GPIBlanketDeliveryLog)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Document Delivery Log';
                    Image = Log;
                    ToolTip = 'Shows Gamer document delivery records for this Blanket Sales Order.';

                    trigger OnAction()
                    var
                        DeliveryLog: Record "GPI Document Delivery Log";
                    begin
                        DeliveryLog.SetRange("Source Table ID", Database::"Sales Header");
                        DeliveryLog.SetRange("Source Document Type", Format(Rec."Document Type"));
                        DeliveryLog.SetRange("Source Document No.", Rec."No.");
                        Page.Run(Page::"GPI Document Delivery Log", DeliveryLog);
                    end;
                }

                action(GPIBlanketRoutingRules)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Document Routing Rules';
                    Image = Setup;
                    RunObject = page "GPI Document Routing Rules";
                    ToolTip = 'Opens customer, location, and document-specific recipient rules.';
                }

                action(GPIBlanketSentEmailHistory)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Sent Email History';
                    Image = Email;
                    ToolTip = 'Shows native Business Central sent emails related to this Blanket Sales Order.';

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
