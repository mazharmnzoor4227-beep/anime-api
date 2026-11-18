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
* ``streams`` — v1.2: NO watch call any more. The ``/wp-json/dgt/v1/watch``
  endpoint is ad-gated for datacenter IPs (returns ``{"gated": true}``
  since ~2026-11-18; the gate is the site's own "skip the ad once per
  24h" wall and must NOT be automated around). Instead the embed URL is
  built directly: ``{host}/embed/<post_id>/<season>-<episode>`` — that
  page is the site's own player surface and is publicly reachable (HTTP
  200, verified 2026-11-18); the user's own browser deals with the
  site's ad-skip exactly as on the real site. Stream ``type`` is
  ``"embed"``, played in an ``<iframe>``. Episode ``data`` now carries
  ``season`` + ``number`` so the URL can be built; old-format data
  (post_id/episode_id/url only) falls back to the episode page URL
  itself as the embed target.
* ``home`` — ``category`` (``"tamil"`` / ``"telugu"``) fetches
  ``/category/<name>/`` and returns those dubs (audio_lang set).
* ``details`` also parses Characters (``.dgt-cast``) and Hindi Voice
  Cast (``.dgt-vcast__grid``) from the series page when present.
* ``fetch_widgets()`` — the site-wide sidebar: Other updates
  (``ul.dgt-upd__list``), Release schedule (``.dgt-sch__day``),
  Upcoming shows (list under the ``#dgt-up-h`` heading).
"""

import html as _html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from anime_api.http import get, get_json
from anime_api.sources.base import Source

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


class AnimeDekho(Source):
    id = "animedekho"
    name = "AnimeDekho"
    language = "hindi"
    domain_key = ""  # not a CloudStream extension; no Firebase key
    default_url = "https://animedekho.tv"

    # -- fetching ----------------------------------------------------------

    def _soup(self, url):
        resp = get(url, timeout=30)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")

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

    def home(self, section, page=1, category=None):
        """Rows from /home/ (or /browse/ for page > 1).

        v1.2: ``category`` ("tamil" / "telugu") fetches that language's
        category page instead — the site's Hindi/Tamil/Telugu sections.
        Items from a category page carry ``audio_lang`` so clients can
        label them correctly.
        """
        try:
            if category in ("tamil", "telugu"):
                soup = self._soup(
                    "%s/category/%s/" % (self.base_url, category))
                items = self._parse_cards(soup)
                for it in items:
                    it["audio_lang"] = category
                return items
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
        # v1.2.2 — detail fields the clone shows (cross-check 2026-11-18):
        # runtime comes from the data-snapshot; age rating / studio from
        # the .dgt-fact blocks; external links from the .dgt-ext__btn
        # buttons (TMDB / MyAnimeList / AniList).
        runtime = None
        if snapshot:
            try:
                runtime = int(snapshot.get("runtime")) if snapshot.get("runtime") else None
            except (TypeError, ValueError):
                runtime = None
        age_rating = None
        studio = None
        for fact in soup.select(".dgt-fact"):
            small = fact.select_one("small")
            label = small.get_text(strip=True) if small else ""
            bold = fact.select_one("b")
            value = bold.get_text(" ", strip=True) if bold else ""
            if not value:
                continue
            if label == "Age rating" and not age_rating:
                age_rating = value
            elif label == "Studio" and not studio:
                studio = value
        links = {}
        for key, sel in (("tmdb", ".dgt-ext__btn--tmdb"),
                         ("mal", ".dgt-ext__btn--mal"),
                         ("anilist", ".dgt-ext__btn--anilist")):
            a = soup.select_one(sel)
            if a and a.get("href"):
                links[key] = a["href"]
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
            # v1.2: fetch seasons in parallel — sequential calls made
            # details() take 3.4s+ for a 5-season series.
            with ThreadPoolExecutor(max_workers=5) as pool:
                fetched = list(pool.map(
                    lambda n: (n, self._season_episodes(post_id, n)),
                    sorted(season_numbers)))
            for num, episodes in fetched:
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
            "runtime": runtime,
            "age_rating": age_rating,
            "studio": studio,
            "links": links,
            "seasons": seasons,
            "characters": self._parse_cast(soup),
            "voice_cast": self._parse_voice_cast(soup),
        }

    def _parse_cast(self, soup):
        """Characters block (.dgt-cast under a 'Characters' heading)."""
        out = []
        for block in soup.select(".dgt-cast"):
            head = block.find_previous(["h2", "h3"])
            label = head.get_text(" ", strip=True) if head else ""
            if "Character" not in label:
                continue
            for item in block.select(".dgt-cast__item"):
                try:
                    spans = item.select(":scope > span")
                    name = ""
                    for sp in spans:
                        if "dgt-cast__img" not in (sp.get("class") or []):
                            name = sp.get_text(" ", strip=True)
                            break
                    role_el = item.select_one(".dgt-cast__role")
                    role = role_el.get_text(strip=True) if role_el else ""
                    out.append({
                        "name": name,
                        "image": _poster_of(
                            item.select_one("img"), self.base_url),
                        "role": role,
                    })
                except Exception:
                    continue
        return out

    def _parse_voice_cast(self, soup):
        """Hindi Voice Cast grid (.dgt-vcast__grid)."""
        out = []
        for item in soup.select(".dgt-vcast__item"):
            try:
                char_el = item.select_one(".dgt-vcast__char")
                char = ""
                badge = ""
                if char_el is not None:
                    badge_el = char_el.select_one(".dgt-vcast__badge")
                    badge = badge_el.get_text(strip=True) if badge_el else ""
                    char = char_el.get_text(" ", strip=True)
                    if badge:
                        char = char.replace(badge, "").strip()
                va_el = item.select_one(".dgt-vcast__va")
                actor = va_el.get_text(" ", strip=True) if va_el else ""
                out.append({
                    "character": char,
                    "actor": actor,
                    "image": _poster_of(
                        item.select_one("img"), self.base_url),
                    "role": badge,
                })
            except Exception:
                continue
        return out

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
                    # v1.2.2: the dgt endpoint carries these — the clone
                    # shows filler episodes orange-bordered, episode stills
                    # in the grid, and air dates.
                    "filler": bool(raw.get("filler")),
                    "still": raw.get("still") or None,
                    "air_date": raw.get("air_date") or None,
                    # v1.2: season + number included so streams() can
                    # build the /embed/<post>/<season>-<ep> URL directly.
                    "data": json.dumps({
                        "post_id": post_id,
                        "episode_id": int(ep_id) if ep_id else 0,
                        "season": season,
                        "number": number,
                        "url": raw.get("url") or "",
                    }),
                })
            except Exception:
                continue
        episodes.sort(key=lambda e: e["number"])
        return episodes

    def streams(self, episode_data):
        """Direct embed URL — no watch API call (v1.2).

        The ``/wp-json/dgt/v1/watch`` endpoint is ad-gated for datacenter
        IPs (``{"gated": true}`` since 2026-11-18): the site's own
        "skip the ad once per 24h" wall, which must not be automated
        around. The embed page itself
        (``{host}/embed/<post_id>/<season>-<episode>``) is publicly
        reachable (HTTP 200) and is the site's own player surface, so
        the stream URL is built directly from the episode data. The
        user's own browser deals with the site's ad-skip exactly as on
        the real site. Old-format data without season/number falls back
        to the episode page URL itself as the embed target.
        """
        try:
            parsed = json.loads(str(episode_data or ""))
            post_id = int(parsed.get("post_id") or 0)
            season = parsed.get("season")
            number = parsed.get("number")
            referer = parsed.get("url") or self.base_url + "/"
        except Exception:
            return {"streams": [], "subtitles": []}
        if not post_id:
            return {"streams": [], "subtitles": []}
        try:
            season = int(season)
            number = int(number)
        except (TypeError, ValueError):
            season = number = None
        if season is not None and number is not None:
            embed = "%s/embed/%d/%d-%d" % (
                self.base_url, post_id, season, number)
        else:
            embed = referer
        return {"streams": [{
            "name": "AnimeDekho",
            "url": embed,
            "quality": None,
            "type": "embed",
            "headers": {"Referer": referer},
            "proxy": False,
            "label": "AnimeDekho Player",
        }], "subtitles": []}


def fetch_widgets(base_url="https://animedekho.tv"):
    """Site-wide sidebar widgets, parsed from the series/home HTML.

    Returns {"updates": [str], "schedule": [{"day": str, "count": int}],
    "upcoming": [{"title": str, "note": str}]}. Best-effort: any widget
    that cannot be parsed is returned as an empty list, never an error.
    """
    out = {"updates": [], "schedule": [], "upcoming": []}
    try:
        resp = get(base_url + "/home/", timeout=30)
        soup = BeautifulSoup(resp.text, "lxml")
    except Exception:
        return out
    try:
        for li in soup.select("ul.dgt-upd__list li"):
            text = li.get_text(" ", strip=True)
            if text:
                out["updates"].append(text)
    except Exception:
        pass
    try:
        for day in soup.select(".dgt-sch__day"):
            text = day.get_text(" ", strip=True)
            if not text:
                continue
            parts = text.rsplit(" ", 1)
            try:
                count = int(parts[1])
                out["schedule"].append({"day": parts[0], "count": count})
            except (IndexError, ValueError):
                out["schedule"].append({"day": text, "count": 0})
    except Exception:
        pass
    try:
        head = soup.select_one("#dgt-up-h")
        if head is not None:
            section = head.find_parent("section") or head.find_parent("div")
            if section is not None:
                for row in section.select("li, a"):
                    text = row.get_text(" ", strip=True)
                    if text and "Upcoming shows" not in text:
                        out["upcoming"].append({"title": text, "note": ""})
    except Exception:
        pass
    return out
