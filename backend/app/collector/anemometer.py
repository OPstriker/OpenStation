"""Cup anemometer read through a KY-025 reed switch module.

The anemometer's magnet closes the reed switch once (or N times) per cup
revolution. The KY-025's LM393 comparator turns that into a clean digital
pulse on DO, which goes to a Pi GPIO pin. Wind speed is proportional to the
pulse frequency: mph = Hz * mph_per_hz.
"""

import threading
import time
from collections import deque
from collections.abc import Callable

from gpiozero import DigitalInputDevice


class PulseCounter:
    """Thread-safe pulse counter plus wind math. No GPIO, so it is unit-testable.

    on_pulse() is called from gpiozero's callback thread; take() from the
    collector loop.
    """

    def __init__(
        self,
        *,
        mph_per_hz: float,
        pulses_per_rev: int,
        gust_avg_s: float,
        gust_window_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.mph_per_hz = mph_per_hz
        self.pulses_per_rev = max(pulses_per_rev, 1)
        self.gust_avg_s = gust_avg_s
        self.gust_window_s = gust_window_s
        self._clock = clock
        self._lock = threading.Lock()
        self._count = 0
        self._total = 0
        self._last_pulse: float | None = None
        # (t, mph, elapsed) per sample, kept for the rolling gust average
        self._speeds: deque[tuple[float, float, float]] = deque()
        # (t, rolling mean mph) kept for the gust window
        self._rolling: deque[tuple[float, float]] = deque()

    def on_pulse(self) -> None:
        now = self._clock()
        with self._lock:
            self._count += 1
            self._total += 1
            self._last_pulse = now

    def take(self, elapsed_s: float) -> dict[str, float]:
        now = self._clock()
        with self._lock:
            count = self._count
            self._count = 0
            total = self._total
            last_pulse = self._last_pulse

        hz = count / elapsed_s if elapsed_s > 0 else 0.0
        mph = hz * self.mph_per_hz
        rpm = hz * 60.0 / self.pulses_per_rev

        # Gust: max over the gust window of the time-weighted mean speed of the
        # last gust_avg_s seconds (WMO-style 3 s gust).
        self._speeds.append((now, mph, elapsed_s))
        while self._speeds and self._speeds[0][0] <= now - self.gust_avg_s:
            self._speeds.popleft()
        weight = sum(e for _, _, e in self._speeds)
        rolling = sum(m * e for _, m, e in self._speeds) / weight if weight > 0 else mph
        self._rolling.append((now, rolling))
        while self._rolling and self._rolling[0][0] <= now - self.gust_window_s:
            self._rolling.popleft()
        gust = max(r for _, r in self._rolling)

        metrics = {
            "wind_speed_mph": mph,
            "wind_gust_mph": gust,
            "pulse_hz": hz,
            "rpm": rpm,
            "pulse_count": float(count),
            "pulse_total": float(total),
        }
        if last_pulse is not None:
            metrics["secs_since_pulse"] = max(now - last_pulse, 0.0)
        return metrics


class KY025Anemometer:
    name = "anemometer"

    def __init__(
        self,
        *,
        gpio: int,
        active_high: bool,
        bounce_s: float | None,
        counter: PulseCounter,
    ) -> None:
        self.counter = counter
        # pull_up=None: the KY-025 drives DO itself, so no internal pull.
        self.device = DigitalInputDevice(
            gpio,
            pull_up=None,
            active_state=active_high,
            bounce_time=bounce_s or None,
        )
        self.device.when_activated = self.counter.on_pulse

    def sample(self, elapsed_s: float) -> dict[str, float]:
        metrics = self.counter.take(elapsed_s)
        metrics["do_active"] = 1.0 if self.device.is_active else 0.0
        return metrics

    def close(self) -> None:
        self.device.close()
