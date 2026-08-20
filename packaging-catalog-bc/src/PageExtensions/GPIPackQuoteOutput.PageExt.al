pageextension 71103 "GPI Quote Output" extends "GPI Pack Quote Card"
{
    actions
    {
        addlast(Processing)
        {
            action(PreviewCustomerQuote)
            {
                ApplicationArea = All;
                Caption = 'Customer Quote';
                Image = Print;
                Enabled = Rec.Status = "GPI Pack Quote Stat"::Approved;
                Promoted = true;
                PromotedCategory = Report;
                PromotedIsBig = true;
                ToolTip = 'Previews or prints the approved customer-facing packaging quote without internal cost, margin, guardrail, or approval fields.';

                trigger OnAction()
                var
                    OutputMgt: Codeunit "GPI Quote Output Mgt";
                begin
                    CurrPage.SaveRecord();
                    OutputMgt.PreviewCustomerQuote(Rec);
                end;
            }
            action(DownloadCustomerQuotePdf)
            {
                ApplicationArea = All;
                Caption = 'Download Customer Quote PDF';
                Image = ExportFile;
                Enabled = Rec.Status = "GPI Pack Quote Stat"::Approved;
                Promoted = true;
                PromotedCategory = Report;
                ToolTip = 'Downloads the approved customer-facing packaging quote as a PDF.';

                trigger OnAction()
                var
                    OutputMgt: Codeunit "GPI Quote Output Mgt";
                begin
                    CurrPage.SaveRecord();
                    OutputMgt.DownloadCustomerQuotePdf(Rec);
                end;
            }
        }
    }
}
