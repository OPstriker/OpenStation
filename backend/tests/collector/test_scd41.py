import logging
import random

import pytest

from app.collector.air_quality import (
    HOLD_S,
    NO_DATA_RESET_S,
    PRESSURE_EVERY_S,
    SCD41AirQuality,
    air_quality_metrics,
    dew_point_c,
)
from app.collector.scd41 import (
    CMD_GET_DATA_READY,
    CMD_GET_SERIAL,
    CMD_READ_MEASUREMENT,
    CMD_SET_AMBIENT_PRESSURE,
    CMD_SET_ASC_ENABLED,
    CMD_SET_TEMPERATURE_OFFSET,
    CMD_START_PERIODIC,
    CMD_STOP_PERIODIC,
    CRCError,
    convert_measurement,
    crc8,
    pack_word,
    unpack_words,
)
from app.collector.simulate import SimulatedAirQuality
from app.core.config import Settings
from tests.collector.fake_i2c import FakeClock

SERIAL = 0x6A565F073B88
IDLE_ONLY = {CMD_GET_SERIAL, CMD_SET_TEMPERATURE_OFFSET, CMD_SET_ASC_ENABLED}


def raw_words(co2: int, temp_c: float, rh: float) -> list[int]:
    return [co2, round((temp_c + 45) * 65535 / 175), round(rh * 65535 / 100)]


class FakeSCD41:
    """Emulates the SCD41's command protocol (RawI2C)."""

    def __init__(self) -> None:
        self.periodic = False
        self.ready = False
        self.measurement = raw_words(800, 22.0, 40.0)
        self.fail = False
        self.corrupt_crc = False
        self.closed = False
        self.commands: list[int] = []
        self.words_written: dict[int, int] = {}
        self._pending = b""

    def write(self, data: bytes) -> None:
        if self.fail:
            raise OSError(121, "Remote I/O error")
        cmd = int.from_bytes(data[:2], "big")
        self.commands.append(cmd)
        if cmd in IDLE_ONLY and self.periodic:
            raise OSError(121, "NACK: command not allowed while measuring")
        if len(data) > 2:
            (word,) = unpack_words(data[2:])
            self.words_written[cmd] = word
        if cmd == CMD_STOP_PERIODIC:
            self.periodic = False
        elif cmd == CMD_START_PERIODIC:
            if self.periodic:
                raise OSError(121, "NACK: already measuring")
            self.periodic = True
        elif cmd == CMD_GET_SERIAL:
            self._respond([SERIAL >> 32, (SERIAL >> 16) & 0xFFFF, SERIAL & 0xFFFF])
        elif cmd == CMD_GET_DATA_READY:
            self._respond([0x8006 if self.ready else 0x8000])
        elif cmd == CMD_READ_MEASUREMENT:
            self._respond(self.measurement)
            self.ready = False

    def _respond(self, words: list[int]) -> None:
        self._pending = b"".join(pack_word(w) for w in words)
        if self.corrupt_crc:
            self._pending = self._pending[:-1] + bytes([self._pending[-1] ^ 0xFF])

    def read(self, length: int) -> bytes:
        if self.fail:
            raise OSError(121, "Remote I/O error")
        data, self._pending = self._pending[:length], b""
        return data

    def close(self) -> None:
        self.closed = True


class Opener:
    def __init__(self, dev: FakeSCD41 | None) -> None:
        self.dev = dev
        self.calls = 0

    def __call__(self) -> FakeSCD41:
        self.calls += 1
        if self.dev is None:
            raise FileNotFoundError(2, "No such file or directory: '/dev/i2c-1'")
        return self.dev


def make(
    opener: Opener,
    clock: FakeClock,
    *,
    pressure: list[float | None] | None = None,
    temperature_offset_c: float | None = None,
    asc_enabled: bool | None = None,
) -> SCD41AirQuality:
    return SCD41AirQuality(
        open_i2c=opener,
        address=0x62,
        temperature_offset_c=temperature_offset_c,
        asc_enabled=asc_enabled,
        pressure_hpa=(lambda: pressure[0]) if pressure is not None else None,
        retry_s=30.0,
        clock=clock,
        sleep=clock.sleep,
    )


# ---- driver ----


def test_crc8_datasheet_example() -> None:
    assert crc8(b"\xbe\xef") == 0x92


def test_unpack_rejects_bad_crc() -> None:
    assert unpack_words(pack_word(0x1234) + pack_word(0xBEEF)) == [0x1234, 0xBEEF]
    with pytest.raises(CRCError):
        unpack_words(b"\xbe\xef\x00")
    assert issubclass(CRCError, OSError)


def test_convert_measurement() -> None:
    co2, t, rh = convert_measurement(raw_words(1234, 25.0, 50.0))
    assert co2 == 1234
    assert t == pytest.approx(25.0, abs=0.01)
    assert rh == pytest.approx(50.0, abs=0.01)


def test_dew_point() -> None:
    assert dew_point_c(20.0, 50.0) == pytest.approx(9.26, abs=0.05)
    assert dew_point_c(15.0, 100.0) == pytest.approx(15.0, abs=1e-6)
    assert dew_point_c(15.0, 0.0) is None
    assert "dew_point_c" not in air_quality_metrics(500, 20.0, 0.0)


# ---- sensor ----


def test_setup_stops_configures_then_starts() -> None:
    dev = FakeSCD41()
    dev.periodic = True  # left measuring by a previous collector run
    sensor = make(Opener(dev), FakeClock(), temperature_offset_c=4.0, asc_enabled=False)
    assert sensor.ready
    assert sensor.serial == SERIAL
    assert dev.commands == [
        CMD_STOP_PERIODIC,
        CMD_GET_SERIAL,
        CMD_SET_TEMPERATURE_OFFSET,
        CMD_SET_ASC_ENABLED,
        CMD_START_PERIODIC,
    ]
    assert dev.words_written[CMD_SET_TEMPERATURE_OFFSET] == round(4.0 * 65535 / 175)
    assert dev.words_written[CMD_SET_ASC_ENABLED] == 0
    assert dev.periodic


def test_chip_settings_untouched_by_default() -> None:
    dev = FakeSCD41()
    make(Opener(dev), FakeClock())
    assert CMD_SET_TEMPERATURE_OFFSET not in dev.commands
    assert CMD_SET_ASC_ENABLED not in dev.commands


def test_reads_and_holds_last_measurement() -> None:
    clock = FakeClock()
    dev = FakeSCD41()
    sensor = make(Opener(dev), clock)

    assert sensor.sample(1.0) == {}  # first measurement takes ~5 s
    clock.t += 5
    dev.ready = True
    m = sensor.sample(1.0)
    assert m["co2_ppm"] == 800
    assert m["temperature_c"] == pytest.approx(22.0, abs=0.01)
    assert m["humidity_pct"] == pytest.approx(40.0, abs=0.01)
    assert m["dew_point_c"] == pytest.approx(dew_point_c(22.0, 40.0), abs=0.05)

    # Between measurements the last values are repeated...
    clock.t += 1
    assert sensor.sample(1.0) == m
    # ...until they are older than HOLD_S.
    clock.t += HOLD_S
    assert sensor.sample(1.0) == {}
    assert sensor.ready


def test_reinitialises_when_measurements_stop(caplog: pytest.LogCaptureFixture) -> None:
    clock = FakeClock()
    dev = FakeSCD41()
    sensor = make(Opener(dev), clock)
    with caplog.at_level(logging.WARNING):
        clock.t += NO_DATA_RESET_S + 1
        assert sensor.sample(1.0) == {}
    assert not sensor.ready
    assert "no new measurement" in caplog.text


def test_missing_sensor_retries_with_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = FakeClock()
    opener = Opener(None)
    with caplog.at_level(logging.WARNING):
        sensor = make(opener, clock)
        assert not sensor.ready
        clock.t += 10
        assert sensor.sample(1.0) == {}
        assert opener.calls == 1
        clock.t += 25
        assert sensor.sample(1.0) == {}
        assert opener.calls == 2
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1

    dev = FakeSCD41()
    dev.ready = True
    opener.dev = dev
    clock.t += 31
    assert sensor.sample(1.0)["co2_ppm"] == 800


@pytest.mark.parametrize("fault", ["oserror", "crc"])
def test_bus_or_crc_error_drops_sample_and_recovers(fault: str) -> None:
    clock = FakeClock()
    dev = FakeSCD41()
    sensor = make(Opener(dev), clock)
    dev.ready = True
    assert sensor.sample(1.0)

    dev.ready = True
    if fault == "oserror":
        dev.fail = True
    else:
        dev.corrupt_crc = True
    assert sensor.sample(1.0) == {}
    assert not sensor.ready
    assert dev.closed

    dev.fail = dev.corrupt_crc = dev.closed = False
    assert sensor.sample(1.0) == {}  # waits retry_s
    clock.t += 31
    dev.ready = True
    assert "co2_ppm" in sensor.sample(1.0)


def test_pressure_compensation_is_rate_limited() -> None:
    clock = FakeClock()
    dev = FakeSCD41()
    pressure: list[float | None] = [1001.6]
    sensor = make(Opener(dev), clock, pressure=pressure)

    sensor.sample(1.0)
    assert dev.words_written[CMD_SET_AMBIENT_PRESSURE] == 1002
    dev.commands.clear()

    pressure[0] = 990.0
    clock.t += 10
    sensor.sample(1.0)
    assert CMD_SET_AMBIENT_PRESSURE not in dev.commands

    clock.t += PRESSURE_EVERY_S
    dev.ready = True  # keep it from tripping the no-data reset
    sensor.sample(1.0)
    assert dev.words_written[CMD_SET_AMBIENT_PRESSURE] == 990


@pytest.mark.parametrize("hpa", [None, 500.0, 1500.0])
def test_no_pressure_sent_when_unknown_or_out_of_range(hpa: float | None) -> None:
    dev = FakeSCD41()
    sensor = make(Opener(dev), FakeClock(), pressure=[hpa])
    sensor.sample(1.0)
    assert CMD_SET_AMBIENT_PRESSURE not in dev.commands


def test_close_stops_measuring() -> None:
    dev = FakeSCD41()
    sensor = make(Opener(dev), FakeClock())
    sensor.close()
    assert not dev.periodic
    assert dev.closed
    sensor.close()  # idempotent


def test_simulated_air_quality_stays_plausible() -> None:
    clock = FakeClock()
    sim = SimulatedAirQuality(
        base_co2_ppm=650.0,
        base_temp_c=21.0,
        base_humidity_pct=45.0,
        clock=clock,
        rng=random.Random(1),
    )
    for _ in range(100):
        clock.t += 60
        m = sim.sample(1.0)
        assert 450 < m["co2_ppm"] < 850
        assert 19 < m["temperature_c"] < 23
        assert 35 < m["humidity_pct"] < 55
        assert m["dew_point_c"] < m["temperature_c"]


def test_hex_i2c_address_setting() -> None:
    cfg = Settings(AIR_QUALITY_I2C_ADDRESS="0x61")  # type: ignore[arg-type]
    assert cfg.AIR_QUALITY_I2C_ADDRESS == 0x61
