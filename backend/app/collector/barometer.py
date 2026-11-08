"""Seeed Grove Barometer (SPA06-003) as a collector sensor.

The chip runs in continuous mode (pressure 4 Hz with 32x oversampling,
temperature 4 Hz), and each sample() reads its latest result. A missing or
flaky sensor never stops the collector: sample() returns no metrics, so the
barometer shows as stale on the dashboard, and setup is retried every
retry_s seconds.
"""

import logging
import time
from collections.abc import Callable

from app.collector.spa06 import (
    MODE_CONT_PRES_TEMP,
    MODE_IDLE,
    OS_1,
    OS_32,
    PRS_RDY,
    RATE_4HZ,
    SPA06_003,
    I2CBus,
    calc_altitude,
)

logger = logging.getLogger(__name__)

# The SPA06-003's specified pressure range; anything outside is a bad read.
MIN_HPA = 300.0
MAX_HPA = 1100.0


def sea_level_pressure(pressure_pa: float, altitude_m: float) -> float:
    """Station pressure -> pressure reduced to sea level (inverse of calc_altitude)."""
    return pressure_pa / float((1.0 - altitude_m / 44330.0) ** 5.255)


def barometer_metrics(
    pressure_pa: float,
    temperature_c: float,
    *,
    sea_level_ref_hpa: float,
    station_altitude_m: float | None,
) -> dict[str, float]:
    """Metric dict stored for sensor="barometer" (shared with the simulator)."""
    metrics = {
        "pressure_hpa": pressure_pa / 100.0,
        "temperature_c": temperature_c,
        "altitude_m": calc_altitude(pressure_pa, sea_level_ref_hpa * 100.0),
    }
    if station_altitude_m is not None:
        metrics["sea_level_pressure_hpa"] = (
            sea_level_pressure(pressure_pa, station_altitude_m) / 100.0
        )
    return metrics


class SPA06Barometer:
    name = "barometer"

    def __init__(
        self,
        *,
        open_bus: Callable[[], I2CBus],
        address: int,
        sea_level_ref_hpa: float,
        station_altitude_m: float | None,
        retry_s: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._open_bus = open_bus
        self.address = address
        self.sea_level_ref_hpa = sea_level_ref_hpa
        self.station_altitude_m = station_altitude_m
        self.retry_s = retry_s
        self._clock = clock
        self._sleep = sleep
        self._dev: SPA06_003 | None = None
        self._have_data = False
        self._next_try = 0.0
        self._failing = False  # log one warning per outage, not one per retry
        self._bad_reads = 0
        # Latest good station pressure, for other sensors' compensation (SCD41).
        self.last_pressure_hpa: float | None = None
        self._setup()

    @property
    def ready(self) -> bool:
        return self._dev is not None

    @property
    def chip_id(self) -> int | None:
        return self._dev.chip_id if self._dev else None

    def _setup(self) -> bool:
        self._next_try = self._clock() + self.retry_s
        try:
            bus = self._open_bus()
        except OSError as e:
            self._fail(f"cannot open the I2C bus ({e})")
            return False
        dev = SPA06_003(bus, self.address, sleep=self._sleep, clock=self._clock)
        try:
            ok = dev.begin()
            if ok:
                dev.set_pressure_config(RATE_4HZ, OS_32)
                dev.set_temperature_config(RATE_4HZ, OS_1)
                dev.set_mode(MODE_CONT_PRES_TEMP)
        except OSError:
            ok = False
        if not ok:
            bus.close()
            self._fail(f"no SPA06-003 answering at I2C address 0x{self.address:02X}")
            return False
        self._dev = dev
        self._have_data = False
        if self._failing:
            logger.info("Barometer is back (chip id 0x%02X)", dev.chip_id or 0)
        self._failing = False
        return True

    def _fail(self, reason: str) -> None:
        if self._dev is not None:
            try:
                self._dev.close()
            except OSError:
                pass
            self._dev = None
        self.last_pressure_hpa = None
        self._next_try = self._clock() + self.retry_s
        if not self._failing:
            logger.warning(
                "Barometer unavailable: %s. Retrying every %.0f s.",
                reason,
                self.retry_s,
            )
        self._failing = True

    def sample(self, elapsed_s: float) -> dict[str, float]:
        # elapsed_s is unused: the chip reports instantaneous values.
        if self._dev is None:
            if self._clock() < self._next_try or not self._setup():
                return {}
        dev = self._dev
        assert dev is not None
        try:
            # Until the first conversion finishes the result registers are 0.
            if not self._have_data:
                if not dev.status() & PRS_RDY:
                    return {}
                self._have_data = True
            pressure_pa, temperature_c = dev.read()
        except OSError as e:
            self._fail(f"read failed ({e})")
            return {}

        if not MIN_HPA <= pressure_pa / 100.0 <= MAX_HPA:
            self._bad_reads += 1
            if self._bad_reads == 1:
                logger.warning(
                    "Barometer pressure %.1f hPa out of range; dropping such reads",
                    pressure_pa / 100.0,
                )
            return {}
        self._bad_reads = 0
        self.last_pressure_hpa = pressure_pa / 100.0
        return barometer_metrics(
            pressure_pa,
            temperature_c,
            sea_level_ref_hpa=self.sea_level_ref_hpa,
            station_altitude_m=self.station_altitude_m,
        )

    def close(self) -> None:
        dev, self._dev = self._dev, None
        if dev is None:
            return
        try:
            dev.set_mode(MODE_IDLE)
        except OSError:
            pass
        finally:
            dev.close()
