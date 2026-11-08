from datetime import UTC, datetime

from sqlalchemy import BigInteger, Column, DateTime, Index
from sqlmodel import Field, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


class SensorReading(SQLModel, table=True):
    """One metric value from one sensor at one time (long/narrow format).

    Every sensor writes rows here, e.g. sensor="anemometer",
    metric="wind_speed_mph". New sensors need no schema change.
    """

    __tablename__ = "sensor_reading"
    __table_args__ = (
        Index("ix_sensor_reading_sensor_metric_ts", "sensor", "metric", "ts"),
    )

    id: int | None = Field(
        default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True)
    )
    ts: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    sensor: str = Field(max_length=64)
    metric: str = Field(max_length=64)
    value: float


class ReadingPoint(SQLModel):
    ts: datetime
    value: float
    # Only set for bucketed history: the max value inside the bucket.
    max: float | None = None


class ReadingHistory(SQLModel):
    sensor: str
    metric: str
    bucket_s: float | None
    points: list[ReadingPoint]


class LatestReadings(SQLModel):
    sensor: str
    ts: datetime | None
    age_s: float | None
    stale: bool
    metrics: dict[str, float]
