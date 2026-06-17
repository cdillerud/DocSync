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

                field("Source Document Type"; Rec."Source Document Type")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the Business Central source document type.';
                }

                field("Source Document No."; Rec."Source Document No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the source document number.';
                }

                field("Sales Order No."; Rec."Sales Order No.")
                {
                    ApplicationArea = All;
                    Visible = false;
                    ToolTip = 'Specifies the legacy related sales order number.';
                }

                field("Source Party Type"; Rec."Source Party Type")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies whether the related party is a customer, vendor, or another entity.';
                }

                field("Source Party No."; Rec."Source Party No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the related customer or vendor number.';
                }

                field("Customer No."; Rec."Customer No.")
                {
                    ApplicationArea = All;
                    Visible = false;
                    ToolTip = 'Specifies the legacy customer number.';
                }

                field("Location Code"; Rec."Location Code")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the location code used for the document.';
                }

                field("Sender Email Address"; Rec."Sender Email Address")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the email address that was expected to send the document.';
                }

                field("Sender User"; Rec."Sender User")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the Business Central user who initiated the delivery.';
                }

                field("Sender Policy"; Rec."Sender Policy")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies how the sender account was selected.';
                }

                field("Sender Account Name"; Rec."Sender Account Name")
                {
                    ApplicationArea = All;
                    Visible = false;
                    ToolTip = 'Specifies the Business Central email account name.';
                }

                field("Sender Connector"; Rec."Sender Connector")
                {
                    ApplicationArea = All;
                    Visible = false;
                    ToolTip = 'Specifies the Business Central email connector.';
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

                field("BCC Recipients"; Rec."BCC Recipients")
                {
                    ApplicationArea = All;
                    Visible = false;
                    ToolTip = 'Specifies the final BCC recipients from the email editor.';
                }

                field(Subject; Rec.Subject)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the final email subject.';
                }

                field("Routing Rule Entry Nos."; Rec."Routing Rule Entry Nos.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the routing rules that changed or added recipients.';
                }

                field("Created Date/Time"; Rec."Created Date/Time")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies when the document and email draft were created.';
                }

                field("Created By"; Rec."Created By")
                {
                    ApplicationArea = All;
                    Visible = false;
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
                    Visible = false;
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

            action(OpenSourceDocument)
            {
                ApplicationArea = All;
                Caption = 'Open Source Document';
                Image = Document;
                ToolTip = 'Opens the Business Central source document related to this delivery entry.';

                trigger OnAction()
                var
                    SalesHeader: Record "Sales Header";
                    SalesInvoiceHeader: Record "Sales Invoice Header";
                    SourceDocumentNo: Code[20];
                begin
                    SourceDocumentNo := Rec."Source Document No.";
                    if SourceDocumentNo = '' then
                        SourceDocumentNo := Rec."Sales Order No.";

                    if Rec."Source Table ID" in [0, Database::"Sales Header"] then begin
                        if not SalesHeader.Get(SalesHeader."Document Type"::Order, SourceDocumentNo) then
                            Error('Sales Order %1 could not be found.', SourceDocumentNo);

                        Page.Run(Page::"Sales Order", SalesHeader);
                        exit;
                    end;

                    if Rec."Source Table ID" = Database::"Sales Invoice Header" then begin
                        if not SalesInvoiceHeader.Get(SourceDocumentNo) then
                            Error('Posted Sales Invoice %1 could not be found.', SourceDocumentNo);

                        Page.Run(Page::"Posted Sales Invoice", SalesInvoiceHeader);
                        exit;
                    end;

                    Error('Opening source table %1 is not implemented yet.', Rec."Source Table ID");
                end;
            }

            action(OpenSentEmailHistory)
            {
                ApplicationArea = All;
                Caption = 'Open Sent Email History';
                Image = Email;
                ToolTip = 'Opens native Business Central sent-email history for the related source document.';

                trigger OnAction()
                var
                    Email: Codeunit Email;
                    SourceTableId: Integer;
                    SourceSystemId: Guid;
                begin
                    SourceTableId := Rec."Source Table ID";
                    SourceSystemId := Rec."Source SystemId";

                    if SourceTableId = 0 then begin
                        SourceTableId := Database::"Sales Header";
                        SourceSystemId := Rec."Sales Order SystemId";
                    end;

                    if IsNullGuid(SourceSystemId) then
                        Error('The delivery entry is not linked to a source record system ID.');

                    Email.OpenSentEmails(SourceTableId, SourceSystemId);
                end;
            }

            action(OpenRoutingRules)
            {
                ApplicationArea = All;
                Caption = 'Document Routing Rules';
                Image = Setup;
                RunObject = page "GPI Document Routing Rules";
                ToolTip = 'Opens the configurable customer, vendor, location, and document recipient rules.';
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
