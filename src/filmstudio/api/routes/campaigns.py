from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/v1/campaigns", tags=["campaigns"])


@router.get("")
def list_campaigns(
    request: Request,
    family: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=100),
):
    return request.app.state.campaign_service.list_campaigns(family=family, limit=limit)


@router.get("/overview")
def get_campaign_overview(request: Request):
    return request.app.state.campaign_service.build_overview()


@router.get("/{campaign_name}")
def get_campaign(request: Request, campaign_name: str):
    payload = request.app.state.campaign_service.get_campaign(campaign_name)
    if payload is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return payload
