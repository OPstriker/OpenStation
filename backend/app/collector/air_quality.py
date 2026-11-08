"""Seeed Grove SCD41 (CO2, temperature, humidity) as a collector sensor.

The SCD41 measures every 5 s in periodic mode, while the collector samples
every second. sample() reads a new measurement when one is ready and repeats
the last one in between (up to HOLD_S), so the dashboard doesn't flicker
stale between measurements.

A missing or flaky sensor never stops the collector. sample() returns no
metrics, the page shows stale, and setup is retried every retry_s seconds.
"""

import logging
import math
import time
from collections.abc import Callable

from app.collector.scd41 import MAX_AMBIENT_HPA, MIN_AMBIENT_HPA, SCD41, RawI2C

logger = logging.getLogger(__name__)

# Repeat the last measurement for this long (the sensor's period is 5 s).
HOLD_S = 15.0
# No new measurement for this long: re-initialise the sensor.
NO_DATA_RESET_S = 30.0
# Send the barometer's pressure for CO2 compensation this often.
PRESSURE_EVERY_S = 60.0


def dew_point_c(temperature_c: float, humidity_pct: float) -> float | None:
    """Magnus formula (Sonntag 1990 constants). None for RH <= 0."""
    if humidity_pct <= 0:
        return None
    a, b = 17.62, 243.12
    gamma = math.log(humidity_pct / 100.0) + a * temperature_c / (b + temperature_c)
    return b * gamma / (a - gamma)


def air_quality_metrics(
    co2_ppm: float, temperature_c: float, humidity_pct: float
) -> dict[str, float]:
    """Metric dict stored for sensor="air_quality" (shared with the simulator)."""
    metrics = {
        "co2_ppm": co2_ppm,
        "temperature_c": temperature_c,
        "humidity_pct": humidity_pct,
    }
    dew = dew_point_c(temperature_c, humidity_pct)
    if dew is not None:
        metrics["dew_point_c"] = dew
    return metrics


class SCD41AirQuality:
    name = "air_quality"

    def __init__(
        self,
        *,
        open_i2c: Callable[[], RawI2C],
        address: int,
        temperature_offset_c: float | None,
        asc_enabled: bool | None,
        pressure_hpa: Callable[[], float | None] | None,
        retry_s: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._open_i2c = open_i2c
        self.address = address
        self.temperature_offset_c = temperature_offset_c
        self.asc_enabled = asc_enabled
        self._pressure_hpa = pressure_hpa
        self.retry_s = retry_s
        self._clock = clock
        self._sleep = sleep
        self._dev: SCD41 | None = None
        self.serial: int | None = None
        self._next_try = 0.0
        self._failing = False  # log one warning per outage, not one per retry
        self._last: dict[str, float] | None = None
        self._last_at = 0.0
        self._started_at = 0.0
        self._pressure_sent_at: float | None = None
        self._setup()

    @property
    def ready(self) -> bool:
        return self._dev is not None

    def _setup(self) -> bool:
        self._next_try = self._clock() + self.retry_s
        try:
            i2c = self._open_i2c()
        except OSError as e:
            self._fail(f"cannot open the I2C bus ({e})")
            return False
        dev = SCD41(i2c, sleep=self._sleep)
        try:
            # It may still be measuring from before a collector restart, and
            # the settings below are only accepted while idle.
            dev.stop_periodic_measurement()
            serial = dev.get_serial_number()
            if self.temperature_offset_c is not None:
                dev.set_temperature_offset_c(self.temperature_offset_c)
            if self.asc_enabled is not None:
                dev.set_asc_enabled(self.asc_enabled)
            dev.start_periodic_measurement()
        except OSError as e:
            i2c.close()
            self._fail(f"no SCD41 answering at I2C address 0x{self.address:02X} ({e})")
            return False
        self._dev = dev
        self.serial = serial
        self._started_at = self._clock()
        self._last = None
        self._pressure_sent_at = None
        if self._failing:
            logger.info("SCD41 is back (serial 0x%012X)", serial)
        self._failing = False
        return True

    def _fail(self, reason: str) -> None:
        dev, self._dev = self._dev, None
        if dev is not None:
            try:
                dev.close()
            except OSError:
                pass
        self._last = None
        self._next_try = self._clock() + self.retry_s
        if not self._failing:
            logger.warning(
                "Air quality sensor unavailable: %s. Retrying every %.0f s.",
                reason,
                self.retry_s,
            )
        self._failing = True

    def _send_pressure(self, dev: SCD41, now: float) -> None:
        if self._pressure_hpa is None:
            return
        if (
            self._pressure_sent_at is not None
            and now - self._pressure_sent_at < PRESSURE_EVERY_S
        ):
            return
        hpa = self._pressure_hpa()
        if hpa is None or not MIN_AMBIENT_HPA <= hpa <= MAX_AMBIENT_HPA:
            return
        dev.set_ambient_pressure_hpa(hpa)
        self._pressure_sent_at = now

    def sample(self, elapsed_s: float) -> dict[str, float]:
        # elapsed_s is unused: the sensor reports instantaneous values.
        now = self._clock()
        if self._dev is None:
            if now < self._next_try or not self._setup():
                return {}
        dev = self._dev
        assert dev is not None
        try:
            self._send_pressure(dev, now)
            if dev.data_ready():
                co2, temp_c, rh = dev.read_measurement()
                self._last = air_quality_metrics(co2, temp_c, rh)
                self._last_at = now
        except OSError as e:
            self._fail(f"read failed ({e})")
            return {}

        newest = self._last_at if self._last is not None else self._started_at
        if now - newest > NO_DATA_RESET_S:
            self._fail(f"no new measurement for {NO_DATA_RESET_S:.0f} s")
            return {}
        if self._last is None or now - self._last_at > HOLD_S:
            return {}
        return dict(self._last)

    def close(self) -> None:
        dev, self._dev = self._dev, None
        if dev is None:
            return
        try:
            dev.stop_periodic_measurement()
        except OSError:
            pass
        finally:
            dev.close()
