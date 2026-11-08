"""Upload readings to a Weather Underground personal weather station (PWS).

Protocol: one GET to UPLOAD_URL with the station ID, the station key as
PASSWORD, dateutc=now, action=updateraw and the values in imperial units. WU
answers "success" in plain text, anything else is an error message.

Shared by the collector (scheduled uploads) and the API ("Upload now" and the
dashboard preview). Fields are only sent when their sensor has a fresh reading:
WU treats a sent value as real, so a missing sensor is left out, never sent as 0.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session

from app.collector.barometer import sea_level_pressure
from app.models import (
    LatestReadings,
    WundergroundConfig,
    WundergroundConfigPublic,
    WundergroundField,
    get_datetime_utc,
)
from app.readings import latest_readings, mean_since

logger = logging.getLogger(__name__)
# httpx logs every request URL at INFO, and the URL carries the station key.
logging.getLogger("httpx").setLevel(logging.WARNING)

UPLOAD_URL = (
    "https://weatherstation.wunderground.com/weatherstation/updateweatherstation.php"
)
SOFTWARE_TYPE = "makecu-weather-station"
TIMEOUT_S = 10.0
# A sensor whose newest reading is older than this is left out of the upload.
MAX_AGE_S = 60.0
# windspeedmph is the mean over this window: one 1 s sample is too noisy.
WIND_AVG_S = 120.0
HPA_TO_INHG = 0.029529983071445
# winddir is shown on the dashboard but not sent until the vane is trusted.
UPLOAD_WIND_DIRECTION = False

SENSOR_LABELS = {
    "air_quality": "air-quality sensor",
    "barometer": "barometer",
    "anemometer": "anemometer",
    "wind_vane": "wind vane",
}


def c_to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


def get_config(session: Session) -> WundergroundConfig:
    """The single config row, created on first use."""
    cfg = session.get(WundergroundConfig, 1)
    if cfg is None:
        # ON CONFLICT: the API and the collector may both get here first.
        session.connection().execute(
            insert(WundergroundConfig).values(id=1).on_conflict_do_nothing()
        )
        session.commit()
        cfg = session.get(WundergroundConfig, 1)
        assert cfg is not None
    return cfg


@dataclass
class _Spec:
    field: str
    label: str
    unit: str
    sensor: str
    metric: str
    digits: int
    convert: Callable[[float], float] = lambda v: v


TEMP = _Spec("tempf", "Temperature", "°F", "air_quality", "temperature_c", 1, c_to_f)
HUMIDITY = _Spec("humidity", "Humidity", "%", "air_quality", "humidity_pct", 0)
DEW_POINT = _Spec("dewptf", "Dew point", "°F", "air_quality", "dew_point_c", 1, c_to_f)
PRESSURE = _Spec(
    "baromin", "Pressure (sea level)", "inHg", "barometer", "pressure_hpa", 2
)
SPEED = _Spec(
    "windspeedmph", "Wind speed (2 min avg)", "mph", "anemometer", "wind_speed_mph", 1
)
GUST = _Spec(
    "windgustmph", "Wind gust (10 min)", "mph", "anemometer", "wind_gust_mph", 1
)
DIRECTION = _Spec(
    "winddir", "Wind direction (2 min avg)", "°", "wind_vane", "direction_avg_deg", 0
)


def _freshness(latest: LatestReadings | None) -> str | None:
    """Why this sensor can't be used, or None if it is fresh."""
    if latest is None or latest.age_s is None:
        return "no readings"
    if latest.age_s > MAX_AGE_S:
        return f"stale (last reading {latest.age_s:.0f} s ago)"
    return None


def build_fields(
    latest: dict[str, LatestReadings],
    *,
    wind_avg_mph: float | None,
    elevation_m: float | None,
) -> list[WundergroundField]:
    """Every upload field with its value, or the reason it is skipped. Pure."""
    fields: list[WundergroundField] = []

    def add(spec: _Spec, value: float | None, skipped: str | None, source: str) -> None:
        fields.append(
            WundergroundField(
                field=spec.field,
                label=spec.label,
                value=None if value is None else round(value, spec.digits),
                unit=spec.unit,
                source=source,
                skipped=skipped,
            )
        )

    def lookup(spec: _Spec) -> tuple[float | None, str | None]:
        reading = latest.get(spec.sensor)
        problem = _freshness(reading)
        if problem is not None:
            return None, f"{SENSOR_LABELS[spec.sensor]} {problem}"
        assert reading is not None
        raw = reading.metrics.get(spec.metric)
        if raw is None:
            return None, f"{SENSOR_LABELS[spec.sensor]} not reporting {spec.metric}"
        return spec.convert(raw), None

    for spec in (TEMP, HUMIDITY, DEW_POINT):
        value, skipped = lookup(spec)
        add(spec, value, skipped, f"{spec.sensor}.{spec.metric}")

    # Pressure, reduced to sea level (what WU and weather reports show).
    station_hpa, skipped = lookup(PRESSURE)
    pressure: float | None = None
    source = "barometer.pressure_hpa"
    if station_hpa is not None:
        if elevation_m is not None:
            pressure = sea_level_pressure(station_hpa * 100.0, elevation_m) / 100.0
            source = f"barometer.pressure_hpa at {elevation_m:.0f} m"
        elif (
            sl := latest["barometer"].metrics.get("sea_level_pressure_hpa")
        ) is not None:
            pressure = sl
            source = "barometer.sea_level_pressure_hpa"
        else:
            skipped = "set the station elevation"
    add(PRESSURE, None if pressure is None else pressure * HPA_TO_INHG, skipped, source)

    # Wind speed: mean over WIND_AVG_S, falling back to the latest sample.
    latest_speed, skipped = lookup(SPEED)
    add(
        SPEED,
        None
        if skipped
        else (wind_avg_mph if wind_avg_mph is not None else latest_speed),
        skipped,
        "anemometer.wind_speed_mph, 2 min mean",
    )
    value, skipped = lookup(GUST)
    add(GUST, value, skipped, "anemometer.wind_gust_mph")

    # Direction: only once north has been set, or the bearing is meaningless.
    direction, skipped = lookup(DIRECTION)
    if skipped is None and latest["wind_vane"].metrics.get("calibrated") != 1:
        direction, skipped = None, "north not set (press the vane's knob)"
    if skipped is None and not UPLOAD_WIND_DIRECTION:
        # Keep the value so the dashboard still shows it, but never send it.
        skipped = "not uploaded yet (wind direction is disabled for now)"
    add(
        DIRECTION,
        None if direction is None else direction % 360,
        skipped,
        "wind_vane.direction_avg_deg",
    )
    return fields


def collect_fields(
    session: Session, cfg: WundergroundConfig
) -> list[WundergroundField]:
    latest = {name: latest_readings(session, name) for name in SENSOR_LABELS}
    wind_avg = mean_since(session, "anemometer", "wind_speed_mph", WIND_AVG_S)
    return build_fields(latest, wind_avg_mph=wind_avg, elevation_m=cfg.elevation_m)


def has_credentials(cfg: WundergroundConfig) -> bool:
    return bool(cfg.station_id.strip() and cfg.station_key)


def next_upload_at(cfg: WundergroundConfig, now: datetime) -> datetime | None:
    if not cfg.enabled or not has_credentials(cfg):
        return None
    if cfg.last_attempt_at is None:
        return now
    return cfg.last_attempt_at + timedelta(seconds=cfg.interval_s)


def is_due(cfg: WundergroundConfig, now: datetime) -> bool:
    due = next_upload_at(cfg, now)
    return due is not None and now >= due


def _format(value: float) -> str:
    return f"{value:g}"


def upload(
    session: Session,
    cfg: WundergroundConfig,
    *,
    client: httpx.Client,
    dry_run: bool,
    now: datetime | None = None,
) -> str:
    """Send the fresh fields once and record the outcome on the config row."""
    now = now or get_datetime_utc()
    sent = {
        f.field: f.value
        for f in collect_fields(session, cfg)
        if f.skipped is None and f.value is not None
    }
    if not has_credentials(cfg):
        result = "error: station ID and key are required"
    elif not sent:
        result = "skipped: no fresh readings to send"
    elif dry_run:
        result = "dry run: not sent (simulate mode)"
    else:
        params = {
            "ID": cfg.station_id.strip(),
            "PASSWORD": cfg.station_key,
            "dateutc": "now",
            "action": "updateraw",
            "softwaretype": SOFTWARE_TYPE,
            **{k: _format(v) for k, v in sent.items()},
        }
        try:
            r = client.get(UPLOAD_URL, params=params, timeout=TIMEOUT_S)
            body = r.text.strip()
            if r.status_code == 200 and body.lower() == "success":
                result = "success"
            else:
                result = f"error: HTTP {r.status_code}: {body or r.reason_phrase}"
        except httpx.HTTPError as exc:
            result = f"error: {type(exc).__name__}: {exc}"
        # Never store or show the key, whatever an error message contains.
        result = result.replace(cfg.station_key, "***")

    cfg.last_attempt_at = now
    if result == "success":
        cfg.last_success_at = now
    cfg.last_result = result[:512]
    cfg.last_payload = sent
    session.add(cfg)
    session.commit()
    session.refresh(cfg)
    return result


def to_public(
    session: Session, cfg: WundergroundConfig, *, dry_run: bool
) -> WundergroundConfigPublic:
    return WundergroundConfigPublic(
        enabled=cfg.enabled,
        station_id=cfg.station_id,
        has_key=bool(cfg.station_key),
        interval_s=cfg.interval_s,
        elevation_m=cfg.elevation_m,
        last_attempt_at=cfg.last_attempt_at,
        last_success_at=cfg.last_success_at,
        last_result=cfg.last_result,
        last_payload=cfg.last_payload,
        next_upload_at=next_upload_at(cfg, get_datetime_utc()),
        dry_run=dry_run,
        fields=collect_fields(session, cfg),
    )
