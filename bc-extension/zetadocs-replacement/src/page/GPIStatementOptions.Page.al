page 70514 "GPI Statement Options"
{
    Caption = 'Customer Statement Options';
    PageType = StandardDialog;
    ApplicationArea = All;

    layout
    {
        area(Content)
        {
            group(Period)
            {
                Caption = 'Statement Period';

                field(StartDate; StartDate)
                {
                    ApplicationArea = All;
                    Caption = 'Start Date';
                    ToolTip = 'Specifies the first posting date included on the customer statement.';
                }

                field(EndDate; EndDate)
                {
                    ApplicationArea = All;
                    Caption = 'End Date';
                    ToolTip = 'Specifies the final posting date included on the customer statement.';
                }
            }
        }
    }

    trigger OnOpenPage()
    begin
        if EndDate = 0D then
            EndDate := WorkDate();
        if StartDate = 0D then
            StartDate := CalcDate('<-1M>', EndDate);
    end;

    trigger OnQueryClosePage(CloseAction: Action): Boolean
    begin
        if CloseAction = Action::OK then begin
            if StartDate = 0D then
                Error('Enter a statement start date.');
            if EndDate = 0D then
                Error('Enter a statement end date.');
            if EndDate < StartDate then
                Error('The statement end date cannot be before the start date.');
        end;
        exit(true);
    end;

    procedure SetDates(NewStartDate: Date; NewEndDate: Date)
    begin
        StartDate := NewStartDate;
        EndDate := NewEndDate;
    end;

    procedure GetDates(var SelectedStartDate: Date; var SelectedEndDate: Date)
    begin
        SelectedStartDate := StartDate;
        SelectedEndDate := EndDate;
    end;

    var
        StartDate: Date;
        EndDate: Date;
}
