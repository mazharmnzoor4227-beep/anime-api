"""Tiny thread-safe in-memory TTL cache for anime-api v1.2.

Why: every home/search/details call used to re-scrape the source sites
(0.5-3s per call, and a single slow source gated the whole fan-out).
Cached list responses make repeat loads near-instant; the pre-warm
thread in app.py keeps the hot keys warm so the first user of the day
never pays a cold scrape either.

Keys are plain strings; values are (expires_at_monotonic, payload).
No external dependency — the API must stay a plain Flask app.
"""

import threading
import time

_MAX_ENTRIES = 512


class TTLCache:
    def __init__(self, max_entries=_MAX_ENTRIES):
        self._lock = threading.Lock()
        self._store = {}
        self._max = max_entries

    def get(self, key):
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None, False
            expires, value = entry
            if now >= expires:
                del self._store[key]
                return None, False
            return value, True

    def set(self, key, value, ttl_seconds):
        if ttl_seconds is None or ttl_seconds <= 0:
            return
        with self._lock:
            if len(self._store) >= self._max:
                # Evict the entry expiring soonest (cheap scan, small store).
                oldest = min(self._store.items(),
                             key=lambda kv: kv[1][0])[0]
                del self._store[oldest]
            self._store[key] = (time.monotonic() + ttl_seconds, value)

    def clear(self):
        with self._lock:
            self._store.clear()

    def __len__(self):
        with self._lock:
            return len(self._store)


# Process-wide cache used by app.py.
CACHE = TTLCache()
