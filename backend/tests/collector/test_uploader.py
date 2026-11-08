from collections.abc import Callable
from datetime import datetime, timedelta

import httpx
import pytest
from sqlmodel import Session

from app import wunderground as wu
from app.collector.uploader import WundergroundUploader
from app.core.db import engine
from app.models import LatestReadings, WundergroundConfig, get_datetime_utc


@pytest.fixture
def fresh_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    latest = {
        "air_quality": LatestReadings(
            sensor="air_quality",
            ts=get_datetime_utc(),
            age_s=1,
            stale=False,
            metrics={"temperature_c": 20.0, "humidity_pct": 50.0, "dew_point_c": 9.3},
        )
    }
    fields = wu.build_fields(latest, wind_avg_mph=None, elevation_m=None)
    monkeypatch.setattr(wu, "collect_fields", lambda _s, _c: fields)


@pytest.mark.usefixtures("fresh_fields")
def test_uploads_when_due_and_not_before(
    db: Session, wu_config: WundergroundConfig
) -> None:
    wu_config.enabled, wu_config.station_id, wu_config.station_key = True, "KTEST1", "k"
    wu_config.interval_s = 300
    wu_config.last_attempt_at = None
    db.add(wu_config)
    db.commit()

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="success")

    now = [get_datetime_utc()]
    clock: Callable[[], datetime] = lambda: now[0]  # noqa: E731
    uploader = WundergroundUploader(
        dry_run=False,
        session_factory=lambda: Session(engine),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=clock,
    )
    assert uploader.tick() == "success"
    assert requests[0].url.params["tempf"] == "68"
    assert "baromin" not in requests[0].url.params  # no barometer reading

    now[0] += timedelta(seconds=120)
    assert uploader.tick() is None  # 2 min later: not due yet
    now[0] += timedelta(seconds=180)
    assert uploader.tick() == "success"  # 5 min after the first
    assert len(requests) == 2

    # Disabled from the dashboard: stops without a restart.
    db.refresh(wu_config)
    wu_config.enabled = False
    db.add(wu_config)
    db.commit()
    now[0] += timedelta(seconds=600)
    assert uploader.tick() is None
    assert len(requests) == 2
