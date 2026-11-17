"""Cloudflare clearance handling for the Hindi sources (AnimeWorldIndia,
RareAnimesIndia).

Background
----------
Both Hindi sites sit behind Cloudflare and block plain ``requests`` calls:

* ``watchanimeworld.one`` -> HTTP 403, Cloudflare "Attention Required!"
  block page (``CF-RAY`` header, no JS challenge is presented).
* ``www.rareanimes.fans`` -> HTTP 403, bare body ``"Your request was blocked."``

The Android extensions solve this with an interactive WebView that captures
a ``cf_clearance`` cookie (15 h TTL, per-host store).  On a server the
equivalent is a headless browser, so this module provides:

1. :func:`get_clearance` — Playwright headless-Chromium solver.  Navigates
   to the site, waits for the Cloudflare challenge to pass and for a
   ``cf_clearance`` cookie to appear, then caches ``{cookies, user-agent}``
   per host in ``~/workspace/anime-api/.cf_cookies.json`` with a 15 h TTL
   (same TTL the extensions use).  Chromium is launched from the Playwright
   browser cache (``~/.cache/ms-playwright``); no browser download is done
   here.  ``playwright`` is an *optional* dependency: if it is not
   installed, the solver is skipped and the env/file fallback below applies.
2. :func:`cf_get` / :func:`cf_session` — ``requests`` helpers used by the
   Hindi sources.  A plain request is tried first; on a Cloudflare block
   the cached clearance (or an env-provided one) is retried, and only then
   is the headless solver attempted (at most once per host per process).
3. Manual fallback — a clearance obtained once in a real browser can be
   pasted in, no solver needed:

   * Environment variables, one per host, named
     ``CF_CLEARANCE_<HOST>`` where ``<HOST>`` is the host upper-cased with
     ``.`` and ``-`` replaced by ``_``.  Example::

         CF_CLEARANCE_WATCHANIMEWORLD_ONE=<cookie value>
         CF_CLEARANCE_WWW_RAREANIMES_FANS=<cookie value>

     The value is the bare ``cf_clearance`` cookie value (not a full
     ``Cookie:`` header).  An optional matching user-agent may be supplied
     as ``CF_UA_<HOST>``; otherwise the shared browser UA is used.
   * Or a JSON file (same shape as the cache file) at the path in
     ``ANIME_API_CF_COOKIES``.  Shape::

         {"<host>": {"cookies": {"cf_clearance": "...", ...},
                     "ua": "Mozilla/5.0 ...",
                     "saved_at": 1794950000}}

   No clearance cookie is ever hard-coded in this module.

Sandbox note: in the Muse sandbox the egress proxy MITMs TLS with its own
CA (``SSL_CERT_FILE`` points at the CA bundle) and Chromium does not read
that variable, so the browser context is created with
``ignore_https_errors=True`` whenever ``SSL_CERT_FILE`` is set.  The
browser also honours ``ANIME_API_CF_PROXY`` (``http://host:port``) when
set — in the sandbox Chromium cannot authenticate to the egress proxy
directly, so a tiny local CONNECT relay must be pointed to instead.
On a normal deployment host neither knob is needed.

Status (2026-11-18, sandbox): the headless solver does NOT clear either
site from this sandbox — both return an immediate hard 403 block page with
no JS challenge to solve (most likely an IP/ASN reputation block of the
sandbox egress IP).  The code below is the correct solver for a deployment
host with a clean IP, and the env/file fallback is the working route until
then.  Both Hindi sources are therefore DEGRADED in this sandbox.
"""

import json
import os
import re
import threading
import time
from urllib.parse import urlparse

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COOKIE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".cf_cookies.json",
)
# Extra seed file (same shape) for manually pasted clearances.
ENV_COOKIES_FILE = os.environ.get("ANIME_API_CF_COOKIES", "")
TTL_SECONDS = 15 * 3600  # 15 h, same as the Android extensions

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Markers the extensions use to detect a Cloudflare block (see report).
_CF_BODY_MARKERS = (
    "just a moment",
    "checking your browser",
    "cf-browser-verification",
    "checking if the site connection is secure",
    "attention required",
    "your request was blocked",
    "challenge-platform",
)

_lock = threading.Lock()
_solve_attempted = set()  # hosts the headless solver already tried (per process)


# ---------------------------------------------------------------------------
# Cache file helpers
# ---------------------------------------------------------------------------

def _load_store():
    """Load the clearance cache (file + optional seed file), best effort."""
    store = {}
    for path in (COOKIE_FILE, ENV_COOKIES_FILE):
        if not path:
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                for host, entry in data.items():
                    if isinstance(entry, dict) and entry.get("cookies"):
                        # Seed file wins over the cache file for the same host.
                        store[str(host).lower()] = entry
        except Exception:
            continue
    return store


def _save_store(store):
    try:
        tmp = COOKIE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(store, fh)
        os.replace(tmp, COOKIE_FILE)
    except Exception:
        pass


def _host_key(host):
    return re.sub(r"[^A-Z0-9]", "_", host.upper())


def _env_clearance(host):
    """(cookies, ua) from CF_CLEARANCE_<HOST> / CF_UA_<HOST>, or None."""
    key = _host_key(host)
    value = os.environ.get("CF_CLEARANCE_" + key)
    if not value:
        return None
    ua = os.environ.get("CF_UA_" + key) or BROWSER_UA
    return ({"cf_clearance": value.strip()}, ua)


def get_cached(host):
    """Return (cookies, ua) for ``host`` if a fresh (<= 15 h) entry exists.

    Checks the cache file, the optional seed file, then the environment.
    Returns ``None`` when nothing usable is stored.
    """
    host = host.lower()
    entry = _load_store().get(host)
    if entry:
        saved_at = float(entry.get("saved_at") or 0)
        if saved_at and time.time() - saved_at < TTL_SECONDS:
            cookies = entry.get("cookies") or {}
            if cookies.get("cf_clearance"):
                return (dict(cookies), entry.get("ua") or BROWSER_UA)
    return _env_clearance(host)


def save_clearance(host, cookies, ua):
    """Persist a fresh clearance for ``host`` (15 h TTL from now)."""
    host = host.lower()
    with _lock:
        store = _load_store()
        store[host] = {
            "cookies": dict(cookies),
            "ua": ua,
            "saved_at": time.time(),
        }
        _save_store(store)


# ---------------------------------------------------------------------------
# Block detection
# ---------------------------------------------------------------------------

def is_cf_blocked(resp):
    """True when ``resp`` (a requests Response) looks like a CF block.

    Mirrors the extensions: HTTP 503 always; on 403 the body markers
    (``just a moment`` alone counts on 403); the bare
    ``"Your request was blocked."`` body is also a block.
    """
    if resp is None:
        return False
    if resp.status_code == 503:
        return True
    if resp.status_code != 403:
        return False
    try:
        body = (resp.text or "").lower()
    except Exception:
        body = ""
    if not body.strip():
        return True
    return any(m in body for m in _CF_BODY_MARKERS)


# ---------------------------------------------------------------------------
# Headless solver (Playwright)
# ---------------------------------------------------------------------------

def _find_chromium_executable():
    """Locate a Playwright-cached Chromium binary, or None."""
    import glob

    base = os.path.expanduser("~/.cache/ms-playwright")
    patterns = [
        os.path.join(base, "chromium-*/chrome-linux64/chrome"),
        os.path.join(
            base, "chromium_headless_shell-*/chrome-headless-shell-linux64/"
            "chrome-headless-shell"
        ),
    ]
    for pattern in patterns:
        for path in sorted(glob.glob(pattern), reverse=True):
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
    return None


def get_clearance(host, url=None, timeout=90):
    """Solve the Cloudflare challenge for ``host`` with headless Chromium.

    Returns ``(cookies, ua)`` on success (and caches them), else ``None``.
    ``url`` defaults to ``https://<host>/``.  Returns ``None`` quickly when
    Playwright is not installed or no Chromium binary is cached.  A page
    that answers with an immediate hard 403 block page (no JS challenge)
    yields ``None`` — there is nothing to solve.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    exe = _find_chromium_executable()
    if not exe:
        return None
    url = url or "https://" + host + "/"
    ua = BROWSER_UA
    # Sandbox egress proxy MITMs TLS with its own CA; Chromium does not
    # read SSL_CERT_FILE, so ignore cert errors only in that environment.
    ignore_https = bool(os.environ.get("SSL_CERT_FILE"))
    proxy = None
    proxy_env = os.environ.get("ANIME_API_CF_PROXY")
    if proxy_env:
        proxy = {"server": proxy_env}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                executable_path=exe,
                args=["--no-sandbox"],
            )
            context = browser.new_context(
                user_agent=ua,
                proxy=proxy,
                ignore_https_errors=ignore_https,
            )
            page = context.new_page()
            try:
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
            except Exception:
                pass  # challenge pages / slow loads: poll below anyway
            deadline = time.time() + timeout
            cookies = {}
            while time.time() < deadline:
                try:
                    cookies = {
                        c["name"]: c["value"] for c in context.cookies()
                    }
                    if cookies.get("cf_clearance"):
                        break
                    title = (page.title() or "").lower()
                    page_url = page.url or ""
                    if (
                        title
                        and "just a moment" not in title
                        and "attention required" not in title
                        and "chrome-error" not in page_url
                    ):
                        # Real page loaded without a challenge cookie:
                        # either no challenge exists or we are hard-blocked.
                        break
                except Exception:
                    pass
                time.sleep(5)
            browser.close()
            if cookies.get("cf_clearance"):
                save_clearance(host, cookies, ua)
                return (cookies, ua)
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# requests integration
# ---------------------------------------------------------------------------

def apply_clearance(session, host):
    """Apply any cached/env clearance for ``host`` to a requests Session.

    Returns True when cookies were applied.
    """
    cached = get_cached(host)
    if not cached:
        return False
    cookies, ua = cached
    for name, value in cookies.items():
        session.cookies.set(name, value, domain="." + host.lstrip("."))
    session.headers.setdefault("User-Agent", ua)
    return True


def cf_session(host):
    """A requests Session preloaded with the cached clearance for ``host``."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;"
                      "q=0.9,*/*;q=0.8",
        }
    )
    apply_clearance(session, host)
    return session


def cf_get(url, headers=None, timeout=30, _session=None, _allow_solve=True):
    """GET ``url`` with Cloudflare handling; returns the Response.

    Strategy: plain request -> cached/env clearance retry -> (once per host
    per process) headless Playwright solve + retry.  Never raises for a
    403/503 block page — the caller inspects the response (use
    :func:`is_cf_blocked`).  Other HTTP errors are still raised by the
    caller; this helper only returns what the server sent.
    """
    host = urlparse(url).netloc.lower()
    session = _session or cf_session(host)
    merged = dict(session.headers)
    if headers:
        merged.update(headers)
    try:
        resp = session.get(url, headers=merged, timeout=timeout)
    except requests.RequestException:
        raise
    if not is_cf_blocked(resp):
        return resp

    # Retry with any cached/env clearance (the session may predate it).
    if apply_clearance(session, host):
        try:
            resp2 = session.get(url, headers=merged, timeout=timeout)
        except requests.RequestException:
            resp2 = None
        if resp2 is not None and not is_cf_blocked(resp2):
            return resp2
        resp = resp2 or resp

    # Last resort: headless solve, once per host per process.
    if _allow_solve:
        with _lock:
            attempted = host in _solve_attempted
            if not attempted:
                _solve_attempted.add(host)
        if not attempted:
            solved = get_clearance(host, url="https://" + host + "/")
            if solved:
                cookies, _ua = solved
                for name, value in cookies.items():
                    session.cookies.set(
                        name, value, domain="." + host.lstrip(".")
                    )
                try:
                    resp3 = session.get(url, headers=merged, timeout=timeout)
                except requests.RequestException:
                    resp3 = None
                if resp3 is not None and not is_cf_blocked(resp3):
                    return resp3
                resp = resp3 or resp
    return resp
