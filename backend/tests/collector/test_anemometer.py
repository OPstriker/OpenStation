import pytest
from gpiozero import Device
from gpiozero.pins.mock import MockFactory

from app.collector.anemometer import KY025Anemometer, PulseCounter


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def make_counter(clock: FakeClock, **kw: float) -> PulseCounter:
    args: dict[str, float] = {
        "mph_per_hz": 1.492,
        "pulses_per_rev": 1,
        "gust_avg_s": 3.0,
        "gust_window_s": 600.0,
    }
    args.update(kw)
    return PulseCounter(clock=clock, **args)  # type: ignore[arg-type]


def pulses(counter: PulseCounter, clock: FakeClock, n: int, over_s: float) -> None:
    for _ in range(n):
        clock.t += over_s / n
        counter.on_pulse()


def test_speed_from_pulse_rate() -> None:
    clock = FakeClock()
    counter = make_counter(clock)
    pulses(counter, clock, 10, over_s=1.0)
    m = counter.take(1.0)
    assert m["pulse_count"] == 10
    assert m["pulse_hz"] == pytest.approx(10.0)
    assert m["wind_speed_mph"] == pytest.approx(14.92)
    assert m["rpm"] == pytest.approx(600.0)
    assert m["pulse_total"] == 10
    assert m["secs_since_pulse"] == pytest.approx(0.0)


def test_uses_measured_elapsed_time() -> None:
    clock = FakeClock()
    counter = make_counter(clock)
    pulses(counter, clock, 10, over_s=2.0)
    assert counter.take(2.0)["pulse_hz"] == pytest.approx(5.0)


def test_pulses_per_rev_only_affects_rpm() -> None:
    clock = FakeClock()
    counter = make_counter(clock, pulses_per_rev=2)
    pulses(counter, clock, 4, over_s=1.0)
    m = counter.take(1.0)
    assert m["wind_speed_mph"] == pytest.approx(4 * 1.492)
    assert m["rpm"] == pytest.approx(120.0)


def test_no_pulses() -> None:
    clock = FakeClock()
    counter = make_counter(clock)
    clock.t += 1
    m = counter.take(1.0)
    assert m["wind_speed_mph"] == 0
    assert m["wind_gust_mph"] == 0
    assert "secs_since_pulse" not in m  # never saw a pulse


def test_counter_resets_but_total_keeps_counting() -> None:
    clock = FakeClock()
    counter = make_counter(clock)
    pulses(counter, clock, 3, over_s=1.0)
    counter.take(1.0)
    clock.t += 2.0
    m = counter.take(1.0)
    assert m["pulse_count"] == 0
    assert m["pulse_total"] == 3
    assert m["secs_since_pulse"] == pytest.approx(2.0)


def test_gust_is_max_3s_mean_and_expires() -> None:
    clock = FakeClock()
    counter = make_counter(clock, mph_per_hz=1.0, gust_window_s=10.0)
    # 3 s at 9 mph, then calm
    for _ in range(3):
        pulses(counter, clock, 9, over_s=1.0)
        counter.take(1.0)
    for _ in range(3):
        clock.t += 1.0
        m = counter.take(1.0)
    assert m["wind_speed_mph"] == 0
    assert m["wind_gust_mph"] == pytest.approx(9.0)
    # after the gust window passes, the gust decays to the current speed
    for _ in range(10):
        clock.t += 1.0
        m = counter.take(1.0)
    assert m["wind_gust_mph"] == pytest.approx(0.0)


def test_single_spike_is_averaged_in_gust() -> None:
    clock = FakeClock()
    counter = make_counter(clock, mph_per_hz=1.0)
    for n in (0, 0, 9, 0, 0):
        if n:
            pulses(counter, clock, n, over_s=1.0)
        else:
            clock.t += 1.0
        m = counter.take(1.0)
    assert m["wind_gust_mph"] == pytest.approx(3.0)  # 9 mph for 1 s of 3 s


@pytest.fixture
def mock_factory() -> MockFactory:
    factory = MockFactory()
    Device.pin_factory = factory
    yield factory
    factory.reset()
    Device.pin_factory = None


@pytest.mark.parametrize("active_high", [True, False])
def test_ky025_counts_activations_on_gpio(
    mock_factory: MockFactory, active_high: bool
) -> None:
    clock = FakeClock()
    sensor = KY025Anemometer(
        gpio=17, active_high=active_high, bounce_s=None, counter=make_counter(clock)
    )
    pin = mock_factory.pin(17)
    idle, active = (
        (pin.drive_low, pin.drive_high)
        if active_high
        else (pin.drive_high, pin.drive_low)
    )
    idle()
    for _ in range(5):
        active()
        idle()
    active()  # leave the magnet over the switch
    m = sensor.sample(1.0)
    assert m["pulse_count"] == 6
    assert m["do_active"] == 1.0
    idle()
    assert sensor.sample(1.0)["do_active"] == 0.0
    sensor.close()
