import unittest

from poc.commercial_guardrails.item_similarity import rank_related_items, score_related_item


PROPOSED = "12oz, 38-400, CT, Clear, Hot Fill PET, Ring Neck, Bottle, Bulk, FH"


class ItemSimilarityTests(unittest.TestCase):
    def test_cold_fill_pet_ringneck_is_close_match(self):
        score, reasons = score_related_item(
            PROPOSED,
            "12oz, 38-400, CT, Clear, PET, Cold Fill Ring Neck, Bottle, 40g, Bag Packed",
        )
        self.assertGreaterEqual(score, 90)
        self.assertIn("cold fill vs hot fill", reasons)

    def test_glass_ringneck_is_rejected_when_proposed_is_pet(self):
        score, reasons = score_related_item(
            PROPOSED,
            "12oz, 38-405, CT, Flint, Glass, Ring Neck, Bottle, HH",
        )
        self.assertEqual(score, 0)
        self.assertIn("different material", reasons)

    def test_different_ounce_size_is_rejected(self):
        score, reasons = score_related_item(
            PROPOSED,
            "24oz, 38-400, CT, Clear, PET, Hot Fill Ring Neck, Bottle",
        )
        self.assertEqual(score, 0)
        self.assertIn("different ounce size", reasons)

    def test_rank_prefers_same_finish_pet_ringneck(self):
        items = [
            {
                "number": "20041936-P4305",
                "displayName": PROPOSED,
                "blocked": False,
                "baseUnitOfMeasureCode": "EA",
            },
            {
                "number": "8404730008",
                "displayName": "12oz, 38-400, CT, Clear, PET, Cold Fill Ring Neck, Bottle, 40g, Bag Packed",
                "blocked": False,
                "baseUnitOfMeasureCode": "EA",
            },
            {
                "number": "8404730005",
                "displayName": "12oz, 38-400, CT, Clear, PET, Cold Fill Ring Neck, Bottle, 40g, Tray Packed",
                "blocked": False,
                "baseUnitOfMeasureCode": "EA",
            },
            {
                "number": "11328-869254",
                "displayName": "12oz, 38-405, CT, Flint, Glass, Ring Neck, Bottle, HH",
                "blocked": False,
                "baseUnitOfMeasureCode": "EA",
            },
            {
                "number": "BLOCKEDPET",
                "displayName": "12oz, 38-400, CT, Clear, PET, Hot Fill Ring Neck, Bottle",
                "blocked": True,
                "baseUnitOfMeasureCode": "EA",
            },
        ]

        ranked = rank_related_items(
            "20041936-P4305",
            PROPOSED,
            items,
            min_score=55,
            max_results=10,
        )
        numbers = [candidate.item_no for candidate in ranked]
        self.assertIn("8404730008", numbers)
        self.assertIn("8404730005", numbers)
        self.assertNotIn("11328-869254", numbers)
        self.assertNotIn("BLOCKEDPET", numbers)


if __name__ == "__main__":
    unittest.main()
