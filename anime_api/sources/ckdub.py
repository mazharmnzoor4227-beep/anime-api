"""CKDub source — Korean (and Chinese) dramas dubbed in Hindi.

Site: ``https://www.ckdub.com`` (Next.js App Router site, no search
API). Hindi-dubbed K-drama catalogue: ``/category/korean`` lists the
Korean dramas, ``/browse`` the full catalogue, detail pages live at
``/drama/<slug>/`` and episode watch pages at
``/drama/<slug>/watch/<n>``.

Endpoints used (all public, no login):

* ``search`` — the site has no server-side search endpoint
  (``/search`` and ``/api/search`` 404; ``/browse?q=`` returns an
  empty list — results render client-side). The catalogue is small
  (tens of dramas), so search fetches ``/browse``,
  ``/category/korean`` and ``/category/chinese`` and filters the
  cards client-side by title/slug substring.
* ``home`` — drama cards on ``GET {host}/`` (``latest``),
  ``/category/korean`` (``trending``) and ``/browse`` (``popular``).
  ``category="kdrama"`` fetches ``/category/korean``. Cards are
  ``a[href^="/drama/"]`` links with an ``img`` whose ``alt`` is the
  title (usually suffixed ``" poster"``).
* ``details`` — ``GET /drama/<slug>/``: title/poster/plot from the
  page head; episodes from the ``/drama/<slug>/watch/<n>`` links.
  Episode ``data`` is the watch-page URL itself.
* ``streams`` — ``GET`` the watch page and take its ``<iframe>``
  ``src`` (a video-host embed, e.g. playmogo) as an ``embed`` stream
  — the site's own player surface, played in an ``<iframe>``
  exactly like the source site does (same contract as AnimeDekho's
  embed streams). No direct file URL is scraped from the host page.
  Caveat (verified 2026-11-18): the playmogo embed answers 403
  Cloudflare "Just a moment..." from the Mumbai server IP, so the
  embed could not be resolved further server-side — on a normal
  (phone) network it loads like any other video-host embed, and the
  iframe URL is what the site itself plays.
  Verified live 2026-11-18 from the Mumbai server: home 200 with
  real drama cards; ``/category/korean`` 200 (42 drama links);
  detail "Boys Over Flowers Hindi Dubbed" 200 with watch links for
  episodes 1..N; watch page 200 with a playmogo iframe.
"""

import re

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from anime_api.http import get
from anime_api.sources.base import Source

_DRAMA_RE = re.compile(r"^/drama/([a-z0-9\-]+)/?$")
_WATCH_RE = re.compile(r"^/drama/[a-z0-9\-]+/watch/(\d+)/?$")


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


class CKDub(Source):
    id = "ckdub"
    name = "CKDub"
    language = "hindi"
    domain_key = ""  # no Firebase key
    default_url = "https://www.ckdub.com"
    categories = ("kdrama",)

    # -- fetching ----------------------------------------------------------

    def _soup(self, url):
        resp = get(url, timeout=30)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")

    def _parse_cards(self, soup):
        """a[href^=/drama/<slug>] links -> item dicts (deduped)."""
        base = self.base_url
        items, seen = [], set()
        for a in soup.select('a[href^="/drama/"]'):
            try:
                href = a.get("href") or ""
                m = _DRAMA_RE.match(href.split("?")[0])
                if not m:
                    continue
                url = base.rstrip("/") + "/drama/%s" % m.group(1)
                if url in seen:
                    continue
                seen.add(url)
                img = a.select_one("img")
                title = ""
                poster = None
                if img is not None:
                    title = (img.get("alt") or "").strip()
                    if title.lower().endswith(" poster"):
                        title = title[:-len(" poster")].strip()
                    poster = _abs_url(img.get("src"), base)
                if not title:
                    title = a.get_text(" ", strip=True)
                if not title:
                    title = _title_from_slug(m.group(1))
                # Homepage carries non-drama cards (e.g. a "More Info"
                # button tile) — never surface those as titles.
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
        q = query.strip().lower()
        items, seen = [], set()
        for path in ("/browse", "/category/korean", "/category/chinese"):
            try:
                soup = self._soup(self.base_url + path)
                for it in self._parse_cards(soup):
                    if it["id"] in seen:
                        continue
                    hay = (it["title"] + " " + it["id"]).lower()
                    if q in hay:
                        seen.add(it["id"])
                        items.append(it)
            except Exception:
                continue
        return items

    def home(self, section, page=1, category=None):
        try:
            if category == "kdrama":
                path = "/category/korean"
            elif section == "trending":
                path = "/category/korean"
            elif section == "popular":
                path = "/browse"
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
        if not title:
            t = soup.select_one("title")
            if t:
                title = t.get_text(strip=True)
        # Both og:title and <title> carry the site's SEO suffix
        # ("... - Watch Online & Download Free HD | CKDub") — strip it.
        if title:
            title = re.split(
                r"\s+-\s+Watch Online|\s*\|\s*CKDub\s*$", title)[0].strip()
        if not title:
            m = re.search(r"/drama/([a-z0-9\-]+)", item_id)
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
        for a in soup.select('a[href*="/watch/"]'):
            try:
                href = (a.get("href") or "").split("?")[0]
                m = _WATCH_RE.match(href)
                if not m:
                    continue
                num = int(m.group(1))
                if num in seen:
                    continue
                seen.add(num)
                episodes.append({
                    "number": num,
                    "title": "Episode %d" % num,
                    "data": self.base_url + href,
                })
            except Exception:
                continue
        episodes.sort(key=lambda e: e["number"])
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
            "audio": ["dub"],
            "seasons": [{
                "number": 1,
                "name": "Season 1",
                "episodes": episodes,
            }],
        }

    def streams(self, episode_data):
        """Watch page -> its <iframe> src as an embed stream."""
        watch_url = (episode_data or "").strip()
        if not watch_url.startswith("http"):
            return {"streams": [], "subtitles": []}
        try:
            soup = self._soup(watch_url)
        except Exception:
            return {"streams": [], "subtitles": []}
        iframe = soup.select_one("iframe[src]")
        if iframe is None:
            return {"streams": [], "subtitles": []}
        embed = urljoin(watch_url, iframe.get("src"))
        if not embed:
            return {"streams": [], "subtitles": []}
        return {"streams": [{
            "name": "CKDub",
            "url": embed,
            "quality": None,
            "type": "embed",
            "headers": {"Referer": watch_url},
            "proxy": False,
            "label": "CKDub Player",
        }], "subtitles": []}
