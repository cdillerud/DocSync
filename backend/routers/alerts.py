"""GPI Document Hub - Alerts Router"""

from fastapi import APIRouter, HTTPException
from services.alert_pattern_service import get_alert_pattern_service

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.get("/active")
async def get_active_alerts(
    severity: str = None,
    vendor: str = None,
    predicted_label: str = None,
    actual_entity_type: str = None,
):
    svc = get_alert_pattern_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Alert service not initialized")
    return await svc.get_active_alerts(
        severity=severity, vendor=vendor,
        predicted_label=predicted_label, actual_entity_type=actual_entity_type
    )


@router.get("/summary")
async def get_alert_summary():
    svc = get_alert_pattern_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Alert service not initialized")
    return await svc.get_alert_summary()


@router.get("/all")
async def get_all_alerts(include_resolved: bool = False):
    svc = get_alert_pattern_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Alert service not initialized")
    return await svc.get_all_alerts(include_resolved=include_resolved)


@router.post("/evaluate")
async def trigger_alert_evaluation():
    svc = get_alert_pattern_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Alert service not initialized")
    return await svc.trigger_evaluation()


@router.post("/{pattern_key}/dismiss")
async def dismiss_alert(pattern_key: str):
    svc = get_alert_pattern_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Alert service not initialized")
    ok = await svc.dismiss_alert(pattern_key)
    if not ok:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"status": "dismissed", "pattern_key": pattern_key}


@router.post("/{pattern_key}/resolve")
async def resolve_alert(pattern_key: str):
    svc = get_alert_pattern_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Alert service not initialized")
    ok = await svc.resolve_alert(pattern_key)
    if not ok:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"status": "resolved", "pattern_key": pattern_key}
