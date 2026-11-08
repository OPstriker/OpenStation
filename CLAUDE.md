# CLAUDE.md

Raspberry Pi 5 weather station. Sensors so far: a cup anemometer whose magnet closes a KY-025 reed-switch module (GPIO), a wind vane on a KY-040 rotary encoder (GPIO), a Seeed Grove Barometer, SPA06-003 (I2C 0x77), and a Grove CO2 & Temperature & Humidity Sensor, Sensirion SCD41 (I2C 0x62). Started from `fastapi/full-stack-fastapi-template`, with users, auth, items, email and Traefik removed.

## Architecture

```
Raspberry Pi 5 host (Docker Compose)
 ├─ collector  same image, `python -m app.collector`; ONLY service with /dev/gpiochipN + /dev/i2c-1
 │              gpiozero + lgpio count pulses and read the vane encoder, smbus2 reads the barometer + SCD41
 │              → every SAMPLE_INTERVAL_S (1 s) insert rows
 │              + a thread that uploads to Weather Underground on the dashboard-configured schedule
 ├─ prestart   one-shot `bash scripts/prestart.sh` (alembic upgrade head);
 │              backend + collector wait for it (service_completed_successfully)
 ├─ db         postgres:18, volume app-db-data
 ├─ backend    FastAPI (4 workers, no GPIO): /api/v1/* + built React dashboard on :8000
 └─ adminer    DB browser on :8080
```

- **One image**, `weather-station:${TAG:-latest}` (linux/arm64), built from `backend/Dockerfile`. A Bun stage builds the dashboard into `backend/app/frontend`, which FastAPI serves.
- **Data**: the `sensor_reading` table in narrow format, with columns `id, ts (timestamptz), sensor, metric, value` and an index on `(sensor, metric, ts)`. The model is `SensorReading` in `backend/app/models.py`. Anemometer rows use `sensor="anemometer"` and these metrics: `wind_speed_mph, wind_gust_mph, pulse_hz, rpm, pulse_count, pulse_total, secs_since_pulse, do_active`. Barometer rows use `sensor="barometer"`: `pressure_hpa, temperature_c, altitude_m`, plus `sea_level_pressure_hpa` when `BAROMETER_STATION_ALTITUDE_M` is set. Wind vane rows use `sensor="wind_vane"`: `direction_deg, direction_avg_deg, direction_sin, direction_cos, position, calibrated`. Directions are where the wind comes FROM. Air quality rows use `sensor="air_quality"`: `co2_ppm, temperature_c, humidity_pct, dew_point_c`. Storage is SI or mph; the dashboard converts for display (°F, ft).
- **API** (`backend/app/api/routes/readings.py`):
  - `GET /api/v1/readings/latest?sensor=` returns the newest value per metric. Its `stale` flag is set when the newest row is older than `STALE_AFTER_S`.
  - `GET /api/v1/readings/history?sensor=&metric=&minutes=` returns raw points for up to 15 minutes. Longer windows are bucketed with `date_bin`.
  - `GET/PUT /api/v1/wunderground` reads or updates the Weather Underground upload settings. GET also returns the status and what would be sent now, and never returns the station key. `POST /api/v1/wunderground/upload` uploads once, immediately.
  - `GET /api/v1/utils/health-check/` is unchanged from the template.
- **Dashboard** (`frontend/`): React, TanStack Router and Query, polling every 1 s. It has one page per sensor: Wind (`/`), Wind direction (`/wind-direction`, a compass with the current and 2-min average bearing, plus a direction history), Barometer (`/barometer`, pressure in hPa, temperature in °F) and Air quality (`/air-quality`, CO2 in ppm with a Good/Elevated/High level, temperature and dew point in °F, humidity in %). Under "Sharing", Weather Underground (`/weather-underground`) holds the upload settings, status and field preview. The API calls go through a **hand-written fetch layer in `frontend/src/lib/api.ts`**; there is no generated client in use. When a response shape changes, update `api.ts` by hand.

## Hardware

### Anemometer: KY-025 reed switch (GPIO)

KY-025 module: a reed switch feeding an LM393 comparator, with pins DO / AO / + / G, a sensitivity potentiometer and a status LED.

| KY-025 | Pi 5 | Physical pin |
|---|---|---|
| `+` | **3.3 V** | 1 |
| `G` | GND | 6 |
| `DO` | GPIO17 (BCM) | 11 |
| `AO` | unused | |

**Warning: power it from 3.3 V (pin 1), never 5 V.** At 5 V the module puts 5 V on DO, which drives 5 V into a GPIO that only tolerates 3.3 V and can damage the Pi.

- **Pot tuning**: turn the potentiometer until the module LED toggles cleanly each time the magnet passes the switch.
- **Polarity**: if DO reads LOW while the magnet is over the switch, set `ANEMOMETER_ACTIVE_HIGH=false`.

### Barometer: Grove SPA06-003 (I2C)

| Grove | Pi 5 | Physical pin |
|---|---|---|
| VCC | **3.3 V** | 1 (shared with the KY-025; use pin 17 if pin 1 is taken) |
| GND | GND | 6 (or 9) |
| SDA | GPIO2 / SDA1 | 3 |
| SCL | GPIO3 / SCL1 | 5 |

- **Enable I2C** on the Pi once: `sudo raspi-config nonint do_i2c 0`, then reboot. Check with `ls /dev/i2c-1` and `i2cdetect -y 1` (package `i2c-tools`), which should show `77`.
- **Address**: 0x77 is the Grove default; 0x76 if the SDO/address pads were changed. Set `BAROMETER_I2C_ADDRESS` (it accepts `0x76`).
- **Driver**: `backend/app/collector/spa06.py` is a port of Seeed's Arduino example, following the SPA06-003 datasheet. `barometer.py` wraps it as a `Sensor`:
  - continuous mode: pressure 4 Hz with 32x oversampling, temperature 4 Hz with 1x;
  - if the sensor is missing or a read fails, it logs one warning, returns no metrics (the page shows stale) and retries every `BAROMETER_RETRY_S`.
- **Sea-level pressure** (what weather reports show) needs the station elevation: set `BAROMETER_STATION_ALTITUDE_M`. `altitude_m` is relative to `BAROMETER_SEA_LEVEL_HPA` (1013.25 by default), so it drifts with the weather.
- **Temperature is the chip's own temperature.** The board and the Pi warm it, so it is not air temperature.

### Wind vane: KY-040 rotary encoder (GPIO)

| KY-040 | Pi 5 | Physical pin |
|---|---|---|
| CLK | GPIO23 | 16 |
| DT | GPIO24 | 18 |
| SW | GPIO22 | 15 |
| `+` | **3.3 V** | 1 or 17 |
| GND | GND | 6, 9 or 14 |

- **Resolution**: 20 detents per turn, so 18° per step (`WIND_VANE_STEPS_PER_REV`).
- **It is a relative encoder.** 0 is wherever the vane pointed when the collector started. Point the vane at `WIND_VANE_OFFSET_DEG` (north by default) and press the knob (SW) to set it. The `calibrated` metric, and a warning on the page, show whether that has happened since the collector started. **Every collector restart needs the button press again.**
- **Code**: `backend/app/collector/wind_vane.py` (`KY040WindVane`) uses gpiozero `RotaryEncoder(max_steps=0)` and a `Button`. The position is `steps % 20`.
- **Averaging**: `direction_avg_deg` is a vector mean over `WIND_VANE_AVG_S`, so 350° and 10° average to 0°, not 180°.
- **History**: `direction_sin` and `direction_cos` are stored so the history chart can compute bucket means with `atan2` instead of averaging degrees.
- **Wrong way round?** If the bearing goes down when the vane turns clockwise, set `WIND_VANE_INVERT=true` or swap CLK and DT.
- **Simulation**: in simulate mode, `VaneSimulator` drives the encoder's mock pins with quadrature edges, wandering around `SIM_WIND_DIR_DEG`.

### Air quality: Grove SCD41 (I2C)

It goes on the same I2C bus as the barometer (a Grove I2C hub, or chain the wires): VCC→**3.3 V** (pin 1 or 17), GND→pin 6 or 9, SDA→GPIO2 pin 3, SCL→GPIO3 pin 5.

- **Power it from 3.3 V.** The Grove board's I2C pull-ups go to VCC, so at 5 V it would drive 5 V onto the Pi's SDA and SCL.
- **Check it** with `i2cdetect -y 1`, which should show `62` (and `77` for the barometer). No compose change is needed, because `/dev/i2c-1` is already passed in.
- **Code**:
  - `backend/app/collector/scd41.py` is the driver. It sends 16-bit commands through `smbus2` `i2c_rdwr`, and every data word is checked against its CRC-8.
  - `air_quality.py` wraps it as a `Sensor`. It stops any running measurement, reads the serial, applies the optional settings, then starts periodic measurement (one reading every **5 s**).
  - Between measurements it repeats the last values for up to 15 s, so the page doesn't flicker stale.
  - If no new measurement arrives for 30 s, or the bus fails, or a CRC check fails, it logs one warning and retries every `AIR_QUALITY_RETRY_S`.
- **Pressure compensation**: when the barometer is enabled, its latest pressure is sent to the SCD41 once a minute (`AIR_QUALITY_PRESSURE_COMPENSATION`).
- **Calibration**:
  - Automatic self-calibration (ASC, on by default) assumes the sensor sees fresh air (about 400 ppm) at least weekly.
  - `AIR_QUALITY_TEMPERATURE_OFFSET_C` corrects the sensor's self-heating (the chip default is 4 °C).
  - Neither setting is written to EEPROM.
  - Readings settle over the first couple of hours.

### Weather Underground upload

- **Settings live in the database, not in `.env`.** They are one row in `wunderground_config` (id=1), edited on the dashboard's Weather Underground page: enabled, station ID, station key, interval (default 300 s) and station elevation.
- **Who uploads:** `WundergroundUploader` (`backend/app/collector/uploader.py`), a thread in the collector. It re-reads the row every 15 s, so changes apply without a restart, and it never blocks the 1 Hz sampling loop. The backend's 4 workers never upload on a schedule.
- **Logic:** `backend/app/wunderground.py` builds the fields, uploads and records the status. It is shared with the API's "Upload now". The upload is one GET to `weatherstation.wunderground.com/.../updateweatherstation.php` with `ID`, `PASSWORD` (the key), `dateutc=now`, `action=updateraw`. The reply `success` means it worked; anything else is stored as `error: …`.
- **Field mapping:**
  - `tempf`, `humidity` and `dewptf` come from the SCD41 (`air_quality`), never from the barometer's chip temperature;
  - `baromin` is sea-level pressure, computed from `pressure_hpa` and the configured elevation, or taken from `sea_level_pressure_hpa`;
  - `windspeedmph` is the 2-minute mean, `windgustmph` is the anemometer gust, and `winddir` is `direction_avg_deg`;
  - no rain fields are sent.
- **When a field is left out:** while its sensor's newest row is older than 60 s, or for `winddir`, while `calibrated` is 0. The station never sends 0 as a placeholder.
- **Secrets:**
  - The key is write-only through the API; a blank key in a PUT keeps the stored one.
  - The key is replaced with `***` in stored error messages.
  - The `httpx` logger is raised to WARNING because its request log line would contain the key.
  - The dashboard has no login, so anyone who can open it can change the settings, and the key is visible in Postgres/Adminer.
- **`COLLECTOR_SIMULATE=true` makes every upload a dry run**, from both the collector and "Upload now", so simulated data never reaches WU.

### Calibration (anemometer)

```
hz  = pulses / measured elapsed seconds
mph = hz × ANEMOMETER_MPH_PER_HZ          (default 1.492, SparkFun/Argent value)
rpm = hz × 60 / ANEMOMETER_PULSES_PER_REV (default 1)
gust = max ANEMOMETER_GUST_AVG_S (3 s) rolling mean over ANEMOMETER_GUST_WINDOW_S (600 s)
```

Calibrate by spinning at a known rate or comparing against a handheld anemometer. Then set `ANEMOMETER_MPH_PER_HZ` in `.env.pi` and redeploy. All settings live in `backend/app/core/config.py`.

## Commands

### Mac (development; no GPIO, the collector simulates pulses)

```bash
docker compose watch                         # full stack, http://localhost:8000 (compose.override.yml auto-loaded)
docker compose logs -f collector
docker compose up -d db                      # just Postgres, for running things below on the host
cd backend && uv run pytest                  # needs db running + migrated (uv run bash scripts/prestart.sh)
cd backend && uv run ruff check && uv run ruff format --check && uv run mypy app && uv run ty check app
cd backend && uv run alembic revision --autogenerate -m "..."   # after changing models.py
cd backend && uv run python -m app.collector # simulated collector (COLLECTOR_SIMULATE=true in .env)
bun run dev                                  # Vite on :5173, proxies /api to :8000
bun run lint && bun run --filter frontend build
bash scripts/test.sh                         # backend tests in Docker against a throwaway DB
```

### Raspberry Pi (deploy from the Mac)

```bash
cp .env.pi.example .env.pi                   # once; gitignored. Set POSTGRES_PASSWORD, GPIO_CHIP, calibration
PI_HOST=pi@raspberrypi.local ./scripts/deploy-pi.sh   # optional: PI_DIR (default weather-station), TAG (default latest)
```

On the Pi, in `~/weather-station`:

```bash
docker compose -f compose.yml -f compose.pi.yml logs -f collector
docker compose -f compose.yml -f compose.pi.yml ps
```

**The image is always built on the Mac for linux/arm64 (`docker buildx ... --load`) and never on the Pi.** `deploy-pi.sh` streams it over ssh (`docker save | gzip | ssh ... docker load`), rsyncs `compose.yml`, `compose.pi.yml` and `.env.pi` (as `.env`, with `TAG=` appended), then runs `up -d --no-build`. `compose.pi.yml` sets `pull_policy: never`. The Pi needs only Docker, the compose plugin and rsync: no source checkout and no registry.

## Compose and env files

- `compose.yml` is the base for both machines and has no devices. The shared `x-app` anchor gives backend, collector and prestart the same image, `platform`, `build`, `env_file: .env` and a `DATABASE_URL` pointing at `db`.
- `compose.override.yml` is the Mac dev file and is auto-loaded. It runs `fastapi dev` with watch, publishes db on :5432 and runs the collector with `COLLECTOR_SIMULATE=true`.
- `compose.pi.yml` is the Pi file and must be passed explicitly. It gives the collector `devices: /dev/gpiochip${GPIO_CHIP:-0}` and `/dev/i2c-${BAROMETER_I2C_BUS:-1}`, plus `GPIOZERO_PIN_FACTORY=lgpio` and `GPIO_CHIP`. It is not privileged.
- `.env` holds the Mac dev settings and is committed (`POSTGRES_PASSWORD=changethis` is allowed only when `FASTAPI_ENV=development`). `.env.pi` holds the Pi settings, is gitignored and has a template in `.env.pi.example`.

## Conventions

- SQLModel models go in `backend/app/models.py`. There is one Alembic history in `backend/app/alembic/versions/`; commit generated revisions after reviewing them.
- Python: ruff, mypy `strict`, ty. Use `logging`, never `print`: ruff `T201` bans it.
- Frontend: Biome (`bun run lint`). There is no generated API client, so keep `frontend/src/lib/api.ts` in sync with the API.
- **Only the collector touches GPIO.** The backend runs 4 workers, and those processes can't share one GPIO line.
- Don't commit `.env.pi` or any other real secret.

## Adding a sensor

The barometer is the worked example: `spa06.py` (driver), `barometer.py` (`Sensor`), `SimulatedBarometer` in `simulate.py`, `build_barometer()` in `__main__.py`, `BAROMETER_*` settings, and `frontend/src/routes/_layout/barometer.tsx`.

1. Implement the `Sensor` protocol from `backend/app/collector/base.py` in a new module under `backend/app/collector/`. The protocol is `name: str`, `sample(elapsed_s) -> dict[str, float]` and `close()`. `sample()` gets the measured seconds since the previous call; use those rather than the nominal interval.
2. Build it in `build_sensors()` in `backend/app/collector/__main__.py`, behind a `<SENSOR>_ENABLED` setting, with its pins and calibration as settings in `backend/app/core/config.py`. Add matching keys to `.env.pi.example`.
3. Its metrics are stored as rows under a new `sensor` name, so no migration is needed. `/readings/latest?sensor=<name>` and `/history` already work for it.
4. Pass any new device node (I2C `/dev/i2c-1`, SPI, another gpiochip) to the collector in `compose.pi.yml` only.
5. Unit-test it with gpiozero's `MockFactory` (see `backend/tests/collector/`), then add a dashboard page.

## GPIO/I2C-in-Docker gotchas

- **Every device in `compose.pi.yml` must exist on the Pi, or the whole collector container fails to start**, and wind data stops with it. The usual cause is I2C not enabled, so `/dev/i2c-1` doesn't exist. `deploy-pi.sh` checks for both device nodes before deploying. To run without the barometer, remove its device line and set `BAROMETER_ENABLED=false`.

- **gpiochip0 vs gpiochip4**: on Pi OS kernels ≥ 6.6.45 the Pi 5's RP1 header is `gpiochip0`; older kernels use `gpiochip4`. Check with `gpioinfo` or `ls -l /dev/gpiochip*`, then set `GPIO_CHIP` in `.env.pi`. The same value picks both the device passed in and the chip lgpio opens. Without `GPIO_CHIP`, gpiozero guesses from the board revision and whether `/dev/gpiochip4` exists.
- **`LG_WD=/tmp`** is set in the Dockerfile because lgpio writes notification pipe files into its working directory.
- **lgpio is only installed on linux/aarch64** (environment marker in `backend/pyproject.toml`), so `uv sync` on the Mac skips it. There is no cp314 wheel, so the image builds it from the sdist. That build needs `swig` (apt) and `PYPI=1`: without `PYPI=1`, lgpio's `setup.py` links against a system `liblgpio`, which isn't there, instead of compiling its bundled C sources. Both are already in `backend/Dockerfile`.
- **One process per GPIO line.** Don't read GPIO from the backend or from a second collector; the line is already claimed.
- **`ANEMOMETER_BOUNCE_S` caps the maximum measurable speed**: at most 1/bounce Hz. The default 0.01 s gives 100 Hz, about 149 mph at 1.492 mph/Hz.
- **Mac or no hardware**: `COLLECTOR_SIMULATE=true` uses gpiozero's `MockFactory` and toggles the mock pin at a rate matching `SIM_WIND_MPH`. It also swaps the barometer for `SimulatedBarometer`, which produces values around `SIM_PRESSURE_HPA` and `SIM_TEMP_C`.
- Several I2C sensors share `/dev/i2c-1`: barometer 0x77, SCD41 0x62. Each opens its own `smbus2` handle, and the kernel serialises transfers, so no extra locking is needed. A new I2C sensor needs no compose change unless it is on another bus.
- `smbus2` is pure Python and installs everywhere. Opening `/dev/i2c-N` on the Mac just fails (FileNotFoundError), and the barometer retries.
- The container runs as root with only the gpiochip device passed in: no `privileged`, no `/dev/mem`, no group mapping.
- gpiozero reads the board revision from `/proc/cpuinfo`, which containers share with the host. This works because Docker masks `/sys/firmware` (the device tree), but not `/proc/cpuinfo`.

## Skills

The repo links library skills in `.claude/skills/`: `fastapi` and `sqlmodel`. They are symlinks into `.venv`, so they appear after `uv sync`. Use them for FastAPI and SQLModel questions.
