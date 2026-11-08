# Weather Station - Development

Two machines are involved:

- **Mac** (Apple Silicon): where code is written, tested and the Docker image is built. There is no GPIO or I2C here, so the collector simulates the anemometer, the wind vane, the barometer and the SCD41.
- **Raspberry Pi 5**: runs the stack with the real sensor. It never builds anything. It only loads the image built on the Mac.

## Compose files

| File | Loaded | Purpose |
|---|---|---|
| `compose.yml` | always | Base stack: `db`, `prestart` (migrations, one-shot), `backend` (:8000), `collector`, `adminer` (:8080). Image `weather-station:${TAG:-latest}`, `platform: linux/arm64`, `restart: unless-stopped`. No devices, so it works on both machines. |
| `compose.override.yml` | automatically, on the Mac | `fastapi dev` with `docker compose watch`, Postgres on :5432, collector with `COLLECTOR_SIMULATE=true`. |
| `compose.pi.yml` | explicitly, on the Pi | Collector gets `/dev/gpiochip${GPIO_CHIP:-0}`, `/dev/i2c-${BAROMETER_I2C_BUS:-1}` and `GPIOZERO_PIN_FACTORY=lgpio`. `pull_policy: never` on the app services. |

Settings come from `.env` (Mac) or `.env.pi` (Pi, copied there as `.env`). Every setting the app reads is defined in `backend/app/core/config.py`. Containers get their own `DATABASE_URL` pointing at the `db` service. The `DATABASE_URL` in `.env` (host `localhost`) is for code run directly on the Mac.

## Full stack on the Mac

```bash
docker compose watch
```

- Dashboard and API: <http://localhost:8000>
- API docs: <http://localhost:8000/docs>
- Adminer: <http://localhost:8080> (system PostgreSQL, server `db`, user `postgres`, password from `.env`, database `app`)

`prestart` runs `alembic upgrade head` before `backend` and `collector` start. Backend code changes sync into the container and reload `fastapi dev`. Changes under `backend/app` also restart the collector. Changes to `frontend/` or `backend/pyproject.toml` rebuild the image.

Useful commands:

```bash
docker compose logs -f collector
```

```bash
docker compose stop collector    # the dashboard badge turns "stale" within STALE_AFTER_S (5 s)
```

```bash
docker compose exec backend bash
```

Change the simulated readings with `SIM_WIND_MPH`, `SIM_PRESSURE_HPA`, `SIM_TEMP_C`, `SIM_CO2_PPM`, `SIM_HUMIDITY_PCT` and `SIM_WIND_DIR_DEG` in `.env`, then `docker compose up -d collector`. The Barometer page is at <http://localhost:8000/barometer>.

## Running pieces locally

Start only Postgres in Docker, then run the backend on the Mac:

```bash
docker compose up -d db
```

```bash
cd backend && uv sync && uv run bash scripts/prestart.sh && uv run fastapi dev
```

The simulated collector (needs `COLLECTOR_SIMULATE=true`, already set in `.env`):

```bash
cd backend && uv run python -m app.collector
```

The dashboard with hot reload, from the repo root (Vite on <http://localhost:5173> proxies `/api` to `localhost:8000`):

```bash
bun install && bun run dev
```

`lgpio` is only installed on linux/aarch64 (see the marker in `backend/pyproject.toml`), so `uv sync` on the Mac doesn't try to build it.

## Tests and linting

Backend, from `backend/` with `db` running and migrated:

```bash
uv run pytest
```

```bash
uv run ruff check && uv run ruff format --check && uv run mypy app && uv run ty check app
```

Backend tests in Docker against a throwaway database (starts only `db` and `prestart`, not the collector):

```bash
bash scripts/test.sh
```

Frontend, from the repo root:

```bash
bun run lint && bun run --filter frontend build
```

The frontend talks to the API through the hand-written fetch layer in `frontend/src/lib/api.ts`. Update it by hand when an API response shape changes.

## Migrations

There is one Alembic history in `backend/app/alembic/versions/`. After changing a model in `backend/app/models.py`, with `db` running:

```bash
cd backend && uv run alembic revision --autogenerate -m "describe the change"
```

Review the generated file, commit it, then apply it with `uv run alembic upgrade head` (or let `prestart` apply it on the next `docker compose up` or deploy).

## Deploying to the Raspberry Pi

### One-time Pi setup

1. Raspberry Pi OS (64-bit) on a Pi 5.
2. Install Docker with the compose plugin (`curl -fsSL https://get.docker.com | sh`), add your user to the `docker` group (`sudo usermod -aG docker $USER`, then log in again) and make sure `rsync` is installed (`sudo apt install rsync`).
3. Set up ssh key login from the Mac (`ssh-copy-id pi@raspberrypi.local`).
4. Find the GPIO chip of the 40-pin header: `ls -l /dev/gpiochip*` or `gpioinfo` (package `gpiod`). On kernels ≥ 6.6.45 it is `gpiochip0`; older kernels use `gpiochip4`.
5. Enable I2C for the barometer: `sudo raspi-config nonint do_i2c 0`, then reboot. Check it with `ls /dev/i2c-1`, and `sudo apt install i2c-tools && i2cdetect -y 1` should show `77` for the barometer and `62` for the SCD41 once they are wired. The collector container won't start if `/dev/i2c-1` is missing; `deploy-pi.sh` checks for it.
6. Wire the KY-025 and the barometer to **3.3 V** (see [CLAUDE.md](CLAUDE.md#hardware)).

### Deploy

On the Mac, create `.env.pi` once (it is gitignored) and set at least `POSTGRES_PASSWORD` and `GPIO_CHIP`:

```bash
cp .env.pi.example .env.pi
```

Then, for each deploy:

```bash
PI_HOST=pi@raspberrypi.local ./scripts/deploy-pi.sh
```

`scripts/deploy-pi.sh` (variables `PI_HOST` (required), `PI_DIR` (default `weather-station`, relative to the Pi home) and `TAG` (default `latest`)):

1. `docker buildx build --platform linux/arm64 -f backend/Dockerfile -t weather-station:$TAG --load .`. This builds natively on Apple Silicon. On an Intel Mac it runs under QEMU: slower, but it works.
2. `docker save | gzip | ssh $PI_HOST 'gunzip | docker load'`.
3. rsync of `compose.yml`, `compose.pi.yml` and `.env.pi` (as `.env`, with `TAG=` appended) to `$PI_HOST:$PI_DIR`.
4. `docker compose -f compose.yml -f compose.pi.yml up -d --no-build` on the Pi.

The first deploy also pulls `postgres:18` and `adminer` from Docker Hub on the Pi, so the Pi needs internet access then.

### Operating the Pi

On the Pi, in `~/weather-station`:

```bash
docker compose -f compose.yml -f compose.pi.yml logs -f collector
```

```bash
docker compose -f compose.yml -f compose.pi.yml ps
```

```bash
docker image ls weather-station    # tag + arch of the deployed image
```

The collector's startup log names the pin factory (`LGPIOFactory`) and GPIO17, then the barometer line: `Barometer SPA06-003 on /dev/i2c-1 at 0x77: ready, chip id 0x..`. Waving the magnet past the switch should increase `pulse_count` and toggle `do_active`. If the barometer says "not responding", check the wiring and address with `i2cdetect -y 1`; the collector keeps retrying every `BAROMETER_RETRY_S` and keeps recording wind meanwhile. Set `BAROMETER_STATION_ALTITUDE_M` in `.env.pi` to get sea-level pressure comparable to local weather reports. The wind vane logs `Wind vane KY-040 on CLK GPIO23, DT GPIO24, SW GPIO22`. Point it north and press the knob (the log says `Wind vane zeroed`); turning it by hand should move the compass 18° per click. The SCD41 logs `Air quality SCD41 on /dev/i2c-1 at 0x62: ready, serial 0x…`, and its first CO₂ reading arrives about 5 s later. Breathing near it should push CO₂ up within a reading or two. All services use `restart: unless-stopped`, so the station comes back after a reboot. `prestart` is one-shot, so it doesn't restart; the next deploy runs migrations again.

Each deploy with the same `TAG` leaves the previous image dangling. Free the space with `docker image prune` on the Pi.

The `POSTGRES_PASSWORD` is only applied when the database volume is first created. Changing it later in `.env.pi` breaks the connection until you also change it inside Postgres.

## Pre-commit hooks

The project uses [prek](https://prek.j178.dev/) (a pre-commit alternative), configured in `.pre-commit-config.yaml`:

```bash
uv run prek install -f
```

```bash
uv run prek run --all-files
```
