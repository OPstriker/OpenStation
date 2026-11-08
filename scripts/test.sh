#! /usr/bin/env sh
# Run the backend tests in Docker against a throwaway Postgres.
# Extra arguments go to the coverage HTML title (see backend/scripts/test.sh).
#
# Only db + migrations are started: the collector is left out so simulated
# readings don't land in the test database.

# Exit in case of error
set -e
set -x

docker compose build backend
docker compose down -v --remove-orphans # Remove possibly previous broken stacks left hanging after an error
docker compose run --rm prestart # starts db, waits for it, runs migrations
# The image doesn't contain backend/tests, so mount them (and htmlcov for the report).
docker compose run --rm --no-deps \
    -v "$(pwd)/backend/tests:/app/backend/tests" \
    -v "$(pwd)/backend/htmlcov:/app/backend/htmlcov" \
    backend bash scripts/tests-start.sh "$@"
docker compose down -v --remove-orphans
