from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from commercial_context import (
    cost_change_context,
    customer_item_history,
    incorrect_item_context,
    item_cost_context,
)
from inbound_auth import require_inbound_principal
from item_similarity import similar_items
from margin_context import historical_margin_context, posted_margin_candidates


router = APIRouter(
    prefix="/commercialContext",
    tags=["Commercial Context"],
    dependencies=[Depends(require_inbound_principal)],
)


def _context_failure(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=502,
        detail={
            "error": "commercial_context_failure",
            "message": str(exc),
        },
    )


@router.get("/customerItemHistory")
def get_customer_item_history(
    customerNo: str = Query(min_length=1, max_length=20),
    itemNo: str | None = Query(default=None, max_length=20),
    top: int = Query(default=250, ge=1, le=1000),
) -> dict:
    try:
        return customer_item_history(
            customerNo,
            itemNo,
            top=top,
        )
    except Exception as exc:
        raise _context_failure(exc) from exc


@router.get("/itemCost")
def get_item_cost_context(
    itemNo: str = Query(min_length=1, max_length=20),
) -> dict:
    try:
        return item_cost_context(itemNo)
    except Exception as exc:
        raise _context_failure(exc) from exc


@router.get("/costChange")
def get_cost_change_context(
    itemNo: str = Query(min_length=1, max_length=20),
    top: int = Query(default=500, ge=1, le=1000),
) -> dict:
    try:
        return cost_change_context(itemNo, top=top)
    except Exception as exc:
        raise _context_failure(exc) from exc


@router.get("/marginHistory")
def get_margin_history(
    customerNo: str = Query(min_length=1, max_length=20),
    itemNo: str = Query(min_length=1, max_length=20),
    top: int = Query(default=250, ge=1, le=1000),
) -> dict:
    try:
        return historical_margin_context(
            customerNo,
            itemNo,
            top=top,
        )
    except Exception as exc:
        raise _context_failure(exc) from exc


@router.get("/lowMarginCandidates")
def get_low_margin_candidates(
    postingDate: date,
    hardFloorPercent: float = Query(default=20.0, ge=-1000, le=100),
    top: int = Query(default=1000, ge=1, le=5000),
) -> dict:
    try:
        return posted_margin_candidates(
            postingDate,
            hard_floor_percent=hardFloorPercent,
            top=top,
        )
    except Exception as exc:
        raise _context_failure(exc) from exc


@router.get("/similarItems")
def get_similar_items(
    itemNo: str = Query(min_length=1, max_length=20),
    topCandidates: int = Query(default=20, ge=1, le=100),
) -> dict:
    try:
        return similar_items(
            itemNo,
            top_candidates=topCandidates,
        )
    except Exception as exc:
        raise _context_failure(exc) from exc


@router.get("/incorrectItem")
def get_incorrect_item_context(
    customerNo: str = Query(min_length=1, max_length=20),
    itemNo: str = Query(min_length=1, max_length=20),
    top: int = Query(default=500, ge=1, le=1000),
) -> dict:
    try:
        result = incorrect_item_context(
            customerNo,
            itemNo,
            top=top,
        )
        result["similarItems"] = similar_items(
            itemNo,
            top_candidates=20,
        )
        return result
    except Exception as exc:
        raise _context_failure(exc) from exc
