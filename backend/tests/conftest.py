from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.core.db import engine
from app.main import app
from app.models import SensorReading

# Tests write under this sensor name and clean it up, so a real collector
# running against the same database is left alone.
TEST_SENSOR = "pytest-sensor"


@pytest.fixture(scope="session")
def db() -> Generator[Session]:
    with Session(engine) as session:
        yield session
        session.execute(
            delete(SensorReading).where(SensorReading.sensor == TEST_SENSOR)
        )  # type: ignore[arg-type]
        session.commit()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient]:
    with TestClient(app) as c:
        yield c
