report 70531 "GPI Email Customer Statements"
{
    Caption = 'Email Customer Statements';
    ProcessingOnly = true;
    ApplicationArea = All;
    UsageCategory = Tasks;

    dataset
    {
        dataitem(Customer; Customer)
        {
            RequestFilterFields = "No.", "Customer Posting Group", "Salesperson Code";

            trigger OnPreDataItem()
            begin
                StatementEmail.SendStatementBatch(Customer, StartDate, EndDate);
                CurrReport.Break();
            end;
        }
    }

    requestpage
    {
        SaveValues = true;

        layout
        {
            area(Content)
            {
                group(StatementPeriod)
                {
                    Caption = 'Statement Period';

                    field(StartDate; StartDate)
                    {
                        ApplicationArea = All;
                        Caption = 'Start Date';
                        ToolTip = 'Specifies the first posting date included on each statement.';
                    }

                    field(EndDate; EndDate)
                    {
                        ApplicationArea = All;
                        Caption = 'End Date';
                        ToolTip = 'Specifies the final posting date included on each statement.';
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
    }

    var
        StatementEmail: Codeunit "GPI Customer Statement Email";
        StartDate: Date;
        EndDate: Date;
}
