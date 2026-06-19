pageextension 70521 "GPI Delivery Log Archive" extends "GPI Document Delivery Log"
{
    layout
    {
        addafter("SharePoint URL")
        {
            field("Archive Status"; Rec."Archive Status")
            {
                ApplicationArea = All;
                StyleExpr = ArchiveStatusStyle;
                ToolTip = 'Specifies whether the PDF is pending, archived, failed, or skipped.';
            }
            field("Archived Date/Time"; Rec."Archived Date/Time")
            {
                ApplicationArea = All;
                ToolTip = 'Specifies when SharePoint archival completed.';
            }
            field("Archive Path"; Rec."Archive Path")
            {
                ApplicationArea = All;
                ToolTip = 'Specifies the Zetadocs-compatible path used in SharePoint.';
            }
            field("Archive Attempt Count"; Rec."Archive Attempt Count")
            {
                ApplicationArea = All;
                Visible = false;
            }
            field("Last Archive Attempt"; Rec."Last Archive Attempt")
            {
                ApplicationArea = All;
                Visible = false;
            }
            field("Last Archive Error"; Rec."Last Archive Error")
            {
                ApplicationArea = All;
                ToolTip = 'Specifies the most recent SharePoint archival error.';
            }
            field("Local PDF Cleared"; Rec."Local PDF Cleared")
            {
                ApplicationArea = All;
                Visible = false;
            }
        }
    }

    actions
    {
        addafter(DownloadPDF)
        {
            action(OpenSharePointArchive)
            {
                ApplicationArea = All;
                Caption = 'Open SharePoint Archive';
                Image = Web;
                ToolTip = 'Opens the archived PDF in SharePoint.';

                trigger OnAction()
                begin
                    if Rec."SharePoint URL" = '' then
                        Error('This delivery entry does not have a SharePoint archive URL.');
                    Hyperlink(Rec."SharePoint URL");
                end;
            }
            action(RetrySharePointArchive)
            {
                ApplicationArea = All;
                Caption = 'Retry SharePoint Archive';
                Image = Refresh;
                ToolTip = 'Retries SharePoint archival using the PDF retained in Business Central.';

                trigger OnAction()
                var
                    ArchiveMgt: Codeunit "GPI SharePoint Archive";
                begin
                    ArchiveMgt.ArchiveDeliveryLog(Rec);
                    CurrPage.Update(false);

                    case Rec."Archive Status" of
                        Rec."Archive Status"::Archived:
                            Message('Document archived to %1.', Rec."Archive Path");
                        Rec."Archive Status"::Failed:
                            Message('Archival failed: %1', Rec."Last Archive Error");
                        else
                            Message('The document was not archived. Confirm SharePoint Archive Setup is enabled, the email status is Sent, and an archive file account is assigned.');
                    end;
                end;
            }
            action(OpenSharePointArchiveSetup)
            {
                ApplicationArea = All;
                Caption = 'SharePoint Archive Setup';
                Image = Setup;
                RunObject = page "GPI SharePoint Archive Setup";
            }
        }
    }

    trigger OnAfterGetRecord()
    begin
        case Rec."Archive Status" of
            Rec."Archive Status"::Archived:
                ArchiveStatusStyle := 'Favorable';
            Rec."Archive Status"::Failed:
                ArchiveStatusStyle := 'Unfavorable';
            Rec."Archive Status"::Pending:
                ArchiveStatusStyle := 'Ambiguous';
            else
                ArchiveStatusStyle := 'Standard';
        end;
    end;

    var
        ArchiveStatusStyle: Text;
}
