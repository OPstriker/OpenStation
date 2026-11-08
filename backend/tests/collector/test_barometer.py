import logging
import random

import pytest

from app.collector.barometer import (
    SPA06Barometer,
    barometer_metrics,
    sea_level_pressure,
)
from app.collector.simulate import SimulatedBarometer
from app.collector.spa06 import (
    COEF_RDY,
    MODE_CONT_PRES_TEMP,
    MODE_IDLE,
    PRS_RDY,
    REG_MEAS_CFG,
    SENSOR_RDY,
    TMP_RDY,
    calc_altitude,
)
from tests.collector.fake_i2c import COEFFS, FakeBus, FakeClock

ALL_READY = COEF_RDY | SENSOR_RDY | PRS_RDY | TMP_RDY


class Opener:
    """open_bus callable that hands out a FakeBus or raises like a missing /dev."""

    def __init__(self, bus: FakeBus | None) -> None:
        self.bus = bus
        self.calls = 0

    def __call__(self) -> FakeBus:
        self.calls += 1
        if self.bus is None:
            raise FileNotFoundError(2, "No such file or directory: '/dev/i2c-1'")
        return self.bus


def make(
    opener: Opener, clock: FakeClock, station_altitude_m: float | None = None
) -> SPA06Barometer:
    return SPA06Barometer(
        open_bus=opener,
        address=0x77,
        sea_level_ref_hpa=1013.25,
        station_altitude_m=station_altitude_m,
        retry_s=30.0,
        clock=clock,
        sleep=clock.sleep,
    )


def ready_bus() -> FakeBus:
    bus = FakeBus()
    bus.set_status(ALL_READY)
    bus.set_raw(0, 0)  # pressure = c00 Pa, temperature = c0 / 2 degC
    return bus


def test_metrics_without_station_altitude() -> None:
    m = barometer_metrics(
        101325.0, 20.5, sea_level_ref_hpa=1013.25, station_altitude_m=None
    )
    assert m == {
        "pressure_hpa": pytest.approx(1013.25),
        "temperature_c": 20.5,
        "altitude_m": pytest.approx(0.0, abs=1e-6),
    }


def test_metrics_with_station_altitude() -> None:
    m = barometer_metrics(
        100000.0, 15.0, sea_level_ref_hpa=1013.25, station_altitude_m=110.9
    )
    assert m["pressure_hpa"] == pytest.approx(1000.0)
    assert m["sea_level_pressure_hpa"] == pytest.approx(1013.25, abs=0.1)


def test_sea_level_pressure_inverts_calc_altitude() -> None:
    p = 95000.0
    h = calc_altitude(p, 101325.0)
    assert sea_level_pressure(p, h) == pytest.approx(101325.0)


def test_sets_up_continuous_mode_and_reads() -> None:
    bus = ready_bus()
    baro = make(Opener(bus), FakeClock())
    assert baro.ready
    assert baro.chip_id == 0x11
    assert bus.regs[REG_MEAS_CFG] & 0x07 == MODE_CONT_PRES_TEMP

    m = baro.sample(1.0)
    assert m["pressure_hpa"] == pytest.approx(COEFFS["c00"] / 100)
    assert m["temperature_c"] == pytest.approx(COEFFS["c0"] * 0.5)
    assert "sea_level_pressure_hpa" not in m


def test_no_data_until_first_pressure_conversion() -> None:
    bus = ready_bus()
    bus.set_status(COEF_RDY | SENSOR_RDY)  # no PRS_RDY yet
    baro = make(Opener(bus), FakeClock())
    assert baro.sample(1.0) == {}
    bus.set_status(ALL_READY)
    assert "pressure_hpa" in baro.sample(1.0)
    # Once data has been seen, a cleared PRS_RDY doesn't block reads.
    bus.set_status(COEF_RDY | SENSOR_RDY)
    assert "pressure_hpa" in baro.sample(1.0)


def test_missing_bus_retries_after_retry_s(caplog: pytest.LogCaptureFixture) -> None:
    clock = FakeClock()
    opener = Opener(None)
    with caplog.at_level(logging.WARNING):
        baro = make(opener, clock)
        assert not baro.ready
        assert baro.sample(1.0) == {}
        clock.t += 10
        assert baro.sample(1.0) == {}
        assert opener.calls == 1  # no retry before retry_s

        clock.t += 25
        assert baro.sample(1.0) == {}
        assert opener.calls == 2
    # One warning per outage, not one per retry.
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1

    opener.bus = ready_bus()
    clock.t += 31
    assert "pressure_hpa" in baro.sample(1.0)
    assert baro.ready


def test_read_error_drops_sample_and_recovers() -> None:
    clock = FakeClock()
    bus = ready_bus()
    baro = make(Opener(bus), clock)
    assert baro.sample(1.0)

    bus.fail = True
    assert baro.sample(1.0) == {}
    assert not baro.ready
    assert bus.closed

    bus.fail = False
    bus.closed = False
    assert baro.sample(1.0) == {}  # waits retry_s
    clock.t += 31
    assert "pressure_hpa" in baro.sample(1.0)


def test_out_of_range_pressure_is_dropped() -> None:
    bus = FakeBus(coeffs={**COEFFS, "c00": 5000})  # 50 hPa
    bus.set_status(ALL_READY)
    baro = make(Opener(bus), FakeClock())
    assert baro.ready
    assert baro.sample(1.0) == {}


def test_station_altitude_adds_sea_level_pressure() -> None:
    baro = make(Opener(ready_bus()), FakeClock(), station_altitude_m=200.0)
    m = baro.sample(1.0)
    assert m["sea_level_pressure_hpa"] > m["pressure_hpa"]


def test_close_idles_the_chip() -> None:
    bus = ready_bus()
    baro = make(Opener(bus), FakeClock())
    baro.close()
    assert bus.regs[REG_MEAS_CFG] & 0x07 == MODE_IDLE
    assert bus.closed
    baro.close()  # idempotent


def test_simulated_barometer_stays_plausible() -> None:
    clock = FakeClock()
    sim = SimulatedBarometer(
        base_hpa=1013.25,
        base_temp_c=21.0,
        sea_level_ref_hpa=1013.25,
        station_altitude_m=None,
        clock=clock,
        rng=random.Random(1),
    )
    for _ in range(100):
        clock.t += 60
        m = sim.sample(1.0)
        assert 1010.0 < m["pressure_hpa"] < 1016.5
        assert 19.0 < m["temperature_c"] < 23.0
        assert set(m) == {"pressure_hpa", "temperature_c", "altitude_m"}
