page 70511 "GPI Document Delivery Log"
{
    Caption = 'GPI Document Delivery Log';
    PageType = List;
    SourceTable = "GPI Document Delivery Log";
    SourceTableView = sorting("Entry No.") order(descending);
    ApplicationArea = All;
    UsageCategory = History;
    Editable = false;

    layout
    {
        area(Content)
        {
            repeater(Entries)
            {
                field("Entry No."; Rec."Entry No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the delivery log entry number.';
                }

                field(Status; Rec.Status)
                {
                    ApplicationArea = All;
                    StyleExpr = StatusStyle;
                    ToolTip = 'Specifies whether the email was sent, saved as a draft, discarded, failed, or archived.';
                }

                field("Delivery Document Type"; Rec."Delivery Document Type")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the Gamer-owned document that was generated.';
                }

                field("Sales Order No."; Rec."Sales Order No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the related sales order.';
                }

                field("Customer No."; Rec."Customer No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the customer number.';
                }

                field("Location Code"; Rec."Location Code")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the location code used for the document.';
                }

                field("Attachment Filename"; Rec."Attachment Filename")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the PDF filename.';
                }

                field("To Recipients"; Rec."To Recipients")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the final To recipients from the email editor.';
                }

                field("CC Recipients"; Rec."CC Recipients")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the final CC recipients from the email editor.';
                }

                field(Subject; Rec.Subject)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the final email subject.';
                }

                field("Created Date/Time"; Rec."Created Date/Time")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies when the document and email draft were created.';
                }

                field("Created By"; Rec."Created By")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies who created the document and email draft.';
                }

                field("Completed Date/Time"; Rec."Completed Date/Time")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies when the user completed the email editor action.';
                }

                field("Completed By"; Rec."Completed By")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies who completed the email editor action.';
                }

                field("External Delivery ID"; Rec."External Delivery ID")
                {
                    ApplicationArea = All;
                    Visible = false;
                    ToolTip = 'Specifies the external email delivery identifier when available.';
                }

                field("SharePoint URL"; Rec."SharePoint URL")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the SharePoint archive URL when the document has been archived.';
                }

                field("Error Message"; Rec."Error Message")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the error recorded for a failed delivery.';
                }
            }
        }
    }

    actions
    {
        area(Processing)
        {
            action(DownloadPDF)
            {
                ApplicationArea = All;
                Caption = 'Download PDF';
                Image = ExportFile;
                ToolTip = 'Downloads the exact PDF stored with this delivery entry.';

                trigger OnAction()
                var
                    DocumentInStream: InStream;
                    FileName: Text;
                begin
                    Rec.CalcFields("Document Content");
                    if not Rec."Document Content".HasValue then
                        Error('No PDF is stored for delivery log entry %1.', Rec."Entry No.");

                    FileName := Rec."Attachment Filename";
                    if FileName = '' then
                        FileName := StrSubstNo('GPI-Document-%1.pdf', Rec."Entry No.");

                    Rec."Document Content".CreateInStream(DocumentInStream);
                    DownloadFromStream(DocumentInStream, '', '', 'PDF files (*.pdf)|*.pdf', FileName);
                end;
            }

            action(OpenSalesOrder)
            {
                ApplicationArea = All;
                Caption = 'Open Sales Order';
                Image = Document;
                ToolTip = 'Opens the sales order related to this delivery entry.';

                trigger OnAction()
                var
                    SalesHeader: Record "Sales Header";
                begin
                    if not SalesHeader.Get(SalesHeader."Document Type"::Order, Rec."Sales Order No.") then
                        Error('Sales Order %1 could not be found.', Rec."Sales Order No.");

                    Page.Run(Page::"Sales Order", SalesHeader);
                end;
            }

            action(OpenSentEmailHistory)
            {
                ApplicationArea = All;
                Caption = 'Open Sent Email History';
                Image = Email;
                ToolTip = 'Opens native Business Central sent-email history for the related sales order.';

                trigger OnAction()
                var
                    Email: Codeunit Email;
                begin
                    if IsNullGuid(Rec."Sales Order SystemId") then
                        Error('The delivery entry is not linked to a sales order system ID.');

                    Email.OpenSentEmails(Database::"Sales Header", Rec."Sales Order SystemId");
                end;
            }
        }
    }

    trigger OnAfterGetRecord()
    begin
        case Rec.Status of
            Rec.Status::Sent,
            Rec.Status::Archived:
                StatusStyle := 'Favorable';
            Rec.Status::Failed:
                StatusStyle := 'Unfavorable';
            Rec.Status::"Saved As Draft":
                StatusStyle := 'Ambiguous';
            else
                StatusStyle := 'Standard';
        end;
    end;

    var
        StatusStyle: Text;
}
