report 71103 "GPI Pack Quote Rpt"
{
    Caption = 'Gamer Packaging Quote';
    ApplicationArea = All;
    UsageCategory = None;
    DefaultRenderingLayout = CustomerQuote;

    dataset
    {
        dataitem(Quote; "GPI Pack Quote")
        {
            RequestFilterFields = "Entry No.";

            column(CompanyName; CompanyInfo.Name) { }
            column(CompanyAddress; CompanyInfo.Address) { }
            column(CompanyAddress2; CompanyInfo."Address 2") { }
            column(CompanyCityStateZip; CompanyCityStateZip) { }
            column(CompanyPhone; CompanyInfo."Phone No.") { }
            column(CompanyEmail; CompanyInfo."E-Mail") { }
            column(CompanyWeb; CompanyInfo."Home Page") { }
            column(QuoteNo; "Entry No.") { }
            column(QuoteDate; "Quote Date") { }
            column(ExpirationDate; "Expiration Date") { }
            column(CustomerNo; "Customer No.") { }
            column(CustomerName; "Customer Name") { }
            column(CustomerAddress; Customer.Address) { }
            column(CustomerAddress2; Customer."Address 2") { }
            column(CustomerCityStateZip; CustomerCityStateZip) { }
            column(QuoteDescription; Description) { }
            column(TotalSell; "Total Sell") { }

            dataitem(QuoteLine; "GPI Pack Quote Line")
            {
                DataItemLinkReference = Quote;
                DataItemLink = "Quote Entry No." = field("Entry No.");
                DataItemTableView = sorting("Quote Entry No.", "Line No.");

                column(LineNo; "Line No.") { }
                column(ProductNo; "Product No.") { }
                column(BCItemNo; "BC Item No.") { }
                column(LineDescription; LineDisplayDescription) { }
                column(Quantity; Quantity) { }
                column(UOMCode; "UOM Code") { }
                column(UnitSellPrice; "Proposed Sell Price") { }
                column(ExtendedSell; "Extended Sell") { }

                trigger OnAfterGetRecord()
                begin
                    BuildLineDescription(QuoteLine);
                end;
            }

            trigger OnAfterGetRecord()
            begin
                if Status <> "GPI Pack Quote Stat"::Approved then
                    Error('Customer quote output is available only for approved packaging quotes.');

                CalcFields("Customer Name", "Total Sell");
                Clear(Customer);
                CustomerCityStateZip := '';
                if Customer.Get("Customer No.") then
                    CustomerCityStateZip := BuildCityStateZip(Customer.City, Customer.County, Customer."Post Code");
            end;
        }
    }

    rendering
    {
        layout(CustomerQuote)
        {
            Type = RDLC;
            LayoutFile = 'Layouts/GPIPackQuote.rdlc';
            Caption = 'Customer Quote';
            Summary = 'Customer-facing Gamer Packaging quote.';
        }
    }

    trigger OnPreReport()
    begin
        CompanyInfo.Get();
        CompanyCityStateZip := BuildCityStateZip(CompanyInfo.City, CompanyInfo.County, CompanyInfo."Post Code");
    end;

    var
        CompanyInfo: Record "Company Information";
        Customer: Record Customer;
        Product: Record "GPI Pack Product";
        CompanyCityStateZip: Text[100];
        CustomerCityStateZip: Text[100];
        LineDisplayDescription: Text[500];

    local procedure BuildLineDescription(QuoteLineRec: Record "GPI Pack Quote Line")
    var
        ProductSpec: Text[250];
    begin
        LineDisplayDescription := QuoteLineRec.Description;
        ProductSpec := '';
        Clear(Product);

        if Product.Get(QuoteLineRec."Product No.") then begin
            AddSpec(ProductSpec, Product.Material);
            if Product.Capacity <> 0 then
                AddSpec(ProductSpec, StrSubstNo('%1 %2', Product.Capacity, Product."Capacity UOM"));
            AddSpec(ProductSpec, Product.Style);
            AddSpec(ProductSpec, Product.Color);
            AddSpec(ProductSpec, Product.Finish);
        end;

        if ProductSpec <> '' then begin
            if LineDisplayDescription <> '' then
                LineDisplayDescription := CopyStr(LineDisplayDescription + ' | ' + ProductSpec, 1, MaxStrLen(LineDisplayDescription))
            else
                LineDisplayDescription := ProductSpec;
        end;
    end;

    local procedure AddSpec(var SpecText: Text[250]; Value: Text)
    begin
        if Value = '' then
            exit;

        if SpecText = '' then
            SpecText := CopyStr(Value, 1, MaxStrLen(SpecText))
        else
            SpecText := CopyStr(SpecText + ' | ' + Value, 1, MaxStrLen(SpecText));
    end;

    local procedure BuildCityStateZip(City: Text; StateCode: Text; PostCode: Text): Text[100]
    var
        Result: Text[100];
    begin
        Result := CopyStr(City, 1, MaxStrLen(Result));
        if StateCode <> '' then begin
            if Result <> '' then
                Result := CopyStr(Result + ', ', 1, MaxStrLen(Result));
            Result := CopyStr(Result + StateCode, 1, MaxStrLen(Result));
        end;
        if PostCode <> '' then begin
            if Result <> '' then
                Result := CopyStr(Result + ' ', 1, MaxStrLen(Result));
            Result := CopyStr(Result + PostCode, 1, MaxStrLen(Result));
        end;
        exit(Result);
    end;
}
