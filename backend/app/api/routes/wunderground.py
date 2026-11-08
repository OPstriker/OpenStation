"""Weather Underground upload settings, status and "Upload now"."""

import httpx
from fastapi import APIRouter

from app.api.deps import SessionDep
from app.core.config import settings
from app.models import WundergroundConfigPublic, WundergroundConfigUpdate
from app.wunderground import get_config, to_public, upload

router = APIRouter(prefix="/wunderground", tags=["wunderground"])


@router.get("")
def read_wunderground(session: SessionDep) -> WundergroundConfigPublic:
    """Settings (never the key), last upload status and what would be sent now."""
    cfg = get_config(session)
    return to_public(session, cfg, dry_run=settings.COLLECTOR_SIMULATE)


@router.put("")
def update_wunderground(
    session: SessionDep, body: WundergroundConfigUpdate
) -> WundergroundConfigPublic:
    """Partial update. A blank or missing station_key keeps the stored key."""
    cfg = get_config(session)
    changes = body.model_dump(exclude_unset=True)
    key = changes.pop("station_key", None)
    if key and key.strip():
        cfg.station_key = key.strip()
    if changes.get("station_id") is not None:
        changes["station_id"] = changes["station_id"].strip()
    for name in ("enabled", "station_id", "interval_s"):
        if changes.get(name) is None:
            changes.pop(name, None)  # null means "unchanged" for these
    for name, value in changes.items():
        setattr(cfg, name, value)
    session.add(cfg)
    session.commit()
    session.refresh(cfg)
    return to_public(session, cfg, dry_run=settings.COLLECTOR_SIMULATE)


@router.post("/upload")
def upload_now(session: SessionDep) -> WundergroundConfigPublic:
    """Upload once now, whatever the schedule. Dry run in simulate mode."""
    cfg = get_config(session)
    with httpx.Client() as client:
        upload(session, cfg, client=client, dry_run=settings.COLLECTOR_SIMULATE)
    return to_public(session, cfg, dry_run=settings.COLLECTOR_SIMULATE)
