"""Wind vane read through a KY-040 rotary encoder (CLK/DT quadrature + SW button).

The vane turns the encoder shaft. The KY-040 has 20 detents per turn, so the
resolution is 18 degrees. It is a *relative* encoder: position 0 is wherever
the vane was when the collector started. Point the vane at
WIND_VANE_OFFSET_DEG (north by default) and press the knob (SW) to set it.
The `calibrated` metric says whether that has happened since the start.

The reported direction is the bearing the vane points at, i.e. where the wind
comes FROM (meteorological convention).
"""

import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable

from gpiozero import Button, RotaryEncoder

logger = logging.getLogger(__name__)


def circular_mean_deg(angles_deg: list[float]) -> float | None:
    """Mean direction (vector average), so 350 and 10 average to 0, not 180."""
    if not angles_deg:
        return None
    s = sum(math.sin(math.radians(a)) for a in angles_deg)
    c = sum(math.cos(math.radians(a)) for a in angles_deg)
    if math.hypot(s, c) < 1e-9:  # perfectly opposed: no mean direction
        return None
    # Round first so a tiny negative (-1e-15) doesn't wrap to 360.0.
    return round(math.degrees(math.atan2(s, c)), 9) % 360.0


class KY040WindVane:
    name = "wind_vane"

    def __init__(
        self,
        *,
        clk_gpio: int,
        dt_gpio: int,
        sw_gpio: int | None,
        steps_per_rev: int,
        offset_deg: float,
        invert: bool,
        avg_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.steps_per_rev = max(steps_per_rev, 1)
        self.offset_deg = offset_deg
        self.invert = invert
        self.avg_s = avg_s
        self._clock = clock
        self._lock = threading.Lock()
        self.calibrated = False
        # (t, direction) per sample, for the rolling average
        self._history: deque[tuple[float, float]] = deque()
        # max_steps=0: unbounded count; the position is taken modulo one turn.
        self.encoder = RotaryEncoder(clk_gpio, dt_gpio, max_steps=0)
        self.button: Button | None = None
        if sw_gpio is not None:
            self.button = Button(sw_gpio, pull_up=True, bounce_time=0.05)
            self.button.when_pressed = self.zero

    def zero(self) -> None:
        """The vane now points at offset_deg (north by default)."""
        with self._lock:
            self.encoder.steps = 0
            self.calibrated = True
            self._history.clear()
        logger.info("Wind vane zeroed: now pointing at %.0f deg", self.offset_deg)

    @property
    def position(self) -> int:
        """Detent position 0..steps_per_rev-1 (clockwise from the zero point)."""
        steps = int(self.encoder.steps)
        return (-steps if self.invert else steps) % self.steps_per_rev

    @property
    def direction_deg(self) -> float:
        return (self.position * 360.0 / self.steps_per_rev + self.offset_deg) % 360.0

    def sample(self, elapsed_s: float) -> dict[str, float]:
        # elapsed_s is unused: the position is read directly.
        now = self._clock()
        with self._lock:
            position = self.position
            direction = self.direction_deg
            self._history.append((now, direction))
            while self._history and self._history[0][0] <= now - self.avg_s:
                self._history.popleft()
            avg = circular_mean_deg([d for _, d in self._history])
            calibrated = self.calibrated
        rad = math.radians(direction)
        metrics = {
            "direction_deg": direction,
            # Components let the API's bucket averages be turned back into a
            # correct mean direction (averaging degrees breaks at 0/360).
            "direction_sin": math.sin(rad),
            "direction_cos": math.cos(rad),
            "position": float(position),
            "calibrated": 1.0 if calibrated else 0.0,
        }
        if avg is not None:
            metrics["direction_avg_deg"] = avg
        return metrics

    def close(self) -> None:
        self.encoder.close()
        if self.button is not None:
            self.button.close()
