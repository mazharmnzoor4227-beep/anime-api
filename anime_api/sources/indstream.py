"""IndStream source — Hindi-dub movies via keyless public APIs.

No single site is scraped for the catalogue: this is the minimal port
of the IndStream provider in the CINEMORA Android app (itself a port
of the IndStream CloudStream plugin in dipender98/Indflix, GPL-3.0).

* ``search`` — the IMDb suggestion API
  ``https://v2.sg.media-imdb.com/suggestion/<first-letter>/<query>.json``
  (no key). Only ``"feature"`` (movie) entries are kept; item ``id``
  is ``"imdb:<tt-id>"``.
* ``home`` — Cinemeta catalogs (no key)
  ``https://v3-cinemeta.strem.io/catalog/movie/top.json`` (``trending``
  and ``latest``) and ``.../catalog/movie/popular.json``
  (``popular``). Items carry the IMDb id, TMDB poster, year, rating.
* ``details`` — Cinemeta meta
  ``https://v3-cinemeta.strem.io/meta/movie/<imdb>.json`` (title,
  poster, background, description, genres, year, rating, and
  ``moviedb_id``). Episode ``data`` is a JSON string ``{"tmdb":
  <tmdb id>, "imdb": <tt-id>, "title": <title>}``. A small in-memory
  cache of cards seen via search/home lets details() still build a
  page when the Cinemeta meta call fails.
* ``streams`` — the Vidly embed
  ``https://vidly.pro/embed/movie/<tmdb id>``: the embed page carries
  ``.m3u8`` master playlist URLs; each master is fetched once to
  learn the best variant height (quality) and subtitle renditions.
  Masters below 720p are dropped (the plugin's quality floor).
  Verified live 2026-11-18 from the Mumbai server: Vidly master
  fetches with ``#EXTM3U`` and carries a Hindi audio rendition
  (``LANGUAGE="hin", NAME="Hindi"``) alongside Telugu/Tamil — the
  Hindi dub is a selectable audio track in the HLS playlist.
  The plugin's other flagship server (VidLink, libsodium token) and
  Vidrift (no ``.m3u8`` in its embed page for the probe title) are
  NOT ported — see the Cinemora provider's scope note.
"""

import json
import re
from urllib.parse import quote_plus, urljoin

from anime_api.http import BROWSER_UA, get, get_json
from anime_api.sources.base import Source

_IMDB_SUGGEST = "https://v2.sg.media-imdb.com/suggestion"
_CINEMETA = "https://v3-cinemeta.strem.io"
_VIDLY_ORIGIN = "https://vidly.pro"

_M3U8_RE = re.compile(
    r"https?://[^\"'<>\s\\]+\.m3u8[^\"'<>\s\\]*", re.IGNORECASE)
_STREAM_INF_RE = re.compile(
    r"#EXT-X-STREAM-INF:[^\n]*RESOLUTION=\d+x(\d+)[^\n]*\n([^\n#][^\n]*)")
_SUB_MEDIA_RE = re.compile(r"#EXT-X-MEDIA:TYPE=SUBTITLES[^\n]*")


class IndStream(Source):
    id = "indstream"
    name = "IndStream"
    language = "hindi"
    domain_key = ""  # keyless public APIs; no Firebase key
    default_url = "https://www.themoviedb.org"  # identity only
    media_type = "movie"

    def __init__(self):
        self._card_cache = {}

    # -- helpers -----------------------------------------------------------

    def _remember(self, card):
        m = re.search(r"tt\d{7,8}", card.get("id") or "")
        if m and len(self._card_cache) < 200:
            self._card_cache[m.group(0)] = card

    @staticmethod
    def _imdb_of(card_id):
        m = re.search(r"tt\d{7,8}", card_id or "")
        return m.group(0) if m else None

    # -- Source API --------------------------------------------------------

    def search(self, query, page=1):
        if not query:
            return []
        q = query.strip()
        first = q[0].lower() if q[0].isalpha() else "a"
        try:
            data = get_json(
                "%s/%s/%s.json" % (_IMDB_SUGGEST, first, quote_plus(q)),
                timeout=30)
        except Exception:
            return []
        out = []
        for m in (data or {}).get("d") or []:
            try:
                kind = m.get("q") or ""
                if kind and kind != "feature":
                    continue
                imdb = m.get("id") or ""
                if not imdb.startswith("tt"):
                    continue
                title = (m.get("l") or "").strip()
                if not title:
                    continue
                poster = None
                img = m.get("i") or {}
                if isinstance(img, dict):
                    poster = img.get("imageUrl") or None
                year = m.get("y")
                try:
                    year = int(year) if year else None
                except (TypeError, ValueError):
                    year = None
                out.append({
                    "id": "imdb:%s" % imdb,
                    "title": title,
                    "poster": poster,
                    "year": year,
                    "type": "movie",
                    "audio": ["dub"],
                    "source": self.id,
                })
            except Exception:
                continue
        for card in out:
            self._remember(card)
        return out[:12]

    def home(self, section, page=1):
        if page != 1:
            return []
        url = "%s/catalog/movie/%s.json" % (
            _CINEMETA, "popular" if section == "popular" else "top")
        try:
            data = get_json(url, timeout=30)
        except Exception:
            return []
        out = []
        for m in (data or {}).get("metas") or []:
            try:
                imdb = m.get("id") or ""
                if not imdb.startswith("tt"):
                    continue
                title = (m.get("name") or "").strip()
                if not title:
                    continue
                year = None
                try:
                    year = int(str(m.get("year") or "")[:4])
                except (TypeError, ValueError):
                    year = None
                rating = None
                try:
                    rating = float(m.get("imdbRating"))
                except (TypeError, ValueError):
                    rating = None
                out.append({
                    "id": "imdb:%s" % imdb,
                    "title": title,
                    "poster": m.get("poster") or None,
                    "year": year,
                    "type": "movie",
                    "audio": ["dub"],
                    "source": self.id,
                    "_rating": rating,
                })
            except Exception:
                continue
        for card in out:
            self._remember(card)
        for card in out:
            card.pop("_rating", None)
        return out

    def details(self, item_id):
        imdb = self._imdb_of(item_id)
        if not imdb:
            return {"error": "movie not found"}
        cached = self._card_cache.get(imdb)
        meta = None
        try:
            data = get_json("%s/meta/movie/%s.json" % (_CINEMETA, imdb),
                            timeout=30)
            meta = (data or {}).get("meta") or None
        except Exception:
            meta = None
        title = None
        tmdb_id = None
        year = None
        poster = None
        banner = None
        plot = None
        genres = []
        score = None
        if meta:
            title = (meta.get("name") or "").strip() or None
            try:
                tmdb_id = int(meta.get("moviedb_id"))
            except (TypeError, ValueError):
                tmdb_id = None
            try:
                year = int(str(meta.get("year") or "")[:4])
            except (TypeError, ValueError):
                year = None
            poster = meta.get("poster") or None
            banner = meta.get("background") or None
            plot = meta.get("description") or None
            genres = [str(g) for g in (meta.get("genre") or []) if g]
            try:
                score = float(meta.get("imdbRating"))
            except (TypeError, ValueError):
                score = None
        if not title:
            title = (cached or {}).get("title") or None
        if not title:
            return {"error": "movie not found"}
        if year is None:
            year = (cached or {}).get("year")
        if poster is None:
            poster = (cached or {}).get("poster")
        if score is None:
            score = (cached or {}).get("_rating")
        episode_data = json.dumps({
            "tmdb": tmdb_id, "imdb": imdb, "title": title})
        return {
            "id": item_id,
            "title": title,
            "poster": poster,
            "banner": banner,
            "plot": plot,
            "genres": genres,
            "year": year,
            "status": None,
            "score": score,
            "type": "movie",
            "audio": ["dub"],
            "seasons": [{
                "number": 1,
                "name": "Movie",
                "episodes": [{"number": 1, "title": title,
                              "data": episode_data}],
            }],
        }

    def streams(self, episode_data):
        try:
            parsed = json.loads(str(episode_data or ""))
            tmdb_id = int(parsed.get("tmdb") or 0)
        except Exception:
            return {"streams": [], "subtitles": []}
        if not tmdb_id:
            return {"streams": [], "subtitles": []}
        embed_url = "%s/embed/movie/%d" % (_VIDLY_ORIGIN, tmdb_id)
        try:
            html = get(embed_url, headers={"Referer": _VIDLY_ORIGIN + "/"},
                       timeout=20).text
        except Exception:
            return {"streams": [], "subtitles": []}
        urls = sorted(set(_M3U8_RE.findall(
            html.replace("\\/", "/").replace("\\u0026", "&")
                .replace("\\u003d", "=").replace("\\u003f", "?"))))
        streams, subtitles = [], []
        for url in urls[:2]:
            quality = None
            subs = []
            try:
                master = get(url, headers={"Referer": _VIDLY_ORIGIN + "/"},
                             timeout=20).text
                if "#EXTM3U" not in master:
                    continue
                heights = [int(h[0]) for h in
                           _STREAM_INF_RE.findall(master)]
                quality = max(heights) if heights else 0
                if quality and quality < 720:
                    continue
                for line in _SUB_MEDIA_RE.findall(master):
                    uri = re.search(r'URI="([^"]+)"', line)
                    lang = re.search(r'LANGUAGE="([^"]+)"', line)
                    label = re.search(r'NAME="([^"]+)"', line)
                    if uri:
                        subs.append({
                            "label": (label.group(1) if label
                                      else lang.group(1) if lang else "sub"),
                            "url": urljoin(url, uri.group(1)),
                            "referer": _VIDLY_ORIGIN + "/",
                        })
            except Exception:
                # Master fetch failed — still hand back the master URL;
                # the browser/proxy can try it (quality unknown).
                pass
            streams.append({
                "name": "IndStream Vidly",
                "url": url,
                "quality": quality,
                "type": "m3u8",
                # Browser UA in headers (same reason as the Multimovies
                # Cineverse stream: hosts 403 python-requests UA).
                "headers": {"Referer": _VIDLY_ORIGIN + "/",
                            "User-Agent": BROWSER_UA},
                "proxy": True,
                "label": "Vidly (Hindi audio)",
            })
            subtitles.extend(subs)
        streams.sort(key=lambda s: -(s.get("quality") or 0))
        return {"streams": streams, "subtitles": subtitles}
