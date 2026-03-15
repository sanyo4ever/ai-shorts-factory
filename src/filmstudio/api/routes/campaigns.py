from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from filmstudio.domain.models import CampaignReleaseUpdateRequest

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


@router.get("/compare")
def compare_campaigns(
    request: Request,
    left: str = Query(...),
    right: str = Query(...),
):
    payload = request.app.state.campaign_service.compare_campaigns(left, right)
    if payload is None:
        raise HTTPException(status_code=404, detail="Campaign comparison target not found")
    return payload


@router.get("/release/baseline")
def get_release_baseline(request: Request):
    payload = request.app.state.campaign_service.get_release_baseline(generate_if_missing=True)
    if payload is None:
        raise HTTPException(status_code=404, detail="Canonical release baseline not found")
    return payload


@router.post("/{campaign_name}/release")
def update_campaign_release_status(
    request: Request,
    campaign_name: str,
    release_update: CampaignReleaseUpdateRequest,
):
    try:
        return request.app.state.campaign_service.update_release_status(
            campaign_name,
            status=release_update.status,
            note=release_update.note,
            compared_to=release_update.compared_to,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Campaign not found") from exc


@router.get("/{campaign_name}")
def get_campaign(
    request: Request,
    campaign_name: str,
    compare_to: str | None = Query(default=None),
):
    payload = request.app.state.campaign_service.get_campaign(
        campaign_name,
        compare_to=compare_to,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return payload
