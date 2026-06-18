pageextension 70530 "GPI Delivery Log Credit Memo" extends "GPI Document Delivery Log"
{
    actions
    {
        addafter(OpenSourceDocument)
        {
            action(GPIOpenPostedCreditMemo)
            {
                ApplicationArea = All;
                Caption = 'Open Posted Credit Memo';
                Image = Document;
                Visible = IsCreditMemo;
                ToolTip = 'Opens the posted sales credit memo related to this delivery entry.';

                trigger OnAction()
                var
                    SalesCreditMemoHeader: Record "Sales Cr.Memo Header";
                begin
                    if not SalesCreditMemoHeader.Get(Rec."Source Document No.") then
                        Error('Posted Sales Credit Memo %1 could not be found.', Rec."Source Document No.");

                    Page.Run(Page::"Posted Sales Credit Memo", SalesCreditMemoHeader);
                end;
            }
        }
    }

    trigger OnAfterGetRecord()
    begin
        IsCreditMemo := Rec."Delivery Document Type" = Rec."Delivery Document Type"::"Credit Memo";
    end;

    var
        IsCreditMemo: Boolean;
}
