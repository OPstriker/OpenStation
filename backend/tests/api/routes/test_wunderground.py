import pytest
from fastapi.testclient import TestClient

from app.core.config import settings

URL = f"{settings.API_V1_STR}/wunderground"
KEY = "dummy-key-456"

# Restore the real config row after each test.
pytestmark = pytest.mark.usefixtures("wu_config")


def test_get_never_returns_the_key(client: TestClient) -> None:
    r = client.put(URL, json={"station_id": " KTEST1 ", "station_key": KEY})
    assert r.status_code == 200
    body = client.get(URL).json()
    assert KEY not in r.text and KEY not in str(body)
    assert "station_key" not in body
    assert body["has_key"] is True
    assert body["station_id"] == "KTEST1"
    assert {f["field"] for f in body["fields"]} >= {"tempf", "baromin", "winddir"}


def test_blank_key_keeps_the_stored_key(client: TestClient) -> None:
    client.put(URL, json={"station_key": KEY})
    body = client.put(
        URL, json={"station_key": "", "enabled": True, "interval_s": 300}
    ).json()
    assert body["has_key"] is True
    assert body["enabled"] is True
    assert body["interval_s"] == 300


def test_elevation_can_be_set_and_cleared(client: TestClient) -> None:
    assert client.put(URL, json={"elevation_m": 12.5}).json()["elevation_m"] == 12.5
    assert client.put(URL, json={"elevation_m": None}).json()["elevation_m"] is None


def test_interval_is_validated(client: TestClient) -> None:
    assert client.put(URL, json={"interval_s": 30}).status_code == 422
    assert client.put(URL, json={"interval_s": 7200}).status_code == 422


def test_upload_now_without_credentials(client: TestClient) -> None:
    client.put(URL, json={"station_id": ""})
    body = client.post(f"{URL}/upload").json()
    assert body["last_result"] == "error: station ID and key are required"
