page 71100 "GPI Hist Cost Evid"
{
    PageType = List;
    SourceTable = "GPI Hist Cost Buf";
    SourceTableTemporary = true;
    SourceTableView = sorting("Posting Date", "Item Ledger Entry No.") order(descending);
    ApplicationArea = All;
    Caption = 'Historical Posted Landed-Cost Evidence';
    Editable = false;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;

    layout
    {
        area(Content)
        {
            repeater(Evidence)
            {
                field("Posting Date"; Rec."Posting Date")
                {
                    ApplicationArea = All;
                    ToolTip = 'Shows the latest posted cost date included in this historical item-ledger cost group.';
                }
                field("Item Ledger Entry No."; Rec."Item Ledger Entry No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Shows the Business Central Item Ledger Entry that ties the direct item cost and posted item charges together.';
                }
                field("Quantity EA"; Rec."Quantity EA")
                {
                    ApplicationArea = All;
                }
                field("Direct Actual Cost"; Rec."Direct Actual Cost")
                {
                    ApplicationArea = All;
                    ToolTip = 'Shows posted direct item cost for the historical receipt group.';
                }
                field(Freight; Rec.Freight)
                {
                    ApplicationArea = All;
                    ToolTip = 'Shows posted FREIGHT item charges assigned to the historical receipt group.';
                }
                field(Customs; Rec.Customs)
                {
                    ApplicationArea = All;
                    ToolTip = 'Shows posted CUSTOMS item charges assigned to the historical receipt group.';
                }
                field(Drayage; Rec.Drayage)
                {
                    ApplicationArea = All;
                    ToolTip = 'Shows posted DRAYAGE item charges assigned to the historical receipt group.';
                }
                field("Other Charges"; Rec."Other Charges")
                {
                    ApplicationArea = All;
                }
                field("Total Charges"; Rec."Total Charges")
                {
                    ApplicationArea = All;
                    Style = Strong;
                }
                field("Total Actual Cost"; Rec."Total Actual Cost")
                {
                    ApplicationArea = All;
                    Style = Strong;
                }
                field("Direct Cost per EA"; Rec."Direct Cost per EA")
                {
                    ApplicationArea = All;
                }
                field("Charges per EA"; Rec."Charges per EA")
                {
                    ApplicationArea = All;
                }
                field("Landed Cost per EA"; Rec."Landed Cost per EA")
                {
                    ApplicationArea = All;
                    Style = Strong;
                }
                field("M Qty. per UOM"; Rec."M Qty. per UOM")
                {
                    ApplicationArea = All;
                }
                field("Landed Cost per M"; Rec."Landed Cost per M")
                {
                    ApplicationArea = All;
                    Style = Strong;
                }
                field("Charge Codes"; Rec."Charge Codes")
                {
                    ApplicationArea = All;
                }
            }
        }
    }

    trigger OnOpenPage()
    begin
        if ItemNo = '' then
            Error('BC Item No. is required to show historical landed-cost evidence.');

        HistCostMgt.BuildHistoricalEvidence(ItemNo, Rec);

        if Rec.IsEmpty() then
            Message('No posted item-charge landed-cost evidence was found for BC Item %1.', ItemNo)
        else
            Message(
                'This page shows historical posted Business Central cost evidence for %1. It does not represent a current freight quote or current landed-cost rate.',
                ItemNo);
    end;

    procedure SetItemNo(NewItemNo: Code[20])
    begin
        ItemNo := NewItemNo;
    end;

    var
        HistCostMgt: Codeunit "GPI Hist Cost Mgt";
        ItemNo: Code[20];
}
