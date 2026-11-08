import math
import random
from collections.abc import Generator

import pytest
from gpiozero import Device
from gpiozero.pins.mock import MockFactory, MockPin

from app.collector.simulate import VaneSimulator
from app.collector.wind_vane import KY040WindVane, circular_mean_deg
from tests.collector.fake_i2c import FakeClock

CLK, DT, SW = 23, 24, 22


@pytest.fixture
def mock_factory() -> Generator[MockFactory]:
    factory = MockFactory()
    Device.pin_factory = factory
    yield factory
    factory.reset()
    Device.pin_factory = None


def make(
    clock: FakeClock | None = None,
    *,
    offset_deg: float = 0.0,
    invert: bool = False,
    sw: int | None = SW,
) -> KY040WindVane:
    return KY040WindVane(
        clk_gpio=CLK,
        dt_gpio=DT,
        sw_gpio=sw,
        steps_per_rev=20,
        offset_deg=offset_deg,
        invert=invert,
        avg_s=120.0,
        clock=clock or FakeClock(),
    )


def turn(vane: KY040WindVane, detents: int) -> None:
    """Rotate by `detents` clicks (positive = clockwise) via quadrature."""
    sim = VaneSimulator(
        vane.encoder.a.pin,  # type: ignore[arg-type]
        vane.encoder.b.pin,  # type: ignore[arg-type]
        base_deg=0,
        direction_deg=lambda: vane.direction_deg,
        steps_per_rev=20,
    )
    for _ in range(abs(detents)):
        sim.detent(clockwise=detents > 0)


def press(factory: MockFactory) -> None:
    pin = factory.pin(SW)
    assert isinstance(pin, MockPin)
    pin.drive_low()  # pull-up: pressed = low
    pin.drive_high()


@pytest.mark.usefixtures("mock_factory")
def test_detents_map_to_18_degree_steps() -> None:
    vane = make()
    assert vane.sample(1.0)["direction_deg"] == 0
    turn(vane, 3)
    m = vane.sample(1.0)
    assert m["position"] == 3
    assert m["direction_deg"] == pytest.approx(54.0)
    assert m["direction_sin"] == pytest.approx(math.sin(math.radians(54)))
    assert m["direction_cos"] == pytest.approx(math.cos(math.radians(54)))


@pytest.mark.usefixtures("mock_factory")
def test_wraps_both_ways() -> None:
    vane = make()
    turn(vane, -1)  # counter-clockwise from north
    assert vane.sample(1.0)["direction_deg"] == pytest.approx(342.0)
    turn(vane, 21)  # a full turn and one more
    assert vane.sample(1.0)["direction_deg"] == pytest.approx(0.0)
    assert vane.sample(1.0)["position"] == 0


@pytest.mark.usefixtures("mock_factory")
def test_offset_and_invert() -> None:
    vane = make(offset_deg=90.0, invert=True)
    turn(vane, 1)
    assert vane.sample(1.0)["direction_deg"] == pytest.approx(72.0)


def test_button_zeroes_and_calibrates(mock_factory: MockFactory) -> None:
    vane = make()
    assert vane.sample(1.0)["calibrated"] == 0
    turn(vane, 7)
    press(mock_factory)
    m = vane.sample(1.0)
    assert m["calibrated"] == 1
    assert m["direction_deg"] == 0
    assert m["position"] == 0


@pytest.mark.usefixtures("mock_factory")
def test_no_button_wired() -> None:
    vane = make(sw=None)
    assert vane.button is None
    assert vane.sample(1.0)["calibrated"] == 0
    vane.close()


@pytest.mark.usefixtures("mock_factory")
def test_rolling_average_is_circular() -> None:
    clock = FakeClock()
    vane = make(clock)
    turn(vane, -1)  # 342
    vane.sample(1.0)
    clock.t += 1
    turn(vane, 2)  # 18
    m = vane.sample(1.0)
    assert m["direction_avg_deg"] == pytest.approx(0.0, abs=1e-6)

    # Old samples fall out of the window.
    clock.t += 200
    turn(vane, 4)  # 90
    assert vane.sample(1.0)["direction_avg_deg"] == pytest.approx(90.0)


def test_circular_mean() -> None:
    assert circular_mean_deg([]) is None
    assert circular_mean_deg([350.0, 10.0]) == pytest.approx(0.0, abs=1e-9)
    assert circular_mean_deg([90.0, 180.0]) == pytest.approx(135.0)
    assert circular_mean_deg([0.0, 180.0]) is None


@pytest.mark.usefixtures("mock_factory")
def test_simulator_moves_vane_towards_base() -> None:
    vane = make()
    sim = VaneSimulator(
        vane.encoder.a.pin,  # type: ignore[arg-type]
        vane.encoder.b.pin,  # type: ignore[arg-type]
        base_deg=225.0,
        direction_deg=lambda: vane.direction_deg,
        steps_per_rev=20,
        rng=random.Random(3),
    )
    # Step the simulator's control loop directly (no thread, no sleeps).
    for _ in range(40):
        diff = (225.0 - vane.direction_deg + 540.0) % 360.0 - 180.0
        if abs(diff) > 9:
            sim.detent(diff > 0)
    assert vane.direction_deg == pytest.approx(216.0) or vane.direction_deg == (
        pytest.approx(234.0)
    )
    vane.close()
