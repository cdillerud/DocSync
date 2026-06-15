page 70150002 "GPI Delivery Preview"
{
    Caption = 'GPI Order Confirmation Preview';
    PageType = Card;
    SourceTable = "GPI Delivery Preview Buffer";
    SourceTableTemporary = true;
    ApplicationArea = All;
    UsageCategory = None;
    Editable = false;

    layout
    {
        area(Content)
        {
            group(StatusGroup)
            {
                Caption = 'Preflight';

                field(Status; Rec.Status)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies whether GPI Hub resolved the delivery package successfully.';
                }
                field(CanCreateDraft; Rec."Can Create Draft")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies whether the package has all required information for a future email draft.';
                }
                field(Duplicate; Rec.Duplicate)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies whether GPI Hub returned an existing idempotent package.';
                }
                field(PackageID; Rec."Package ID")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the GPI Hub delivery package identifier.';
                }
                field(CorrelationID; Rec."Correlation ID")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the correlation identifier shared by Business Central and GPI Hub.';
                }
            }
            group(EmailGroup)
            {
                Caption = 'Email Preview';

                field(FromAddress; Rec."From Address")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the resolved sender address.';
                }
                field(ToRecipients; Rec."To Recipients")
                {
                    ApplicationArea = All;
                    MultiLine = true;
                    ToolTip = 'Specifies the resolved primary recipients.';
                }
                field(CCRecipients; Rec."CC Recipients")
                {
                    ApplicationArea = All;
                    MultiLine = true;
                    ToolTip = 'Specifies the resolved carbon-copy recipients.';
                }
                field(BCCRecipients; Rec."BCC Recipients")
                {
                    ApplicationArea = All;
                    MultiLine = true;
                    ToolTip = 'Specifies the resolved blind-carbon-copy recipients.';
                }
                field(Subject; Rec.Subject)
                {
                    ApplicationArea = All;
                    MultiLine = true;
                    ToolTip = 'Specifies the rendered email subject.';
                }
                field(Body; Rec.Body)
                {
                    ApplicationArea = All;
                    MultiLine = true;
                    ToolTip = 'Specifies the rendered email body.';
                }
            }
            group(DocumentGroup)
            {
                Caption = 'Document';

                field(RecordNo; Rec."Record No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the source Sales Order number.';
                }
                field(ReportID; Rec."Report ID")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the Business Central report used for the PDF preview.';
                }
                field(FileName; Rec."File Name")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the planned PDF attachment name.';
                }
                field(ArchivePath; Rec."Archive Path")
                {
                    ApplicationArea = All;
                    MultiLine = true;
                    ToolTip = 'Specifies the planned SharePoint destination. Sprint 1 does not write the file.';
                }
                field(RoutingRule; Rec."Routing Rule")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the deterministic GPI Hub routing rule that was applied.';
                }
                field(Warnings; Rec.Warnings)
                {
                    ApplicationArea = All;
                    MultiLine = true;
                    ToolTip = 'Specifies blocking and nonblocking preflight warnings.';
                }
            }
        }
    }

    actions
    {
        area(Processing)
        {
            action(PreviewPDF)
            {
                ApplicationArea = All;
                Caption = 'Preview PDF';
                Image = ViewReport;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;
                ToolTip = 'Runs the configured Sales Order Confirmation report for preview. No email is created or sent.';

                trigger OnAction()
                var
                    SalesHeader: Record "Sales Header";
                begin
                    if Rec."Report ID" = 0 then
                        Error('A report ID was not returned by GPI Hub.');

                    if not SalesHeader.Get(SalesHeader."Document Type"::Order, Rec."Record No.") then
                        Error('Sales Order %1 could not be found.', Rec."Record No.");

                    Report.RunModal(Rec."Report ID", true, false, SalesHeader);
                end;
            }
        }
    }

    procedure SetPreview(var PreviewBuffer: Record "GPI Delivery Preview Buffer" temporary)
    begin
        Rec.Copy(PreviewBuffer, true);
    end;
}
