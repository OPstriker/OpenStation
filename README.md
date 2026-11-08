# Weather Station

A Raspberry Pi 5 weather station: sensors are read on GPIO and I2C, samples are stored in PostgreSQL once a second, and a live dashboard shows them in the browser. The sensors are a cup anemometer whose magnet closes a KY-025 reed-switch module, a wind vane on a KY-040 rotary encoder (the Wind direction tab with a compass), a Seeed Grove Barometer (SPA06-003) for pressure and temperature, and a Grove SCD41 for CO₂, temperature and humidity (the Air quality tab).

The code started as a stripped-down copy of [full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template). Users, auth, email and Traefik have been removed.

## How it works

```
Raspberry Pi 5 (Docker Compose)
 ├─ collector  python -m app.collector   the only container with /dev/gpiochip + /dev/i2c-1
 │              gpiozero + lgpio count reed-switch pulses, smbus2 reads the barometer + SCD41
 │              → 1 Hz rows in Postgres
 ├─ prestart   one-shot: alembic upgrade head
 ├─ db         postgres:18 (named volume)
 ├─ backend    FastAPI: REST API + the built React dashboard on :8000
 └─ adminer    database browser on :8080
```

- **One image** (`weather-station:<tag>`, linux/arm64) runs backend, collector and prestart.
- **Wind speed** (mph) = pulse frequency (Hz) × `ANEMOMETER_MPH_PER_HZ` (default 1.492). Gust = the highest 3-second average in the last 10 minutes.
- **Pressure** is stored in hPa (plus sea-level pressure once `BAROMETER_STATION_ALTITUDE_M` is set). The dashboard shows hPa and °F.
- **Storage**: one narrow `sensor_reading` table (`ts, sensor, metric, value`), so a new sensor needs no schema change.
- **Dashboard**: React + TanStack Query polls `/api/v1/readings/latest` and `/history` every second.

## Hardware

Anemometer (KY-025 reed switch):

| KY-025 pin | Raspberry Pi 5 | Physical pin |
|---|---|---|
| `+` | 3.3 V | 1 |
| `G` | GND | 6 |
| `DO` | GPIO17 | 11 |
| `AO` | not connected | |

> **Power the module from 3.3 V, not 5 V.** At 5 V the module's DO output drives 5 V into GPIO17, and Pi GPIO pins tolerate only 3.3 V.

Turn the module's potentiometer until its LED toggles cleanly each time the magnet passes the reed switch.

Barometer (Grove SPA06-003, I2C address 0x77):

| Grove pin | Raspberry Pi 5 | Physical pin |
|---|---|---|
| VCC | 3.3 V | 1 or 17 |
| GND | GND | 6 or 9 |
| SDA | GPIO2 (SDA1) | 3 |
| SCL | GPIO3 (SCL1) | 5 |

Wind vane (KY-040 rotary encoder, 18° per step):

| KY-040 pin | Raspberry Pi 5 | Physical pin |
|---|---|---|
| CLK | GPIO23 | 16 |
| DT | GPIO24 | 18 |
| SW | GPIO22 | 15 |
| `+` | 3.3 V | 1 or 17 |
| GND | GND | 6, 9 or 14 |

The encoder only counts relative turns. After every collector start, point the vane north and press the knob to set north; the Wind direction tab warns until you do.

Air quality (Grove SCD41, I2C address 0x62): wire it to the same four pins as the barometer (a Grove I2C hub makes this easy), and power it from **3.3 V**.

Enable I2C on the Pi once with `sudo raspi-config nonint do_i2c 0` and reboot. `i2cdetect -y 1` should then show `62` and `77`. The collector container won't start without `/dev/i2c-1`.

## Weather Underground

The station can upload to your Weather Underground personal weather station. Open the **Weather Underground** page in the dashboard and enter:
- the **station ID** and **station key** (wunderground.com → My Profile → My Devices);
- how often to upload (5 minutes by default);
- the station elevation in feet, which is needed to send sea-level pressure.

Then tick **Upload enabled**. Each upload sends:
- temperature, humidity and dew point from the SCD41;
- sea-level pressure from the barometer;
- the 2-minute average wind speed, the 10-minute gust and the 2-minute average direction.

A field is left out while its sensor has no fresh reading, and wind direction is left out until north is set. No precipitation is sent. In simulate mode (the Mac) uploads are dry runs and nothing is sent.

## Quick start

### Mac (development, simulated sensors)

```bash
docker compose watch
```

Open <http://localhost:8000>. The collector fakes a steady `SIM_WIND_MPH` (8 mph) wind with gpiozero's mock pins, and barometer readings around `SIM_PRESSURE_HPA` (1013.25 hPa). API docs are at <http://localhost:8000/docs> and Adminer at <http://localhost:8080>.

### Raspberry Pi (real sensor)

The image is always built on the Mac and copied to the Pi over ssh. The Pi needs only Docker with the compose plugin and rsync: no source checkout and no registry.

```bash
cp .env.pi.example .env.pi   # set POSTGRES_PASSWORD, check GPIO_CHIP, calibration, station altitude
```

```bash
PI_HOST=pi@raspberrypi.local ./scripts/deploy-pi.sh
```

Then open `http://raspberrypi.local:8000`.

## Documentation

- [development.md](development.md): local development, tests, migrations, deploying and operating the Pi.
- [CLAUDE.md](CLAUDE.md): architecture, conventions, GPIO-in-Docker gotchas and how to add a sensor.
- [backend/README.md](backend/README.md) and [frontend/README.md](frontend/README.md): per-app notes.

## License

MIT, inherited from the template. See [LICENSE](LICENSE).
