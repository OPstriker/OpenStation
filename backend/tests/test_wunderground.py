from datetime import timedelta

import httpx
import pytest
from sqlmodel import Session

from app import wunderground as wu
from app.models import (
    LatestReadings,
    SensorReading,
    WundergroundConfig,
    WundergroundField,
    get_datetime_utc,
)
from app.readings import mean_since
from tests.conftest import TEST_SENSOR

KEY = "dummy-key-123"


def reading(
    sensor: str, metrics: dict[str, float], age_s: float = 1.0
) -> LatestReadings:
    return LatestReadings(
        sensor=sensor,
        ts=get_datetime_utc() - timedelta(seconds=age_s),
        age_s=age_s,
        stale=False,
        metrics=metrics,
    )


def all_fresh(**overrides: LatestReadings) -> dict[str, LatestReadings]:
    latest = {
        "air_quality": reading(
            "air_quality",
            {
                "temperature_c": 20.0,
                "humidity_pct": 45.4,
                "dew_point_c": 7.7,
                "co2_ppm": 600,
            },
        ),
        "barometer": reading(
            "barometer", {"pressure_hpa": 1000.0, "temperature_c": 30}
        ),
        "anemometer": reading(
            "anemometer", {"wind_speed_mph": 9.0, "wind_gust_mph": 14.04}
        ),
        "wind_vane": reading(
            "wind_vane",
            {"direction_deg": 225.0, "direction_avg_deg": 226.4, "calibrated": 1},
        ),
    }
    latest.update(overrides)
    return latest


def by_field(fields: list[WundergroundField]) -> dict[str, WundergroundField]:
    return {f.field: f for f in fields}


def test_all_fields_converted() -> None:
    f = by_field(wu.build_fields(all_fresh(), wind_avg_mph=8.26, elevation_m=10.0))
    assert f["tempf"].value == 68.0
    assert f["humidity"].value == 45
    assert f["dewptf"].value == pytest.approx(45.9)
    # 1000 hPa at 10 m -> ~1001.2 hPa sea level -> 29.57 inHg
    assert f["baromin"].value == pytest.approx(29.565, abs=0.01)
    assert f["windspeedmph"].value == 8.3  # the 2-min mean, not the latest 9.0
    assert f["windgustmph"].value == 14.0
    # Direction is computed and shown, but left out of the upload for now.
    assert f["winddir"].value == 226
    assert f["winddir"].skipped is not None and "not uploaded" in f["winddir"].skipped
    assert all(x.skipped is None for x in f.values() if x.field != "winddir")
    assert set(f) == {
        "tempf",
        "humidity",
        "dewptf",
        "baromin",
        "windspeedmph",
        "windgustmph",
        "winddir",
    }


def test_no_rain_fields() -> None:
    fields = wu.build_fields(all_fresh(), wind_avg_mph=1, elevation_m=0)
    assert not any("rain" in f.field for f in fields)


def test_pressure_needs_elevation_or_sea_level_metric() -> None:
    f = by_field(wu.build_fields(all_fresh(), wind_avg_mph=None, elevation_m=None))
    assert f["baromin"].value is None
    assert f["baromin"].skipped == "set the station elevation"

    baro = reading(
        "barometer", {"pressure_hpa": 1000.0, "sea_level_pressure_hpa": 1013.25}
    )
    f = by_field(
        wu.build_fields(all_fresh(barometer=baro), wind_avg_mph=None, elevation_m=None)
    )
    assert f["baromin"].value == pytest.approx(29.92, abs=0.01)


def test_stale_and_missing_sensors_are_skipped() -> None:
    latest = all_fresh(
        air_quality=reading("air_quality", {"temperature_c": 20}, age_s=600)
    )
    del latest["anemometer"]
    latest["anemometer"] = LatestReadings(
        sensor="anemometer", ts=None, age_s=None, stale=True, metrics={}
    )
    f = by_field(wu.build_fields(latest, wind_avg_mph=None, elevation_m=0))
    assert f["tempf"].skipped == "air-quality sensor stale (last reading 600 s ago)"
    assert f["humidity"].value is None
    assert f["windspeedmph"].skipped == "anemometer no readings"
    assert f["windgustmph"].value is None
    assert f["baromin"].skipped is None


def test_wind_speed_falls_back_to_latest_sample() -> None:
    f = by_field(wu.build_fields(all_fresh(), wind_avg_mph=None, elevation_m=0))
    assert f["windspeedmph"].value == 9.0


def test_direction_needs_north_set() -> None:
    vane = reading("wind_vane", {"direction_avg_deg": 90.0, "calibrated": 0})
    f = by_field(
        wu.build_fields(all_fresh(wind_vane=vane), wind_avg_mph=1, elevation_m=0)
    )
    assert f["winddir"].value is None
    assert f["winddir"].skipped is not None and "north not set" in f["winddir"].skipped


def test_direction_uploaded_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wu, "UPLOAD_WIND_DIRECTION", True)
    f = by_field(wu.build_fields(all_fresh(), wind_avg_mph=1, elevation_m=0))
    assert f["winddir"].value == 226 and f["winddir"].skipped is None


def test_is_due() -> None:
    now = get_datetime_utc()
    cfg = WundergroundConfig(
        enabled=True, station_id="KTEST1", station_key=KEY, interval_s=300
    )
    assert wu.is_due(cfg, now)  # never uploaded
    cfg.last_attempt_at = now - timedelta(seconds=299)
    assert not wu.is_due(cfg, now)
    cfg.last_attempt_at = now - timedelta(seconds=300)
    assert wu.is_due(cfg, now)
    cfg.enabled = False
    assert not wu.is_due(cfg, now)
    cfg.enabled, cfg.station_key = True, ""
    assert not wu.is_due(cfg, now)


def test_mean_since(db: Session) -> None:
    now = get_datetime_utc()
    db.add_all(
        [
            SensorReading(
                ts=now - timedelta(seconds=300),
                sensor=TEST_SENSOR,
                metric="m",
                value=100,
            ),
            SensorReading(
                ts=now - timedelta(seconds=60), sensor=TEST_SENSOR, metric="m", value=2
            ),
            SensorReading(
                ts=now - timedelta(seconds=1), sensor=TEST_SENSOR, metric="m", value=4
            ),
        ]
    )
    db.commit()
    assert mean_since(db, TEST_SENSOR, "m", 120) == 3
    assert mean_since(db, TEST_SENSOR, "nope", 120) is None


# ---- upload() --------------------------------------------------------------


@pytest.fixture
def fresh_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    fields = wu.build_fields(all_fresh(), wind_avg_mph=8.26, elevation_m=10.0)
    monkeypatch.setattr(wu, "collect_fields", lambda _session, _cfg: fields)


def configure(cfg: WundergroundConfig) -> None:
    cfg.enabled, cfg.station_id, cfg.station_key = True, "KTEST1", KEY
    cfg.last_attempt_at = cfg.last_success_at = None


def client_returning(status: int, text: str, seen: list[httpx.Request]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, text=text)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.usefixtures("fresh_fields")
def test_upload_success(db: Session, wu_config: WundergroundConfig) -> None:
    configure(wu_config)
    seen: list[httpx.Request] = []
    result = wu.upload(
        db, wu_config, client=client_returning(200, "success\n", seen), dry_run=False
    )
    assert result == "success"
    q = seen[0].url.params
    assert seen[0].url.host == "weatherstation.wunderground.com"
    assert q["ID"] == "KTEST1" and q["PASSWORD"] == KEY
    assert q["action"] == "updateraw" and q["dateutc"] == "now"
    assert q["tempf"] == "68" and q["windspeedmph"] == "8.3"
    assert "winddir" not in q
    assert wu_config.last_success_at is not None
    assert (
        wu_config.last_payload is not None and "PASSWORD" not in wu_config.last_payload
    )
    assert wu_config.last_payload["humidity"] == 45


@pytest.mark.usefixtures("fresh_fields")
def test_upload_error_keeps_message_and_hides_key(
    db: Session, wu_config: WundergroundConfig
) -> None:
    configure(wu_config)
    seen: list[httpx.Request] = []
    body = f"INVALIDPASSWORDID|Password or key and/or id are incorrect ({KEY})"
    result = wu.upload(
        db, wu_config, client=client_returning(401, body, seen), dry_run=False
    )
    assert result.startswith("error: HTTP 401: INVALIDPASSWORDID")
    assert KEY not in result
    assert wu_config.last_success_at is None
    assert wu_config.last_attempt_at is not None


@pytest.mark.usefixtures("fresh_fields")
def test_dry_run_sends_nothing(db: Session, wu_config: WundergroundConfig) -> None:
    configure(wu_config)
    seen: list[httpx.Request] = []
    result = wu.upload(
        db, wu_config, client=client_returning(200, "success", seen), dry_run=True
    )
    assert result.startswith("dry run")
    assert seen == []
    assert wu_config.last_payload and wu_config.last_payload["tempf"] == 68


def test_upload_skips_without_fresh_readings(
    db: Session, wu_config: WundergroundConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(wu_config)
    monkeypatch.setattr(wu, "collect_fields", lambda _s, _c: [])
    seen: list[httpx.Request] = []
    result = wu.upload(
        db, wu_config, client=client_returning(200, "success", seen), dry_run=False
    )
    assert result == "skipped: no fresh readings to send"
    assert seen == []
