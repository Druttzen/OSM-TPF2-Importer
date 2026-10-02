"""Conservative request pacing for public OpenStreetMap services."""
from __future__ import annotations

import threading
import time
from urllib.parse import urlparse

from .jobs import JobCancelled

_MIN_INTERVAL_SECONDS = 1.1
_LOCK = threading.Lock()
_LAST_REQUEST: dict[str, float] = {}


def wait_for_request_slot(url: str, cancel=None) -> None:
    host = (urlparse(url).hostname or "").lower()
    if not host.endswith("openstreetmap.org") and not host.endswith("overpass-api.de"):
        return

    while True:
        with _LOCK:
            now = time.monotonic()
            delay = _MIN_INTERVAL_SECONDS - (now - _LAST_REQUEST.get(host, 0.0))
            if delay <= 0:
                _LAST_REQUEST[host] = now
                return
        if cancel is not None:
            if cancel.wait(min(delay, 0.2)):
                raise JobCancelled()
        else:
            time.sleep(min(delay, 0.2))
