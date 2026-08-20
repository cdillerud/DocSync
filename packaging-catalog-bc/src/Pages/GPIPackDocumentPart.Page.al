page 71101 "GPI Pack Doc Part"
{
    PageType = ListPart;
    SourceTable = "GPI Pack Product Doc";
    SourceTableView = sorting("Product No.", "Document Type", "Entry No.");
    ApplicationArea = All;
    Caption = 'Product Documents';
    DelayedInsert = true;

    layout
    {
        area(Content)
        {
            repeater(Documents)
            {
                field("Document Type"; Rec."Document Type")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the type of packaging product document.';
                }
                field(Description; Rec.Description)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies a business-friendly description for the document.';
                }
                field("File Name"; Rec."File Name")
                {
                    ApplicationArea = All;
                    ToolTip = 'Shows the uploaded file name.';
                }
                field("Primary Document"; Rec."Primary Document")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies whether this is the primary document for the product.';
                }
                field("Uploaded At"; Rec."Uploaded At")
                {
                    ApplicationArea = All;
                }
                field("Uploaded By"; Rec."Uploaded By")
                {
                    ApplicationArea = All;
                }
            }
        }
    }

    actions
    {
        area(Processing)
        {
            action(UploadFile)
            {
                ApplicationArea = All;
                Caption = 'Upload File';

                trigger OnAction()
                var
                    DocMgt: Codeunit "GPI Pack Doc Mgt";
                    ProductNo: Code[20];
                begin
                    ProductNo := DocMgt.GetProductNoFromFilter(Rec);
                    if DocMgt.UploadDocument(ProductNo) then
                        CurrPage.Update(false);
                end;
            }
            action(DownloadFile)
            {
                ApplicationArea = All;
                Caption = 'Download File';

                trigger OnAction()
                var
                    DocMgt: Codeunit "GPI Pack Doc Mgt";
                begin
                    Rec.TestField("Entry No.");
                    DocMgt.DownloadDocument(Rec);
                end;
            }
            action(DeleteFile)
            {
                ApplicationArea = All;
                Caption = 'Delete File';

                trigger OnAction()
                var
                    DocMgt: Codeunit "GPI Pack Doc Mgt";
                begin
                    Rec.TestField("Entry No.");
                    DocMgt.DeleteDocument(Rec);
                    CurrPage.Update(false);
                end;
            }
        }
    }
}
