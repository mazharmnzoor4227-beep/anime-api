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
FANOUT_TIMEOUT_SECONDS = 45
