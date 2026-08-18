import unittest

from poc.commercial_guardrails.bc_cost_probe import normalize_cost_probe_rows


class BCCostProbeTests(unittest.TestCase):
    def test_m_uom_exposes_base_scaled_cost_candidate(self):
        rows = normalize_cost_probe_rows(
            [
                {
                    "postingDate": "2025-05-06",
                    "invoiceNo": "285914",
                    "orderNo": "97745",
                    "customerNo": "TRIPLEH",
                    "lineType": "Item",
                    "itemNo": "20041936-P4305",
                    "description": "12oz 38-400 Ring Neck PET",
                    "quantity": 139.39,
                    "quantityBase": 139390,
                    "unitOfMeasureCode": "M",
                    "unitCostLCY": 0.18,
                    "unitPrice": 224.81,
                    "lineAmount": 31336.72,
                }
            ]
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertAlmostEqual(row.base_units_per_sales_uom, 1000.0, places=4)
        self.assertAlmostEqual(row.base_scaled_cost_candidate, 180.0, places=4)
        self.assertAlmostEqual(row.net_unit_sell, 224.81, places=2)
        self.assertGreater(row.gp_pct_raw_cost, 99.0)
        self.assertAlmostEqual(row.gp_pct_base_scaled_cost, 19.93, places=1)

    def test_non_item_lines_are_ignored(self):
        rows = normalize_cost_probe_rows(
            [
                {
                    "postingDate": "2025-05-06",
                    "invoiceNo": "285914",
                    "lineType": "Comment",
                    "quantity": 1,
                    "quantityBase": 1,
                    "lineAmount": 0,
                }
            ]
        )
        self.assertEqual(rows, [])

    def test_zero_quantity_is_ignored(self):
        rows = normalize_cost_probe_rows(
            [
                {
                    "postingDate": "2025-05-06",
                    "invoiceNo": "285914",
                    "lineType": "Item",
                    "itemNo": "X",
                    "quantity": 0,
                    "quantityBase": 0,
                }
            ]
        )
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
