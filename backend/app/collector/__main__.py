"""Sensor collector: `python -m app.collector`.

The only process that touches GPIO. Samples every sensor once per
SAMPLE_INTERVAL_S and stores the metrics as SensorReading rows.
"""

import logging
import signal
import threading
import time
from types import FrameType

from gpiozero import Device
from sqlmodel import Session

from app.collector.air_quality import SCD41AirQuality
from app.collector.anemometer import KY025Anemometer, PulseCounter
from app.collector.barometer import SPA06Barometer
from app.collector.base import Sensor
from app.collector.scd41 import SMBusRawI2C
from app.collector.simulate import (
    SimulatedAirQuality,
    SimulatedBarometer,
    VaneSimulator,
    WindSimulator,
)
from app.collector.uploader import WundergroundUploader
from app.collector.wind_vane import KY040WindVane
from app.core.config import Settings, settings
from app.core.db import engine
from app.models import SensorReading, get_datetime_utc

logger = logging.getLogger("app.collector")


def setup_pin_factory(cfg: Settings) -> None:
    if cfg.COLLECTOR_SIMULATE:
        from gpiozero.pins.mock import MockFactory

        Device.pin_factory = MockFactory()
    elif cfg.GPIO_CHIP is not None:
        from gpiozero.pins.lgpio import LGPIOFactory

        Device.pin_factory = LGPIOFactory(chip=cfg.GPIO_CHIP)
    # else: gpiozero picks (GPIOZERO_PIN_FACTORY env, then lgpio on a Pi 5)


Simulator = WindSimulator | VaneSimulator


def build_sensors(cfg: Settings) -> tuple[list[Sensor], list[Simulator]]:
    sensors: list[Sensor] = []
    sims: list[Simulator] = []
    if cfg.ANEMOMETER_ENABLED:
        anemometer = KY025Anemometer(
            gpio=cfg.ANEMOMETER_GPIO,
            active_high=cfg.ANEMOMETER_ACTIVE_HIGH,
            bounce_s=cfg.ANEMOMETER_BOUNCE_S,
            counter=PulseCounter(
                mph_per_hz=cfg.ANEMOMETER_MPH_PER_HZ,
                pulses_per_rev=cfg.ANEMOMETER_PULSES_PER_REV,
                gust_avg_s=cfg.ANEMOMETER_GUST_AVG_S,
                gust_window_s=cfg.ANEMOMETER_GUST_WINDOW_S,
            ),
        )
        sensors.append(anemometer)
        logger.info(
            "Anemometer on GPIO%d (active_high=%s, bounce=%ss, %.3f mph/Hz) via %s",
            cfg.ANEMOMETER_GPIO,
            cfg.ANEMOMETER_ACTIVE_HIGH,
            cfg.ANEMOMETER_BOUNCE_S,
            cfg.ANEMOMETER_MPH_PER_HZ,
            type(anemometer.device.pin_factory).__name__,
        )
        if cfg.COLLECTOR_SIMULATE:
            sims.append(
                WindSimulator(
                    anemometer.device.pin,
                    base_mph=cfg.SIM_WIND_MPH,
                    mph_per_hz=cfg.ANEMOMETER_MPH_PER_HZ,
                    active_high=cfg.ANEMOMETER_ACTIVE_HIGH,
                )
            )
    if cfg.WIND_VANE_ENABLED:
        vane = KY040WindVane(
            clk_gpio=cfg.WIND_VANE_CLK_GPIO,
            dt_gpio=cfg.WIND_VANE_DT_GPIO,
            sw_gpio=cfg.WIND_VANE_SW_GPIO,
            steps_per_rev=cfg.WIND_VANE_STEPS_PER_REV,
            offset_deg=cfg.WIND_VANE_OFFSET_DEG,
            invert=cfg.WIND_VANE_INVERT,
            avg_s=cfg.WIND_VANE_AVG_S,
        )
        sensors.append(vane)
        logger.info(
            "Wind vane KY-040 on CLK GPIO%d, DT GPIO%d, SW %s: %d steps/rev, "
            "zero = %.0f deg. Point it at %.0f deg and press the knob to set it.",
            cfg.WIND_VANE_CLK_GPIO,
            cfg.WIND_VANE_DT_GPIO,
            f"GPIO{cfg.WIND_VANE_SW_GPIO}"
            if cfg.WIND_VANE_SW_GPIO is not None
            else "not wired",
            cfg.WIND_VANE_STEPS_PER_REV,
            cfg.WIND_VANE_OFFSET_DEG,
            cfg.WIND_VANE_OFFSET_DEG,
        )
        if cfg.COLLECTOR_SIMULATE:
            vane.zero()  # pretend it was calibrated
            sims.append(
                VaneSimulator(
                    vane.encoder.a.pin,
                    vane.encoder.b.pin,
                    base_deg=cfg.SIM_WIND_DIR_DEG,
                    direction_deg=lambda: vane.direction_deg,
                    steps_per_rev=cfg.WIND_VANE_STEPS_PER_REV,
                    cw_increases=not cfg.WIND_VANE_INVERT,
                )
            )
    barometer = build_barometer(cfg) if cfg.BAROMETER_ENABLED else None
    if barometer is not None:
        sensors.append(barometer)
    if cfg.AIR_QUALITY_ENABLED:
        # After the barometer, so its pressure is fresh for compensation.
        sensors.append(build_air_quality(cfg, barometer))
    return sensors, sims


def build_barometer(cfg: Settings) -> SPA06Barometer | SimulatedBarometer:
    if cfg.COLLECTOR_SIMULATE:
        return SimulatedBarometer(
            base_hpa=cfg.SIM_PRESSURE_HPA,
            base_temp_c=cfg.SIM_TEMP_C,
            sea_level_ref_hpa=cfg.BAROMETER_SEA_LEVEL_HPA,
            station_altitude_m=cfg.BAROMETER_STATION_ALTITUDE_M,
        )

    from smbus2 import SMBus

    def open_bus() -> SMBus:
        return SMBus(cfg.BAROMETER_I2C_BUS)

    barometer = SPA06Barometer(
        open_bus=open_bus,
        address=cfg.BAROMETER_I2C_ADDRESS,
        sea_level_ref_hpa=cfg.BAROMETER_SEA_LEVEL_HPA,
        station_altitude_m=cfg.BAROMETER_STATION_ALTITUDE_M,
        retry_s=cfg.BAROMETER_RETRY_S,
    )
    logger.info(
        "Barometer SPA06-003 on /dev/i2c-%d at 0x%02X: %s",
        cfg.BAROMETER_I2C_BUS,
        cfg.BAROMETER_I2C_ADDRESS,
        f"ready, chip id 0x{barometer.chip_id:02X}"
        if barometer.ready and barometer.chip_id is not None
        else "not responding yet",
    )
    return barometer


def build_air_quality(
    cfg: Settings, barometer: SPA06Barometer | SimulatedBarometer | None
) -> Sensor:
    if cfg.COLLECTOR_SIMULATE:
        return SimulatedAirQuality(
            base_co2_ppm=cfg.SIM_CO2_PPM,
            base_temp_c=cfg.SIM_TEMP_C,
            base_humidity_pct=cfg.SIM_HUMIDITY_PCT,
        )

    def open_i2c() -> SMBusRawI2C:
        return SMBusRawI2C(cfg.AIR_QUALITY_I2C_BUS, cfg.AIR_QUALITY_I2C_ADDRESS)

    def pressure_hpa() -> float | None:
        return barometer.last_pressure_hpa if barometer is not None else None

    sensor = SCD41AirQuality(
        open_i2c=open_i2c,
        address=cfg.AIR_QUALITY_I2C_ADDRESS,
        temperature_offset_c=cfg.AIR_QUALITY_TEMPERATURE_OFFSET_C,
        asc_enabled=cfg.AIR_QUALITY_ASC_ENABLED,
        pressure_hpa=pressure_hpa
        if cfg.AIR_QUALITY_PRESSURE_COMPENSATION and barometer is not None
        else None,
        retry_s=cfg.AIR_QUALITY_RETRY_S,
    )
    logger.info(
        "Air quality SCD41 on /dev/i2c-%d at 0x%02X: %s%s",
        cfg.AIR_QUALITY_I2C_BUS,
        cfg.AIR_QUALITY_I2C_ADDRESS,
        f"ready, serial 0x{sensor.serial:012X}"
        if sensor.ready and sensor.serial is not None
        else "not responding yet",
        ", pressure-compensated by the barometer"
        if cfg.AIR_QUALITY_PRESSURE_COMPENSATION and barometer is not None
        else "",
    )
    return sensor


def store(rows: list[SensorReading]) -> None:
    with Session(engine) as session:
        session.add_all(rows)
        session.commit()


def run(cfg: Settings = settings) -> None:
    stop = threading.Event()

    def _handle_signal(signum: int, _frame: FrameType | None) -> None:
        logger.info("Got signal %d, stopping", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    setup_pin_factory(cfg)
    sensors, sims = build_sensors(cfg)
    if not sensors:
        logger.warning("No sensors enabled; nothing to collect")
        return
    for sim in sims:
        sim.start()
    uploader = WundergroundUploader(dry_run=cfg.COLLECTOR_SIMULATE)
    uploader.start()

    interval = cfg.SAMPLE_INTERVAL_S
    last = time.monotonic()
    next_at = last + interval
    last_log = last
    try:
        while not stop.wait(max(next_at - time.monotonic(), 0)):
            now = time.monotonic()
            elapsed = now - last
            last = now
            next_at += interval
            if next_at < now:  # fell behind (e.g. slow DB); don't burst
                next_at = now + interval

            ts = get_datetime_utc()
            rows: list[SensorReading] = []
            summaries: list[str] = []
            for sensor in sensors:
                try:
                    metrics = sensor.sample(elapsed)
                except Exception:
                    logger.exception("Sampling %s failed", sensor.name)
                    continue
                rows.extend(
                    SensorReading(ts=ts, sensor=sensor.name, metric=k, value=v)
                    for k, v in metrics.items()
                )
                summaries.append(
                    f"{sensor.name}: "
                    + (
                        " ".join(f"{k}={v:.2f}" for k, v in metrics.items())
                        or "no data"
                    )
                )
            try:
                store(rows)
            except Exception:
                logger.exception("Storing %d readings failed; dropped", len(rows))

            if now - last_log >= cfg.COLLECTOR_LOG_EVERY_S:
                last_log = now
                logger.info(" | ".join(summaries))
    finally:
        uploader.stop()
        for sim in sims:
            sim.stop()
        for sensor in sensors:
            sensor.close()
        logger.info("Collector stopped")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    run()
