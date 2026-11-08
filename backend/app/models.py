from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, Column, DateTime, Index
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


# ---- Weather Underground upload ---------------------------------------------


class WundergroundConfig(SQLModel, table=True):
    """Upload settings, edited from the dashboard. One row, id=1.

    The collector reads it every few seconds and writes the last_* status
    fields after each upload. station_key is a secret: never return it from
    the API.
    """

    __tablename__ = "wunderground_config"

    id: int = Field(default=1, primary_key=True)
    enabled: bool = False
    station_id: str = Field(default="", max_length=64)
    station_key: str = Field(default="", max_length=128)
    interval_s: int = 300
    elevation_m: float | None = None
    last_attempt_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_success_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_result: str | None = Field(default=None, max_length=512)
    # The fields sent (WU name -> value), without the credentials.
    last_payload: dict[str, float] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )


class WundergroundField(SQLModel):
    """One upload field: what would be sent now, or why it is left out."""

    field: str  # WU parameter, e.g. "tempf"
    label: str
    value: float | None
    unit: str
    source: str
    skipped: str | None = None


class WundergroundConfigPublic(SQLModel):
    enabled: bool
    station_id: str
    has_key: bool
    interval_s: int
    elevation_m: float | None
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_result: str | None
    last_payload: dict[str, float] | None
    next_upload_at: datetime | None
    dry_run: bool
    fields: list[WundergroundField]


class WundergroundConfigUpdate(SQLModel):
    enabled: bool | None = None
    station_id: str | None = Field(default=None, max_length=64)
    # Blank or missing keeps the stored key.
    station_key: str | None = Field(default=None, max_length=128)
    interval_s: int | None = Field(default=None, ge=60, le=3600)
    elevation_m: float | None = Field(default=None, ge=-500, le=9000)
