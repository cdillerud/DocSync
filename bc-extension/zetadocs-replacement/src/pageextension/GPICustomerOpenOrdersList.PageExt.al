pageextension 70581 "GPI Customer Open Order List" extends "Customer List"
{
    actions
    {
        addlast(Processing)
        {
            action(GPIBatchOpenOrderStatus)
            {
                ApplicationArea = All;
                Caption = 'Gamer Send Open Order Status Batch';
                Image = Email;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;
                ToolTip = 'Sends a Customer Open Order Status PDF to each selected or filtered customer that has outstanding Sales Order item lines and a resolved recipient.';

                trigger OnAction()
                var
                    OpenOrderEmail: Codeunit "GPI Customer Open Order Email";
                    SelectedCustomers: Record Customer;
                begin
                    CurrPage.SetSelectionFilter(SelectedCustomers);
                    OpenOrderEmail.SendOpenOrderBatch(SelectedCustomers);
                end;
            }
        }
    }
}
