import unittest

from poc.commercial_guardrails.bc_item_costs import (
    build_item_cost_filter,
    item_cost_contexts_from_rows,
)


class BCItemCostContextTests(unittest.TestCase):
    def test_alternate_uom_converts_base_unit_cost(self):
        contexts = item_cost_contexts_from_rows(
            [
                {
                    "itemNo": "20041936-P4305",
                    "description": "12oz ring neck",
                    "baseUnitOfMeasure": "EA",
                    "unitCost": 0.16104,
                    "blocked": False,
                    "vendorNo": "VEND1",
                    "vendorItemNo": "RG12",
                    "uomCode": "M",
                    "qtyPerUnitOfMeasure": 1000,
                }
            ]
        )
        context = contexts[0]
        self.assertEqual(context.base_uom, "EA")
        self.assertEqual(context.uom, "M")
        self.assertEqual(context.qty_per_uom, 1000)
        self.assertAlmostEqual(context.unit_cost_in_uom, 161.04, places=4)

    def test_base_uom_missing_factor_falls_back_to_one(self):
        context = item_cost_contexts_from_rows(
            [
                {
                    "itemNo": "BALLARTWORK",
                    "baseUnitOfMeasure": "EA",
                    "unitCost": 100,
                    "uomCode": "EA",
                    "qtyPerUnitOfMeasure": 0,
                }
            ]
        )[0]
        self.assertEqual(context.qty_per_uom, 1.0)
        self.assertEqual(context.unit_cost_in_uom, 100.0)

    def test_non_base_uom_with_zero_factor_is_not_converted(self):
        context = item_cost_contexts_from_rows(
            [
                {
                    "itemNo": "X",
                    "baseUnitOfMeasure": "EA",
                    "unitCost": 2,
                    "uomCode": "CASE",
                    "qtyPerUnitOfMeasure": 0,
                }
            ]
        )[0]
        self.assertIsNone(context.unit_cost_in_uom)

    def test_item_filter_escapes_quotes(self):
        value = build_item_cost_filter(["ABC", "O'HARE"])
        self.assertIn("itemNo eq 'ABC'", value)
        self.assertIn("itemNo eq 'O''HARE'", value)


if __name__ == "__main__":
    unittest.main()
