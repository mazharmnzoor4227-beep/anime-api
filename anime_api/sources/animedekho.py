"""AnimeDekho source — "Anime Dekho" (Hindi).

Site: ``https://animedekho.tv`` (verified live 2026-11-18 from this sandbox;
``animedekho.app`` does not resolve, ``animedekho.co`` is the same brand's
older domain). WordPress site with a custom REST namespace
``/wp-json/dgt/v1/`` and a "dgt" theme. Hindi / Tamil / Telugu dubs of
anime + cartoons; this source exposes the Hindi-dub catalogue only
(every item is Hindi-dubbed or multi-audio with a Hindi track).

Endpoints used (all public, no login):

* ``search`` — ``GET {host}/wp-json/dgt/v1/suggest?q=<query>`` returns
  ``{"items": [{id, title, year, type, url, poster}]}`` (``type`` is
  ``"series"`` or ``"movie"``; posters are TMDB ``w342`` images).
* ``home`` — HTML rows on ``GET {host}/home/``:
  ``latest`` = "New series" + "New movies" rows, ``trending`` = "Top 10
  series today" + "Top 10 movies today" rows, ``popular`` = "Top rated"
  row. Cards are ``a.dgt-card[data-id]`` with ``.dgt-card__title``,
  ``.dgt-card__meta`` ("2012 · Series") and a lazy ``img[data-src]``.
  Pages > 1 use ``GET {host}/browse/?sort=<latest|popular|rating>&page=N``
  (``sort`` values: ``latest`` = recently added, ``popular`` = most
  viewed, ``rating`` = top rated).
* ``details`` — ``GET <detail URL>`` (``/series-hindi/<slug>/`` or
  ``/movie-hindi/<slug>/``). The page carries a ``data-snapshot`` JSON
  attribute with ``id`` (post id), ``type``, ``title``, ``poster``,
  ``backdrop``, ``year``, ``rating``, ``audio``, ``runtime``, ``genres``
  and ``total``. Plot comes from ``[class*=overview]``; status from
  ``.dgt-meta`` ("Returning Series" -> ongoing, "Ended" -> completed).
  Season tabs are ``.dgt-tab[data-season]``; episodes for a season come
  from ``GET {host}/wp-json/dgt/v1/episodes?series=<post_id>&season=<n>``
  returning ``{"episodes": [{id, season, episode, name, overview,
  air_date, still, url}]}``. Movies have no seasons: one episode with
  ``episode_id`` 0 (the site's own watch flow uses
  ``/movie-hindi/<slug>/?watch=1`` with ``data-term="0"``).
* ``streams`` — ``POST {host}/wp-json/dgt/v1/watch`` with JSON body
  ``{"post_id": <id>, "episode_id": <id>}`` and header
  ``X-WP-Nonce: <nonce>``. The nonce is scraped from the inline
  ``DGT={"rest": "...", "nonce": "..."}`` config on any site page; a
  POST without it returns ``{"gated": true, "sources": []}``. Response
  ``{"gated": false, "sources": [{kind, server, language, quality,
  embed, download, show_embed, rank_embed, ...}]}``. Only
  ``kind == "embed"`` sources with ``show_embed`` are returned.

Episode ``data`` format: JSON string
``{"post_id": <int>, "episode_id": <int>, "url": "<episode page URL>"}``.

Stream ``type`` is ``"embed"`` (new — see INTERFACE.md): the URL is the
site's own iframe embed page (``player.php?url=...``,
``aaa/myth/play2.php?id=...`` or ``/embed/<post>/<season>-<ep>``), which
itself iframes the video host (AbyssPlayer, Ravok, ...). Those hosts are
JWPlayer shells whose file URL is only assembled in JS, so there is no
direct .m3u8/.mp4 to return server-side; the website plays embed streams
in an ``<iframe>``, exactly like the source site does. ``proxy`` is False
(the embed pages are same-origin to animedekho.tv and need no proxy).
Download-kind sources (``download.php`` gate pages) are skipped — they are
not playable streams.
"""

import html as _html
import json
import re
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from anime_api.http import BROWSER_UA, get, get_json
from anime_api.sources.base import Source

_NONCE_RE = re.compile(r'DGT=\{"rest":"[^"]*","nonce":"([0-9a-f]+)"')
_NONCE_LOOSE_RE = re.compile(r'"nonce":"([0-9a-f]{10,})"')
_QUALITY_RE = re.compile(r"(\d{3,4})p", re.IGNORECASE)
_YEAR_RE = re.compile(r"(19|20)\d{2}")

# Rows on /home/ per section (matched by prefix on the row heading).
_HOME_ROWS = {
    "latest": ("New series", "New movies"),
    "trending": ("Top 10 series today", "Top 10 movies today"),
    "popular": ("Top rated",),
}
# /browse/ sort value per section (used for page > 1 and as fallback).
_BROWSE_SORT = {"latest": "latest", "trending": "popular", "popular": "rating"}


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


def _poster_of(img, base):
    if img is None:
        return None
    for attr in ("data-src", "data-lazy-src", "srcset", "src"):
        value = img.get(attr)
        if not value:
            continue
        if attr == "srcset":
            value = value.split(",")[0].split(" ")[0]
        if value.startswith("data:"):
            continue
        return _abs_url(value, base)
    return None


def _quality(server, language):
    for text in (language or "", server or ""):
        match = _QUALITY_RE.search(text or "")
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    return None


class AnimeDekho(Source):
    id = "animedekho"
    name = "AnimeDekho"
    language = "hindi"
    domain_key = ""  # not a CloudStream extension; no Firebase key
    default_url = "https://animedekho.tv"

    def __init__(self):
        self._nonce = None

    # -- fetching ----------------------------------------------------------

    def _soup(self, url):
        resp = get(url, timeout=30)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")

    def _nonce_value(self, refresh=False, url=None):
        """WP REST nonce from the inline DGT config (cached per instance).

        The homepage does NOT carry the ``dgt-store`` script (LiteSpeed
        cache serves a reduced page), but series/episode pages do — so the
        episode page (``url``, usually the watch referer) is tried first
        and the homepage only as a fallback.
        """
        if self._nonce and not refresh:
            return self._nonce
        candidates = []
        if url:
            candidates.append(url)
        candidates.append(self.base_url + "/")
        for cand in candidates:
            try:
                resp = get(cand, timeout=30)
                text = resp.text or ""
            except Exception:
                continue
            for rx in (_NONCE_RE, _NONCE_LOOSE_RE):
                match = rx.search(text)
                if match:
                    self._nonce = match.group(1)
                    return self._nonce
        return None

    def _parse_cards(self, soup):
        """a.dgt-card elements -> item dicts (deduped, order kept)."""
        base = self.base_url
        items, seen = [], set()
        for card in soup.select("a.dgt-card"):
            try:
                href = _abs_url(card.get("href"), base)
                if not href or href in seen:
                    continue
                title_el = card.select_one(".dgt-card__title")
                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue
                seen.add(href)
                meta = card.select_one(".dgt-card__meta")
                meta_text = meta.get_text(" ", strip=True) if meta else ""
                year = None
                match = _YEAR_RE.search(meta_text)
                if match:
                    try:
                        year = int(match.group(0))
                    except ValueError:
                        year = None
                items.append({
                    "id": href,
                    "title": title,
                    "poster": _poster_of(card.select_one("img"), base),
                    "year": year,
                    "type": "movie" if "/movie-" in href else "anime",
                    "audio": ["dub"],
                    "source": self.id,
                })
            except Exception:
                continue
        return items

    def _row_cards(self, soup, row_titles):
        items = []
        for row in soup.select(".dgt-row"):
            head = row.select_one(".dgt-row__head")
            heading = head.get_text(" ", strip=True) if head else ""
            if not any(heading.startswith(t) for t in row_titles):
                continue
            items.extend(self._parse_cards(row))
        return items

    # -- Source API --------------------------------------------------------

    def search(self, query, page=1):
        if not query or page != 1:  # suggest has no pagination
            return []
        try:
            url = "%s/wp-json/dgt/v1/suggest?q=%s" % (
                self.base_url, quote_plus(query))
            data = get_json(url, timeout=30)
        except Exception:
            return []
        items = []
        for raw in (data or {}).get("items") or []:
            try:
                href = _abs_url(raw.get("url"), self.base_url)
                title = (raw.get("title") or "").strip()
                if not href or not title:
                    continue
                year = raw.get("year")
                try:
                    year = int(year) if year else None
                except (TypeError, ValueError):
                    year = None
                items.append({
                    "id": href,
                    "title": title,
                    "poster": _abs_url(raw.get("poster"), self.base_url),
                    "year": year,
                    "type": "movie" if raw.get("type") == "movie" else "anime",
                    "audio": ["dub"],
                    "source": self.id,
                })
            except Exception:
                continue
        return items

    def home(self, section, page=1):
        try:
            if page <= 1:
                soup = self._soup(self.base_url + "/home/")
                return self._row_cards(
                    soup, _HOME_ROWS.get(section, _HOME_ROWS["latest"]))
            url = "%s/browse/?sort=%s&page=%d" % (
                self.base_url, _BROWSE_SORT.get(section, "latest"), page)
            soup = self._soup(url)
            return self._parse_cards(soup)
        except Exception:
            return []

    def details(self, item_id):
        try:
            soup = self._soup(item_id)
        except Exception:
            return {"error": "anime not found"}
        snapshot = None
        el = soup.select_one("[data-snapshot]")
        if el:
            try:
                snapshot = json.loads(_html.unescape(el.get("data-snapshot")))
            except Exception:
                snapshot = None
        title = ""
        if snapshot:
            title = str(snapshot.get("title") or "").strip()
        if not title:
            h1 = soup.select_one("h1")
            title = h1.get_text(strip=True) if h1 else ""
        if not title:
            return {"error": "anime not found"}
        poster = None
        banner = None
        year = None
        score = None
        genres = []
        post_id = None
        is_movie = "/movie-" in item_id
        if snapshot:
            poster = _abs_url(snapshot.get("poster"), self.base_url)
            banner = _abs_url(snapshot.get("backdrop"), self.base_url)
            try:
                year = int(snapshot.get("year")) if snapshot.get("year") else None
            except (TypeError, ValueError):
                year = None
            try:
                score = float(snapshot.get("rating")) if snapshot.get("rating") else None
            except (TypeError, ValueError):
                score = None
            if score is not None:
                score = round(score, 2)
            genres = [str(g) for g in (snapshot.get("genres") or []) if g]
            try:
                post_id = int(snapshot.get("id")) if snapshot.get("id") else None
            except (TypeError, ValueError):
                post_id = None
            if snapshot.get("type") == "movie":
                is_movie = True
        if post_id is None:
            post_el = soup.select_one("[data-post]")
            try:
                post_id = int(post_el.get("data-post")) if post_el else None
            except (TypeError, ValueError):
                post_id = None
        plot = None
        overview = soup.select_one("[class*=overview]")
        if overview:
            plot = overview.get_text(" ", strip=True) or None
        status = None
        meta_el = soup.select_one(".dgt-meta")
        meta_text = meta_el.get_text(" ", strip=True) if meta_el else ""
        if "Returning Series" in meta_text or "Ongoing" in meta_text:
            status = "ongoing"
        elif "Ended" in meta_text or "Completed" in meta_text:
            status = "completed"
        if is_movie:
            status = "completed"
        seasons = []
        if not is_movie and post_id:
            season_numbers = []
            for tab in soup.select(".dgt-tab[data-season]"):
                try:
                    num = int(tab.get("data-season"))
                except (TypeError, ValueError):
                    continue
                if num not in season_numbers:
                    season_numbers.append(num)
            if not season_numbers:
                season_numbers = [1]
            for num in sorted(season_numbers):
                episodes = self._season_episodes(post_id, num)
                if episodes:
                    seasons.append({
                        "number": num,
                        "name": "Season %d" % num,
                        "episodes": episodes,
                    })
        if not seasons:
            # Movie, or a series whose season lists could not be fetched.
            data = json.dumps({
                "post_id": post_id, "episode_id": 0,
                "url": item_id,
            }) if post_id else item_id
            seasons = [{
                "number": 1,
                "name": "Season 1",
                "episodes": [{
                    "number": 1,
                    "title": title,
                    "data": data,
                }],
            }]
        return {
            "id": item_id,
            "title": title,
            "poster": poster,
            "banner": banner,
            "plot": plot,
            "genres": genres,
            "year": year,
            "status": status,
            "score": score,
            "type": "movie" if is_movie else "anime",
            "audio": ["dub"],
            "seasons": seasons,
        }

    def _season_episodes(self, post_id, season):
        """Episodes of one season via the dgt REST endpoint."""
        try:
            url = "%s/wp-json/dgt/v1/episodes?series=%d&season=%d" % (
                self.base_url, post_id, season)
            data = get_json(url, timeout=30)
        except Exception:
            return []
        episodes = []
        for raw in (data or {}).get("episodes") or []:
            try:
                ep_id = raw.get("id")
                number = raw.get("episode")
                try:
                    number = int(number)
                except (TypeError, ValueError):
                    number = len(episodes) + 1
                name = (raw.get("name") or "").strip() or "Episode %d" % number
                episodes.append({
                    "number": number,
                    "title": name,
                    "data": json.dumps({
                        "post_id": post_id,
                        "episode_id": int(ep_id) if ep_id else 0,
                        "url": raw.get("url") or "",
                    }),
                })
            except Exception:
                continue
        episodes.sort(key=lambda e: e["number"])
        return episodes

    def streams(self, episode_data):
        try:
            parsed = json.loads(str(episode_data or ""))
            post_id = int(parsed.get("post_id") or 0)
            episode_id = int(parsed.get("episode_id") or 0)
            referer = parsed.get("url") or self.base_url + "/"
        except Exception:
            return {"streams": [], "subtitles": []}
        if not post_id:
            return {"streams": [], "subtitles": []}
        payload = {"post_id": post_id, "episode_id": episode_id}
        body = self._watch(payload, referer)
        if body is None:
            return {"streams": [], "subtitles": []}
        if body.get("gated"):
            return {"streams": [], "subtitles": []}
        streams = []
        sources = body.get("sources") or []
        sources = sorted(
            sources, key=lambda s: s.get("rank_embed") if isinstance(
                s.get("rank_embed"), int) else 9999)
        for src in sources:
            try:
                if src.get("kind") != "embed" or not src.get("show_embed"):
                    continue
                embed = src.get("embed") or ""
                if not embed.startswith("http"):
                    continue
                server = str(src.get("server") or "Server").strip() or "Server"
                quality = _quality(server, src.get("language"))
                label = "AnimeDekho %s" % server
                if quality:
                    label += " (%dp)" % quality
                streams.append({
                    "name": "AnimeDekho",
                    "url": embed,
                    "quality": quality,
                    "type": "embed",
                    "headers": {"Referer": referer},
                    "proxy": False,
                    "label": label,
                })
            except Exception:
                continue
        return {"streams": streams, "subtitles": []}

    def _watch(self, payload, referer):
        """POST /wp-json/dgt/v1/watch; returns the parsed body or None.

        Retries once with a fresh nonce when the first attempt is gated
        (a missing/stale nonce returns gated=true with no sources).
        """
        url = self.base_url + "/wp-json/dgt/v1/watch"
        for attempt in range(2):
            nonce = self._nonce_value(refresh=(attempt > 0), url=referer)
            headers = {
                "User-Agent": BROWSER_UA,
                "Content-Type": "application/json",
                "Referer": referer,
            }
            if nonce:
                headers["X-WP-Nonce"] = nonce
            try:
                resp = requests.post(url, json=payload, headers=headers,
                                     timeout=30)
            except Exception:
                return None
            if resp.status_code >= 400:
                return None
            try:
                body = resp.json()
            except Exception:
                return None
            if not isinstance(body, dict):
                return None
            if body.get("gated") and attempt == 0:
                continue  # stale nonce: refresh and retry once
            return body
        return None
