"""Queries over sensor_reading shared by the API and the collector."""

from datetime import timedelta

from sqlmodel import Session, func, select

from app.core.config import settings
from app.models import LatestReadings, SensorReading, get_datetime_utc


def latest_readings(session: Session, sensor: str) -> LatestReadings:
    """Newest value of every metric for a sensor, plus a staleness flag."""
    latest_ts = session.exec(
        select(func.max(SensorReading.ts)).where(SensorReading.sensor == sensor)
    ).one()
    if latest_ts is None:
        return LatestReadings(
            sensor=sensor, ts=None, age_s=None, stale=True, metrics={}
        )

    rows = session.exec(
        select(SensorReading.metric, SensorReading.value).where(
            SensorReading.sensor == sensor, SensorReading.ts == latest_ts
        )
    ).all()
    age_s = (get_datetime_utc() - latest_ts).total_seconds()
    return LatestReadings(
        sensor=sensor,
        ts=latest_ts,
        age_s=age_s,
        stale=age_s > settings.STALE_AFTER_S,
        metrics=dict(rows),
    )


def mean_since(
    session: Session, sensor: str, metric: str, seconds: float
) -> float | None:
    """Average of one metric over the last `seconds`, or None without samples."""
    since = get_datetime_utc() - timedelta(seconds=seconds)
    value = session.exec(
        select(func.avg(SensorReading.value)).where(
            SensorReading.sensor == sensor,
            SensorReading.metric == metric,
            SensorReading.ts >= since,
        )
    ).one()
    return None if value is None else float(value)
