"""AniSuge source for the anime API.

Ports ``com.laddu100.AniSugeProvider`` (plus ``AniSugeResolver.kt``:
``AniSugeMapper``, ``PaheDownloadResolver``, ``KwikExtractor``) from the
Raghav CloudStream extension. Site: https://anisuge.tv (domain resolved
via the Firebase helper map, key ``"anisuge"``, falling back to the
static default URL).

Headers: UA Chrome/124 + ``Referer: {mainUrl}/`` on site requests, no
cookies. The extension uses a CloudflareKiller interceptor; plain
``requests`` returned HTTP 200 from this sandbox, so no CF bypass is
implemented here — if the live site starts challenging, this module
will fail with 403 and needs a bypass.

Episode ``data`` format (opaque pipe string, built by :meth:`details`)::
    {mainUrl}|{dataId}|{epNum}|{dataIds}|{malId}|{slug}|{timestamp}|sub
(and a second entry ending ``|dub`` when the episode is dubbed).
``dataIds`` feeds the legacy server flow, ``malId``/``slug``/``timestamp``
feed the mapper API.

Home section mapping (interface -> provider): trending -> recent
("Recently Updated"), popular -> mostview ("Most Viewed"),
latest -> added ("Recently Added"). Page > 1 returns an empty list
(the provider has no pagination).

WebView fallback: the extension falls back to a WebView resolver for
embeds no extractor handles. There is no server-side equivalent, so
:func:`resolve_embed` instead does a best-effort plain GET of the
player URL and regex-searches for a ``.m3u8`` (or ``.mp4``) URL.
"""

import base64
import binascii
import codecs
import json
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

try:  # scaffold-owned base class, when it exists
    from anime_api.sources.base import Source as _BaseSource
except Exception:  # pragma: no cover - scaffold not created yet
    _BaseSource = None

try:  # scaffold-owned domain resolver, when it exists
    from anime_api.http import resolve_domain as _resolve_domain
except Exception:  # pragma: no cover - scaffold not created yet
    _resolve_domain = None

try:  # owned by the NineAnime+AniKoto agent; do NOT reimplement
    from anime_api.extractors.megaplay import resolve_megaplay as _resolve_megaplay
except Exception:  # pragma: no cover - extractor not written yet
    _resolve_megaplay = None

UA_124 = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
UA_131 = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
MAPPER_API = "https://mapper.nekostream.site/api/mal/"
_FIREBASE_URL = (
    "https://cloudstreampluginhelper-default-rtdb.firebaseio.com/.json"
)

_VRF_KEY = b"ysJhV6U27FVIjjuk"
# shiftCharcode: index r, r % 8 -> delta
_SHIFT = {0: -3, 1: +3, 2: -4, 3: +2, 4: -2, 5: +5, 6: +4, 7: +5}
_SUB_TYPES = {"sub", "hsub", "h-sub", "raw"}
_DUB_TYPES = {"dub", "adub", "a-dub"}
_MEGAPLAY_HOSTS = ("megaplay", "vidwish", "vidtube", "vidstream", "vidplay")
_M3U8_RE = re.compile(r"https?://[^\s\"'<>]+\.m3u8(?:[?#][^\s\"'<>]*)?", re.I)
_MP4_RE = re.compile(r"https?://[^\s\"'<>]+\.mp4(?:[?#][^\s\"'<>]*)?", re.I)

_domain_cache = {"domains": {}, "ts": 0.0}


def _fallback_resolve_domain(key, default):
    """Firebase RTDB lookup (same logic as INTERFACE.md), 5-min cache."""
    now = time.time()
    if now - _domain_cache["ts"] < 300 and _domain_cache["domains"]:
        domains = _domain_cache["domains"]
    else:
        try:
            resp = requests.get(_FIREBASE_URL, timeout=5)
            resp.raise_for_status()
            raw = resp.json()
            domains = {
                k: str(v).rstrip("/")
                for k, v in raw.items()
                if isinstance(v, (str, int, float)) and str(v).strip()
            }
            _domain_cache["domains"] = domains
            _domain_cache["ts"] = now
        except Exception:
            domains = _domain_cache["domains"]
    for candidate in (key, key + "_url", key + "_domain"):
        if domains.get(candidate):
            return domains[candidate]
    return default


def _resolve(key, default):
    if _resolve_domain is not None:
        try:
            return _resolve_domain(key, default)
        except Exception:
            return default
    return _fallback_resolve_domain(key, default)


if _BaseSource is not None:
    _SourceBase = _BaseSource
else:  # minimal stand-in until the scaffold agent writes base.py
    class _SourceBase:  # type: ignore[no-redef]
        id = ""
        name = ""
        language = ""
        domain_key = ""
        default_url = ""

        @property
        def base_url(self):
            return _resolve(self.domain_key, self.default_url)


# ---------------------------------------------------------------------------
# generateVrf — exact port of AniSugeProvider.generateVrf
# ---------------------------------------------------------------------------

def _rc4(key, data):
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) & 0xFF
        s[i], s[j] = s[j], s[i]
    i = j = 0
    out = bytearray()
    for byte in data:
        i = (i + 1) & 0xFF
        j = (j + s[i]) & 0xFF
        s[i], s[j] = s[j], s[i]
        out.append(byte ^ s[(s[i] + s[j]) & 0xFF])
    return bytes(out)


def _shift_charcode(text):
    return bytes(
        (ord(ch) + _SHIFT[r % 8]) & 0xFF for r, ch in enumerate(text)
    )


def _b64_urlsafe_nopad(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _rot13(text):
    return codecs.encode(text, "rot_13")


def generate_vrf(value):
    """URLEncoder.encode -> RC4(key ysJhV6U27FVIjjuk) -> b64 urlsafe ->
    shiftCharcode -> b64 urlsafe -> ROT13. Exact port of generateVrf."""
    encoded = quote_plus(str(value), encoding="utf-8").replace("+", "%20")
    rc4_bytes = _rc4(_VRF_KEY, encoded.encode("utf-8"))
    b64 = base64.urlsafe_b64encode(rc4_bytes).decode("ascii")
    shifted = _shift_charcode(b64)
    b64_shifted = base64.urlsafe_b64encode(shifted).decode("ascii")
    return _rot13(b64_shifted)


# ---------------------------------------------------------------------------
# Dean Edwards p.a.c.k.e.r unpack (KwikExtractor.getAndUnpack equivalent)
# ---------------------------------------------------------------------------

_BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def _to_base36(num):
    if num == 0:
        return "0"
    out = ""
    while num:
        num, rem = divmod(num, 36)
        out = _BASE36[rem] + out
    return out


_PACKED_RE = re.compile(
    r"\}\('(.*)',\s*(\d+),\s*(\d+),\s*'(.*?)'\.split\('\|'\)",
    re.DOTALL,
)


def unpack_packed(script):
    """Unpack a ``function(p,a,c,k,e,d)`` packed script; None if not packed."""
    if "function(p,a,c,k,e,d)" not in script:
        return None
    m = _PACKED_RE.search(script)
    if not m:
        return None
    payload, radix, count, keywords = m.groups()
    try:
        radix = int(radix)
        count = int(count)
    except ValueError:
        return None
    payload = payload.replace("\\'", "'").replace("\\\\", "\\")
    keywords = keywords.replace("\\'", "'").split("|")
    if radix != 36:
        return None
    result = payload
    for i in range(count - 1, -1, -1):
        if i < len(keywords) and keywords[i]:
            result = re.sub(
                r"\b" + _to_base36(i) + r"\b",
                lambda _m, word=keywords[i]: word,
                result,
            )
    return result


# ---------------------------------------------------------------------------
# Pahe / Kwik resolvers
# ---------------------------------------------------------------------------

def resolve_kwik_url(pahe_url, session):
    """PaheDownloadResolver: Pahe page -> workers.dev redirector -> Kwik URL."""
    try:
        resp = session.get(pahe_url, headers={"User-Agent": UA_131}, timeout=15)
        resp.raise_for_status()
    except Exception:
        return None
    page = resp.text
    base = None
    m = re.search(r"""const\s+url\s*=\s*"(https?://[^"]+)\"""", page)
    if m:
        base = m.group(1)
    else:
        m = re.search(r'"(https?://[^"]*workers\.dev[^"]*)"', page)
        if m:
            base = m.group(1)
    if not base:
        return None
    last = pahe_url.rstrip("/").rsplit("/", 1)[-1]
    redirector = base.rstrip("/") + "/" + last
    try:
        resp = session.get(redirector, timeout=15, allow_redirects=False)
    except Exception:
        return None
    loc = resp.headers.get("location") or resp.headers.get("Location")
    if loc and loc.startswith("http"):
        return loc
    return None


def resolve_kwik(kwik_url, referer, session):
    """KwikExtractor.resolve -> (play_url, kwik_page_url) or None.

    Unpacks the packed player script; if it holds ``source = "..."`` use
    it, else POST the form token (up to 10 tries) until a 302 Location.
    This is the only POST in the AniSuge flow.
    """
    headers = {"User-Agent": UA_131, "Referer": referer or "https://kwik.cx"}
    try:
        resp = session.get(kwik_url, headers=headers, timeout=20)
        resp.raise_for_status()
    except Exception:
        return None
    html = resp.text
    page_url = resp.url or kwik_url

    unpacked = None
    try:
        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script"):
            data = script.string or ""
            if "function(p,a,c,k,e,d)" in data:
                unpacked = unpack_packed(data)
                if unpacked:
                    break
    except Exception:
        unpacked = None

    if unpacked:
        m = re.search(r"""source\s*=\s*["']([^"']+)["']""", unpacked)
        if m and m.group(1).startswith("http"):
            return m.group(1), page_url
        action_m = re.search(r"""action="([^"]+)\"""", unpacked)
        token_m = re.search(r"""value="([^"]+)\"""", unpacked)
        if action_m and token_m:
            action, token = action_m.group(1), token_m.group(1)
            code, location = 419, ""
            tries = 0
            while code != 302 and tries < 10:
                try:
                    r = session.post(
                        action,
                        data={"_token": token},
                        headers={"User-Agent": UA_131, "Referer": page_url},
                        timeout=20,
                        allow_redirects=False,
                    )
                    code = r.status_code
                    if code == 302:
                        location = r.headers.get("location") or r.headers.get("Location") or ""
                except Exception:
                    pass
                tries += 1
            if location.startswith("http"):
                return location, page_url

    # Some mirrors inline the source without a packer.
    m = re.search(r"""source\s*=\s*["']([^"']+)["']""", html)
    if m and m.group(1).startswith("http") and (
        ".m3u8" in m.group(1) or ".mp4" in m.group(1)
    ):
        return m.group(1), page_url
    return None


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------

class AniSugeSource(_SourceBase):
    id = "anisuge"
    name = "AniSuge"
    language = "english"
    domain_key = "anisuge"
    default_url = "https://anisuge.tv"

    def __init__(self):
        self.session = requests.Session()
        self._streams = []
        self._subtitles = []

    # -- helpers ---------------------------------------------------------
    def _headers(self, referer=None):
        return {
            "User-Agent": UA_124,
            "Referer": referer or (self.base_url + "/"),
        }

    def _get(self, url, headers=None, timeout=30):
        resp = self.session.get(url, headers=headers or self._headers(), timeout=timeout)
        resp.raise_for_status()
        return resp

    def _abs(self, href):
        if not href:
            return None
        if href.startswith("http"):
            return href
        return urljoin(self.base_url + "/", href.lstrip("/"))

    def _parse_items(self, soup):
        items = []
        for item in soup.select(".item"):
            try:
                if item.name == "a":
                    a = item
                else:
                    a = item.select_one("a[href]")
                if a is None:
                    continue
                href = a.get("href")
                if not href:
                    continue
                title_el = item.select_one(".name")
                title = (
                    title_el.get_text(strip=True)
                    if title_el
                    else a.get_text(strip=True)
                ) or "Unknown"
                img = item.select_one("img")
                poster = None
                if img is not None:
                    poster = img.get("data-src") or img.get("src") or None
                    if poster and not poster.strip():
                        poster = None
                items.append(
                    {
                        "id": self._abs(href),
                        "title": title,
                        "poster": self._abs(poster) if poster else None,
                        "year": None,
                        "type": "anime",
                        "audio": [],
                        "source": self.id,
                    }
                )
            except Exception:
                continue
        return items

    # -- home / search ---------------------------------------------------
    def home(self, section, page=1):
        if page > 1:
            return []
        mapping = {"trending": "recent", "popular": "mostview", "latest": "added"}
        key = mapping.get(section, section)
        try:
            resp = self._get(self.base_url + "/home")
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception:
            return []
        section_el = None
        if key == "recent":
            for sec in soup.find_all("section"):
                h2 = sec.find("h2")
                if h2 and "Recently Updated" in h2.get_text():
                    section_el = sec
                    break
            if section_el is None:
                section_el = soup.select_one("section.pt-4")
        elif key == "added":
            section_el = soup.select_one("section.added")
        elif key == "complete":
            section_el = soup.select_one("section.complete")
        elif key == "mostview":
            section_el = soup.select_one("section.mostview")
        if section_el is None:
            return []
        return self._parse_items(section_el)

    def search(self, query, page=1):
        try:
            encoded = quote_plus(query, encoding="utf-8")
            resp = self._get(self.base_url + "/filter?keyword=" + encoded)
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception:
            return []
        return self._parse_items(soup)

    # -- details ---------------------------------------------------------
    def details(self, item_id):
        url = item_id if item_id.startswith("http") else self._abs(item_id)
        try:
            resp = self._get(url)
            html = resp.text
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            return None

        data_id = None
        watch_wrap = soup.select_one(".watch-wrap")
        if watch_wrap is not None:
            data_id = watch_wrap.get("data-id") or None
        if not data_id:
            m = re.search(r"mangaId\s*=\s*(\d+)", html)
            if m:
                data_id = m.group(1)
        if not data_id:
            return None

        title_el = soup.select_one(".maindata h1.title")
        if title_el is not None:
            title = title_el.get_text(strip=True)
        else:
            og = soup.select_one("meta[property='og:title']")
            title = (
                (og.get("content") or "").split(" Episode")[0].strip()
                if og is not None
                else "Unknown"
            ) or "Unknown"

        og_img = soup.select_one("meta[property='og:image']")
        poster = og_img.get("content") if og_img is not None else None

        banner = None
        media_bg = soup.select_one(".media-bg")
        if media_bg is not None:
            style = media_bg.get("style") or ""
            m = re.search(r"""url\(['"]?([^'")]+)['"]?\)""", style)
            if m:
                banner = m.group(1)

        plot = None
        full = soup.select_one(".description .full")
        if full is not None:
            plot = full.get_text(strip=True)
        else:
            desc = soup.select_one(".description")
            if desc is not None:
                plot = desc.get_text().replace("more+", "").strip() or None
            if not plot:
                og_desc = soup.select_one("meta[property='og:description']")
                if og_desc is not None:
                    plot = (og_desc.get("content") or "").strip() or None

        year = None
        for div in soup.select(".meta div"):
            text = div.get_text()
            if "premiered:" in text.lower() or "aired:" in text.lower():
                m = re.search(r"\b(19\d\d|20\d\d)\b", text)
                if m:
                    year = int(m.group(1))

        genres = [
            a.get_text(strip=True)
            for a in soup.select(".meta a[href*='/genre/'], .data a[href*='/genre/']")
            if a.get_text(strip=True)
        ]

        sub_eps, dub_eps = [], []
        try:
            vrf = generate_vrf(data_id)
            eps_url = (
                self.base_url + "/ajax/episode/list/" + data_id + "?vrf=" + vrf
            )
            eps_resp = self.session.get(
                eps_url,
                headers={
                    "User-Agent": UA_124,
                    "Referer": url,
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=30,
            )
            eps_resp.raise_for_status()
            eps_json = eps_resp.json()
            eps_html = eps_json.get("result") if isinstance(eps_json, dict) else None
            if eps_html:
                eps_soup = BeautifulSoup(eps_html, "html.parser")
                for link in eps_soup.select("a[data-ids]"):
                    try:
                        text = link.get_text(strip=True)
                        try:
                            ep_num = int(text)
                        except ValueError:
                            try:
                                ep_num = int(link.get("data-slug") or "")
                            except ValueError:
                                digits = re.sub(r"\D", "", link.get("data-num") or "")
                                ep_num = int(digits) if digits else 1
                        ep_title = link.get("data-num") or ""
                        if not ep_title.strip():
                            ep_title = "Episode %d" % ep_num
                        data_ids = link.get("data-ids") or ""
                        mal_id = (link.get("data-mal") or "").strip()
                        slug = link.get("data-slug") or str(ep_num)
                        timestamp = (link.get("data-timestamp") or "").strip()
                        has_sub = link.get("data-sub") == "1"
                        has_dub = link.get("data-dub") == "1"
                        base = self.base_url
                        if has_sub:
                            sub_eps.append(
                                {
                                    "number": ep_num,
                                    "title": ep_title,
                                    "data": "|".join(
                                        [
                                            base,
                                            data_id,
                                            str(ep_num),
                                            data_ids,
                                            mal_id,
                                            slug,
                                            timestamp,
                                            "sub",
                                        ]
                                    ),
                                }
                            )
                        if has_dub:
                            dub_eps.append(
                                {
                                    "number": ep_num,
                                    "title": ep_title,
                                    "data": "|".join(
                                        [
                                            base,
                                            data_id,
                                            str(ep_num),
                                            data_ids,
                                            mal_id,
                                            slug,
                                            timestamp,
                                            "dub",
                                        ]
                                    ),
                                }
                            )
                    except Exception:
                        continue
        except Exception:
            pass

        seasons = []
        if sub_eps:
            seasons.append({"number": 1, "name": "Season 1", "episodes": sub_eps})
        if dub_eps:
            seasons.append(
                {
                    "number": 2 if sub_eps else 1,
                    "name": "Dubbed",
                    "episodes": dub_eps,
                }
            )
        if not seasons:
            seasons = [{"number": 1, "name": "Season 1", "episodes": []}]

        return {
            "id": url,
            "title": title,
            "poster": poster,
            "banner": banner,
            "plot": plot,
            "genres": genres,
            "year": year,
            "status": None,
            "score": None,
            # This module does not distinguish movies (list items also
            # hardcode "anime"); audio follows the sub/dub episode split.
            "type": "anime",
            "audio": (["sub"] if sub_eps else []) + (["dub"] if dub_eps else []),
            "seasons": seasons,
        }

    # -- streams ---------------------------------------------------------
    def streams(self, episode_data):
        self._streams = []
        self._subtitles = []
        if not episode_data or not episode_data.startswith("https://"):
            return {"streams": [], "subtitles": []}
        parts = episode_data.split("|")
        if len(parts) < 5:
            return {"streams": [], "subtitles": []}
        base_url = parts[0]
        ep_num = parts[2]
        data_ids = parts[3]
        mal_id = parts[4] if len(parts) > 4 else ""
        slug = parts[5] if len(parts) > 5 else ep_num
        timestamp = parts[6] if len(parts) > 6 else ""
        selected_type = parts[-1] if parts[-1] in ("sub", "dub") else "sub"

        # The two resolver paths are independent (both parse only from
        # episode_data) — run them concurrently. Sequentially they cost
        # 1.86s + 0.98s = 2.84s cold; in parallel the resolve is ~1.9s,
        # which is what keeps a cold first frame under the 5s target.
        # (Measured on the server 2026-11-18; requests.Session use from
        # two threads is safe — urllib3 pools are thread-safe, and the
        # Flask app already calls these singletons concurrently.)
        jobs = [lambda: self._load_legacy_servers(base_url, data_ids, selected_type)]
        if mal_id.strip() and timestamp.strip():
            jobs.append(lambda: self._load_mapper_sources(
                base_url, mal_id.strip(), slug, timestamp.strip(), selected_type
            ))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futs = [pool.submit(j) for j in jobs]
            for f in futs:
                try:
                    f.result()
                except Exception:
                    pass

        seen = set()
        streams = []
        for s in self._streams:
            # Dedup on the URL path: megaplay signs the same variant with a
            # fresh token each call, so two providers resolving to the same
            # variant yield near-identical URLs differing only in ?token=.
            key = s["url"].split("?", 1)[0]
            if key in seen:
                continue
            seen.add(key)
            streams.append(s)
        streams.sort(key=lambda s: -(s["quality"] or 0))
        return {"streams": streams, "subtitles": self._subtitles}

    def _add_stream(self, name, url, quality=None, stream_type="m3u8",
                    headers=None, proxy=True):
        # proxy=True by default: these CDNs (MegaPlay/crystaldrift, kwik,
        # gogoanime) 403 direct browser fetches (Cloudflare hotlink check
        # needs the site Referer); the website must play them via
        # /api/proxy, which forwards the headers (reanime.py precedent).
        if not url or not url.startswith("http"):
            return
        self._streams.append(
            {
                "name": name,
                "url": url,
                "quality": quality,
                "type": stream_type,
                "headers": headers or {},
                "proxy": proxy,
            }
        )

    def _load_legacy_servers(self, base_url, data_ids, selected_type):
        headers = {
            "User-Agent": UA_124,
            "Referer": base_url + "/watch/",
            "X-Requested-With": "XMLHttpRequest",
        }
        resp = self.session.get(
            base_url + "/ajax/server/list?servers=" + quote(data_ids, safe=""),
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        html = payload.get("result") if isinstance(payload, dict) else None
        if not html:
            return False
        soup = BeautifulSoup(html, "html.parser")
        wanted = _SUB_TYPES if selected_type == "sub" else _DUB_TYPES
        servers = []
        for st in soup.select(".server-type"):
            if (st.get("data-type") or "").strip().lower() not in wanted:
                continue
            for s in st.select(".server"):
                link_id = s.get("data-link-id")
                if not link_id:
                    continue
                span = s.select_one("span")
                name = span.get_text(strip=True) if span else "Unknown Server"
                servers.append((name, link_id))
        if not servers:
            return False
        loaded = False
        for server_name, link_id in servers:
            try:
                info = self.session.get(
                    base_url + "/ajax/server?get=" + quote(link_id, safe=""),
                    headers=headers,
                    timeout=30,
                )
                info.raise_for_status()
                data = info.json()
                result = data.get("result") if isinstance(data, dict) else None
                player_url = None
                if isinstance(result, dict):
                    player_url = result.get("url")
                elif isinstance(result, str):
                    player_url = result
                if player_url and self._resolve_embed(
                    player_url, base_url, server_name, selected_type
                ):
                    loaded = True
            except Exception:
                continue
        return loaded

    def _load_mapper_sources(self, base_url, mal_id, slug, timestamp, selected_type):
        try:
            resp = self.session.get(
                MAPPER_API + mal_id + "/" + slug + "/" + timestamp,
                headers={"User-Agent": UA_131, "Accept": "application/json"},
                timeout=15,
            )
            resp.raise_for_status()
            providers = resp.json()
        except Exception:
            return False
        if not isinstance(providers, dict):
            return False
        headers = {
            "User-Agent": UA_124,
            "Referer": base_url + "/watch/",
            "X-Requested-With": "XMLHttpRequest",
        }
        loaded = False
        for provider_key, pair in providers.items():
            if not isinstance(pair, dict):
                continue
            display = self._display_provider_name(provider_key)
            entry = pair.get(selected_type)
            if not isinstance(entry, dict):
                continue
            stream_url = entry.get("url")
            if stream_url:
                embed_url = None
                try:
                    info = self.session.get(
                        base_url + "/ajax/server?get=" + quote(stream_url, safe=""),
                        headers=headers,
                        timeout=30,
                    )
                    info.raise_for_status()
                    data = info.json()
                    result = data.get("result") if isinstance(data, dict) else None
                    if isinstance(result, dict):
                        embed_url = result.get("url")
                    elif isinstance(result, str):
                        embed_url = result
                except Exception:
                    embed_url = None
                if not embed_url:
                    embed_url = stream_url
                try:
                    if self._resolve_embed(embed_url, base_url, display, selected_type):
                        loaded = True
                except Exception:
                    pass
            downloads = entry.get("download") or {}
            if isinstance(downloads, dict):
                for quality_label, pahe_url in downloads.items():
                    try:
                        if not isinstance(pahe_url, str) or not pahe_url.startswith("http"):
                            continue
                        kwik_url = resolve_kwik_url(pahe_url, self.session)
                        if not kwik_url:
                            continue
                        resolved = resolve_kwik(kwik_url, pahe_url, self.session)
                        if not resolved:
                            continue
                        play_url, kwik_page = resolved
                        quality = None
                        digits = re.sub(r"\D", "", quality_label)
                        if digits:
                            quality = int(digits)
                        self._add_stream(
                            "%s %s %s" % (self.name, display, quality_label),
                            play_url,
                            quality=quality,
                            stream_type="m3u8" if ".m3u8" in play_url else "video",
                            headers={"Referer": kwik_page},
                        )
                        loaded = True
                    except Exception:
                        continue
        return loaded

    @staticmethod
    def _display_provider_name(key):
        low = key.lower()
        if low == "gogoanime":
            return "Vidstream"
        if low == "anivibe":
            return "vibe-Stream"
        if low == "animepahe":
            return "Kiwi-Stream"
        return key[:1].upper() + key[1:] if key else key

    def _resolve_embed(self, player_url, base_url, server_name, audio_type):
        if "plyr.php#" in player_url:
            frag = player_url.split("#", 1)[1].split("#", 1)[0]
            try:
                padded = frag + "=" * (-len(frag) % 4)
                decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
            except (binascii.Error, ValueError):
                decoded = ""
            if decoded.strip():
                self._add_stream(
                    "%s %s" % (self.name, server_name),
                    decoded.strip(),
                    stream_type="m3u8" if ".m3u8" in decoded else "video",
                    headers={"Referer": "https://gogoanime.me.uk/"},
                )
                return True

        host_m = re.search(r"https?://([^/]+)", player_url or "")
        host = host_m.group(1).lower() if host_m else ""
        if any(h in host for h in _MEGAPLAY_HOSTS):
            if _resolve_megaplay is not None:
                try:
                    streams, subtitles = _resolve_megaplay(
                        player_url, base_url + "/"
                    )
                    for s in streams or []:
                        self._streams.append(s)
                    for sub in subtitles or []:
                        self._subtitles.append(sub)
                    return bool(streams)
                except Exception:
                    pass
            # Fallback (megaplay extractor unavailable): plain GET + .m3u8 regex.
            return self._regex_embed(player_url, base_url, server_name)

        # Generic embed: best-effort plain GET + .m3u8/.mp4 regex.
        # (The extension's WebView fallback has no server-side equivalent.)
        return self._regex_embed(player_url, base_url, server_name)

    def _regex_embed(self, player_url, base_url, server_name):
        try:
            resp = self.session.get(
                player_url,
                headers={"User-Agent": UA_124, "Referer": base_url + "/"},
                timeout=15,
            )
            resp.raise_for_status()
            html = resp.text
        except Exception:
            return False
        m = _M3U8_RE.search(html)
        if m:
            self._add_stream(
                "%s %s" % (self.name, server_name),
                m.group(0),
                stream_type="m3u8",
                headers={"Referer": player_url},
            )
            return True
        m = _MP4_RE.search(html)
        if m:
            self._add_stream(
                "%s %s" % (self.name, server_name),
                m.group(0),
                stream_type="video",
                headers={"Referer": player_url},
            )
            return True
        return False


# Backwards-friendly alias (module is also importable as a source class).
Source = AniSugeSource
