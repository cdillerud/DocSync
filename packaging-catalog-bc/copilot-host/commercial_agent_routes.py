from __future__ import annotations

import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ai_provider import ai_provider_configured, evaluate_with_ai
from commercial_agent_service import (
    build_cost_change_request,
    build_incorrect_item_request,
    build_low_margin_request,
)
from commercial_persistence import persist_evaluation
from commercial_queue_worker import (
    execute_next_queue,
    prepare_next_queue,
)
from commercial_screening import screen_request
from inbound_auth import require_inbound_principal


router = APIRouter(
    prefix="/commercialAgents",
    tags=["Commercial Agents"],
    dependencies=[Depends(require_inbound_principal)],
)


class LowMarginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customerNo: str = Field(min_length=1, max_length=20)
    itemNo: str = Field(min_length=1, max_length=20)
    documentNo: str = Field(min_length=1, max_length=20)
    unitPrice: float
    unitCost: float
    quantity: float = Field(gt=0)
    lineAmount: float | None = None
    sourceSystemId: UUID | None = None


class CostChangeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    itemNo: str = Field(min_length=1, max_length=20)
    previousUnitCost: float
    currentUnitCost: float
    sourceKey: str | None = Field(default=None, max_length=100)
    sourceSystemId: UUID | None = None


class IncorrectItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customerNo: str = Field(min_length=1, max_length=20)
    itemNo: str = Field(min_length=1, max_length=20)
    documentNo: str = Field(min_length=1, max_length=20)
    sourceSystemId: UUID | None = None


def persistence_enabled() -> bool:
    return (
        os.getenv("GPI_ENABLE_COMMERCIAL_PERSISTENCE", "0")
        .strip()
        .lower()
        in {"1", "true", "yes", "on"}
    )


def _evaluate_or_prepare(request):
    screening = screen_request(request)
    screening_payload = screening.to_dict()

    if not screening.should_evaluate:
        return {
            "mode": "screenedOut",
            "aiProviderConfigured": ai_provider_configured(),
            "persistenceEnabled": persistence_enabled(),
            "screening": screening_payload,
            "evaluationRequest": request.model_dump(mode="json"),
        }

    if not ai_provider_configured():
        return {
            "mode": "prepared",
            "aiProviderConfigured": False,
            "persistenceEnabled": persistence_enabled(),
            "screening": screening_payload,
            "evaluationRequest": request.model_dump(mode="json"),
        }

    result = evaluate_with_ai(request)
    persistence = {
        "persisted": False,
        "reason": "persistence_disabled",
    }
    if persistence_enabled():
        persistence = persist_evaluation(request, result)

    return {
        "mode": "evaluated",
        "aiProviderConfigured": True,
        "persistenceEnabled": persistence_enabled(),
        "screening": screening_payload,
        "evaluationRequest": request.model_dump(mode="json"),
        "evaluationResult": result.model_dump(mode="json"),
        "persistence": persistence,
    }


@router.post("/lowMargin/evaluate")
def evaluate_low_margin(payload: LowMarginInput) -> dict:
    try:
        request = build_low_margin_request(
            customer_no=payload.customerNo,
            item_no=payload.itemNo,
            document_no=payload.documentNo,
            unit_price=payload.unitPrice,
            unit_cost=payload.unitCost,
            quantity=payload.quantity,
            line_amount=payload.lineAmount,
            source_system_id=payload.sourceSystemId,
        )
        return _evaluate_or_prepare(request)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "low_margin_evaluation_failure",
                "message": str(exc),
            },
        ) from exc


@router.post("/costChange/evaluate")
def evaluate_cost_change(payload: CostChangeInput) -> dict:
    try:
        request = build_cost_change_request(
            item_no=payload.itemNo,
            previous_unit_cost=payload.previousUnitCost,
            current_unit_cost=payload.currentUnitCost,
            source_key=payload.sourceKey,
            source_system_id=payload.sourceSystemId,
        )
        return _evaluate_or_prepare(request)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "cost_change_evaluation_failure",
                "message": str(exc),
            },
        ) from exc


@router.post("/incorrectItem/evaluate")
def evaluate_incorrect_item(payload: IncorrectItemInput) -> dict:
    try:
        request = build_incorrect_item_request(
            customer_no=payload.customerNo,
            item_no=payload.itemNo,
            document_no=payload.documentNo,
            source_system_id=payload.sourceSystemId,
        )
        return _evaluate_or_prepare(request)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "incorrect_item_evaluation_failure",
                "message": str(exc),
            },
        ) from exc


@router.post("/queue/prepareNext")
def prepare_next_commercial_queue() -> dict:
    try:
        return prepare_next_queue()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "commercial_queue_prepare_failure",
                "message": str(exc),
            },
        ) from exc


@router.post("/queue/executeNext")
def execute_next_commercial_queue() -> dict:
    try:
        return execute_next_queue()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "commercial_queue_execute_refused_or_failed",
                "message": str(exc),
            },
        ) from exc
