pageextension 70513 "GPI Delivery Log Blanket Ext" extends "GPI Document Delivery Log"
{
    actions
    {
        addafter(OpenSourceDocument)
        {
            action(OpenBlanketSalesOrder)
            {
                ApplicationArea = All;
                Caption = 'Open Blanket Sales Order';
                Image = Document;
                Visible = IsBlanketSalesOrder;
                ToolTip = 'Opens the Blanket Sales Order related to this delivery entry.';

                trigger OnAction()
                var
                    SalesHeader: Record "Sales Header";
                begin
                    if not SalesHeader.Get(SalesHeader."Document Type"::"Blanket Order", Rec."Source Document No.") then
                        Error('Blanket Sales Order %1 could not be found.', Rec."Source Document No.");

                    Page.Run(Page::"Blanket Sales Order", SalesHeader);
                end;
            }
        }
    }

    trigger OnAfterGetRecord()
    begin
        IsBlanketSalesOrder := Rec."Delivery Document Type" = Rec."Delivery Document Type"::"Blanket Sales Order";
    end;

    var
        IsBlanketSalesOrder: Boolean;
}
