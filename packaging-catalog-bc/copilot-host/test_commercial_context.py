from __future__ import annotations

import unittest
from unittest.mock import patch

import commercial_context


class FakeClient:
    def __init__(self, payloads: dict[str, dict]):
        self.payloads = payloads

    def get_api_json(
        self,
        api_group: str,
        relative_path: str,
        *,
        api_version: str = "v1.0",
    ) -> dict:
        if api_group != "commercialGuardrails":
            raise AssertionError(api_group)

        if relative_path.startswith("historicalSalesLines?"):
            return self.payloads.get("historicalSalesLines", {"value": []})

        if relative_path.startswith("itemCostContexts?"):
            return self.payloads.get("itemCostContexts", {"value": []})

        raise AssertionError(relative_path)


class CommercialContextTests(unittest.TestCase):
    def test_customer_item_history_summarizes_sales(self) -> None:
        fake = FakeClient(
            {
                "historicalSalesLines": {
                    "value": [
                        {
                            "invoiceNo": "INV1",
                            "orderNo": "SO1",
                            "postingDate": "2026-08-01",
                            "customerNo": "C1",
                            "itemNo": "ITEM-A",
                            "quantityBase": 10,
                            "lineAmount": 100,
                        },
                        {
                            "invoiceNo": "INV2",
                            "orderNo": "SO2",
                            "postingDate": "2026-08-15",
                            "customerNo": "C1",
                            "itemNo": "ITEM-B",
                            "quantityBase": 20,
                            "lineAmount": 240,
                        },
                    ]
                }
            }
        )

        with patch.object(commercial_context, "_client", return_value=fake):
            result = commercial_context.customer_item_history("C1")

        self.assertEqual(result["lineCount"], 2)
        self.assertEqual(result["invoiceCount"], 2)
        self.assertEqual(result["orderCount"], 2)
        self.assertEqual(result["distinctItemCount"], 2)
        self.assertEqual(result["totalQuantityBase"], 30.0)
        self.assertEqual(result["totalSales"], 340.0)
        self.assertEqual(result["latestPostingDate"], "2026-08-15")

    def test_incorrect_item_context_marks_new_item(self) -> None:
        class RoutedClient(FakeClient):
            def get_api_json(
                self,
                api_group: str,
                relative_path: str,
                *,
                api_version: str = "v1.0",
            ) -> dict:
                if relative_path.startswith("itemCostContexts?"):
                    return {
                        "value": [
                            {
                                "itemNo": "ITEM-X",
                                "description": "Candidate",
                                "baseUnitOfMeasure": "EA",
                                "unitCost": 2.5,
                            }
                        ]
                    }

                if "ITEM-X" in relative_path:
                    return {"value": []}

                return {
                    "value": [
                        {
                            "invoiceNo": "INV1",
                            "orderNo": "SO1",
                            "postingDate": "2026-08-01",
                            "customerNo": "C1",
                            "itemNo": "ITEM-A",
                            "quantityBase": 10,
                            "lineAmount": 100,
                        }
                    ]
                }

        fake = RoutedClient({})
        with patch.object(commercial_context, "_client", return_value=fake):
            result = commercial_context.incorrect_item_context(
                "C1",
                "ITEM-X",
            )

        self.assertFalse(result["candidatePurchasedBefore"])
        self.assertEqual(result["candidateHistoricalLineCount"], 0)
        self.assertEqual(
            result["mostCommonItems"][0]["itemNo"],
            "ITEM-A",
        )

    def test_cost_change_context_ranks_customer_exposure(self) -> None:
        fake = FakeClient(
            {
                "historicalSalesLines": {
                    "value": [
                        {
                            "postingDate": "2026-08-10",
                            "customerNo": "BIG",
                            "itemNo": "ITEM-A",
                            "quantityBase": 100,
                            "lineAmount": 5000,
                            "salespersonCode": "REP1",
                        },
                        {
                            "postingDate": "2026-08-11",
                            "customerNo": "SMALL",
                            "itemNo": "ITEM-A",
                            "quantityBase": 10,
                            "lineAmount": 200,
                            "salespersonCode": "REP2",
                        },
                    ]
                },
                "itemCostContexts": {
                    "value": [
                        {
                            "itemNo": "ITEM-A",
                            "description": "Test",
                            "unitCost": 1.25,
                            "baseUnitOfMeasure": "EA",
                        }
                    ]
                },
            }
        )

        with patch.object(commercial_context, "_client", return_value=fake):
            result = commercial_context.cost_change_context("ITEM-A")

        self.assertEqual(result["customerCount"], 2)
        self.assertEqual(
            result["customerExposure"][0]["customerNo"],
            "BIG",
        )
        self.assertEqual(result["customerExposure"][0]["sales"], 5000.0)


if __name__ == "__main__":
    unittest.main()
