from datetime import datetime

from poc.commercial_guardrails.bc_adapter import (
    build_analytics_filter,
    build_sales_filter,
    transactions_from_analytics_rows,
    transactions_from_custom_rows,
)


def test_custom_row_preserves_sales_uom_and_net_sell():
    transactions = transactions_from_custom_rows(
        [
            {
                "invoiceNo": "223446",
                "lineNo": 10000,
                "postingDate": "2026-08-01",
                "orderNo": "33650",
                "customerNo": "0PROOFD",
                "customerName": "Proof Customer",
                "salespersonCode": "JR",
                "lineType": "Item",
                "itemNo": "12OZ-RING",
                "description": "12oz Ringneck",
                "quantity": 1000,
                "quantityBase": 1000,
                "unitOfMeasureCode": "EA",
                "unitCostLCY": 0.18,
                "unitPrice": 0.26,
                "lineAmount": 250.00,
            }
        ]
    )

    assert len(transactions) == 1
    tx = transactions[0]
    assert tx.transaction_id == "223446:10000"
    assert tx.order_no == "33650"
    assert tx.transaction_date == datetime(2026, 8, 1)
    assert tx.uom == "EA"
    assert tx.unit_cost == 0.18
    assert tx.unit_sell_price == 0.25


def test_custom_row_ignores_non_item_lines():
    transactions = transactions_from_custom_rows(
        [
            {
                "invoiceNo": "INV1",
                "lineNo": 10000,
                "postingDate": "2026-08-01",
                "lineType": "G/L Account",
                "itemNo": "4000",
                "quantity": 1,
                "unitCostLCY": 1,
                "lineAmount": 10,
            }
        ]
    )
    assert transactions == []


def test_analytics_row_maps_read_only_cost_data():
    transactions = transactions_from_analytics_rows(
        [
            {
                "postingDate": "2026-08-02",
                "type": "Item",
                "description": "12oz Ringneck",
                "documentNo": "223447",
                "lineNo": 10000,
                "no": "12OZ-RING",
                "quantityBase": 2000,
                "amount": 500,
                "unitCostLCY": 0.19,
                "sellToCustomerNo": "0PROOFD",
                "salesInvoiceDocumentNo": "223447",
                "salespersonCode": "JR",
            }
        ]
    )

    assert len(transactions) == 1
    tx = transactions[0]
    assert tx.quantity == 2000
    assert tx.uom == "BASE"
    assert tx.unit_sell_price == 0.25
    assert tx.unit_cost == 0.19


def test_custom_filter_escapes_odata_literals():
    value = build_sales_filter(
        "2026-01-01",
        "2026-08-17",
        ["RING'12"],
        ["C100"],
    )
    assert "postingDate ge 2026-01-01" in value
    assert "itemNo eq 'RING''12'" in value
    assert "customerNo eq 'C100'" in value


def test_analytics_filter_uses_analytics_field_names():
    value = build_analytics_filter(item_nos=["RING12"], customer_nos=["C100"])
    assert "no eq 'RING12'" in value
    assert "sellToCustomerNo eq 'C100'" in value
