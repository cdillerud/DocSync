page 70649 "GPI EOD Invoice Batch Options"
{
    Caption = 'Gamer EOD Invoice Batch Options';
    PageType = StandardDialog;
    ApplicationArea = All;

    layout
    {
        area(Content)
        {
            group(Options)
            {
                Caption = 'Invoice Filters';

                field(PostingDateFrom; PostingDateFrom)
                {
                    ApplicationArea = All;
                    Caption = 'Posting Date From';
                    ToolTip = 'Specifies the first posted sales invoice Posting Date to include. Leave blank to include everything through Posting Date To.';
                }

                field(PostingDateTo; PostingDateTo)
                {
                    ApplicationArea = All;
                    Caption = 'Posting Date To';
                    ToolTip = 'Specifies the last posted sales invoice Posting Date to include. Leave blank to include everything from Posting Date From forward.';
                }

                field(AmountFilterDescription; AmountFilterDescription)
                {
                    ApplicationArea = All;
                    Caption = 'Amount Filter';
                    Editable = false;
                    ToolTip = 'The end-of-day invoice batch always filters Amount not equal to zero.';
                }
            }
        }
    }

    trigger OnOpenPage()
    begin
        if PostingDateFrom = 0D then
            PostingDateFrom := WorkDate();

        if PostingDateTo = 0D then
            PostingDateTo := PostingDateFrom;

        AmountFilterDescription := 'Amount <> 0';
    end;

    procedure SetDefaultPostingDate(DefaultPostingDate: Date)
    begin
        PostingDateFrom := DefaultPostingDate;
        PostingDateTo := DefaultPostingDate;
    end;

    procedure GetPostingDateFilter(var DateFrom: Date; var DateTo: Date)
    begin
        DateFrom := PostingDateFrom;
        DateTo := PostingDateTo;
    end;

    var
        PostingDateFrom: Date;
        PostingDateTo: Date;
        AmountFilterDescription: Text[30];
}