"""Background thread in the collector that uploads to Weather Underground.

The schedule and credentials live in the wunderground_config row, edited from
the dashboard, so the thread re-reads them on every check and changes apply
without a restart. It runs apart from the 1 Hz sampling loop, so a slow or
failing upload never delays sampling.
"""

import logging
import threading
from collections.abc import Callable
from datetime import datetime

import httpx
from sqlmodel import Session

from app.core.db import engine
from app.models import get_datetime_utc
from app.wunderground import get_config, is_due, upload

logger = logging.getLogger(__name__)

TIMEOUT_JOIN_S = 15.0


class WundergroundUploader:
    def __init__(
        self,
        *,
        dry_run: bool,
        check_every_s: float = 15.0,
        first_check_s: float = 10.0,
        session_factory: Callable[[], Session] = lambda: Session(engine),
        client: httpx.Client | None = None,
        clock: Callable[[], datetime] = get_datetime_utc,
    ) -> None:
        self.dry_run = dry_run
        self.check_every_s = check_every_s
        # Give the sensors a few samples before the first upload.
        self.first_check_s = first_check_s
        self._session_factory = session_factory
        self._client = client or httpx.Client()
        self._clock = clock
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="wunderground-uploader", daemon=True
        )

    def tick(self) -> str | None:
        """Upload if due. Returns the result, or None if nothing was due."""
        with self._session_factory() as session:
            cfg = get_config(session)
            if not is_due(cfg, self._clock()):
                return None
            result = upload(
                session,
                cfg,
                client=self._client,
                dry_run=self.dry_run,
                now=self._clock(),
            )
            sent = " ".join(f"{k}={v:g}" for k, v in (cfg.last_payload or {}).items())
        level = logging.INFO if not result.startswith("error") else logging.WARNING
        logger.log(level, "WU upload: %s (%s)", result, sent or "nothing sent")
        return result

    def _run(self) -> None:
        wait = self.first_check_s
        while not self._stop.wait(wait):
            wait = self.check_every_s
            try:
                self.tick()
            except Exception:
                logger.exception("WU upload check failed")

    def start(self) -> None:
        logger.info(
            "Weather Underground uploader started%s; settings are on the "
            "dashboard's Weather Underground page",
            " (dry run: simulate mode never uploads)" if self.dry_run else "",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=TIMEOUT_JOIN_S)
        self._client.close()
