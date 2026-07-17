page 70516 "GPI SharePoint Archive Setup"
{
    Caption = 'GPI SharePoint Archive Setup';
    PageType = Card;
    SourceTable = "GPI SharePoint Archive Setup";
    ApplicationArea = All;
    UsageCategory = Administration;
    InsertAllowed = false;
    DeleteAllowed = false;

    layout
    {
        area(Content)
        {
            group(General)
            {
                field(Enabled; Rec.Enabled)
                {
                    ApplicationArea = All;
                    ToolTip = 'Enables automatic SharePoint archival after an email is successfully sent.';
                }
                field(ArchiveAccountStatus; ArchiveAccountStatus)
                {
                    ApplicationArea = All;
                    Caption = 'Archive Account Status';
                    Editable = false;
                    StyleExpr = ArchiveAccountStyle;
                }
                field(ArchiveAccountName; ArchiveAccountName)
                {
                    ApplicationArea = All;
                    Caption = 'Assigned File Account';
                    Editable = false;
                }
                field(ArchiveConnectorName; ArchiveConnectorName)
                {
                    ApplicationArea = All;
                    Caption = 'Connector';
                    Editable = false;
                }
            }
            group(Folders)
            {
                field("SharePoint Web Base URL"; Rec."SharePoint Web Base URL")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the SharePoint site URL used to construct links in the Delivery Log.';
                }
                field("Root Folder"; Rec."Root Folder")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the archive root folder. The Zetadocs-compatible default is Zetadocs.';
                }
                field("Sales Folder"; Rec."Sales Folder")
                {
                    ApplicationArea = All;
                }
                field("Purchase Folder"; Rec."Purchase Folder")
                {
                    ApplicationArea = All;
                }
                field("Warehouse Folder"; Rec."Warehouse Folder")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the archive folder used for transfer and other warehouse-owned documents.';
                }
                field("Clear Local PDF After Archive"; Rec."Clear Local PDF After Archive")
                {
                    ApplicationArea = All;
                    ToolTip = 'Clears the Business Central PDF BLOB only after SharePoint confirms the file was created.';
                }
            }
            group(ConnectionTest)
            {
                field("Last Connection Test"; Rec."Last Connection Test")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("Last Connection Result"; Rec."Last Connection Result")
                {
                    ApplicationArea = All;
                    Editable = false;
                    MultiLine = true;
                }
            }
        }
    }

    actions
    {
        area(Processing)
        {
            action(OpenFileAccounts)
            {
                ApplicationArea = All;
                Caption = 'External File Accounts';
                Image = Setup;
                ToolTip = 'Creates or manages the standard Business Central SharePoint file account.';

                trigger OnAction()
                begin
                    Page.RunModal(Page::"File Accounts");
                    RefreshAccountStatus();
                    CurrPage.Update(false);
                end;
            }
            action(AssignArchiveScenario)
            {
                ApplicationArea = All;
                Caption = 'Assign Archive Scenario';
                Image = Answers;
                ToolTip = 'Assigns GPI Document Archive to the SharePoint file account.';

                trigger OnAction()
                begin
                    Page.RunModal(Page::"File Scenario Setup");
                    RefreshAccountStatus();
                    CurrPage.Update(false);
                end;
            }
            action(TestConnection)
            {
                ApplicationArea = All;
                Caption = 'Test Connection';
                Image = TestFile;
                Promoted = true;
                PromotedCategory = Process;

                trigger OnAction()
                var
                    ArchiveMgt: Codeunit "GPI SharePoint Archive";
                begin
                    CurrPage.SaveRecord();
                    Commit();
                    ArchiveMgt.TestConnection();
                    CurrPage.Update(false);
                end;
            }
            action(ArchivePending)
            {
                ApplicationArea = All;
                Caption = 'Archive Pending Documents';
                Image = Archive;
                Promoted = true;
                PromotedCategory = Process;

                trigger OnAction()
                var
                    ArchiveMgt: Codeunit "GPI SharePoint Archive";
                    ArchivedCount: Integer;
                    FailedCount: Integer;
                begin
                    CurrPage.SaveRecord();
                    Commit();
                    ArchiveMgt.ArchivePendingDocuments(ArchivedCount, FailedCount);
                    Message('Archive processing complete. Archived: %1. Failed: %2.', ArchivedCount, FailedCount);
                end;
            }
            action(OpenDeliveryLog)
            {
                ApplicationArea = All;
                Caption = 'Document Delivery Log';
                Image = Log;
                RunObject = page "GPI Document Delivery Log";
            }
        }
    }

    trigger OnOpenPage()
    var
        ArchiveMgt: Codeunit "GPI SharePoint Archive";
    begin
        ArchiveMgt.GetSetup(Rec);
        RefreshAccountStatus();
    end;

    local procedure RefreshAccountStatus()
    var
        ArchiveMgt: Codeunit "GPI SharePoint Archive";
    begin
        Clear(ArchiveAccountName);
        Clear(ArchiveConnectorName);
        if ArchiveMgt.GetArchiveAccount(ArchiveAccountName, ArchiveConnectorName) then begin
            ArchiveAccountStatus := 'Configured';
            ArchiveAccountStyle := 'Favorable';
        end else begin
            ArchiveAccountStatus := 'Not configured';
            ArchiveAccountStyle := 'Unfavorable';
        end;
    end;

    var
        ArchiveAccountStatus: Text[50];
        ArchiveAccountName: Text[250];
        ArchiveConnectorName: Text[100];
        ArchiveAccountStyle: Text;
}
