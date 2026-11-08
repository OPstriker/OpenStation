import warnings
from typing import Literal, Self

from pydantic import PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Use top level .env file (one level above ./backend/)
        env_file="../.env",
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    FRONTEND_HOST: str = "http://localhost:5173"
    FASTAPI_ENV: Literal["development"] | None = None

    PROJECT_NAME: str = "Weather Station"
    DATABASE_URL: PostgresDsn

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _use_psycopg_driver(cls, value: str | PostgresDsn) -> str:
        database_url = str(value)
        for scheme in ("postgres://", "postgresql://"):
            if database_url.startswith(scheme):
                return database_url.replace(scheme, "postgresql+psycopg://", 1)
        return database_url

    # --- Readings API ---
    # Latest readings older than this are reported as stale (collector down?)
    STALE_AFTER_S: float = 5.0

    # --- Collector ---
    SAMPLE_INTERVAL_S: float = 1.0
    # Log a one-line summary this often (every sample is still stored).
    COLLECTOR_LOG_EVERY_S: float = 10.0
    # No hardware: use gpiozero's MockFactory and fake pulses (Mac dev, CI).
    COLLECTOR_SIMULATE: bool = False
    # Force the lgpio gpiochip number. None lets gpiozero pick (Pi 5 RP1 is
    # gpiochip0 on kernels >= 6.6.45, gpiochip4 on older ones).
    GPIO_CHIP: int | None = None

    # KY-025 reed switch on a cup anemometer. DO pin -> BCM GPIO number.
    ANEMOMETER_ENABLED: bool = True
    ANEMOMETER_GPIO: int = 17
    # True if the module's DO goes HIGH while the magnet closes the reed switch.
    ANEMOMETER_ACTIVE_HIGH: bool = True
    # Edges closer together than this are ignored. Caps the max measurable
    # pulse rate at 1 / ANEMOMETER_BOUNCE_S Hz.
    ANEMOMETER_BOUNCE_S: float = 0.01
    # mph per Hz of switch closures. 1.492 is the common SparkFun/Argent
    # weather-meter value; calibrate for your anemometer.
    ANEMOMETER_MPH_PER_HZ: float = 1.492
    # Switch closures per cup revolution (only used for the rpm metric).
    ANEMOMETER_PULSES_PER_REV: int = 1
    # Gust = max rolling mean of this many seconds over the gust window.
    ANEMOMETER_GUST_AVG_S: float = 3.0
    ANEMOMETER_GUST_WINDOW_S: float = 600.0

    # Grove Barometer (SPA06-003) on I2C: VCC 3.3V, SDA GPIO2, SCL GPIO3.
    BAROMETER_ENABLED: bool = True
    # /dev/i2c-<bus>; 1 is the 40-pin header's SDA/SCL (pins 3/5).
    BAROMETER_I2C_BUS: int = 1
    # 0x77 is the Grove default (SDO high), 0x76 with the address pads changed.
    # Accepts "0x76" or "118" in .env.
    BAROMETER_I2C_ADDRESS: int = 0x77
    # Reference sea-level pressure for the altitude_m metric.
    BAROMETER_SEA_LEVEL_HPA: float = 1013.25
    # Station elevation in metres. When set, sea_level_pressure_hpa is stored
    # (station pressure reduced to sea level, comparable to weather reports).
    BAROMETER_STATION_ALTITUDE_M: float | None = None
    # While the sensor is missing or failing, retry setup this often.
    BAROMETER_RETRY_S: float = 30.0

    # Wind vane on a KY-040 rotary encoder: CLK/DT quadrature + SW push button.
    WIND_VANE_ENABLED: bool = True
    WIND_VANE_CLK_GPIO: int = 23
    WIND_VANE_DT_GPIO: int = 24
    # Push button: zeroes the vane (point it at WIND_VANE_OFFSET_DEG, press).
    WIND_VANE_SW_GPIO: int | None = 22
    # KY-040: 20 detents per turn = 18 degrees per step.
    WIND_VANE_STEPS_PER_REV: int = 20
    # Bearing the vane points at when the encoder is at zero (collector start
    # or after a button press). 0 = north.
    WIND_VANE_OFFSET_DEG: float = 0.0
    # True if clockwise vane rotation counts down (or swap the CLK/DT pins).
    WIND_VANE_INVERT: bool = False
    # Window for the direction_avg_deg metric (WMO uses 2 minutes).
    WIND_VANE_AVG_S: float = 120.0

    # Grove CO2 & Temperature & Humidity Sensor (Sensirion SCD41) on I2C.
    # Shares the barometer's bus: VCC 3.3V, SDA GPIO2, SCL GPIO3.
    AIR_QUALITY_ENABLED: bool = True
    AIR_QUALITY_I2C_BUS: int = 1
    AIR_QUALITY_I2C_ADDRESS: int = 0x62
    # Temperature offset (degC) the sensor subtracts to correct its own
    # self-heating. None keeps the chip's setting (factory default 4).
    AIR_QUALITY_TEMPERATURE_OFFSET_C: float | None = None
    # Automatic self-calibration: assumes the sensor sees fresh air (~400 ppm)
    # at least once a week. None keeps the chip's setting (factory default on).
    AIR_QUALITY_ASC_ENABLED: bool | None = None
    # Feed the barometer's pressure to the SCD41 for CO2 compensation.
    AIR_QUALITY_PRESSURE_COMPENSATION: bool = True
    AIR_QUALITY_RETRY_S: float = 30.0

    # Only used with COLLECTOR_SIMULATE (no hardware): fake readings.
    SIM_WIND_MPH: float = 8.0
    SIM_PRESSURE_HPA: float = 1013.25
    SIM_TEMP_C: float = 21.0
    SIM_CO2_PPM: float = 650.0
    SIM_WIND_DIR_DEG: float = 225.0
    SIM_HUMIDITY_PCT: float = 45.0

    @field_validator("BAROMETER_I2C_ADDRESS", "AIR_QUALITY_I2C_ADDRESS", mode="before")
    @classmethod
    def _parse_i2c_address(cls, value: int | str) -> int:
        # pydantic doesn't parse hex strings like "0x77".
        return int(value, 0) if isinstance(value, str) else value

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.FASTAPI_ENV == "development":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        for host in self.DATABASE_URL.hosts():
            self._check_default_secret("DATABASE_URL password", host["password"])
        return self


settings = Settings()  # type: ignore # ty: ignore[unused-ignore-comment]
