pageextension 71190 "GPI Quote Action Fix" extends "GPI Pack Quote Card"
{
    actions
    {
        modify(EvaluateAll)
        {
            Visible = false;
        }

        addafter(EvaluateAll)
        {
            action(RunGuardrailEvaluation)
            {
                ApplicationArea = All;
                Caption = 'Run Guardrail Evaluation';
                Image = Calculate;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;

                trigger OnAction()
                var
                    QuoteMgt: Codeunit "GPI Pack Quote Mgt";
                begin
                    CurrPage.SaveRecord();
                    QuoteMgt.EvaluateQuote(Rec);

                    Rec.Get(Rec."Entry No.");
                    Rec.CalcFields("Approval Line Count", "Line Count", "Total Landed Cost", "Total Sell", "Gross Profit Total");
                    CurrPage.Update(false);

                    Message(
                        'Guardrail evaluation completed. %1 of %2 line(s) require approval.',
                        Rec."Approval Line Count",
                        Rec."Line Count");
                end;
            }
        }
    }
}
