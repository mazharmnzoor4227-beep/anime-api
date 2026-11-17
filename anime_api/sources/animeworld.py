r"""AnimeWorldIndia source — "Anime World India" (Hindi).

Ports ``AnimeWorldProvider.kt`` from the CloudStream extension
(``~/workspace/anime-api-work/raghav``).

* Site: ``https://watchanimeworld.one`` (static default; the live host is
  resolved per call from the Firebase domain map under key
  ``animeworldindia`` and applied only when it contains ``"animeworld'``).
* ``home``: one shared homepage list (``li.post`` / ``article.post``);
  ``latest`` = first 20, ``trending`` = shuffled 20, ``popular`` =
  reversed 20, ``franchise`` is a separate ``a[href*="/category/franchise/"]``
  list.  ``hasNext`` is always false in the extension.
* ``search``: ``GET {mainUrl}/page/{n}/?s={query}``, series or ``/movies/``
  links.
* ``details``: title from ``h1``; poster ``.poster img``; plot from
  ``.description`` / ``.synopsis`` / ``.plot`` / ``p``; genres from
  ``a[href*="genre"]``.  Series seasons come from ``[data-season]`` tabs;
  episodes are ``a[href*="/episode/"]`` links with a ``(\d+)x(\d+)``
  (season x episode) pattern; other seasons are fetched via
  ``/wp-admin/admin-ajax.php?action=action_select_season&season={s}&post={postId}``.
* ``streams``: ``episode.data`` is the episode page URL.  The episode page's
  iframes are collected; only ``zephyrix`` / ``zephyrflick`` iframes are
  handled, via :mod:`anime_api.extractors.zephyrix`.  No subtitles.
* Cloudflare: the site 403s plain requests.  All fetches go through
  :mod:`anime_api.cf` (cached clearance -> env clearance -> headless
  Playwright solve).  See ``anime_api/cf.py`` for the status.
"""

import random
import re
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from anime_api.cf import cf_get, is_cf_blocked
from anime_api.extractors import zephyrix
from anime_api.sources.base import Source

_EPISODE_RE = re.compile(r"(\d+)x(\d+)")


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


def _img_url(img, base):
    if img is None:
        return None
    return _abs_url(img.get("data-src") or img.get("src"), base)


def _clean_episode_name(episode_url):
    """Name from the part after ``/episode/`` (extension's cleanEpisodeName)."""
    try:
        tail = episode_url.split("/episode/", 1)[1]
    except IndexError:
        return None
    tail = _EPISODE_RE.sub("", tail)
    tokens = [t for t in tail.split("-") if t and t not in ("ep", "episode")]
    name = " ".join(tokens).strip(" -_")
    if not name:
        return None
    return name[:1].upper() + name[1:]


class AnimeWorld(Source):
    id = "animeworld"
    name = "Anime World India"
    language = "hindi"
    domain_key = "animeworldindia"
    default_url = "https://watchanimeworld.one"

    @property
    def base_url(self):
        # Extension applies the Firebase value only if it contains "animeworld".
        resolved = super().base_url
        if "animeworld" in resolved:
            return resolved
        return self.default_url

    # -- fetching ----------------------------------------------------------

    def _soup(self, url):
        resp = cf_get(url, timeout=30)
        if is_cf_blocked(resp):
            raise RuntimeError(
                "Cloudflare blocked %s (HTTP %s)" % (url, resp.status_code)
            )
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")

    def _parse_items(self, soup):
        base = self.base_url
        items = []
        seen = set()
        for card in soup.select("li.post, article.post"):
            try:
                link = card.select_one('a[href*="/series/"], a[href*="/movies/"]')
                if link is None:
                    continue
                href = link.get("href") or ""
                if href.endswith("/series/") or href.endswith("/movies/"):
                    continue
                href = _abs_url(href, base)
                if not href or href in seen:
                    continue
                seen.add(href)
                title_el = card.select_one("h2, h3")
                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue
                items.append({
                    "id": href,
                    "title": title,
                    "poster": _img_url(card.select_one("img"), base),
                    "year": None,
                    "type": "movie" if "/movies/" in href else "anime",
                    "audio": ["dub"],
                    "source": self.id,
                })
            except Exception:
                continue
        return items

    # -- Source API --------------------------------------------------------

    def home(self, section, page=1):
        try:
            soup = self._soup(self.base_url)
        except Exception:
            return []
        if section == "franchise":
            items, seen = [], set()
            for anchor in soup.select('a[href*="/category/franchise/"]'):
                try:
                    href = _abs_url(anchor.get("href"), self.base_url)
                    title = anchor.get_text(strip=True)
                    if not href or href in seen or not title:
                        continue
                    seen.add(href)
                    items.append({
                        "id": href,
                        "title": title,
                        "poster": _img_url(anchor.select_one("img"), self.base_url),
                        "year": None,
                        "type": "anime",
                        "audio": ["dub"],
                        "source": self.id,
                    })
                except Exception:
                    continue
            return items
        all_items = self._parse_items(soup)
        if section == "trending":
            shuffled = list(all_items)
            random.shuffle(shuffled)
            return shuffled[:20]
        if section == "popular":
            return list(reversed(all_items))[:20]
        return all_items[:20]  # "latest" (and any other section)

    def search(self, query, page=1):
        if page < 1:
            page = 1
        try:
            url = "%s/page/%d/?s=%s" % (
                self.base_url, page, quote_plus(query))
            soup = self._soup(url)
        except Exception:
            return []
        return self._parse_items(soup)

    def details(self, item_id):
        try:
            soup = self._soup(item_id)
        except Exception:
            return None
        title_el = soup.select_one("h1")
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            return None
        poster = _img_url(
            soup.select_one(".poster img, .post-thumbnail img"), self.base_url)
        backdrop = _img_url(
            soup.select_one(".backdrop img, .bg img"), self.base_url)
        plot = None
        for sel in (".description", ".synopsis", ".plot", "p"):
            el = soup.select_one(sel)
            if el:
                text = el.get_text(" ", strip=True)
                if text:
                    plot = text
                    break
        genres = []
        for a in soup.select('a[href*="genre"]'):
            text = a.get_text(strip=True)
            if text and text not in genres:
                genres.append(text)
        if "/movies/" in item_id:
            return {
                "id": item_id,
                "title": title,
                "poster": poster,
                "banner": backdrop,
                "plot": plot,
                "genres": genres,
                "year": None,
                "status": None,
                "score": None,
                "seasons": [{
                    "number": 1,
                    "name": "Season 1",
                    "episodes": [{
                        "number": 1,
                        "title": title,
                        "data": item_id,
                    }],
                }],
            }

        # Series: season tabs + episode links.
        post_id = ""
        post_el = soup.select_one("[data-post]")
        if post_el:
            post_id = post_el.get("data-post") or ""
        seasons = {}
        for el in soup.select("[data-season]"):
            try:
                num = int(el.get("data-season"))
            except (TypeError, ValueError):
                continue
            name = el.get_text(strip=True) or "Season %d" % num
            seasons[num] = name
        initial_links = []
        for a in soup.select('a[href*="/episode/"]'):
            href = _abs_url(a.get("href"), self.base_url)
            if href and href not in initial_links:
                initial_links.append(href)
        initial_season = 1
        if initial_links:
            m = _EPISODE_RE.search(initial_links[0])
            if m:
                initial_season = int(m.group(1))
        elif seasons:
            initial_season = sorted(seasons)[0]
        max_season = max(list(seasons) + [initial_season]) if seasons or initial_links else 1

        out_seasons = []
        for season_num in range(1, max_season + 1):
            if season_num == initial_season:
                links = initial_links
            else:
                links = self._fetch_season_episodes(post_id, season_num)
            episodes = []
            for idx, href in enumerate(links, start=1):
                m = _EPISODE_RE.search(href)
                if m:
                    ep_num = int(m.group(2))
                else:
                    ep_num = idx
                name = _clean_episode_name(href) or "Episode %d" % ep_num
                episodes.append({
                    "number": ep_num,
                    "title": name,
                    "data": href,
                })
            if not episodes:
                continue
            episodes.sort(key=lambda e: e["number"])
            out_seasons.append({
                "number": season_num,
                "name": seasons.get(season_num, "Season %d" % season_num),
                "episodes": episodes,
            })
        if not out_seasons:
            out_seasons = [{
                "number": 1,
                "name": "Season 1",
                "episodes": [],
            }]
        return {
            "id": item_id,
            "title": title,
            "poster": poster,
            "banner": backdrop,
            "plot": plot,
            "genres": genres,
            "year": None,
            "status": None,
            "score": None,
            "seasons": out_seasons,
        }

    def _fetch_season_episodes(self, post_id, season):
        if not post_id:
            return []
        try:
            url = (
                "%s/wp-admin/admin-ajax.php"
                "?action=action_select_season&season=%d&post=%s"
                % (self.base_url, season, post_id)
            )
            resp = cf_get(url, headers={
                "Referer": self.base_url,
                "X-Requested-With": "XMLHttpRequest",
            }, timeout=30)
            if is_cf_blocked(resp):
                return []
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception:
            return []
        links = []
        for a in soup.select('a[href*="/episode/"]'):
            href = _abs_url(a.get("href"), self.base_url)
            if href and href not in links:
                links.append(href)
        return links

    def streams(self, episode_data):
        if not episode_data:
            return {"streams": [], "subtitles": []}
        try:
            soup = self._soup(episode_data)
        except Exception:
            return {"streams": [], "subtitles": []}
        iframes = []
        for frame in soup.select("iframe"):
            src = frame.get("data-src") or frame.get("src")
            if src and src not in iframes:
                iframes.append(src)
        streams = []
        for src in iframes:
            if "zephyrix" not in src and "zephyrflick" not in src:
                continue  # extension handles only these two hosts
            try:
                sub_streams, _subs = zephyrix.resolve_zephyrix(
                    src, self.base_url)
                streams.extend(sub_streams)
            except Exception:
                continue
        return {"streams": streams, "subtitles": []}
