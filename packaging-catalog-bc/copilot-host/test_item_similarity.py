from __future__ import annotations

import unittest

from item_similarity import compare_products


class ItemSimilarityTests(unittest.TestCase):
    def test_identical_core_specs_score_100(self) -> None:
        reference = {
            "productNo": "P1",
            "bcItemNo": "ITEM-1",
            "material": "Glass",
            "style": "Bottle",
            "capacity": 12,
            "capacityUom": "OZ",
            "finish": "Crown",
            "finishType": "26mm",
            "color": "Amber",
            "packoutType": "Case",
            "vendorNo": "V1",
            "gramWeight": 210,
        }
        candidate = dict(reference)
        candidate["productNo"] = "P2"
        candidate["bcItemNo"] = "ITEM-2"

        result = compare_products(reference, candidate)

        self.assertEqual(result["similarityScore"], 100.0)
        self.assertEqual(result["differentAttributes"], [])

    def test_near_identical_item_retains_high_score_and_lists_difference(self) -> None:
        reference = {
            "productNo": "P1",
            "bcItemNo": "ITEM-1",
            "material": "Glass",
            "style": "Bottle",
            "capacity": 12,
            "capacityUom": "OZ",
            "finish": "Crown",
            "finishType": "26mm",
            "color": "Amber",
            "packoutType": "Case",
            "vendorNo": "V1",
            "gramWeight": 210,
        }
        candidate = dict(reference)
        candidate["productNo"] = "P2"
        candidate["bcItemNo"] = "ITEM-2"
        candidate["color"] = "Flint"

        result = compare_products(reference, candidate)

        self.assertGreater(result["similarityScore"], 90)
        self.assertIn("color", result["differentAttributes"])

    def test_material_and_style_changes_reduce_score(self) -> None:
        reference = {
            "productNo": "P1",
            "bcItemNo": "ITEM-1",
            "material": "Glass",
            "style": "Bottle",
            "capacity": 12,
            "capacityUom": "OZ",
            "finish": "Crown",
            "finishType": "26mm",
            "color": "Amber",
            "packoutType": "Case",
            "vendorNo": "V1",
            "gramWeight": 210,
        }
        candidate = dict(reference)
        candidate["productNo"] = "P3"
        candidate["bcItemNo"] = "ITEM-3"
        candidate["material"] = "PET"
        candidate["style"] = "Jar"

        result = compare_products(reference, candidate)

        self.assertLess(result["similarityScore"], 70)
        self.assertIn("material", result["differentAttributes"])
        self.assertIn("style", result["differentAttributes"])


if __name__ == "__main__":
    unittest.main()
