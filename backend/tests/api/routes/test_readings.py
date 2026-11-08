from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.core.config import settings
from app.models import SensorReading, get_datetime_utc
from tests.conftest import TEST_SENSOR

URL = f"{settings.API_V1_STR}/readings"


def _reset(db: Session) -> None:
    db.execute(delete(SensorReading).where(SensorReading.sensor == TEST_SENSOR))  # type: ignore[arg-type]
    db.commit()


def test_latest_empty(client: TestClient, db: Session) -> None:
    _reset(db)
    r = client.get(f"{URL}/latest", params={"sensor": TEST_SENSOR})
    assert r.status_code == 200
    body = r.json()
    assert body["ts"] is None
    assert body["stale"] is True
    assert body["metrics"] == {}


def test_latest_returns_newest_sample(client: TestClient, db: Session) -> None:
    _reset(db)
    now = get_datetime_utc()
    old = now - timedelta(seconds=1)
    db.add_all(
        [
            SensorReading(ts=old, sensor=TEST_SENSOR, metric="wind_speed_mph", value=1),
            SensorReading(ts=now, sensor=TEST_SENSOR, metric="wind_speed_mph", value=5),
            SensorReading(ts=now, sensor=TEST_SENSOR, metric="pulse_hz", value=3.35),
        ]
    )
    db.commit()
    body = client.get(f"{URL}/latest", params={"sensor": TEST_SENSOR}).json()
    assert body["metrics"] == {"wind_speed_mph": 5, "pulse_hz": 3.35}
    assert body["stale"] is False


def test_latest_stale(client: TestClient, db: Session) -> None:
    _reset(db)
    ts = get_datetime_utc() - timedelta(seconds=settings.STALE_AFTER_S + 5)
    db.add(SensorReading(ts=ts, sensor=TEST_SENSOR, metric="wind_speed_mph", value=2))
    db.commit()
    body = client.get(f"{URL}/latest", params={"sensor": TEST_SENSOR}).json()
    assert body["stale"] is True
    assert body["age_s"] > settings.STALE_AFTER_S


def test_history_raw_and_bucketed(client: TestClient, db: Session) -> None:
    _reset(db)
    now = get_datetime_utc()
    db.add_all(
        [
            SensorReading(
                ts=now - timedelta(seconds=s),
                sensor=TEST_SENSOR,
                metric="wind_speed_mph",
                value=float(s % 10),
            )
            for s in range(0, 3600, 1)
        ]
        + [SensorReading(ts=now, sensor=TEST_SENSOR, metric="pulse_hz", value=99)]
    )
    db.commit()

    params = {"sensor": TEST_SENSOR, "metric": "wind_speed_mph"}
    raw = client.get(f"{URL}/history", params={**params, "minutes": 5}).json()
    assert raw["bucket_s"] is None
    assert 299 <= len(raw["points"]) <= 301
    ts = [p["ts"] for p in raw["points"]]
    assert ts == sorted(ts)

    hour = client.get(f"{URL}/history", params={**params, "minutes": 60}).json()
    assert hour["bucket_s"] == 6
    assert len(hour["points"]) <= 601
    assert all(p["max"] is not None and p["max"] >= p["value"] for p in hour["points"])
    assert max(p["max"] for p in hour["points"]) == 9


def test_history_validates_minutes(client: TestClient) -> None:
    r = client.get(f"{URL}/history", params={"minutes": 0})
    assert r.status_code == 422
