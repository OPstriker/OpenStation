"""Fake sensors for running without a Pi (Mac dev, CI)."""

import logging
import math
import random
import threading
import time
from collections.abc import Callable

from gpiozero.pins.mock import MockPin

from app.collector.air_quality import air_quality_metrics
from app.collector.barometer import barometer_metrics

logger = logging.getLogger(__name__)


class WindSimulator:
    """Toggles a mock pin at the pulse rate for a wandering fake wind speed."""

    def __init__(
        self,
        pin: MockPin,
        *,
        base_mph: float,
        mph_per_hz: float,
        active_high: bool,
    ) -> None:
        self.pin = pin
        self.base_mph = base_mph
        self.mph_per_hz = mph_per_hz
        self.active_high = active_high
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="wind-sim", daemon=True)

    def start(self) -> None:
        logger.info("Simulating wind around %.1f mph on %s", self.base_mph, self.pin)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _set(self, active: bool) -> None:
        if active == self.active_high:
            self.pin.drive_high()
        else:
            self.pin.drive_low()

    def _run(self) -> None:
        mph = self.base_mph
        self._set(False)
        while not self._stop.is_set():
            # Random walk around the base speed, with the occasional gust.
            mph += random.gauss(0, 0.4) + 0.05 * (self.base_mph - mph)
            if random.random() < 0.01:
                mph += random.uniform(3, 8)
            mph = max(mph, 0.0)
            hz = mph / self.mph_per_hz
            if hz < 0.2:
                self._stop.wait(1.0)
                continue
            half = 0.5 / hz
            self._set(True)
            if self._stop.wait(half):
                break
            self._set(False)
            self._stop.wait(half)


class SimulatedBarometer:
    """Fake SPA06-003 readings: a slow +/-2 hPa swing so the chart moves."""

    name = "barometer"

    def __init__(
        self,
        *,
        base_hpa: float,
        base_temp_c: float,
        sea_level_ref_hpa: float,
        station_altitude_m: float | None,
        clock: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
    ) -> None:
        self.base_hpa = base_hpa
        self.base_temp_c = base_temp_c
        self.sea_level_ref_hpa = sea_level_ref_hpa
        self.station_altitude_m = station_altitude_m
        self._clock = clock
        self._rng = rng or random.Random()
        self._t0 = clock()
        self.last_pressure_hpa: float | None = None
        logger.info(
            "Simulating barometer around %.2f hPa, %.1f C", base_hpa, base_temp_c
        )

    def sample(self, elapsed_s: float) -> dict[str, float]:
        # elapsed_s is unused: readings are instantaneous.
        t = self._clock() - self._t0
        hpa = (
            self.base_hpa
            + 2.0 * math.sin(2 * math.pi * t / 3600.0)
            + self._rng.gauss(0, 0.03)
        )
        temp_c = (
            self.base_temp_c
            + 1.5 * math.sin(2 * math.pi * t / 5400.0)
            + self._rng.gauss(0, 0.05)
        )
        self.last_pressure_hpa = hpa
        return barometer_metrics(
            hpa * 100.0,
            temp_c,
            sea_level_ref_hpa=self.sea_level_ref_hpa,
            station_altitude_m=self.station_altitude_m,
        )

    def close(self) -> None:
        pass


class SimulatedAirQuality:
    """Fake SCD41 readings: CO2 slowly swinging +/-150 ppm around a base."""

    name = "air_quality"

    def __init__(
        self,
        *,
        base_co2_ppm: float,
        base_temp_c: float,
        base_humidity_pct: float,
        clock: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
    ) -> None:
        self.base_co2_ppm = base_co2_ppm
        self.base_temp_c = base_temp_c
        self.base_humidity_pct = base_humidity_pct
        self._clock = clock
        self._rng = rng or random.Random()
        self._t0 = clock()
        logger.info(
            "Simulating air quality around %.0f ppm CO2, %.0f%% RH",
            base_co2_ppm,
            base_humidity_pct,
        )

    def sample(self, elapsed_s: float) -> dict[str, float]:
        # elapsed_s is unused: readings are instantaneous.
        t = self._clock() - self._t0
        co2 = (
            self.base_co2_ppm
            + 150.0 * math.sin(2 * math.pi * t / 2400.0)
            + self._rng.gauss(0, 8)
        )
        temp_c = (
            self.base_temp_c
            + 1.0 * math.sin(2 * math.pi * t / 5400.0)
            + self._rng.gauss(0, 0.05)
        )
        rh = (
            self.base_humidity_pct
            + 5.0 * math.sin(2 * math.pi * t / 4000.0)
            + self._rng.gauss(0, 0.2)
        )
        return air_quality_metrics(max(co2, 400.0), temp_c, min(max(rh, 0.0), 100.0))

    def close(self) -> None:
        pass


class VaneSimulator:
    """Turns a KY-040's mock CLK/DT pins so the vane wanders around a bearing."""

    def __init__(
        self,
        clk: MockPin,
        dt: MockPin,
        *,
        base_deg: float,
        direction_deg: Callable[[], float],
        steps_per_rev: int,
        cw_increases: bool = True,
        rng: random.Random | None = None,
    ) -> None:
        self.clk = clk
        self.dt = dt
        self.base_deg = base_deg
        self._direction_deg = direction_deg
        self.step_deg = 360.0 / max(steps_per_rev, 1)
        self.cw_increases = cw_increases
        self._rng = rng or random.Random()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="vane-sim", daemon=True)

    def start(self) -> None:
        logger.info("Simulating wind direction around %.0f deg", self.base_deg)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def detent(self, clockwise: bool) -> None:
        """One click of quadrature: the leading pin goes active (low) first."""
        lead, lag = (self.clk, self.dt) if clockwise else (self.dt, self.clk)
        for pin, active in ((lead, True), (lag, True), (lead, False), (lag, False)):
            if active:
                pin.drive_low()
            else:
                pin.drive_high()
            self._stop.wait(0.002)

    def _run(self) -> None:
        target = self.base_deg
        while not self._stop.wait(0.4):
            # Random walk around the base bearing.
            target += self._rng.gauss(0, 6) + 0.05 * (self.base_deg - target)
            diff = (target - self._direction_deg() + 540.0) % 360.0 - 180.0
            if abs(diff) > self.step_deg / 2:
                self.detent((diff > 0) == self.cw_increases)
