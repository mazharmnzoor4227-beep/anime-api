"""MovieBox source — Hollywood / Hindi-dub movies via the MovieBox app backend.

MovieBox itself is proprietary (COIHUB Technology) — there is no official
"MovieBox extension". This source talks to the same backend the MovieBox
Android app uses (``api3.aoneroom.com`` native BFF + the H5 play endpoint
on ``movie-box.co``), following the protocol documented by two MIT
reference implementations:

* ``walterwhite-69/Moviebox-API`` — signed native requests (``x-client-token``,
  ``x-tr-signature`` HMAC-MD5), bootstrap token from the ``x-user`` response
  header, H5 ``/wefeed-h5api-bff/subject/play`` for full streams.
* ``ferelking242/watchtower-extensions`` (``moviebox_app.js`` v2.0.0) —
  native ``play-info`` first, H5 fallback, ``dubsList`` handling, caption
  endpoints.

Why NOT Simatwa's ``moviebox-api`` library (Option A as first named):
it was evaluated live on 2026-11-18 and there is nothing to run — the
GitHub repo (``simatwa/moviebox-api``) is unreachable (``git clone``
prompts for credentials from both the sandbox and the server: private,
renamed or deleted), and the only PyPI release (0.6.0, 2026-07-13) is a
1,665-byte wheel whose ``__init__.py`` is 58 bytes —
``def main(): print("Hello from moviebox-api!")`` — with no search,
stream or API code at all, and it requires Python >=3.14 (the server
runs 3.12). So the port implements the MovieBox protocol natively in
this module (same self-contained pattern as every other source), using
the live-verified app backend above — the same catalogue as the
MovieBox app itself.

Endpoints used (all public, no login, guest Bearer token bootstrapped
per instance, 25-min TTL):

* bootstrap — ``GET https://apig.inmoviebox.com/wefeed-mobile-bff/tab/ranking-list?tabId=0&categoryType=4516404531735022304&page=1&perPage=1``
  with signed headers; the ``x-user`` response header is JSON ``{"token": ...}``.
* ``search`` — ``POST {native}/wefeed-mobile-bff/subject-api/search``
  ``{"keyword", "page", "perPage"}``. Items carry ``subject`` dicts with
  ``subjectId`` / ``title`` / ``subjectType`` (1=movie, 2=series) /
  ``releaseDate`` / ``imdbRatingValue`` / ``genre`` / ``cover.url`` /
  ``detailPath`` (movies only) / ``language``.
* ``home`` — ``POST {native}/wefeed-mobile-bff/subject-api/trending/v2``
  (``trending``) and ``GET {native}/wefeed-mobile-bff/tab/ranking-list``
  with a ``categoryType`` (``popular`` = TOP Movies, ``latest`` = New
  Release, ``category="hollywood"`` = Hollywood, ``"bollywood"`` =
  Bollywood). Ranking-list ``data.subjects`` are full subject dicts.
* ``details`` — ``GET {native}/wefeed-mobile-bff/subject-api/get?subjectId=``
  plus ``season-info``. Episode ``data`` is a JSON string
  ``{"sid": <subjectId>, "se": <season>, "ep": <episode>,
  "dp": <detailPath>}``. ``details()`` also returns ``dubs`` —
  ``[{"subject_id", "lang_name", "language"}]`` — the same title's other
  audio versions as their own subjectIds (e.g. the Hindi-dub subject).
* ``streams`` — ``GET https://movie-box.co/wefeed-h5api-bff/subject/play``
  (fallback ``https://h5-api.aoneroom.com/...``) with the Bearer token.
  Returns full-length MP4 files (360p ~500MB, 480p ~535MB, 720p ~1.4GB,
  1080p ~2.3GB for The Avengers, each with a ``?sign=`` + ``&t=`` token)
  plus a DASH manifest (``dash[].url`` + ``signCookie``).

Verified live 2026-11-18 from the Mumbai server (see TEST-REPORT.md):

* search "avengers" -> 10 items, first "The Avengers"; "avengers hindi"
  -> "The Avengers [Hindi]" first (Hindi-dub subjects exist as their own
  titles). Hollywood ranking -> 18 items, first "Avengers Endgame: Encore
  [Hindi]". New Release -> 20, TOP Movies -> 20, Bollywood -> 20.
* H5 play for a movie -> 4 MP4s + 1 DASH. The 1080p MP4 HEADs 200 with a
  ``Referer: https://movie-box.co/`` (429 WITHOUT it — hotlink protection)
  and a Range GET of bytes 0-262143 returns 206 with a real ``ftyp`` box,
  so the first frame plays through ``/api/proxy`` (streams are
  ``proxy: true`` with that Referer + browser UA in ``headers``).
* Captions work: ``get-stream-captions`` + ``get-ext-captions`` return SRT
  URLs (English verified) with CloudFront ``Policy``/``Signature`` query
  params; they are returned with a ``referer`` hint so ``/api/streams``
  rewrites them through ``/api/proxy``.

HINDI-DUB TRUTH TABLE (live, 2026-11-18 — do not overpromise):

* Hollywood Hindi-dub MOVIES: YES, playable. "The Avengers [Hindi]"
  H5 play -> 2 MP4s (480p 435MB, 720p 1.1GB); Range GET 206 + ``ftyp``.
  Details list a "Hindi dub" entry with its own subjectId (same for
  "Avengers: Infinity War [Hindi]").
* Hindi-dub K-DRAMA / C-DRAMA: subjects EXIST ("Boys Over Flowers
  [Hindi]", "Crash Landing on You [Hindi]") but are series (type 2)
  and series do NOT play via the guest path (see below) — Hindi-dub
  K-drama still comes from CKDub / DramaCool, not MovieBox.
* PAKISTANI dramas: subjects EXIST ("Tere Bin" Urdu/Pakistan, "Dar E
  Nijaat [Urdu]", "Mitti De Baway", "Nashtar") but are series (type 2)
  and do NOT play via the guest path — Pakistani dramas still come
  from the PKDramas source, not MovieBox.
* MovieBox is EXTRA Hollywood/Hindi-dub-movie breadth. Hindi-dub
  coverage overall still comes primarily from AnimeWorld, Vegamovies,
  Multimovies, IndStream and the other Hindi sources.

What does NOT work (deliberate limits, not bugs to paper over):

* MOVIES ONLY (``media_type="movie"``, ``subjectType == 1`` filter).
  Series (``subjectType == 2``) are filtered out of search/home because
  the H5 play endpoint answers ``{"hasResource": false, "streams": [],
  "dash": [], "hls": []}`` for every series probed (Squid Game [Hindi]
  S1E1/E3, Breaking Bad [Hindi] S1E1 — also with a ``/tv/detail`` Referer
  and on ``h5-api.aoneroom.com``). The series subjects DO carry
  ``resourceDetectors`` (community uploads), but the guest H5 play path
  does not resolve them. ``details()`` still lists a series' seasons if
  called directly, but ``streams()`` returns empty for it.
* The native ``play-info`` endpoint is a TRAP and is never used here: it
  returns one 824,720-byte MP4 (``duration: 23``) at the SAME URL for
  every title — a 23-second preview clip, not the title. The H5 play
  endpoint is the only full-length path.
* DASH is NOT emitted in v1.4: the DASH manifest host (``sbcdnw...``)
  answered HTTP 429 on every fetch from the server IP (with and without
  the ``signCookie``, even after a 20s pause), while the MP4 CDN serves
  fine with a Referer. MP4 covers 360p-1080p, so nothing is lost for
  playback. The ``signCookie`` itself is still parsed (see
  ``_policy_resource``) for a future DASH path.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from urllib.parse import urlencode

import requests

from anime_api.http import BROWSER_UA, get_json
from anime_api.sources.base import Source

_NATIVE_BASE = "https://api3.aoneroom.com"
_H5_DOMAINS = ("https://movie-box.co", "https://h5-api.aoneroom.com")
_BOOTSTRAP_URL = (
    "https://apig.inmoviebox.com/wefeed-mobile-bff/tab/ranking-list"
    "?tabId=0&categoryType=4516404531735022304&page=1&perPage=1"
)
_MODERN_UA = (
    "com.community.mbox.in/50020130 (Linux; U; Android 14; en_IN; "
    "Pixel 8; Build/UD1A.230803.041; Cronet/145.0.7582.0)"
)
_WEB_UA = (
    "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/154.0.0.0 Mobile Safari/537.36"
)
_TOKEN_TTL_SECONDS = 25 * 60

# Signing secret, as published in walterwhite-69/Moviebox-API (MIT):
# outer base64 -> inner base64 -> HMAC-MD5 key bytes.
_SECRET_OUTER_B64 = "NzZpUmwwN3MweFNOOWpxbUVXQXQ3OUVCSlp1bElRSXNWNjRGWnIyTw=="

# ranking-list categoryType values (from the live categoryList).
_CATEGORY_TYPES = {
    "top": "9167640870324258216",       # TOP Movies
    "new": "1488104699998914056",       # New Release
    "hollywood": "8019599703232971616",
    "bollywood": "414907768299210008",
    "cinema": "5692654647815587592",
    "south": "3859721901924910512",     # South Indian
}

_QUALITY_RE = re.compile(r"(\d{3,4})")


def _b64decode(text):
    text = text.replace("-", "+").replace("_", "/")
    text += "=" * (-len(text) % 4)
    return base64.b64decode(text)


def _signing_key():
    return _b64decode(_b64decode(_SECRET_OUTER_B64).decode("utf-8"))


_SIGNING_KEY = _signing_key()


def _quality_of(resolutions):
    """Best quality int from a resolutions string like "1080,720,480"."""
    found = [int(q) for q in _QUALITY_RE.findall(str(resolutions or ""))]
    return max(found) if found else None


def _policy_resource(sign_cookie):
    """Derive the DASH index URL from a signCookie (walterwhite helper).

    The Edge-Cache-Cookie carries a base64 urlprefix; the CloudFront
    Policy carries a JSON Resource. Either resolves to the manifest dir.
    Kept for a future DASH path — v1.4 does not emit DASH (429, see
    the module docstring), but the parse is unit-tested.
    """
    if not sign_cookie:
        return None
    m = re.search(r"Edge-Cache-Cookie=urlprefix=([^:;\s]+)", sign_cookie)
    if m:
        try:
            decoded = _b64decode(m.group(1)).decode("utf-8").rstrip("/")
            return decoded + "/index.mpd"
        except Exception:
            pass
    m = re.search(r"CloudFront-Policy=([^;]+)", sign_cookie)
    if m:
        raw = m.group(1)
        for variant in ("cf", "std"):
            try:
                b = (raw.replace("-", "+").replace("_", "=")
                     if variant == "cf" else raw)
                b += "=" * (-len(b) % 4)
                data = json.loads(base64.b64decode(b).decode("utf-8"))
                for stmt in data.get("Statement", []):
                    res = stmt.get("Resource")
                    if res:
                        return res.rstrip("*").rstrip("/") + "/index.mpd"
            except Exception:
                pass
    return None


def _subject_to_item(sub):
    """Native subject dict -> INTERFACE.md item dict (movies only)."""
    if not isinstance(sub, dict):
        return None
    if sub.get("subjectType") not in (1, None):
        # Series (2) and other types have no playable stream via the
        # guest H5 path — never surface them as results.
        return None
    if sub.get("hasResource") is False:
        # No playable resource at all: the H5 play endpoint answers
        # ``hasResource: false`` + empty streams for these titles
        # (e.g. "Avengers" 6891610990048693368, "Captain America:
        # The First Avenger - The Transformation" 4744425413315887552,
        # "Avengers: Doom of the World" 6288431937149617232 — all with
        # an empty detailUrl). Never surface them as results, or the
        # app shows a dead Play button (v1.4.1).
        return None
    sid = sub.get("subjectId")
    if sid is None:
        return None
    title = (sub.get("title") or "").strip()
    if not title:
        return None
    cover = sub.get("cover") or {}
    poster = cover.get("url") if isinstance(cover, dict) else None
    year = None
    rel = str(sub.get("releaseDate") or "")[:4]
    try:
        year = int(rel) if rel.isdigit() else None
    except (TypeError, ValueError):
        year = None
    lang = (sub.get("language") or "").lower()
    audio = ["dub"] if ("hindi" in title.lower()
                        or "hindi" in lang) else []
    return {
        "id": str(sid),
        "title": title,
        "poster": poster,
        "year": year,
        "type": "movie",
        "audio": audio,
        "source": "moviebox",
    }


class MovieBox(Source):
    id = "moviebox"
    name = "MovieBox"
    language = "hindi"
    domain_key = ""  # native API hosts are fixed; no Firebase key
    default_url = "https://movie-box.co"
    media_type = "movie"
    categories = ("hollywood", "bollywood", "movies")

    def __init__(self):
        self._device_id = secrets.token_hex(16)
        self._token = None
        self._token_at = 0.0

    # -- auth --------------------------------------------------------------

    def _client_info(self):
        return json.dumps({
            "package_name": "com.community.mbox.in",
            "version_name": "4.0.03.0920.03",
            "version_code": 50020130,
            "os": "android",
            "os_version": "14",
            "device_id": self._device_id,
            "install_store": "official",
            "gaid": "1b2212c1-dadf-43c3-a0c8-bd6ce48ae22d",
            "brand": "Google",
            "model": "Pixel 8",
            "system_language": "en",
            "net": "NETWORK_WIFI",
            "region": "IN",
            "timezone": "Asia/Calcutta",
            "sp_code": "",
        }, separators=(",", ":"))

    @staticmethod
    def _canonical(method, accept, content_type, url, body, ts):
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        path = parsed.path or "/"
        if parsed.query:
            pairs = []
            for segment in parsed.query.split("&"):
                if not segment:
                    continue
                pieces = segment.split("=", 1)
                pairs.append((pieces[0],
                              pieces[1] if len(pieces) > 1 else ""))
            pairs.sort(key=lambda kv: kv[0])
            canonical_url = path + "?" + "&".join(
                "%s=%s" % kv for kv in pairs)
        else:
            canonical_url = path
        body_bytes = body.encode("utf-8") if body is not None else None
        return "\n".join([
            method.upper(),
            accept or "",
            content_type or "",
            str(len(body_bytes)) if body_bytes else "",
            str(ts),
            hashlib.md5(body_bytes[:102400]).hexdigest()
            if body_bytes else "",
            canonical_url,
        ])

    def _signed_headers(self, method, url, body=None, token=None):
        ts = int(time.time() * 1000)
        canonical = self._canonical(
            method, "application/json", "application/json", url, body, ts)
        digest = hmac.new(_SIGNING_KEY, canonical.encode("utf-8"),
                          hashlib.md5).digest()
        sig = base64.b64encode(digest).decode("ascii")
        headers = {
            "User-Agent": _MODERN_UA,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Connection": "keep-alive",
            "X-Client-Token": "%d,%s" % (
                ts, hashlib.md5(str(ts)[::-1].encode("utf-8")).hexdigest()),
            "X-Tr-Signature": "%d|2|%s" % (ts, sig),
            "X-Client-Info": self._client_info(),
            "X-Client-Status": "0",
        }
        if token:
            headers["Authorization"] = "Bearer " + token
        return headers

    def _bootstrap(self, force=False):
        """Guest Bearer token from the bootstrap call's x-user header."""
        if (self._token and not force
                and time.monotonic() - self._token_at < _TOKEN_TTL_SECONDS):
            return self._token
        try:
            from anime_api.http import get
            resp = get(_BOOTSTRAP_URL,
                       headers=self._signed_headers("GET", _BOOTSTRAP_URL),
                       timeout=20)
            x_user = resp.headers.get("x-user")
            if not x_user:
                return None
            token = json.loads(x_user).get("token")
            if token:
                self._token = token
                self._token_at = time.monotonic()
                return token
        except Exception:
            return None
        return None

    def _api(self, method, path, body=None, retry=True):
        """Signed native-BFF call; re-bootstraps once on 401/441."""
        token = self._bootstrap()
        if not token:
            raise RuntimeError("moviebox bootstrap failed (no token)")
        url = _NATIVE_BASE + path
        body_str = (json.dumps(body, separators=(",", ":"))
                    if body is not None else None)
        headers = self._signed_headers(method, url, body_str, token)
        try:
            if method.upper() == "POST":
                # Send the EXACT compact string that was signed.
                # http.post_json re-serialises with default separators
                # (spaces after "," and ":"), which changes the wire
                # body and the API answers 407 "Signature invalid"
                # (verified live 2026-11-18: data=compact -> 200,
                # json= -> 407).
                resp = requests.post(
                    url,
                    data=body_str.encode("utf-8") if body_str else None,
                    headers=headers, timeout=25)
                resp.raise_for_status()
                data = resp.json()
            else:
                data = get_json(url, headers=headers, timeout=25)
        except Exception as exc:
            status = getattr(getattr(exc, "response", None),
                             "status_code", None)
            if retry and status in (401, 407, 441):
                self._bootstrap(force=True)
                return self._api(method, path, body, retry=False)
            raise
        if isinstance(data, dict) and data.get("code") not in (0, None):
            raise RuntimeError("moviebox api code %s" % data.get("code"))
        return data or {}

    # -- Source API --------------------------------------------------------

    def search(self, query, page=1):
        if not query:
            return []
        try:
            data = self._api("POST", "/wefeed-mobile-bff/subject-api/search",
                             {"keyword": query.strip(), "page": page,
                              "perPage": 20})
        except Exception:
            return []
        raw = (data.get("data") or {}).get("items", []) or \
            (data.get("data") or {}).get("list", [])
        items = []
        for entry in raw:
            sub = entry.get("subject") if isinstance(entry, dict) else None
            item = _subject_to_item(sub or entry)
            if item:
                items.append(item)
        return items

    def home(self, section, page=1, category=None):
        try:
            if category in ("hollywood", "bollywood"):
                return self._ranking(_CATEGORY_TYPES[category], page)
            if category == "movies":
                return self._ranking(_CATEGORY_TYPES["top"], page)
            if section == "trending":
                data = self._api(
                    "POST", "/wefeed-mobile-bff/subject-api/trending/v2",
                    {"page": page} if page and page > 1 else {})
                raw = (data.get("data") or {}).get("items", [])
                items = []
                for entry in raw:
                    sub = (entry.get("subject") if isinstance(entry, dict)
                           else None)
                    item = _subject_to_item(sub or entry)
                    if item:
                        items.append(item)
                return items
            if section == "popular":
                return self._ranking(_CATEGORY_TYPES["top"], page)
            return self._ranking(_CATEGORY_TYPES["new"], page)
        except Exception:
            return []

    def _ranking(self, category_type, page=1):
        url = ("/wefeed-mobile-bff/tab/ranking-list?tabId=0"
               "&categoryType=%s&page=%d&perPage=20"
               % (category_type, page or 1))
        data = self._api("GET", url)
        raw = (data.get("data") or {}).get("subjects", [])
        items = []
        for sub in raw:
            item = _subject_to_item(sub)
            if item:
                items.append(item)
        return items

    def details(self, item_id):
        sid = str(item_id or "").strip()
        if not sid:
            return {"error": "movie not found"}
        try:
            data = self._api(
                "GET", "/wefeed-mobile-bff/subject-api/get?subjectId=%s"
                % sid)
            seasons_data = self._api(
                "GET", "/wefeed-mobile-bff/subject-api/season-info"
                "?subjectId=%s" % sid)
        except Exception:
            return {"error": "movie not found"}
        d = data.get("data") or {}
        title = (d.get("title") or "").strip()
        if not title:
            return {"error": "movie not found"}
        if d.get("hasResource") is False:
            # Unplayable title (see _subject_to_item): details still
            # answers, but there is no stream — say so instead of
            # listing an episode the app cannot play (v1.4.1).
            return {"error": "movie has no playable resource"}
        cover = d.get("cover") or {}
        poster = cover.get("url") if isinstance(cover, dict) else None
        year = None
        rel = str(d.get("releaseDate") or "")[:4]
        try:
            year = int(rel) if rel.isdigit() else None
        except (TypeError, ValueError):
            year = None
        score = None
        try:
            score = float(d.get("imdbRatingValue"))
        except (TypeError, ValueError):
            score = None
        genres = [g.strip() for g in str(d.get("genre") or "").split(",")
                  if g.strip()]
        detail_url = d.get("detailUrl") or ""
        detail_path = (detail_url.rstrip("/").split("/")[-1]
                       if "/" in detail_url else "")
        dubs = []
        for dub in d.get("dubs") or []:
            if isinstance(dub, dict) and dub.get("subjectId"):
                dubs.append({
                    "subject_id": str(dub.get("subjectId")),
                    "lang_name": dub.get("lanName") or dub.get("language"),
                    "language": dub.get("language"),
                })
        is_movie = d.get("subjectType") in (1, None)
        if is_movie:
            episodes = [{
                "number": 1,
                "title": title,
                "data": json.dumps({"sid": sid, "se": 0, "ep": 0,
                                    "dp": detail_path}),
            }]
            seasons = [{"number": 1, "name": "Movie",
                        "episodes": episodes}]
        else:
            # Series: seasons listed, but streams() returns empty for
            # them (guest H5 play has no series resource — see module
            # docstring). Search/home never surface series.
            seasons = []
            for s in (seasons_data.get("data") or {}).get("seasons", []):
                try:
                    se = int(s.get("se") or 1)
                    max_ep = int(s.get("maxEp") or 0)
                except (TypeError, ValueError):
                    continue
                if max_ep <= 0:
                    continue
                seasons.append({
                    "number": se,
                    "name": "Season %d" % se,
                    "episodes": [{
                        "number": ep,
                        "title": "Episode %d" % ep,
                        "data": json.dumps({"sid": sid, "se": se,
                                            "ep": ep,
                                            "dp": detail_path}),
                    } for ep in range(1, max_ep + 1)],
                })
            if not seasons:
                seasons = [{"number": 1, "name": "Season 1", "episodes": [{
                    "number": 1, "title": title,
                    "data": json.dumps({"sid": sid, "se": 1, "ep": 1,
                                        "dp": detail_path}),
                }]}]
        result = {
            "id": sid,
            "title": title,
            "poster": poster,
            "banner": poster,
            "plot": (d.get("description") or "").strip() or None,
            "genres": genres,
            "year": year,
            "status": "completed" if is_movie else None,
            "score": score,
            "type": "movie" if is_movie else "anime",
            "audio": (["dub"] if ("hindi" in title.lower()
                                  or "hindi" in str(d.get("language") or "")
                                  .lower()) else []),
            "seasons": seasons,
        }
        if dubs:
            result["dubs"] = dubs
        return result

    def streams(self, episode_data):
        try:
            parsed = json.loads(str(episode_data or ""))
            sid = str(parsed.get("sid") or "")
            se = int(parsed.get("se") or 0)
            ep = int(parsed.get("ep") or 0)
            detail_path = parsed.get("dp") or ""
        except Exception:
            return {"streams": [], "subtitles": []}
        if not sid:
            return {"streams": [], "subtitles": []}
        token = self._bootstrap()
        if not token:
            return {"streams": [], "subtitles": []}
        play = None
        for domain in _H5_DOMAINS:
            try:
                query = urlencode({
                    "subjectId": sid, "se": se, "ep": ep,
                    "detailPath": detail_path,
                    "streamSignType": 1,
                    "supportCodecs[hevc]": 1,
                    "supportCodecs[h264]": 1,
                })
                url = ("%s/wefeed-h5api-bff/subject/play?%s"
                       % (domain, query))
                referer = ("%s/movies/%s?id=%s&type=/movie/detail"
                           "&detailSe=&detailEp=&lang=en"
                           % (domain, detail_path, sid)) if detail_path \
                    else domain + "/"
                headers = {
                    "User-Agent": _WEB_UA,
                    "Referer": referer,
                    "Accept": "application/json",
                    "X-Client-Info": '{"timezone":"Asia/Calcutta"}',
                    "X-Request-Lang": "en",
                    "X-Vip-Restrict": "0",
                    "X-No-High-Risk-Restrict": "0",
                    "X-Source": "moviebox",
                    "Authorization": "Bearer " + token,
                }
                play = get_json(url, headers=headers, timeout=15)
                if isinstance(play, dict) and play.get("code") == 0:
                    break
                play = None
            except Exception:
                continue
        if not play:
            return {"streams": [], "subtitles": []}
        data = play.get("data") or {}
        streams = []
        for st in data.get("streams") or []:
            url = st.get("url") or ""
            if not url or ".mp4" not in url:
                continue
            quality = _quality_of(st.get("resolutions"))
            streams.append({
                "name": "MovieBox",
                "url": url,
                "quality": quality,
                "type": "video",
                # The MP4 CDN 429s without a Referer (verified live) —
                # play through /api/proxy, which forwards Referer + UA.
                "headers": {"Referer": "https://movie-box.co/",
                            "User-Agent": BROWSER_UA},
                "proxy": True,
                "label": "MovieBox %s" % (
                    "%dp" % quality if quality else "Movie"),
            })
        streams.sort(key=lambda s: -(s.get("quality") or 0))
        seen, unique = set(), []
        for s in streams:
            if s["url"] not in seen:
                seen.add(s["url"])
                unique.append(s)
        subtitles = self._captions(sid, ep, data)
        return {"streams": unique, "subtitles": subtitles}

    def _captions(self, sid, ep, play_data):
        """English (+ other) SRT captions for a resolved stream."""
        # The H5 play payload's first stream id is the caption key.
        raw = (play_data.get("streams") or [{}])[0] if play_data else {}
        stream_id = raw.get("id") if isinstance(raw, dict) else None
        subs, seen = [], set()
        if stream_id:
            for path in (
                    "/wefeed-mobile-bff/subject-api/get-stream-captions"
                    "?subjectId=%s&streamId=%s" % (sid, stream_id),
                    "/wefeed-mobile-bff/subject-api/get-ext-captions"
                    "?subjectId=%s&resourceId=%s&episode=%d"
                    % (sid, stream_id, ep)):
                try:
                    data = self._api("GET", path)
                    caps = (data.get("data") or {}).get("extCaptions") \
                        or (data.get("data") or {}).get("captions") or []
                    if isinstance(data.get("data"), list):
                        caps = data.get("data")
                    for cap in caps:
                        if not isinstance(cap, dict):
                            continue
                        url = cap.get("url") or ""
                        if not url or url in seen:
                            continue
                        seen.add(url)
                        subs.append({
                            "label": cap.get("lanName")
                            or cap.get("language") or "sub",
                            "url": url,
                            "referer": "https://movie-box.co/",
                        })
                except Exception:
                    continue
        return subs
