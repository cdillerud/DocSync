report 70530 "GPI Customer Statement"
{
    Caption = 'GPI Customer Statement';
    UsageCategory = None;
    ApplicationArea = All;
    DataAccessIntent = ReadOnly;
    DefaultRenderingLayout = GPICustomerStatement;

    dataset
    {
        dataitem(Customer; Customer)
        {
            RequestFilterFields = "No.", "Date Filter";

            column(CompanyLogo; CompanyInfo.Picture) { }
            column(CompanyName; CompanyInfo.Name) { }
            column(CompanyAddress; CompanyInfo.Address) { }
            column(CompanyCity; CompanyInfo.City) { }
            column(CompanyState; CompanyInfo.County) { }
            column(CompanyPostCode; CompanyInfo."Post Code") { }
            column(CompanyPhone; CompanyInfo."Phone No.") { }
            column(CompanyHomePage; CompanyInfo."Home Page") { }
            column(CustomerNo; "No.") { }
            column(CustomerName; Name) { }
            column(CustomerAddress; Address) { }
            column(CustomerAddress2; "Address 2") { }
            column(CustomerCity; City) { }
            column(CustomerState; County) { }
            column(CustomerPostCode; "Post Code") { }
            column(StatementStartDate; StatementStartDate) { }
            column(StatementEndDate; StatementEndDate) { }
            column(OpeningBalance; OpeningBalance) { }
            column(EndingBalance; EndingBalance) { }
            column(OutstandingBalance; OutstandingBalance) { }
            column(CurrencyCode; GeneralLedgerSetup."LCY Code") { }
            column(ContactLine; ContactLine) { }

            dataitem(CustLedgerEntry; "Cust. Ledger Entry")
            {
                DataItemLink = "Customer No." = field("No.");

                column(LinePostingDate; "Posting Date") { }
                column(LineDocumentType; LineDocumentType) { }
                column(LineDocumentNo; "Document No.") { }
                column(LineExternalDocumentNo; "External Document No.") { }
                column(LineDescription; Description) { }
                column(LineDueDate; "Due Date") { }
                column(LineAmount; "Original Amt. (LCY)") { }
                column(LineRemainingAmount; "Remaining Amt. (LCY)") { }
                column(LineRunningBalance; RunningBalance) { }

                trigger OnPreDataItem()
                begin
                    SetRange("Posting Date", StatementStartDate, StatementEndDate);
                    RunningBalance := OpeningBalance;
                end;

                trigger OnAfterGetRecord()
                begin
                    CalcFields("Original Amt. (LCY)", "Remaining Amt. (LCY)");
                    RunningBalance += "Original Amt. (LCY)";
                    LineDocumentType := Format("Document Type");
                end;
            }

            trigger OnAfterGetRecord()
            begin
                ResolveStatementDates();
                OpeningBalance := CalculateOriginalAmountLCY("No.", 0D, CalcDate('<-1D>', StatementStartDate));
                EndingBalance := CalculateOriginalAmountLCY("No.", 0D, StatementEndDate);
                OutstandingBalance := CalculateRemainingAmountLCY("No.", StatementEndDate);
                BuildContactLine();
            end;
        }
    }

    requestpage
    {
        SaveValues = false;
    }

    rendering
    {
        layout(GPICustomerStatement)
        {
            Type = RDLC;
            Caption = 'GPI Customer Statement';
            Summary = 'Gamer-owned branded customer statement layout.';
            LayoutFile = 'src/reportlayout/GPICustomerStatementBranded.rdl';
        }
    }

    trigger OnPreReport()
    begin
        CompanyInfo.Get();
        CompanyInfo.CalcFields(Picture);
        GeneralLedgerSetup.Get();
    end;

    local procedure ResolveStatementDates()
    begin
        if Customer.GetFilter("Date Filter") = '' then begin
            StatementEndDate := WorkDate();
            StatementStartDate := CalcDate('<-1M>', StatementEndDate);
        end else begin
            StatementStartDate := Customer.GetRangeMin("Date Filter");
            StatementEndDate := Customer.GetRangeMax("Date Filter");
        end;

        if StatementEndDate < StatementStartDate then
            Error('The statement end date cannot be before the start date.');
    end;

    local procedure CalculateOriginalAmountLCY(CustomerNo: Code[20]; FromDate: Date; ToDate: Date): Decimal
    var
        CustLedgerEntry: Record "Cust. Ledger Entry";
        TotalAmount: Decimal;
    begin
        CustLedgerEntry.SetRange("Customer No.", CustomerNo);
        if FromDate = 0D then
            CustLedgerEntry.SetFilter("Posting Date", '..%1', ToDate)
        else
            CustLedgerEntry.SetRange("Posting Date", FromDate, ToDate);

        if CustLedgerEntry.FindSet() then
            repeat
                CustLedgerEntry.CalcFields("Original Amt. (LCY)");
                TotalAmount += CustLedgerEntry."Original Amt. (LCY)";
            until CustLedgerEntry.Next() = 0;

        exit(TotalAmount);
    end;

    local procedure CalculateRemainingAmountLCY(CustomerNo: Code[20]; ToDate: Date): Decimal
    var
        CustLedgerEntry: Record "Cust. Ledger Entry";
        TotalAmount: Decimal;
    begin
        CustLedgerEntry.SetRange("Customer No.", CustomerNo);
        CustLedgerEntry.SetFilter("Posting Date", '..%1', ToDate);

        if CustLedgerEntry.FindSet() then
            repeat
                CustLedgerEntry.CalcFields("Remaining Amt. (LCY)");
                TotalAmount += CustLedgerEntry."Remaining Amt. (LCY)";
            until CustLedgerEntry.Next() = 0;

        exit(TotalAmount);
    end;

    local procedure BuildContactLine()
    begin
        ContactLine := StrSubstNo(
            'Please contact Gamer Packaging at %1 with any questions regarding this statement.',
            CompanyInfo."Phone No.");
    end;

    var
        CompanyInfo: Record "Company Information";
        GeneralLedgerSetup: Record "General Ledger Setup";
        StatementStartDate: Date;
        StatementEndDate: Date;
        OpeningBalance: Decimal;
        EndingBalance: Decimal;
        OutstandingBalance: Decimal;
        RunningBalance: Decimal;
        LineDocumentType: Text[50];
        ContactLine: Text[250];
}
