#!/usr/bin/env bash
# Build the weather-station image on this Mac (linux/arm64) and run it on the Pi.
#
# No registry and no source checkout on the Pi: the image goes over ssh with
# `docker save | docker load`, and only compose.yml, compose.pi.yml and the
# env file are copied.
#
# Usage (from anywhere in the repo):
#   PI_HOST=pi@raspberrypi.local ./scripts/deploy-pi.sh
#
# Environment:
#   PI_HOST  (required) ssh destination, e.g. pi@raspberrypi.local
#   PI_DIR   directory on the Pi, relative to the Pi user's home or absolute
#            (default: weather-station). Don't use "~/...": it would expand
#            on the Mac.
#   TAG      image tag (default: latest)
#
# Needs on the Pi: Docker with the compose plugin, rsync, and the ssh user in
# the docker group (sudo usermod -aG docker $USER, then log in again).
set -euo pipefail

PI_DIR="${PI_DIR:-weather-station}"
TAG="${TAG:-latest}"
IMAGE="weather-station:${TAG}"

die() {
    echo "error: $*" >&2
    exit 1
}

cd "$(dirname "$0")/.."

[[ -n "${PI_HOST:-}" ]] || die "PI_HOST is not set. Example: PI_HOST=pi@raspberrypi.local $0"
[[ "$PI_DIR" != /Users/* ]] || die "PI_DIR=$PI_DIR looks like a Mac path (did ~ expand locally?). Use a path relative to the Pi home, e.g. PI_DIR=weather-station"
[[ -f .env.pi ]] || die ".env.pi not found. Create it with: cp .env.pi.example .env.pi  (then set POSTGRES_PASSWORD)"
grep -Eq '^POSTGRES_PASSWORD=.+' .env.pi || die "POSTGRES_PASSWORD is empty in .env.pi"
if grep -Eq '^POSTGRES_PASSWORD="?changethis"?$' .env.pi; then
    die "POSTGRES_PASSWORD in .env.pi is still \"changethis\"; the app refuses to start with it on the Pi"
fi
command -v docker >/dev/null || die "docker not found on this Mac"
command -v rsync >/dev/null || die "rsync not found on this Mac"

echo "==> Checking ssh, docker and rsync on $PI_HOST"
ssh "$PI_HOST" 'docker compose version >/dev/null && command -v rsync >/dev/null' \
    || die "cannot run 'docker compose' and rsync on $PI_HOST (is Docker installed, is the user in the docker group, is rsync installed?)"

# Device nodes compose.pi.yml passes to the collector. A missing one stops the
# whole collector container from starting, so check before deploying.
env_value() { # env_value NAME DEFAULT: last NAME= in .env.pi, unquoted
    local v
    v="$(grep -E "^$1=" .env.pi | tail -n1 | cut -d= -f2- | tr -d '"'"'"'\r')"
    echo "${v:-$2}"
}
gpio_dev="/dev/gpiochip$(env_value GPIO_CHIP 0)"
i2c_dev="/dev/i2c-$(env_value BAROMETER_I2C_BUS 1)"
echo "==> Checking $gpio_dev and $i2c_dev on $PI_HOST"
ssh "$PI_HOST" "test -e '$gpio_dev'" \
    || die "$gpio_dev not found on $PI_HOST. Check 'ls /dev/gpiochip*' there and set GPIO_CHIP in .env.pi"
ssh "$PI_HOST" "test -e '$i2c_dev'" \
    || die "$i2c_dev not found on $PI_HOST: enable I2C there (sudo raspi-config nonint do_i2c 0, then reboot)"

echo "==> Building $IMAGE for linux/arm64"
docker buildx build --platform linux/arm64 -f backend/Dockerfile -t "$IMAGE" --load .

arch="$(docker image inspect --format '{{.Architecture}}' "$IMAGE")"
[[ "$arch" == "arm64" ]] || die "$IMAGE is $arch, expected arm64"

echo "==> Copying $IMAGE to $PI_HOST (docker save | gzip | docker load)"
docker save "$IMAGE" | gzip | ssh "$PI_HOST" 'gunzip | docker load'

echo "==> Copying compose files and .env to $PI_HOST:$PI_DIR"
env_tmp="$(mktemp)"
trap 'rm -f "$env_tmp"' EXIT
# TAG goes into the Pi's .env so later `docker compose ...` commands run on the
# Pi (without TAG set) still point at the deployed image.
{
    cat .env.pi
    printf '\n# Added by scripts/deploy-pi.sh\nTAG=%s\n' "$TAG"
} >"$env_tmp"
chmod 600 "$env_tmp"
ssh "$PI_HOST" "mkdir -p '$PI_DIR'"
rsync -t compose.yml compose.pi.yml "$PI_HOST:$PI_DIR/"
# -p keeps the 0600 mode (the file holds the Postgres password).
rsync -tp "$env_tmp" "$PI_HOST:$PI_DIR/.env"

echo "==> Starting the stack on $PI_HOST"
ssh "$PI_HOST" "cd '$PI_DIR' && docker compose -f compose.yml -f compose.pi.yml up -d --no-build --remove-orphans"
ssh "$PI_HOST" "cd '$PI_DIR' && docker compose -f compose.yml -f compose.pi.yml ps"

host="${PI_HOST#*@}"
echo
echo "Deployed $IMAGE. Dashboard: http://$host:8000"
echo "Collector logs: ssh $PI_HOST \"cd $PI_DIR && docker compose -f compose.yml -f compose.pi.yml logs -f collector\""
