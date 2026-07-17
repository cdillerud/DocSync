pageextension 70717 "GPI UAT Sample Pack Actions" extends "GPI Document Delivery Log"
{
    actions
    {
        addlast(Processing)
        {
            action(GenerateUATSamplePack)
            {
                ApplicationArea = All;
                Caption = 'Generate UAT Sample Pack';
                Image = Documents;
                ToolTip = 'Creates persistent sandbox sample documents and seven reviewable PDFs without sending email or uploading to SharePoint.';

                trigger OnAction()
                var
                    SamplePack: Codeunit "GPI UAT Sample Pack";
                    DeliveryLog: Record "GPI Document Delivery Log";
                    PackId: Text[50];
                begin
                    if not Confirm(
                        'Create a persistent UAT sample pack in this sandbox? This creates sample source records and seven Delivery Log PDFs. It does not send email or upload to SharePoint.',
                        false)
                    then
                        exit;

                    PackId := SamplePack.GenerateSamplePack(true);
                    Message(
                        'UAT sample pack %1 was created. Select each entry and choose Download PDF for visual review.',
                        PackId);

                    DeliveryLog.SetRange("External Delivery ID", PackId);
                    Page.Run(Page::"GPI Document Delivery Log", DeliveryLog);
                end;
            }

            action(OpenUATSamplePacks)
            {
                ApplicationArea = All;
                Caption = 'Open UAT Sample Packs';
                Image = View;
                ToolTip = 'Shows persistent PDFs created by the sandbox UAT sample pack generator.';

                trigger OnAction()
                var
                    DeliveryLog: Record "GPI Document Delivery Log";
                begin
                    DeliveryLog.SetRange("Sender Policy", 'UAT Sample Pack');
                    Page.Run(Page::"GPI Document Delivery Log", DeliveryLog);
                end;
            }
        }
    }
}
