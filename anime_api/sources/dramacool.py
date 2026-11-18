"""DramaCool source — Korean / Chinese / Japanese / Thai dramas (English sub).

Site: ``https://dramaacool.best`` (live domain; the ``dramacool.surf``
domain is a static SEO doorway with no catalogue — not used).
English-subbed Asian drama catalogue: drama cards on ``GET {host}/``
(``latest``), ``/explore`` (``trending``/``popular``) and the country
filters ``/explore?country=South%20Korea`` (K-drama),
``/explore?country=China`` (C-drama), ``/explore?country=Japan``,
``/explore?country=Thailand``, ``/explore?country=Philippines``.

Endpoints used (all public, no login):

* ``search`` — the site is an Angular SPA: ``GET {host}/search?q=<q>``
  returns the app shell with NO result cards in the HTML, and the
  ``api.dramacool.rest`` search endpoint 403s behind Cloudflare for
  plain server-side GETs. BUT the server-rendered page embeds the
  search API's own response in an Angular HTTP transfer-cache record
  (``..."b":{"currentPage":1,...,"body":[{name, normalizedName, image,
  coverImage, status, releaseYear, casts, slug}, ...]},"h":{},
  "s":200,"st":"OK","u":"https://api.dramacool.rest/v1/drama/
  search?q=...","rt":"json"``), so ``search()`` parses that record
  out of the page. ``slug`` maps to the detail URL ``/drama/<slug>/``.
* ``home`` — same card layout on ``/`` and ``/explore``.
  ``category="kdrama"`` fetches ``/explore?country=South%20Korea``,
  ``category="cdrama"`` fetches ``/explore?country=China``.
* ``details`` — ``GET /drama/<slug>/``: title/poster from the
  ``og:title`` / ``og:image`` meta tags; country/year/status/genres
  from the page text (``"<Country> <year> <Ongoing|Completed>
  TVSeries Genres: <g1> • <g2> Synopsis <plot>"``); episodes from the
  ``/drama/<slug>/episode-<n>`` links. Episode ``data`` is the
  episode-page URL itself.
* ``streams`` — ``GET`` the episode page and take its ``<iframe>``
  ``src`` (a video-host embed, e.g. vidmoly; the page also lists
  streamtape servers) as ``embed`` streams — the site's own player
  surface, played in an ``<iframe>`` exactly like the source site
  does (same contract as AnimeDekho/CKDub embed streams). No direct
  file URL is scraped from the host page.

Verified live 2026-11-18 from the Mumbai server: home 200 with real
drama cards; ``/search?q=boys`` 200 ("Showing search results for:
boys", 30 cards); detail "Blossom in Darkness (2026)" 200 with
episode-1..11 links; episode page 200 with a vidmoly iframe.
"""

import json
import re
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from anime_api.http import get
from anime_api.sources.base import Source

_SEARCH_API_MARKER = '"u":"https://api.dramacool.rest/v1/drama/search'

_DRAMA_RE = re.compile(r"^/drama/([a-z0-9][a-z0-9\-]*)/?$")
_EPISODE_RE = re.compile(r"^/drama/[a-z0-9][a-z0-9\-]*/episode-(\d+)/?$")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_EMBED_RE = re.compile(
    r"https?://[a-z0-9.\-]*(?:vidmoly|streamtape|dood|filemoon|voe|mixdrop"
    r"|upstream|streamwish|vidhide|filelions)\.[a-z]{2,10}/[^\s\"'<>]+",
    re.IGNORECASE,
)

_COUNTRY_URLS = {
    "kdrama": "/explore?country=South%20Korea",
    "cdrama": "/explore?country=China",
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


def _title_from_slug(slug):
    return slug.replace("-", " ").strip().title()


def _clean_card_text(text):
    """One card text -> clean title candidate (or "" if it is not one).

    Poster ``alt`` attributes on listing pages carry SEO spam
    ("Watch the latest show <Title> with English subtitles for free
    in Dramacool") — unwrap that to the title. "Watch now" links
    carry no title at all. A trailing year/status tail ("Title 2007
    Completed") is cut at the year. Listing link text carries an
    episode + recency prefix/suffix ("EP 11 <Title> 3h ago") — strip
    both so the bare title survives.
    """
    clean = (text or "").strip()
    if not clean or clean.lower() == "watch now":
        return ""
    m = re.search(r"(?i)watch the latest show\s+(.+?)\s+with english "
                  r"subtitles", clean)
    if m:
        clean = m.group(1).strip()
    clean = re.sub(r"(?i)\s+with english subtitles.*$", "", clean).strip()
    clean = re.sub(r"(?i)^ep\.?\s*\d+\s+", "", clean).strip()
    clean = re.sub(r"(?i)\s+\d+\s*(min|mins|hour|hours|h|day|days|week"
                   r"|weeks|month|months|year|years)\s+ago\s*$",
                   "", clean).strip()
    m = _YEAR_RE.search(clean)
    if m:
        clean = clean[:m.start()].strip()
    clean = clean.strip(" -|:,")
    # A bare status badge ("Completed"/"Ongoing") is not a title —
    # without this the shortest-candidate pick in _parse_cards
    # returns the badge instead of the drama name (live bug,
    # 2026-11-18: home items titled "Completed"/"Ongoing").
    if clean.lower() in ("completed", "ongoing"):
        return ""
    return clean


class DramaCool(Source):
    id = "dramacool"
    name = "DramaCool"
    language = "english"
    domain_key = ""  # no Firebase key
    default_url = "https://dramaacool.best"
    categories = ("kdrama", "cdrama")

    # -- fetching ----------------------------------------------------------

    def _soup(self, url):
        resp = get(url, timeout=30)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")

    def _parse_cards(self, soup):
        """a[href^=/drama/<slug>] links -> item dicts (deduped).

        Each title renders up to 3 links (poster, title, "Watch now");
        the title is the longest non-"Watch now" text among them, or
        the img alt, or the slug.
        """
        base = self.base_url
        grouped = {}
        order = []
        for a in soup.select('a[href^="/drama/"]'):
            try:
                href = (a.get("href") or "").split("?")[0]
                m = _DRAMA_RE.match(href)
                if not m:
                    continue
                url = base.rstrip("/") + "/drama/%s" % m.group(1)
                if url not in grouped:
                    grouped[url] = {"alts": [], "texts": [],
                                    "poster": None}
                    order.append(url)
                entry = grouped[url]
                img = a.select_one("img")
                if img is not None:
                    for attr in ("src", "data-src"):
                        v = img.get(attr)
                        if v and not v.startswith("data:"):
                            entry["poster"] = _abs_url(v, base)
                            break
                    alt = (img.get("alt") or "").strip()
                    if alt:
                        entry["alts"].append(alt)
                text = a.get_text(" ", strip=True)
                if text:
                    entry["texts"].append(text)
            except Exception:
                continue
        items = []
        for url in order:
            entry = grouped[url]
            # The poster img alt (SEO spam unwrapped) is the true
            # title — prefer it over link text. Link text can carry
            # a status badge ("Ongoing") or an "EP 11 ... 3h ago"
            # prefix/suffix, and the old shortest-candidate pick
            # chose the badge. Fall back to the shortest cleaned
            # link text, then to the slug.
            alt_titles = [_clean_card_text(t) for t in entry["alts"]]
            alt_titles = [c for c in alt_titles if c]
            text_titles = [_clean_card_text(t) for t in entry["texts"]]
            text_titles = [c for c in text_titles if c]
            slug = url.rstrip("/").rsplit("/", 1)[-1]
            if alt_titles:
                title = min(alt_titles, key=len)
            elif text_titles:
                title = min(text_titles, key=len)
            else:
                title = _title_from_slug(slug)
            year = None
            for text in entry["texts"]:
                m = _YEAR_RE.search(text)
                if m:
                    try:
                        year = int(m.group(0))
                    except ValueError:
                        year = None
                    break
            items.append({
                "id": url,
                "title": title.strip(),
                "poster": entry["poster"],
                "year": year,
                "type": "anime",
                "audio": ["sub"],
                "source": self.id,
            })
        return items

    # -- Source API --------------------------------------------------------

    def search(self, query, page=1):
        if not query:
            return []
        try:
            resp = get("%s/search?q=%s"
                       % (self.base_url, quote_plus(query.strip())),
                       timeout=30)
            resp.raise_for_status()
            return self._parse_search_page(resp.text)
        except Exception:
            return []

    def _parse_search_page(self, html):
        """Search results out of the SSR transfer-cache record.

        The search page embeds the api.dramacool.rest response as
        ``"b":{"currentPage":1,"nextPage":2,"hasNext":true,...,"body":
        [{name, normalizedName, image, coverImage, status, releaseYear,
        casts, slug}, ...]},"h":{},"s":200,"st":"OK","u":"https://api.
        dramacool.rest/v1/drama/search?q=..."``. ``raw_decode`` the
        ``b`` object (the record's own JSON, so no regex over nested
        braces). Falls back to card parsing if the record is absent.
        """
        marker = html.find(_SEARCH_API_MARKER)
        if marker < 0:
            return self._parse_cards(BeautifulSoup(html, "lxml"))
        body_at = html.rfind('"b":{', 0, marker)
        if body_at < 0:
            return []
        try:
            raw, _ = json.JSONDecoder().raw_decode(html[body_at + 4:])
        except Exception:
            return []
        if isinstance(raw, dict):
            raw = raw.get("body") or raw.get("results") \
                or raw.get("items") or raw.get("data") or []
        items = []
        if not isinstance(raw, list):
            return []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            slug = (entry.get("slug") or "").strip()
            title = (entry.get("name") or "").strip()
            if not slug or not title:
                continue
            year = None
            try:
                year = int(str(entry.get("releaseYear") or "")[:4])
            except (TypeError, ValueError):
                year = None
            items.append({
                "id": "%s/drama/%s" % (self.base_url, slug),
                "title": title,
                "poster": entry.get("image") or entry.get("coverImage"),
                "year": year,
                "type": "anime",
                "audio": ["sub"],
                "source": self.id,
            })
        return items

    def home(self, section, page=1, category=None):
        try:
            if category in _COUNTRY_URLS:
                path = _COUNTRY_URLS[category]
            elif section in ("trending", "popular"):
                path = "/explore"
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
            title = re.split(r"\s+English Sub\s*-", title)[0].strip()
        if not title:
            t = soup.select_one("title")
            if t:
                title = re.split(r"\s+English Sub\s*-",
                                 t.get_text(strip=True))[0].strip()
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
        text = soup.get_text(" ", strip=True)
        year = None
        m = re.search(r"\b(19|20)\d{2}\b", text)
        if m:
            try:
                year = int(m.group(0))
            except ValueError:
                year = None
        genres = []
        gm = re.search(r"Genres:\s*(.*?)\s*Synopsis", text)
        if gm:
            genres = [g.strip() for g in gm.group(1).split("•")
                      if g.strip()]
        if not plot:
            sm = re.search(r"Synopsis\s+(.*)", text)
            if sm:
                plot = sm.group(1).strip()[:1200] or None
        status = None
        if re.search(r"\bCompleted\b", text):
            status = "completed"
        elif re.search(r"\bOngoing\b", text):
            status = "ongoing"
        episodes = []
        seen = set()
        for a in soup.select('a[href*="/episode-"]'):
            try:
                href = (a.get("href") or "").split("?")[0]
                m = _EPISODE_RE.match(href)
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
            "genres": genres,
            "year": year,
            "status": status,
            "score": None,
            "type": "anime",
            "audio": ["sub"],
            "seasons": [{
                "number": 1,
                "name": "Season 1",
                "episodes": episodes,
            }],
        }

    def streams(self, episode_data):
        """Episode page -> its <iframe> src(s) as embed streams."""
        ep_url = (episode_data or "").strip()
        if not ep_url.startswith("http"):
            return {"streams": [], "subtitles": []}
        try:
            resp = get(ep_url, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception:
            return {"streams": [], "subtitles": []}
        urls, seen = [], set()
        for iframe in soup.select("iframe[src]"):
            src = urljoin(ep_url, (iframe.get("src") or "").strip())
            if src.startswith("http") and src not in seen:
                seen.add(src)
                urls.append(src)
        for href in _EMBED_RE.findall(resp.text):
            if href not in seen:
                seen.add(href)
                urls.append(href)
        return {"streams": [{
            "name": "DramaCool",
            "url": url,
            "quality": None,
            "type": "embed",
            "headers": {"Referer": ep_url},
            "proxy": False,
            "label": "DramaCool Player %d" % (i + 1),
        } for i, url in enumerate(urls)], "subtitles": []}
