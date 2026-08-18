import unittest

from poc.commercial_guardrails.bc_standard import (
    build_standard_invoice_filter,
    historical_lines_from_standard_invoices,
)


class StandardBCHistoryTests(unittest.TestCase):
    def test_filter_scopes_customer_and_dates(self):
        value = build_standard_invoice_filter(
            start_date="2024-01-01",
            end_date="2026-08-17",
            customer_no="GRUMPY",
        )
        self.assertIn("postingDate ge 2024-01-01", value)
        self.assertIn("postingDate le 2026-08-17", value)
        self.assertIn("customerNumber eq 'GRUMPY'", value)

    def test_expanded_invoice_lines_map_to_history(self):
        invoices = [
            {
                "number": "300506",
                "postingDate": "2026-05-19",
                "customerNumber": "GRUMPY",
                "customerName": "Grumpy Man LLC",
                "orderNumber": "114167",
                "salesInvoiceLines": [
                    {
                        "lineType": "Item",
                        "lineObjectNumber": "8404730008",
                        "description": "12oz PET Cold Fill Ring Neck",
                        "unitOfMeasureCode": "M",
                        "quantity": 4.32,
                        "unitPrice": 338.42,
                        "amountExcludingTax": 1461.97,
                    },
                    {
                        "lineType": "Comment",
                        "lineObjectNumber": "",
                        "description": "ignore me",
                        "quantity": 0,
                        "unitPrice": 0,
                        "amountExcludingTax": 0,
                    },
                ],
            }
        ]

        rows = historical_lines_from_standard_invoices(
            invoices,
            item_nos=["8404730008", "20041936-P4305"],
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].customer_no, "GRUMPY")
        self.assertEqual(rows[0].item_no, "8404730008")
        self.assertAlmostEqual(rows[0].unit_price, 338.42, places=2)
        self.assertEqual(rows[0].uom, "M")

    def test_family_filter_excludes_unrelated_items(self):
        invoices = [
            {
                "number": "1",
                "postingDate": "2026-01-01",
                "customerNumber": "CUST",
                "customerName": "Customer",
                "orderNumber": "SO1",
                "salesInvoiceLines": [
                    {
                        "lineType": "Item",
                        "lineObjectNumber": "KEEP",
                        "description": "Keep",
                        "unitOfMeasureCode": "M",
                        "quantity": 1,
                        "unitPrice": 10,
                        "amountExcludingTax": 10,
                    },
                    {
                        "lineType": "Item",
                        "lineObjectNumber": "DROP",
                        "description": "Drop",
                        "unitOfMeasureCode": "EA",
                        "quantity": 1,
                        "unitPrice": 20,
                        "amountExcludingTax": 20,
                    },
                ],
            }
        ]
        rows = historical_lines_from_standard_invoices(invoices, item_nos=["KEEP"])
        self.assertEqual([row.item_no for row in rows], ["KEEP"])


if __name__ == "__main__":
    unittest.main()
