"""Multimovies source — Hindi / dual-audio movies (+ series).

Site: ``https://m1.multimovies.courses`` (live domain via the Firebase
map key ``multimovies_url``). Ported from the Multimovies provider in
the CINEMORA Android app (itself a port of the Multimovies CloudStream
plugin in dipender98/Indflix, GPL-3.0).

Endpoints used (all public, no login):

* ``search`` — ``GET {host}/api/search?q=<query>&limit=12`` returns
  JSON ``{"results": [{id, title, type, year, rating, quality,
  poster, url}]}`` (``url`` is relative, ``/movie/<slug>-<id>``).
  Fallback: the ``GET {host}/search?q=<query>`` HTML listing
  (``article.poster-card``). Only ``type == "movie"`` hits are kept.
* ``home`` — poster-cards on ``GET {host}/`` (``latest``),
  ``/genre/bollywood-movies`` (``popular``) and ``/genre/action``
  (``trending``). Page > 1 appends ``page/<n>/``.
* ``details`` — ``GET <detail URL>``. Title/poster/plot/genres/year/
  rating from the page; the watch servers come from the
  ``watchConfig.initialServers`` JS object plus
  ``button.server-chip[data-url]`` buttons. Movies get one episode;
  series get seasons from ``div.cinejoy-ep-card`` links. Episode
  ``data`` is a JSON string ``{"page": <detail url>, "servers":
  [{"n": <name>, "u": <embed url>}]}``.
* ``streams`` — each server embed is resolved in parallel. The
  Cineverse server (``modiplay`` embed) is the one that resolves to a
  direct file: embed -> ``/proxy.php?...`` iframe -> the player page
  carries ``var src="/stream_proxy.php?url=<vibuxer master>&tok=..."``
  — that proxied master playlist (``#EXTM3U``) is returned as an
  ``m3u8`` stream (``proxy: true``; its variant/audio URIs are
  themselves ``stream_proxy.php`` URLs, so ``/api/proxy`` rewrites
  them). The master is fetched once to learn the best variant height
  (quality) and subtitle renditions. Other servers are generic JS
  player shells: direct ``.m3u8``/``.mp4`` links are scraped when
  present (plus one iframe hop); otherwise the server embed URL
  itself is returned as an ``embed`` stream — the site's own player
  surface, played in an ``<iframe>`` exactly like the source site
  does (same contract as AnimeDekho's embed streams).
  Verified live 2026-11-18 from the Mumbai server: search
  "avengers" 14 results (first "Avengers: Endgame", 2019); detail
  carries 6 server chips; Cineverse stream_proxy master fetches
  with ``#EXTM3U`` and a Hindi audio rendition (``NAME="हिन्दी",
  LANGUAGE="hi", DEFAULT=YES``).
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from anime_api.http import BROWSER_UA, get, get_json
from anime_api.sources.base import Source

_YEAR_RE = re.compile(r"\d{4}")
_FILE_RE = re.compile(
    r"https?://[^\"'<>\s\\]+\.(?:m3u8|mp4)(?:\?[^\"'<>\s\\]*)?",
    re.IGNORECASE,
)
_STREAM_INF_RE = re.compile(
    r"#EXT-X-STREAM-INF:[^\n]*RESOLUTION=\d+x(\d+)[^\n]*\n([^\n#][^\n]*)"
)
_SUB_MEDIA_RE = re.compile(r"#EXT-X-MEDIA:TYPE=SUBTITLES[^\n]*")

_HOME_URLS = {
    "latest": "/",
    "trending": "/genre/action",
    "popular": "/genre/bollywood-movies",
}


def _abs_url(url, base):
    if not url:
        return None
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return base.rstrip("/") + url
    if url.startswith("http"):
        return url
    return None


def _quality_of(label):
    if not label:
        return None
    m = re.search(r"(?i)\b(\d{3,4})p\b", label)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    if re.search(r"(?i)\b4K\b", label):
        return 2160
    return None


def _strip_affix(raw):
    t = (raw or "").strip()
    t = re.sub(r"(?i)\s*[|:-]\s*Multimovies\s*$", "", t).strip()
    return t or (raw or "").strip()


class Multimovies(Source):
    id = "multimovies"
    name = "Multimovies"
    language = "hindi"
    domain_key = "multimovies_url"
    default_url = "https://m1.multimovies.courses"
    media_type = "movie"

    # -- fetching ----------------------------------------------------------

    def _soup(self, url):
        resp = get(url, timeout=30)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")

    def _is_mm_url(self, url):
        return bool(url) and ("/movie/" in url or "/series/" in url
                              or "/watch/" in url or "multimovies" in url)

    def _parse_cards(self, soup):
        base = self.base_url
        items, seen = [], set()
        for el in soup.select("article.poster-card"):
            try:
                a = el.select_one("a.poster-art[href], div.poster-caption a[href]")
                if a is None:
                    continue
                href = _abs_url(a.get("href"), base)
                if not href or not self._is_mm_url(href) or href in seen:
                    continue
                title = ""
                cap = el.select_one("div.poster-caption a")
                if cap:
                    title = cap.get_text(strip=True)
                if not title:
                    img = el.select_one("img[alt]")
                    title = img.get("alt", "").strip() if img else ""
                if not title:
                    continue
                seen.add(href)
                img = el.select_one("a.poster-art img") or el.select_one("img")
                poster = None
                if img is not None:
                    poster = _abs_url(img.get("src"), base)
                meta = el.select_one("p.poster-meta")
                meta_text = meta.get_text(" ", strip=True) if meta else ""
                year = None
                m = _YEAR_RE.search(meta_text)
                if m:
                    try:
                        year = int(m.group(0))
                    except ValueError:
                        year = None
                items.append({
                    "id": href,
                    "title": _strip_affix(title),
                    "poster": poster,
                    "year": year,
                    "type": "movie" if "/movie/" in href else "anime",
                    "audio": ["dub"],
                    "source": self.id,
                })
            except Exception:
                continue
        return items

    # -- Source API --------------------------------------------------------

    def search(self, query, page=1):
        if not query:
            return []
        base = self.base_url
        q = quote_plus(query.strip())
        try:
            data = get_json("%s/api/search?q=%s&limit=12" % (base, q),
                            timeout=30)
            items = []
            for raw in (data or {}).get("results") or []:
                try:
                    if raw.get("type") != "movie":
                        continue
                    title = (raw.get("title") or "").strip()
                    url = _abs_url(raw.get("url"), base)
                    if not title or not url:
                        continue
                    year = raw.get("year")
                    try:
                        year = int(year) if year else None
                    except (TypeError, ValueError):
                        year = None
                    items.append({
                        "id": url,
                        "title": _strip_affix(title),
                        "poster": _abs_url(raw.get("poster"), base),
                        "year": year,
                        "type": "movie",
                        "audio": ["dub"],
                        "source": self.id,
                    })
                except Exception:
                    continue
            if items:
                return items[:10]
        except Exception:
            pass
        try:
            soup = self._soup("%s/search?q=%s" % (base, q))
            return [it for it in self._parse_cards(soup)
                    if it.get("type") == "movie"][:10]
        except Exception:
            return []

    def home(self, section, page=1):
        try:
            path = _HOME_URLS.get(section, _HOME_URLS["latest"])
            url = self.base_url + path
            if page > 1:
                url = url + "page/%d/" % page
            soup = self._soup(url)
            return self._parse_cards(soup)
        except Exception:
            return []

    def details(self, item_id):
        try:
            soup = self._soup(item_id)
        except Exception:
            return {"error": "movie not found"}
        real_url = item_id
        title = ""
        h1 = soup.select_one(
            "h1.cinejoy-detail-title, div.sheader h1, h1")
        if h1 is not None:
            title = h1.get_text(strip=True)
        if not title:
            og = soup.select_one('meta[property="og:title"]')
            title = og.get("content", "").strip() if og else ""
        title = _strip_affix(
            re.sub(r"(?i)\s*-\s*MultiMovies.*$", "", title))
        if not title:
            return {"error": "movie not found"}
        poster = None
        og_img = soup.select_one('meta[property="og:image"]')
        if og_img and og_img.get("content"):
            poster = _abs_url(og_img.get("content"), self.base_url)
        plot = None
        overview = soup.select_one("p.cinejoy-detail-overview")
        if overview:
            plot = overview.get_text(" ", strip=True) or None
        genres = []
        g_el = soup.select_one("div.cinejoy-detail-genres")
        if g_el:
            genres = [g.strip() for g in re.split(r"[•,|]",
                                                   g_el.get_text(" ", strip=True))
                      if g.strip()]
        year = None
        meta = soup.select_one(".cinejoy-meta-pill")
        if meta is not None and meta.parent is not None:
            m = _YEAR_RE.search(meta.parent.get_text(" ", strip=True))
            if m:
                try:
                    year = int(m.group(0))
                except ValueError:
                    year = None
        score = None
        rating_el = soup.select_one(".cinejoy-score-pill")
        if rating_el:
            try:
                score = float(re.sub(r"[^\d.]", "",
                                     rating_el.get_text(strip=True)))
            except ValueError:
                score = None
        servers = self._parse_servers(soup)
        is_movie = ("/movie/" in real_url or "/watch/movie" in real_url
                    or ("/series/" not in real_url
                        and "/watch/tv" not in real_url))
        data = json.dumps({"page": real_url, "servers": servers})
        if is_movie:
            seasons = [{
                "number": 1,
                "name": "Movie",
                "episodes": [{"number": 1, "title": title, "data": data}],
            }]
        else:
            seasons = self._parse_series_seasons(soup, data)
            if not seasons:
                return {"error": "movie not found"}
        return {
            "id": item_id,
            "title": title,
            "poster": poster,
            "banner": poster,
            "plot": plot,
            "genres": genres,
            "year": year,
            "status": None,
            "score": score,
            "type": "movie" if is_movie else "anime",
            "audio": ["dub"],
            "seasons": seasons,
        }

    @staticmethod
    def _balanced_json(html, marker):
        """JSON object starting at ``marker`` (balanced-brace scan).

        A non-greedy ``\\{.*?\\}`` regex stops at the first nested ``}``
        (the end of the first server object), so scan braces instead.
        """
        start = html.find(marker)
        if start < 0:
            return None
        open_idx = html.find("{", start)
        if open_idx < 0:
            return None
        depth = 0
        in_str = False
        esc = False
        for i in range(open_idx, len(html)):
            ch = html[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(html[open_idx:i + 1])
                    except Exception:
                        return None
        return None

    def _parse_servers(self, soup):
        """watchConfig.initialServers + button.server-chip[data-url]."""
        servers = []
        html = str(soup)
        cfg = self._balanced_json(html, "watchConfig")
        tmdb = None
        if cfg:
            try:
                for o in cfg.get("initialServers") or []:
                    url = (o.get("url") or "").replace("\\/", "/").strip()
                    if url.startswith("http"):
                        servers.append({"n": (o.get("name") or "Server").strip()
                                        or "Server", "u": url})
            except Exception:
                pass
        for b in soup.select("button.server-chip[data-url]"):
            raw = (b.get("data-url") or "").strip().replace("&amp;", "&")
            if not raw.startswith("http"):
                continue
            name_el = b.select_one(".server-name")
            name = (name_el.get_text(strip=True) if name_el
                    else b.get("data-id", "").strip()) or "Server"
            servers.append({"n": name, "u": raw})
        # De-dupe; fill the {tmdbId} placeholder when a TMDB id is known.
        for s in servers:
            tmdb = tmdb or self._tmdb_of(s["u"])
        out, seen = [], set()
        for s in servers:
            url = s["u"]
            if tmdb and "{tmdbId}" in url:
                url = url.replace("{tmdbId}", tmdb)
            if url not in seen:
                seen.add(url)
                out.append({"n": s["n"], "u": url})
        return out

    @staticmethod
    def _tmdb_of(url):
        for pat in (r"[?&]id=(\d{2,10})", r"/(?:movie|tv)/(\d{2,10})",
                    r"/embed/(?:movie|tv)/(\d{2,10})"):
            m = re.search(pat, url or "")
            if m:
                return m.group(1)
        return None

    def _parse_series_seasons(self, soup, data):
        by_season = {}
        for i, card in enumerate(soup.select("div.cinejoy-ep-card")):
            try:
                link = card.select_one(
                    "a.cinejoy-ep-thumb-link[href], a.cinejoy-ep-name[href]")
                if link is None:
                    continue
                ep_url = _abs_url(link.get("href"), self.base_url)
                if not ep_url or not self._is_mm_url(ep_url):
                    continue
                m = re.search(r"/season/(\d+)", ep_url)
                season = int(m.group(1)) if m else 1
                m = re.search(r"/episode/(\d+)", ep_url)
                if m:
                    ep_num = int(m.group(1))
                else:
                    badge = card.select_one("span.cinejoy-ep-badge-num")
                    bm = re.search(r"\d+", badge.get_text() if badge else "")
                    ep_num = int(bm.group(0)) if bm else i + 1
                name_el = card.select_one("a.cinejoy-ep-name")
                ep_title = (name_el.get_text(strip=True) if name_el
                            else "Episode %d" % ep_num)
                by_season.setdefault(season, []).append({
                    "number": ep_num,
                    "title": ep_title,
                    "data": data,
                })
            except Exception:
                continue
        return [{"number": s, "name": "Season %d" % s,
                 "episodes": sorted(eps, key=lambda e: e["number"])}
                for s, eps in sorted(by_season.items())]

    # -- streams -----------------------------------------------------------

    def streams(self, episode_data):
        try:
            parsed = json.loads(str(episode_data or ""))
            page = parsed.get("page") or ""
            servers = parsed.get("servers") or []
        except Exception:
            return {"streams": [], "subtitles": []}
        if not servers:
            # No servers recorded: re-fetch the page once.
            try:
                soup = self._soup(page)
                servers = self._parse_servers(soup)
            except Exception:
                servers = []
        if not servers:
            return {"streams": [], "subtitles": []}
        streams, subtitles = [], []
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(
                lambda s: self._resolve_server(s, page), servers[:6]))
        for found_streams, found_subs in results:
            streams.extend(found_streams)
            subtitles.extend(found_subs)
        seen, unique = set(), []
        for s in streams:
            if s["url"] not in seen:
                seen.add(s["url"])
                unique.append(s)
        unique.sort(key=lambda s: (-(s.get("quality") or 0),
                                   0 if s.get("type") == "m3u8" else 1))
        return {"streams": unique, "subtitles": subtitles}

    def _resolve_server(self, server, page_url):
        """One server embed -> playable streams (+ subtitles)."""
        name, url = server.get("n") or "Server", server.get("u") or ""
        if not url:
            return [], []
        if ".m3u8" in url.lower() or url.lower().endswith(".mp4"):
            return [{
                "name": "Multimovies %s" % name,
                "url": url,
                "quality": _quality_of(url),
                "type": "m3u8" if ".m3u8" in url.lower() else "video",
                "headers": {"Referer": page_url},
                "proxy": True,
                "label": name,
            }], []
        if "modiplay" in url:
            found = self._resolve_cineverse(url, page_url, name)
            if found[0]:
                return found
        # Generic: direct file links on the embed page, else one iframe hop.
        try:
            html = get(url, headers={"Referer": page_url},
                       timeout=20).text
        except Exception:
            return self._embed_fallback(name, url, page_url)
        found = self._file_links(html, url, name, page_url)
        if found[0]:
            return found
        soup = BeautifulSoup(html, "lxml")
        iframe = soup.select_one("iframe[src]")
        if iframe is not None:
            inner_url = urljoin(url, iframe.get("src"))
            if inner_url and inner_url != url:
                try:
                    inner = get(inner_url, headers={"Referer": url},
                                timeout=20).text
                except Exception:
                    inner = ""
                found = self._file_links(inner, inner_url, name, url)
                if found[0]:
                    return found
        return self._embed_fallback(name, url, page_url)

    def _embed_fallback(self, name, url, page_url):
        """The server's own player page, played in an <iframe>."""
        return [{
            "name": "Multimovies %s" % name,
            "url": url,
            "quality": None,
            "type": "embed",
            "headers": {"Referer": page_url},
            "proxy": False,
            "label": "%s (player)" % name,
        }], []

    def _file_links(self, html, base_url, name, referer):
        if not html:
            return [], []
        out = []
        for file_url in sorted(set(_FILE_RE.findall(html.replace("\\/", "/")))):
            out.append({
                "name": "Multimovies %s" % name,
                "url": file_url,
                "quality": _quality_of(file_url),
                "type": "m3u8" if ".m3u8" in file_url.lower() else "video",
                "headers": {"Referer": referer},
                "proxy": True,
                "label": name,
            })
        return out, []

    def _resolve_cineverse(self, embed_url, page_url, name):
        """modiplay embed -> proxy.php player -> stream_proxy master m3u8."""
        try:
            html = get(embed_url, headers={"Referer": page_url},
                       timeout=20).text
        except Exception:
            return [], []
        soup = BeautifulSoup(html, "lxml")
        iframe = soup.select_one("iframe[src]")
        if iframe is None:
            return [], []
        proxy_url = urljoin(embed_url, iframe.get("src"))
        if not proxy_url:
            return [], []
        try:
            player = get(proxy_url, headers={"Referer": embed_url},
                         timeout=20).text
        except Exception:
            return [], []
        m = re.search(r'var src="([^"]*stream_proxy\.php[^"]*)"', player)
        if not m:
            return [], []
        # NOTE: unescape \/ to / (not "" — that would eat the leading
        # slash and leave a bare relative path _abs_url rejects).
        master_url = urljoin(
            proxy_url, m.group(1).replace("\\/", "/"))
        if not master_url:
            return [], []
        quality = None
        subtitles = []
        try:
            master = get(master_url, headers={"Referer": proxy_url},
                         timeout=20).text
            if "#EXTM3U" in master:
                heights = [int(h[0]) for h in
                           _STREAM_INF_RE.findall(master)]
                quality = max(heights) if heights else None
                for line in _SUB_MEDIA_RE.findall(master):
                    uri = re.search(r'URI="([^"]+)"', line)
                    lang = re.search(r'LANGUAGE="([^"]+)"', line)
                    label = re.search(r'NAME="([^"]+)"', line)
                    if uri:
                        subtitles.append({
                            "label": (label.group(1) if label
                                      else lang.group(1) if lang else "sub"),
                            "url": urljoin(master_url, uri.group(1)),
                            "referer": proxy_url,
                        })
            else:
                return [], []
        except Exception:
            # Master fetch failed — still hand back the master URL; the
            # browser/proxy can try it (quality unknown).
            pass
        return [{
            "name": "Multimovies %s" % name,
            "url": master_url,
            "quality": quality,
            "type": "m3u8",
            # Browser UA: the stream_proxy host 403s python-requests UA
            # (verified live 2026-11-18 — /api/proxy 502'd the master
            # until the UA was a browser's). /api/proxy now also
            # defaults to BROWSER_UA, this covers direct players.
            "headers": {"Referer": proxy_url, "User-Agent": BROWSER_UA},
            "proxy": True,
            "label": "%s (Hindi audio)" % name,
        }], subtitles
