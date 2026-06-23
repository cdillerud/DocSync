pageextension 70535 "GPI Delivery Log Statement" extends "GPI Document Delivery Log"
{
    actions
    {
        addafter(OpenSourceDocument)
        {
            action(GPIOpenStatementCustomer)
            {
                ApplicationArea = All;
                Caption = 'Open Statement Customer';
                Image = Customer;
                Visible = IsCustomerStatement;
                ToolTip = 'Opens the customer related to this statement delivery entry.';

                trigger OnAction()
                var
                    Customer: Record Customer;
                begin
                    if not Customer.Get(Rec."Source Document No.") then
                        Error('Customer %1 could not be found.', Rec."Source Document No.");

                    Page.Run(Page::"Customer Card", Customer);
                end;
            }
        }
    }

    trigger OnAfterGetRecord()
    begin
        IsCustomerStatement := Rec."Delivery Document Type" = Rec."Delivery Document Type"::"Customer Statement";
    end;

    var
        IsCustomerStatement: Boolean;
}
