import math
from datetime import timedelta

from fastapi import APIRouter, Query
from sqlalchemy import text
from sqlmodel import col, select

from app.api.deps import SessionDep
from app.models import (
    LatestReadings,
    ReadingHistory,
    ReadingPoint,
    SensorReading,
    get_datetime_utc,
)
from app.readings import latest_readings

router = APIRouter(prefix="/readings", tags=["readings"])

# History windows up to this long return every raw sample; longer windows are
# averaged into buckets so the response stays around MAX_POINTS points.
RAW_HISTORY_MAX_MINUTES = 15
MAX_POINTS = 600


@router.get("/latest")
def read_latest(
    session: SessionDep, sensor: str = Query(default="anemometer", max_length=64)
) -> LatestReadings:
    """Newest value of every metric for a sensor, plus a staleness flag."""
    return latest_readings(session, sensor)


@router.get("/history")
def read_history(
    session: SessionDep,
    sensor: str = Query(default="anemometer", max_length=64),
    metric: str = Query(default="wind_speed_mph", max_length=64),
    minutes: float = Query(default=10, gt=0, le=60 * 24 * 7),
) -> ReadingHistory:
    """Time series of one metric. Raw for short windows, bucketed (avg + max) otherwise."""
    since = get_datetime_utc() - timedelta(minutes=minutes)

    if minutes <= RAW_HISTORY_MAX_MINUTES:
        rows = session.exec(
            select(SensorReading.ts, SensorReading.value)
            .where(
                SensorReading.sensor == sensor,
                SensorReading.metric == metric,
                SensorReading.ts >= since,
            )
            .order_by(col(SensorReading.ts))
        ).all()
        return ReadingHistory(
            sensor=sensor,
            metric=metric,
            bucket_s=None,
            points=[ReadingPoint(ts=ts, value=value) for ts, value in rows],
        )

    bucket_s = float(math.ceil(minutes * 60 / MAX_POINTS))
    bucketed = (
        session.connection()
        .execute(
            text(
                """
            SELECT date_bin(make_interval(secs => :bucket_s), ts,
                            TIMESTAMPTZ '2000-01-01') AS bucket,
                   avg(value) AS avg_value,
                   max(value) AS max_value
            FROM sensor_reading
            WHERE sensor = :sensor AND metric = :metric AND ts >= :since
            GROUP BY bucket
            ORDER BY bucket
            """
            ),
            {"bucket_s": bucket_s, "sensor": sensor, "metric": metric, "since": since},
        )
        .all()
    )
    return ReadingHistory(
        sensor=sensor,
        metric=metric,
        bucket_s=bucket_s,
        points=[
            ReadingPoint(ts=bucket, value=avg_value, max=max_value)
            for bucket, avg_value, max_value in bucketed
        ],
    )
