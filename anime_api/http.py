"""Shared HTTP helpers (scaffold-owned).

Implements the contract in anime-api-work/INTERFACE.md:
- BROWSER_UA / ANDROID_UA constants
- get / get_json / post_form / get_soup
- resolve_domain(): Firebase live-domain map with a 5-minute in-memory cache.
"""

import time

import requests
from bs4 import BeautifulSoup

from anime_api.config import DOMAIN_CACHE_TTL_SECONDS, FIREBASE_DOMAINS_URL

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
)

_DEFAULT_HEADERS = {"User-Agent": BROWSER_UA}

_domain_cache = {"at": 0.0, "map": {}}


def _headers(headers):
    merged = dict(_DEFAULT_HEADERS)
    if headers:
        merged.update(headers)
    return merged


def get(url, headers=None, timeout=30, allow_redirects=True):
    """GET and raise on HTTP >= 400."""
    resp = requests.get(
        url, headers=_headers(headers), timeout=timeout,
        allow_redirects=allow_redirects,
    )
    resp.raise_for_status()
    return resp


def get_json(url, headers=None, timeout=30):
    """GET and parse the body as JSON (raises on HTTP >= 400 / bad JSON)."""
    return get(url, headers=headers, timeout=timeout).json()


def post_form(url, data, headers=None, timeout=30):
    """POST form-encoded data; raise on HTTP >= 400."""
    resp = requests.post(
        url, data=data, headers=_headers(headers), timeout=timeout
    )
    resp.raise_for_status()
    return resp


def post_json(url, payload, headers=None, timeout=30):
    """POST a JSON body; raise on HTTP >= 400."""
    hdrs = _headers(headers)
    hdrs.setdefault("Content-Type", "application/json")
    resp = requests.post(url, json=payload, headers=hdrs, timeout=timeout)
    resp.raise_for_status()
    return resp


def get_soup(url, headers=None, timeout=30):
    """GET a page and parse it with BeautifulSoup (lxml)."""
    resp = get(url, headers=headers, timeout=timeout)
    return BeautifulSoup(resp.text, "lxml")


def _fetch_domain_map():
    now = time.monotonic()
    if now - _domain_cache["at"] < DOMAIN_CACHE_TTL_SECONDS and _domain_cache["map"]:
        return _domain_cache["map"]
    try:
        resp = requests.get(FIREBASE_DOMAINS_URL, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            _domain_cache["map"] = {
                str(k): str(v) for k, v in data.items() if v is not None
            }
            _domain_cache["at"] = now
    except Exception:
        # On any failure keep the previous (possibly empty) map; the caller
        # falls back to the source's static default_url.
        pass
    return _domain_cache["map"]


def resolve_domain(key, default):
    """Resolve a live host for ``key`` via the Firebase domain map.

    Lookup order: ``key``, ``key + "_url"``, ``key + "_domain"``.
    Trailing "/" is stripped. On any failure ``default`` is returned.
    """
    if not key:
        return default.rstrip("/")
    try:
        domain_map = _fetch_domain_map()
        for candidate in (key, key + "_url", key + "_domain"):
            value = domain_map.get(candidate)
            if value:
                value = str(value).strip().rstrip("/")
                if value:
                    if not value.startswith("http"):
                        value = "https://" + value
                    return value
    except Exception:
        pass
    return default.rstrip("/")
