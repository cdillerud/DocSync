from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .bc_adapter import BCConfig, BusinessCentralClient
from .bc_item_costs import fetch_bc_item_cost_contexts
from .bc_pricing_rules import fetch_bc_pricing_rules
from .proposal_special_pricing import ProposalPricingRule
from .supplier_approval_queue import (
    SupplierApprovalItem,
    build_supplier_approval_queue,
    summarize_supplier_approval_queue,
    write_supplier_approval_queue_csv,
)
from .supplier_margin_impact import (
    SupplierMarginImpact,
    analyze_supplier_margin_impact,
    write_supplier_impact_csv,
)
from .supplier_price_compare import SupplierPriceComparison, compare_supplier_prices_to_bc
from .supplier_price_ingest import SupplierPriceChange, load_supplier_notice


DEFAULT_RUN_ROOT = Path("poc/commercial_guardrails/runs")


@dataclass(frozen=True)
class SupplierReviewRun:
    environment: str
    source_path: Path
    staged: tuple[SupplierPriceChange, ...]
    comparisons: tuple[SupplierPriceComparison, ...]
    impacts: tuple[SupplierMarginImpact, ...]
    queue: tuple[SupplierApprovalItem, ...]
    pricing_rule_count: int

    @property
    def summary(self) -> dict:
        queue_summary = summarize_supplier_approval_queue(self.queue)
        return {
            **queue_summary,
            "supplier_rows": len(self.staged),
            "review_rows": sum(row.status == "REVIEW" for row in self.impacts),
            "reject_rows": sum(row.status == "REJECT" for row in self.impacts),
            "pricing_rules_read": self.pricing_rule_count,
        }


@dataclass(frozen=True)
class SupplierReviewArtifacts:
    run_directory: Path
    source_path: Path
    queue_path: Path
    detail_path: Path
    decision_path: Path
    manifest_path: Path
    review_run: SupplierReviewRun


def _safe_source_name(name: str) -> str:
    leaf = Path(str(name or "supplier_notice")).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", leaf).strip("._")
    return cleaned or "supplier_notice"


def _run_directory_name(source_name: str, *, now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = Path(_safe_source_name(source_name)).stem[:48] or "supplier_notice"
    return f"{stamp}_{stem}_{uuid.uuid4().hex[:8]}"


def analyze_supplier_review(
    source_path: str | Path,
    *,
    start_date: str = "2024-01-01",
    end_date: str = "",
    default_supplier: str = "",
    sheet_name: str = "",
    recent_item_cost_count: int = 10,
    recent_customer_count: int = 3,
    history_alignment_tolerance_pct: float = 5.0,
    max_recent_cost_spread_pct: float = 15.0,
    trailing_days: int = 365,
    config: BCConfig | None = None,
    client: BusinessCentralClient | None = None,
) -> SupplierReviewRun:
    """Run the complete read-only supplier review pipeline for one local notice file.

    The function performs no Business Central writes. It reads item/UOM context, pricing
    guardrails, and posted sales history, then builds the human approval queue.
    """
    source = Path(source_path)
    staged = tuple(
        load_supplier_notice(
            source,
            default_supplier=default_supplier,
            sheet_name=sheet_name,
        )
    )
    item_nos = sorted({row.gpi_item_no for row in staged if row.gpi_item_no})

    resolved_config = config or BCConfig.from_env(source="custom")
    resolved_client = client or BusinessCentralClient(resolved_config)

    contexts = fetch_bc_item_cost_contexts(resolved_client, item_nos=item_nos)
    comparisons = tuple(compare_supplier_prices_to_bc(staged, contexts))
    pricing_rules: Sequence[ProposalPricingRule] = fetch_bc_pricing_rules(resolved_client)
    transactions = resolved_client.fetch_transactions(
        start_date=start_date,
        end_date=end_date,
        item_nos=item_nos,
    )

    impacts = tuple(
        analyze_supplier_margin_impact(
            comparison,
            transactions,
            pricing_rules=pricing_rules,
            recent_item_cost_count=recent_item_cost_count,
            recent_customer_count=recent_customer_count,
            history_alignment_tolerance_pct=history_alignment_tolerance_pct,
            max_recent_cost_spread_pct=max_recent_cost_spread_pct,
            trailing_days=trailing_days,
        )
        for comparison in comparisons
    )
    queue = tuple(build_supplier_approval_queue(impacts))

    return SupplierReviewRun(
        environment=resolved_config.environment,
        source_path=source,
        staged=staged,
        comparisons=comparisons,
        impacts=impacts,
        queue=queue,
        pricing_rule_count=len(pricing_rules),
    )


def write_supplier_review_artifacts(
    review_run: SupplierReviewRun,
    run_directory: str | Path,
) -> SupplierReviewArtifacts:
    folder = Path(run_directory)
    folder.mkdir(parents=True, exist_ok=True)

    queue_path = folder / "approval_queue.csv"
    detail_path = folder / "margin_impact.csv"
    decision_path = folder / "decisions.csv"
    manifest_path = folder / "manifest.json"

    write_supplier_approval_queue_csv(review_run.queue, queue_path)
    write_supplier_impact_csv(review_run.impacts, detail_path)

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": review_run.environment,
        "source_file": review_run.source_path.name,
        "summary": review_run.summary,
        "safety": {
            "business_central_writes": False,
            "human_approval_required": True,
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return SupplierReviewArtifacts(
        run_directory=folder,
        source_path=review_run.source_path,
        queue_path=queue_path,
        detail_path=detail_path,
        decision_path=decision_path,
        manifest_path=manifest_path,
        review_run=review_run,
    )


def create_manual_supplier_review_run(
    source_name: str,
    content: bytes,
    *,
    run_root: str | Path = DEFAULT_RUN_ROOT,
    start_date: str = "2024-01-01",
    end_date: str = "",
    default_supplier: str = "",
    sheet_name: str = "",
    recent_item_cost_count: int = 10,
    recent_customer_count: int = 3,
    history_alignment_tolerance_pct: float = 5.0,
    max_recent_cost_spread_pct: float = 15.0,
    trailing_days: int = 365,
    config: BCConfig | None = None,
    client: BusinessCentralClient | None = None,
) -> SupplierReviewArtifacts:
    """Persist a manually uploaded notice into its own auditable local run folder and analyze it."""
    run_root_path = Path(run_root)
    run_directory = run_root_path / _run_directory_name(source_name)
    run_directory.mkdir(parents=True, exist_ok=False)

    source_path = run_directory / _safe_source_name(source_name)
    source_path.write_bytes(content)

    try:
        review_run = analyze_supplier_review(
            source_path,
            start_date=start_date,
            end_date=end_date,
            default_supplier=default_supplier,
            sheet_name=sheet_name,
            recent_item_cost_count=recent_item_cost_count,
            recent_customer_count=recent_customer_count,
            history_alignment_tolerance_pct=history_alignment_tolerance_pct,
            max_recent_cost_spread_pct=max_recent_cost_spread_pct,
            trailing_days=trailing_days,
            config=config,
            client=client,
        )
        return write_supplier_review_artifacts(review_run, run_directory)
    except Exception:
        # Keep the source file for troubleshooting, but mark the run as failed instead of
        # deleting evidence of what the reviewer attempted to analyze.
        failure_path = run_directory / "FAILED.txt"
        failure_path.write_text(
            "Supplier review analysis failed. Inspect the application error and rerun after resolving it.\n",
            encoding="utf-8",
        )
        raise
