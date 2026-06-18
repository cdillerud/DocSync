page 70517 "GPI Documents FactBox"
{
    Caption = 'GPI Documents';
    PageType = CardPart;
    ApplicationArea = All;

    layout
    {
        area(Content)
        {
            usercontrol(DropZone; "GPI Document Drop Zone")
            {
                ApplicationArea = All;

                trigger ControlReady()
                begin
                    ControlIsReady := true;
                    RefreshDropZone();
                end;
            }
            cuegroup(DocumentSummary)
            {
                ShowCaption = false;

                field(DocumentCount; DocumentCount)
                {
                    ApplicationArea = All;
                    Caption = 'Linked Documents';
                    DrillDown = true;

                    trigger OnDrillDown()
                    begin
                        DocumentMgt.OpenDocuments(SourceTableId, SourceSystemId);
                    end;
                }
            }
        }
    }

    procedure SetSourceContext(NewSourceTableId: Integer; NewSourceSystemId: Guid; NewSourceDocumentType: Text; NewSourceDocumentNo: Code[50]; NewSourcePartyNo: Code[20]; NewSourcePartyName: Text; NewBusinessArea: Text)
    begin
        SourceTableId := NewSourceTableId;
        SourceSystemId := NewSourceSystemId;
        SourceDocumentType := CopyStr(NewSourceDocumentType, 1, MaxStrLen(SourceDocumentType));
        SourceDocumentNo := NewSourceDocumentNo;
        SourcePartyNo := NewSourcePartyNo;
        SourcePartyName := CopyStr(NewSourcePartyName, 1, MaxStrLen(SourcePartyName));
        BusinessArea := CopyStr(NewBusinessArea, 1, MaxStrLen(BusinessArea));
        IsContextReady := not IsNullGuid(SourceSystemId);
        ContextCaption := BuildContextCaption();
        RefreshDocumentCount();
        RefreshDropZone();
        CurrPage.Update(false);
    end;

    local procedure RefreshDocumentCount()
    begin
        DocumentCount := DocumentMgt.CountDocuments(SourceTableId, SourceSystemId);
    end;

    local procedure RefreshDropZone()
    begin
        if not ControlIsReady then
            exit;
        CurrPage.DropZone.SetContext(ContextCaption, DocumentCount, IsContextReady);
    end;

    local procedure BuildContextCaption(): Text
    begin
        if SourceDocumentNo <> '' then
            exit(StrSubstNo('Documents for %1', SourceDocumentNo));
        if SourcePartyName <> '' then
            exit(StrSubstNo('Documents for %1', SourcePartyName));
        exit('GPI Documents');
    end;

    var
        DocumentMgt: Codeunit "GPI Document Link Mgt.";
        SourceTableId: Integer;
        SourceSystemId: Guid;
        SourceDocumentType: Text[50];
        SourceDocumentNo: Code[50];
        SourcePartyNo: Code[20];
        SourcePartyName: Text[100];
        BusinessArea: Text[20];
        ContextCaption: Text[150];
        DocumentCount: Integer;
        IsContextReady: Boolean;
        ControlIsReady: Boolean;
}
