"""PKDramas source — Pakistani (Urdu) dramas, full episodes on YouTube.

Site: ``https://www.pkdramas.com`` — an aggregator that catalogues
Pakistani serials (Hum TV, ARY Digital, Har Pal Geo, Green
Entertainment, ...) and plays each episode from the broadcaster's
official YouTube upload. The site hosts no video itself; episodes
stream from official YouTube channels (see the site's own About /
copyright note). ``language`` is ``"hindi"`` — the Urdu catalogue is
served under the Hindi lang filter, the audience the app already
uses for Hindi/Urdu content (same choice as the Hindi-dub sources).

Endpoints used (all public, no login):

* ``search`` — ``GET {host}/search?q=<query>`` (``/?s=`` returns the
  unfiltered homepage — the working search path is ``/search``).
  Drama cards are ``a[href^="/drama/<id>-<slug>"]`` links.
* ``home`` — drama cards on ``GET {host}/`` (``latest``) and
  ``/dramas`` (``trending``/``popular`` — the full catalogue).
  ``category="pakistani"`` fetches ``/dramas``.
* ``details`` — ``GET /drama/<id>-<slug>/``: title from the
  ``og:title`` tag (``"<Title> Full Episodes — <Channel> | Pakistani
  Dramas"``); poster from ``og:image`` (the latest episode's YouTube
  thumbnail); plot from the meta description; episodes from the
  ``/drama/<id>-<slug>/episode/<ep-id>-<slug>`` links. Episode
  ``data`` is the episode-page URL itself.
* ``streams`` — ``GET`` the episode page and read the YouTube video
  id from its embedded player payload. The id lives in the Next.js
  RSC flight data with ESCAPED quotes
  (``\\\"videoId\\\":\\\"<11 chars>\\\"``) and in the JSON-LD
  ``embedUrl`` (``https://www.youtube.com/embed/<id>``) — both are
  tried, in that order. Returned as one ``embed`` stream —
  ``https://www.youtube.com/embed/<id>`` — played in an ``<iframe>``,
  exactly the official upload the site itself plays.

Verified live 2026-11-18 from the Mumbai server: home 200 with real
drama cards; ``/search?q=tere+bin`` 200, first "Tere Bin" (Har Pal
Geo); detail "Hurmat" (Hum TV) 200 with 15 episode links; episode 9
of "Tere Bin" page 200 with videoId ``FOayEzY3C3o`` (in the escaped
RSC payload + JSON-LD embedUrl).
"""

import re
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from anime_api.http import get
from anime_api.sources.base import Source

_DRAMA_RE = re.compile(r"^/drama/(\d+-[a-z0-9\-]+)/?$")
_EPISODE_RE = re.compile(
    r"^/drama/\d+-[a-z0-9\-]+/episode/(\d+)-[a-z0-9\-]+/?$")
_EP_NUM_RE = re.compile(r"(?i)episode\s*(\d+)")
_VIDEO_ID_RE = re.compile(r'"videoId"\s*:\s*"([A-Za-z0-9_\-]{11})"')
_EMBED_URL_RE = re.compile(
    r"https://www\.youtube\.com/embed/([A-Za-z0-9_\-]{11})")


def _path_of(href):
    """Episode href -> site-relative path (absolute hrefs too).

    Some drama pages link episodes as absolute URLs
    (``https://pkdramas.com/drama/...`` — no ``www``); the episode
    regex is anchored to ``/drama/``, so strip any origin first.
    """
    href = (href or "").split("?")[0].strip()
    if "://" in href:
        parts = href.split("://", 1)[1].split("/", 1)
        href = "/" + parts[1] if len(parts) > 1 else "/"
    return href


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


def _title_from_slug(slug):
    return slug.replace("-", " ").strip().title()


class PKDramas(Source):
    id = "pkdramas"
    name = "PKDramas"
    language = "hindi"
    domain_key = ""  # no Firebase key
    default_url = "https://www.pkdramas.com"
    categories = ("pakistani",)

    # -- fetching ----------------------------------------------------------

    def _soup(self, url):
        resp = get(url, timeout=30)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")

    def _parse_cards(self, soup):
        """a[href^=/drama/<id>-<slug>] links -> item dicts (deduped)."""
        base = self.base_url
        items, seen = [], set()
        for a in soup.select('a[href^="/drama/"]'):
            try:
                href = (a.get("href") or "").split("?")[0]
                m = _DRAMA_RE.match(href)
                if not m:
                    continue
                url = base.rstrip("/") + "/drama/%s" % m.group(1)
                if url in seen:
                    continue
                seen.add(url)
                img = a.select_one("img")
                poster = None
                if img is not None:
                    for attr in ("src", "data-src"):
                        v = img.get(attr)
                        if v and not v.startswith("data:"):
                            poster = _abs_url(v, base)
                            break
                title = a.get_text(" ", strip=True)
                # Card text can carry the channel on a second line
                # ("Hurmat Hum TV") — keep the first line only.
                if title:
                    title = title.split("\n")[0].strip()
                if not title and img is not None:
                    title = (img.get("alt") or "").strip()
                if not title:
                    title = _title_from_slug(m.group(1).split("-", 1)[1])
                if title.strip().lower() in (
                        "more info", "view all", "browse", "load more",
                        "see all", "show more"):
                    continue
                items.append({
                    "id": url,
                    "title": title,
                    "poster": poster,
                    "year": None,
                    "type": "anime",
                    "audio": [],
                    "source": self.id,
                })
            except Exception:
                continue
        return items

    # -- Source API --------------------------------------------------------

    def search(self, query, page=1):
        if not query:
            return []
        try:
            soup = self._soup("%s/search?q=%s"
                              % (self.base_url, quote_plus(query.strip())))
            return self._parse_cards(soup)
        except Exception:
            return []

    def home(self, section, page=1, category=None):
        try:
            if category == "pakistani":
                path = "/dramas"
            elif section in ("trending", "popular"):
                path = "/dramas"
            else:
                path = "/"
            soup = self._soup(self.base_url + path)
            return self._parse_cards(soup)
        except Exception:
            return []

    def details(self, item_id):
        try:
            soup = self._soup(item_id)
        except Exception:
            return {"error": "drama not found"}
        title = ""
        og_title = soup.select_one('meta[property="og:title"]')
        if og_title and og_title.get("content"):
            title = og_title.get("content").strip()
            # "Hurmat Full Episodes — Hum TV | Pakistani Dramas"
            title = re.split(r"\s+Full Episodes\s*[—\-]",
                             title)[0].strip()
            title = title.split(" | ")[0].strip()
        if not title:
            t = soup.select_one("title")
            if t:
                title = re.split(r"\s+Full Episodes\s*[—\-]",
                                 t.get_text(strip=True))[0].strip()
        if not title:
            m = re.search(r"/drama/\d+-([a-z0-9\-]+)", item_id)
            title = _title_from_slug(m.group(1)) if m else ""
        if not title:
            return {"error": "drama not found"}
        poster = None
        og_img = soup.select_one('meta[property="og:image"]')
        if og_img and og_img.get("content"):
            poster = _abs_url(og_img.get("content"), self.base_url)
        plot = None
        desc = soup.select_one("meta[name=description]")
        if desc and desc.get("content"):
            plot = desc.get("content").strip() or None
        if not plot:
            og_desc = soup.select_one('meta[property="og:description"]')
            if og_desc and og_desc.get("content"):
                plot = og_desc.get("content").strip() or None
        episodes = []
        seen = set()
        for a in soup.select('a[href*="/episode/"]'):
            try:
                href = _path_of(a.get("href") or "")
                m = _EPISODE_RE.match(href)
                if not m:
                    continue
                ep_id = m.group(1)
                if ep_id in seen:
                    continue
                seen.add(ep_id)
                text = a.get_text(" ", strip=True)
                num_m = _EP_NUM_RE.search(text)
                num = int(num_m.group(1)) if num_m else len(episodes) + 1
                episodes.append({
                    "number": num,
                    "title": text[:120] or "Episode %d" % num,
                    "data": self.base_url + href,
                })
            except Exception:
                continue
        episodes.sort(key=lambda e: e["number"])
        # Episode numbers restart per page load in rare dupes; keep
        # them stable by re-numbering only when duplicates collide.
        nums = [e["number"] for e in episodes]
        if len(nums) != len(set(nums)):
            for i, e in enumerate(episodes, start=1):
                e["number"] = i
        if not episodes:
            episodes = [{
                "number": 1,
                "title": title,
                "data": item_id,
            }]
        return {
            "id": item_id,
            "title": title,
            "poster": poster,
            "banner": poster,
            "plot": plot,
            "genres": [],
            "year": None,
            "status": None,
            "score": None,
            "type": "anime",
            "audio": [],
            "seasons": [{
                "number": 1,
                "name": "Season 1",
                "episodes": episodes,
            }],
        }

    def streams(self, episode_data):
        """Episode page -> its official YouTube embed as an embed stream."""
        ep_url = (episode_data or "").strip()
        if not ep_url.startswith("http"):
            return {"streams": [], "subtitles": []}
        try:
            resp = get(ep_url, timeout=30)
            resp.raise_for_status()
        except Exception:
            return {"streams": [], "subtitles": []}
        # The videoId sits in the Next.js RSC payload with escaped
        # quotes (\"videoId\":\"...\") — unescape before matching.
        # JSON-LD embedUrl is the second source of the same id.
        text = resp.text.replace('\\"', '"')
        m = _VIDEO_ID_RE.search(text) or _EMBED_URL_RE.search(text)
        if not m:
            return {"streams": [], "subtitles": []}
        return {"streams": [{
            "name": "PKDramas YouTube",
            "url": "https://www.youtube.com/embed/%s" % m.group(1),
            "quality": None,
            "type": "embed",
            "headers": {"Referer": ep_url},
            "proxy": False,
            "label": "YouTube (official upload)",
        }], "subtitles": []}
