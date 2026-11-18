"""Configuration for anime-api."""

import os

HOST = os.environ.get("ANIME_API_HOST", "0.0.0.0")
PORT = int(os.environ.get("ANIME_API_PORT", "8000"))
DEBUG = os.environ.get("ANIME_API_DEBUG", "0") == "1"

# Firebase map used by resolve_domain() — the live domain source the
# CloudStream extensions use. See anime_api/http.py.
FIREBASE_DOMAINS_URL = (
    "https://cloudstreampluginhelper-default-rtdb.firebaseio.com/.json"
)
DOMAIN_CACHE_TTL_SECONDS = 300

# Fan-out timeout for /api/search and /api/trending|popular|latest.
# v1.2: was 45s — one slow source could gate every home load for up to
# 45s (the user's "10 seconds of loading"). 12s is the hard ceiling now;
# the per-source calls themselves are fast (<1.5s each when healthy) and
# a source that misses the deadline is reported in ``errors``.
FANOUT_TIMEOUT_SECONDS = 12

# Response-cache TTLs (seconds) — see anime_api/cache.py.
CACHE_TTL_LIST_SECONDS = 600       # trending / popular / latest
CACHE_TTL_SEARCH_SECONDS = 300     # search
CACHE_TTL_DETAILS_SECONDS = 1800   # /api/anime
CACHE_TTL_STREAMS_SECONDS = 600    # /api/streams (tokens live days; see megaplay signUrl)
CACHE_TTL_WIDGETS_SECONDS = 1800   # /api/widgets (site sidebar)

# Pre-warm: refresh the hot list keys this often (seconds).
PREWARM_INTERVAL_SECONDS = 300

# Auto-update (v1.4): background refresh job — every 30 minutes it
# re-fetches latest/trending per source (ALL sources, ALL categories)
# and rewrites the list caches, so new releases appear in the app /
# website automatically with no redeploy and no manual step. List
# TTLs stay short (10 min) so the site always shows fresh titles;
# the refresh keeps the cache warm so users get fresh + fast.
REFRESH_INTERVAL_SECONDS = 1800
