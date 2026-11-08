import pytest

from app.collector.spa06 import (
    MODE_CONT_PRES_TEMP,
    OS_1,
    OS_8,
    OS_16,
    OS_32,
    P_SHIFT,
    RATE_4HZ,
    REG_CFG_REG,
    REG_MEAS_CFG,
    REG_PRS_CFG,
    REG_RESET,
    REG_TMP_CFG,
    SCALE,
    SOFT_RESET,
    SPA06_003,
    T_SHIFT,
    calc_altitude,
    decode_coefficients,
    signed,
)
from tests.collector.fake_i2c import COEFFS, FakeBus, FakeClock, encode_coefficients


def make(bus: FakeBus, clock: FakeClock | None = None) -> SPA06_003:
    clock = clock or FakeClock()
    return SPA06_003(bus, bus.address, sleep=clock.sleep, clock=clock)


@pytest.mark.parametrize(
    ("value", "bits", "expected"),
    [
        (0x000, 12, 0),
        (0x7FF, 12, 2047),
        (0x800, 12, -2048),
        (0xFFF, 12, -1),
        (0x7FFFFF, 24, 8388607),
        (0x800000, 24, -8388608),
    ],
)
def test_signed(value: int, bits: int, expected: int) -> None:
    assert signed(value, bits) == expected


def test_coefficients_round_trip() -> None:
    assert decode_coefficients(encode_coefficients(COEFFS)) == COEFFS


def test_begin_resets_and_loads_calibration() -> None:
    bus = FakeBus(chip_id=0x11)
    dev = make(bus)
    assert dev.begin()
    assert dev.chip_id == 0x11
    assert (REG_RESET, SOFT_RESET) in bus.writes
    assert dev.coefficients == COEFFS


def test_begin_times_out_when_never_ready() -> None:
    bus = FakeBus()
    bus.set_status(0)  # COEF_RDY / SENSOR_RDY never set
    clock = FakeClock()
    assert not make(bus, clock).begin(timeout=1.0)
    assert clock.t > 1001.0


def test_begin_false_when_no_device() -> None:
    bus = FakeBus()
    bus.fail = True
    assert not make(bus).begin()


def test_config_registers_and_shift_bits() -> None:
    bus = FakeBus()
    dev = make(bus)
    assert dev.begin()

    dev.set_pressure_config(RATE_4HZ, OS_32)
    dev.set_temperature_config(RATE_4HZ, OS_1)
    assert bus.regs[REG_PRS_CFG] == 0x25
    assert bus.regs[REG_TMP_CFG] == 0x20
    assert dev.k_p == SCALE[OS_32] == 516096
    assert dev.k_t == SCALE[OS_1] == 524288
    # Pressure > 8x needs P_SHIFT; temperature at 1x must not have T_SHIFT.
    assert bus.regs[REG_CFG_REG] & P_SHIFT
    assert not bus.regs[REG_CFG_REG] & T_SHIFT

    dev.set_temperature_config(RATE_4HZ, OS_16)
    assert bus.regs[REG_CFG_REG] & T_SHIFT
    dev.set_pressure_config(RATE_4HZ, OS_8)
    assert not bus.regs[REG_CFG_REG] & P_SHIFT
    assert bus.regs[REG_CFG_REG] & T_SHIFT


def test_set_mode_only_touches_meas_ctrl() -> None:
    bus = FakeBus()
    dev = make(bus)
    dev.set_mode(MODE_CONT_PRES_TEMP)
    assert bus.regs[REG_MEAS_CFG] & 0x07 == MODE_CONT_PRES_TEMP


@pytest.mark.parametrize(
    ("p_raw", "t_raw"), [(0, 0), (-245000, 312000), (123456, -54321)]
)
def test_read_matches_datasheet_formula(p_raw: int, t_raw: int) -> None:
    bus = FakeBus()
    dev = make(bus)
    assert dev.begin()
    dev.set_pressure_config(RATE_4HZ, OS_32)
    dev.set_temperature_config(RATE_4HZ, OS_1)
    bus.set_raw(p_raw, t_raw)

    assert dev.read_raw() == (p_raw, t_raw)

    # Datasheet formula, written out term by term (not Horner form).
    c = COEFFS
    p = p_raw / 516096
    t = t_raw / 524288
    expected_p = (
        c["c00"]
        + p * c["c10"]
        + p**2 * c["c20"]
        + p**3 * c["c30"]
        + p**4 * c["c40"]
        + t * c["c01"]
        + t * p * c["c11"]
        + t * p**2 * c["c21"]
        + t * p**3 * c["c31"]
    )
    expected_t = c["c0"] * 0.5 + c["c1"] * t

    pressure, temperature = dev.read()
    assert pressure == pytest.approx(expected_p)
    assert temperature == pytest.approx(expected_t)


def test_calc_altitude() -> None:
    assert calc_altitude(101325.0) == pytest.approx(0.0)
    # ~111 m per 1333 Pa near sea level
    assert calc_altitude(100000.0) == pytest.approx(110.9, abs=0.5)
    assert calc_altitude(101325.0, 102000.0) > 0
