import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from poc.commercial_guardrails.supplier_review_pipeline import (
    SupplierReviewRun,
    _safe_source_name,
    analyze_supplier_review,
    create_manual_supplier_review_run,
    validate_manual_supplier_upload,
    write_supplier_review_artifacts,
)


class SupplierReviewPipelineTests(unittest.TestCase):
    def test_safe_source_name_strips_directories_and_unsafe_characters(self):
        self.assertEqual(_safe_source_name(r"..\..\Supplier Notice (Sept).xlsx"), "Supplier_Notice_Sept_.xlsx")
        self.assertEqual(_safe_source_name("../../evil.csv"), "evil.csv")

    def test_manual_upload_accepts_only_supported_nonempty_files(self):
        self.assertEqual(validate_manual_supplier_upload("notice.CSV", b"a,b\n1,2\n"), "notice.CSV")
        with self.assertRaisesRegex(ValueError, "Unsupported supplier notice type"):
            validate_manual_supplier_upload("notice.pdf", b"pdf")
        with self.assertRaisesRegex(ValueError, "empty"):
            validate_manual_supplier_upload("notice.csv", b"")

    def test_manual_upload_enforces_size_limit(self):
        with self.assertRaisesRegex(ValueError, "too large"):
            validate_manual_supplier_upload("notice.csv", b"12345", max_bytes=4)

    @patch("poc.commercial_guardrails.supplier_review_pipeline.analyze_supplier_margin_impact")
    @patch("poc.commercial_guardrails.supplier_review_pipeline.fetch_bc_pricing_rules")
    @patch("poc.commercial_guardrails.supplier_review_pipeline.compare_supplier_prices_to_bc")
    @patch("poc.commercial_guardrails.supplier_review_pipeline.fetch_bc_item_cost_contexts")
    @patch("poc.commercial_guardrails.supplier_review_pipeline.load_supplier_notice")
    def test_analyze_supplier_review_orchestrates_read_only_pipeline(
        self,
        load_notice,
        fetch_contexts,
        compare_prices,
        fetch_rules,
        analyze_impact,
    ):
        load_notice.return_value = [
            SimpleNamespace(gpi_item_no="ITEM2"),
            SimpleNamespace(gpi_item_no="ITEM1"),
            SimpleNamespace(gpi_item_no="ITEM2"),
        ]
        fetch_contexts.return_value = ["CTX"]
        compare_prices.return_value = ["CMP1", "CMP2"]
        fetch_rules.return_value = ["RULE"]
        analyze_impact.side_effect = ["IMP1", "IMP2"]

        client = MagicMock()
        client.fetch_transactions.return_value = ["TX"]
        config = SimpleNamespace(environment="Sandbox_NoZetadocs_UAT")

        with patch(
            "poc.commercial_guardrails.supplier_review_pipeline.build_supplier_approval_queue",
            return_value=["QUEUE"],
        ):
            result = analyze_supplier_review(
                "notice.csv",
                start_date="2024-01-01",
                config=config,
                client=client,
            )

        fetch_contexts.assert_called_once_with(client, item_nos=["ITEM1", "ITEM2"])
        client.fetch_transactions.assert_called_once_with(
            start_date="2024-01-01",
            end_date="",
            item_nos=["ITEM1", "ITEM2"],
        )
        self.assertEqual(result.environment, "Sandbox_NoZetadocs_UAT")
        self.assertEqual(result.pricing_rule_count, 1)
        self.assertEqual(result.impacts, ("IMP1", "IMP2"))
        self.assertEqual(result.queue, ("QUEUE",))

    def test_write_supplier_review_artifacts_creates_manifest_and_sidecars(self):
        source_bytes = b"synthetic supplier notice"
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sample_supplier_price_notice.csv"
            source.write_bytes(source_bytes)
            run = SupplierReviewRun(
                environment="Sandbox_NoZetadocs_UAT",
                source_path=source,
                staged=(),
                comparisons=(),
                impacts=(),
                queue=(),
                pricing_rule_count=0,
            )
            artifacts = write_supplier_review_artifacts(run, folder)
            manifest = json.loads(artifacts.manifest_path.read_text(encoding="utf-8"))

            self.assertTrue(artifacts.queue_path.exists())
            self.assertTrue(artifacts.detail_path.exists())
            self.assertEqual(manifest["environment"], "Sandbox_NoZetadocs_UAT")
            self.assertEqual(manifest["source_size_bytes"], len(source_bytes))
            self.assertEqual(manifest["source_sha256"], hashlib.sha256(source_bytes).hexdigest())
            self.assertFalse(manifest["safety"]["business_central_writes"])
            self.assertTrue(manifest["safety"]["human_approval_required"])

    @patch("poc.commercial_guardrails.supplier_review_pipeline.analyze_supplier_review")
    @patch("poc.commercial_guardrails.supplier_review_pipeline.write_supplier_review_artifacts")
    def test_manual_run_persists_uploaded_source_in_unique_run_folder(
        self,
        write_artifacts,
        analyze_review,
    ):
        analyze_review.return_value = SimpleNamespace()
        write_artifacts.side_effect = lambda review, folder: SimpleNamespace(
            run_directory=Path(folder),
            source_path=next(Path(folder).glob("*.xlsx")),
        )

        with tempfile.TemporaryDirectory() as folder:
            artifacts = create_manual_supplier_review_run(
                "Supplier Notice (Sept).xlsx",
                b"synthetic workbook bytes",
                run_root=folder,
                config=SimpleNamespace(environment="Sandbox"),
                client=MagicMock(),
            )

            self.assertTrue(artifacts.run_directory.is_dir())
            self.assertEqual(artifacts.source_path.read_bytes(), b"synthetic workbook bytes")
            self.assertNotIn(" ", artifacts.source_path.name)

    @patch(
        "poc.commercial_guardrails.supplier_review_pipeline.analyze_supplier_review",
        side_effect=RuntimeError("synthetic failure"),
    )
    def test_failed_manual_run_keeps_source_and_failure_marker(self, _):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                create_manual_supplier_review_run(
                    "notice.csv",
                    b"supplier data",
                    run_root=folder,
                    config=SimpleNamespace(environment="Sandbox"),
                    client=MagicMock(),
                )

            run_dirs = list(Path(folder).iterdir())
            self.assertEqual(len(run_dirs), 1)
            self.assertTrue((run_dirs[0] / "notice.csv").exists())
            self.assertTrue((run_dirs[0] / "FAILED.txt").exists())


if __name__ == "__main__":
    unittest.main()
