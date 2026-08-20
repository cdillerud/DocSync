page 71102 "GPI Pack Doc List"
{
    PageType = List;
    SourceTable = "GPI Pack Product Doc";
    SourceTableView = sorting("Product No.", "Document Type", "Entry No.");
    ApplicationArea = All;
    UsageCategory = Lists;
    Caption = 'Packaging Product Documents';
    DelayedInsert = true;

    layout
    {
        area(Content)
        {
            repeater(Documents)
            {
                field("Product No."; Rec."Product No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the packaging product associated with the document.';
                }
                field("Document Type"; Rec."Document Type")
                {
                    ApplicationArea = All;
                }
                field(Description; Rec.Description)
                {
                    ApplicationArea = All;
                }
                field("File Name"; Rec."File Name")
                {
                    ApplicationArea = All;
                }
                field("Primary Document"; Rec."Primary Document")
                {
                    ApplicationArea = All;
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
                Promoted = true;
                PromotedCategory = Process;

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
                Promoted = true;
                PromotedCategory = Process;

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
