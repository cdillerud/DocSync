pageextension 70525 "GPI Invoice Queue Labels" extends "GPI Posted Invoice Queue"
{
    actions
    {
        modify(PreviewInvoice)
        {
            Caption = 'Gamer Preview Invoice';
        }

        modify(SendSelected)
        {
            Caption = 'Gamer Send Selected';
        }

        modify(SendAllFiltered)
        {
            Caption = 'Gamer Send All Filtered';
        }

        modify(OpenDeliveryLog)
        {
            Caption = 'Gamer Document Delivery Log';
        }

        modify(OpenRoutingRules)
        {
            Caption = 'Gamer Document Routing Rules';
        }
    }
}
