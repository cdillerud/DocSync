from __future__ import annotations

from uuid import UUID, uuid4

from candidate_screening import (
    screen_cost_change,
    screen_incorrect_item,
    screen_low_margin,
)
from commercial_agent_contract import (
    CommercialEvaluationRequest,
    CommercialEvidence,
)
from commercial_context import (
    cost_change_context,
    incorrect_item_context,
)
from item_similarity import similar_items
from margin_context import build_margin_context


def _pct_change(previous: float, current: float) -> float | None:
    if previous == 0:
        return None
    return ((current - previous) / abs(previous)) * 100


def build_low_margin_request(
    *,
    customer_no: str,
    item_no: str,
    document_no: str,
    unit_price: float,
    unit_cost: float,
    quantity: float,
    line_amount: float | None = None,
    source_system_id: UUID | None = None,
    correlation_id: UUID | None = None,
) -> CommercialEvaluationRequest:
    correlation_id = correlation_id or uuid4()

    context = build_margin_context(
        customer_no=customer_no,
        item_no=item_no,
        current_unit_price=unit_price,
        current_unit_cost=unit_cost,
        current_quantity=quantity,
    )

    current_margin_pct = context.get("current", {}).get("marginPct")
    historical_margin_pct = context.get("historical", {}).get(
        "weightedMarginPct"
    )
    variance = None
    if current_margin_pct is not None and historical_margin_pct is not None:
        variance = float(current_margin_pct) - float(historical_margin_pct)

    screening = screen_low_margin(
        current_margin_pct=(
            None if current_margin_pct is None else float(current_margin_pct)
        ),
        historical_margin_pct=(
            None
            if historical_margin_pct is None
            else float(historical_margin_pct)
        ),
    )
    context["screening"] = screening.to_dict()

    evidence = [
        CommercialEvidence(
            evidenceType="Margin",
            sourceSystem="Business Central",
            sourceRecordType="Sales Document",
            sourceSystemId=source_system_id,
            metric="CurrentMarginPct",
            currentValue=str(current_margin_pct),
            comparisonValue=(
                None
                if historical_margin_pct is None
                else str(historical_margin_pct)
            ),
            variance=variance,
            unit="Percent",
            weight=100,
            explanation=(
                "Current authoritative unit-price/unit-cost margin compared "
                "with customer/item posted-sales history."
            ),
            provenance="Business Central deterministic margin context",
        )
    ]

    return CommercialEvaluationRequest(
        agentType="lowMargin",
        correlationId=correlation_id,
        sourceType="SalesDocument",
        sourceSystemId=source_system_id,
        sourceKey=document_no,
        customerNo=customer_no,
        itemNo=item_no,
        documentType="Sales",
        documentNo=document_no,
        authoritativeFacts={
            "unitPrice": unit_price,
            "unitCost": unit_cost,
            "quantity": quantity,
            "lineAmount": line_amount,
            "currentMarginPct": current_margin_pct,
            "deterministicCandidate": screening.should_evaluate,
        },
        context=context,
        evidence=evidence,
    )


def build_cost_change_request(
    *,
    item_no: str,
    previous_unit_cost: float,
    current_unit_cost: float,
    source_key: str | None = None,
    source_system_id: UUID | None = None,
    correlation_id: UUID | None = None,
) -> CommercialEvaluationRequest:
    correlation_id = correlation_id or uuid4()
    context = cost_change_context(item_no)
    change_pct = _pct_change(previous_unit_cost, current_unit_cost)
    source_key = source_key or item_no
    screening = screen_cost_change(
        previous_unit_cost=previous_unit_cost,
        current_unit_cost=current_unit_cost,
    )
    context["screening"] = screening.to_dict()

    evidence = [
        CommercialEvidence(
            evidenceType="CostChange",
            sourceSystem="Business Central",
            sourceRecordType="Packaging Product",
            sourceSystemId=source_system_id,
            metric="SupplierUnitCost",
            currentValue=str(current_unit_cost),
            comparisonValue=str(previous_unit_cost),
            variance=current_unit_cost - previous_unit_cost,
            unit="CurrencyPerUnit",
            weight=100,
            explanation=(
                "Authoritative supplier unit cost change with historical "
                "customer exposure from posted sales."
            ),
            provenance="Business Central Packaging Catalog and posted sales",
        )
    ]

    return CommercialEvaluationRequest(
        agentType="costChange",
        correlationId=correlation_id,
        sourceType="PackagingProduct",
        sourceSystemId=source_system_id,
        sourceKey=source_key,
        itemNo=item_no,
        authoritativeFacts={
            "previousUnitCost": previous_unit_cost,
            "currentUnitCost": current_unit_cost,
            "costDelta": current_unit_cost - previous_unit_cost,
            "costChangePct": change_pct,
            "deterministicCandidate": screening.should_evaluate,
        },
        context=context,
        evidence=evidence,
    )


def build_incorrect_item_request(
    *,
    customer_no: str,
    item_no: str,
    document_no: str,
    source_system_id: UUID | None = None,
    correlation_id: UUID | None = None,
) -> CommercialEvaluationRequest:
    correlation_id = correlation_id or uuid4()
    context = incorrect_item_context(customer_no, item_no)
    similarity = similar_items(item_no, top_candidates=20)
    context["similarItems"] = similarity

    purchased_before = bool(context.get("candidatePurchasedBefore"))
    historical_count = int(context.get("candidateHistoricalLineCount") or 0)
    candidates = similarity.get("candidates", [])
    top_similarity_score = None
    if candidates:
        top_similarity_score = candidates[0].get("score")
        if top_similarity_score is not None:
            top_similarity_score = float(top_similarity_score)

    screening = screen_incorrect_item(
        candidate_purchased_before=purchased_before,
        candidate_historical_line_count=historical_count,
        top_similarity_score=top_similarity_score,
    )
    context["screening"] = screening.to_dict()

    evidence = [
        CommercialEvidence(
            evidenceType="PurchaseHistory",
            sourceSystem="Business Central",
            sourceRecordType="Posted Sales",
            sourceSystemId=None,
            metric="CandidateHistoricalLines",
            currentValue=str(historical_count),
            comparisonValue=None,
            variance=None,
            unit="Count",
            weight=100,
            explanation=(
                "Whether the customer has historically purchased the exact "
                "candidate item."
            ),
            provenance="Business Central posted sales history",
        ),
        CommercialEvidence(
            evidenceType="ItemSimilarity",
            sourceSystem="Business Central",
            sourceRecordType="Packaging Catalog",
            sourceSystemId=source_system_id,
            metric="TopSimilarityScore",
            currentValue=(
                "" if top_similarity_score is None else str(top_similarity_score)
            ),
            comparisonValue=None,
            variance=None,
            unit="Percent",
            weight=90,
            explanation=(
                "Deterministic Packaging Catalog similarity context for "
                "AI anomaly reasoning."
            ),
            provenance="Business Central Packaging Catalog",
        ),
    ]

    return CommercialEvaluationRequest(
        agentType="incorrectItem",
        correlationId=correlation_id,
        sourceType="SalesOrderLine",
        sourceSystemId=source_system_id,
        sourceKey=f"{document_no}:{item_no}",
        customerNo=customer_no,
        itemNo=item_no,
        documentType="SalesOrder",
        documentNo=document_no,
        authoritativeFacts={
            "candidatePurchasedBefore": purchased_before,
            "candidateHistoricalLineCount": historical_count,
            "topSimilarityScore": top_similarity_score,
            "deterministicCandidate": screening.should_evaluate,
        },
        context=context,
        evidence=evidence,
    )
