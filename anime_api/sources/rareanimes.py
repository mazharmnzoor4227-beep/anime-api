"""RareAnimesIndia source — "Rare Toons India" (Hindi).

Ports ``RareAnimesProvider.kt`` (+ ``RAINet.kt`` / ``RAICFBypass.kt``)
from the CloudStream extension (``~/workspace/anime-api-work/raghav``).

* Site: ``https://www.rareanimes.fans`` (static default; the live host is
  resolved per call from the Firebase domain map under key
  ``rareanimes`` — unlike AnimeWorld there is no ``contains(...)`` check).
* ``home``: WordPress category pages — ``hindi-dub``, ``cartoon-network``,
  ``disney-xd``, ``hungama``, ``marvel-hq``, ``pokemon``.  The API's
  sections map as: ``latest`` -> ``hindi-dub``, ``trending`` ->
  ``cartoon-network``, ``popular`` -> ``marvel-hq``.
  Page 1 is ``{mainUrl}/category/{data}/``, later pages
  ``/category/{data}/page/{n}/``.
* ``search``: page 1 ``{mainUrl}/?s={query}``, later pages
  ``{mainUrl}/page/{n}/?s={query}``.
* ``details``: title ``h1.entry-title``; poster ``meta[property=og:image]``;
  meta regexes over ``div.entry-content`` (Season No / Release Year /
  Episodes); plot = first ``p`` starting with Synopsis/Storyline/Story:
  else the longest ``p`` over 120 chars; genres ``.meta-category a``
  (max 8).  Hub pages (collections) load up to 40 sub-pages in chunks of
  6 and merge episodes keyed ``season:episode``; normal pages combine
  ``extractSources`` (store archives + codedew zipper/zipcloud links),
  ``parseDirectEpisodes`` (``Episode N`` rows) and ``loadArchive``
  (max depth 2).  When >= 2 dub keys exist, each dub becomes its own
  synthetic season.
* Episode/movie ``data`` is a JSON string (``variantsJson``):
  ``{"v":[{"n":"<label>","u":"<codedew/store URL>","k":"<dubKey>"}, ...]}``.
  ``streams`` parses it and runs every variant through
  :mod:`anime_api.extractors.codedew`.  Mega links are unsupported
  (``codedew`` returns empty for them).  No subtitles anywhere.
* Cloudflare: the site 403s plain requests.  All fetches go through
  :mod:`anime_api.cf` (cached clearance -> env clearance -> headless
  Playwright solve).  See ``anime_api/cf.py`` for the status.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from anime_api.cf import cf_get, is_cf_blocked
from anime_api.extractors import codedew
from anime_api.sources.base import Source

_HOME_SECTIONS = {
    "latest": "hindi-dub",
    "trending": "cartoon-network",
    "popular": "marvel-hq",
}

_SEASON_RE = re.compile(r"Seasons?\s*[-\u2013:.]?\s*(\d{1,2})", re.IGNORECASE)
_MOVIE_RE = re.compile(r"Movie\s*[-\u2013:.]?\s*(\d{1,3})", re.IGNORECASE)
_EP_ROW_RE = re.compile(
    r"^(?:Episode|EP)\s*[.\-]?\s*(\d{1,3})\b", re.IGNORECASE)
_SEASON_ROW_RE = re.compile(
    r"^\s*Seasons?\s*[-\u2013:.]?\s*(\d{1,2})\s*$", re.IGNORECASE)
_SEASON_EP_RE = re.compile(r"S(\d{1,2})E(\d{1,3})", re.IGNORECASE)

_INFO_LABELS = (
    "movie info", "movies info", "series info", "cartoon series info",
    "anime info",
)

_DUB_LABELS = {
    "cn": "Hindi (Cartoon Network)",
    "xd": "Hindi (Hungama XD)",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "en": "English",
    "be": "Bengali",
    "multi": "Multi Audio",
    "": "Main",
}


def _abs_url(url, base):
    if not url:
        return None
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http"):
        return url
    if url.startswith("/"):
        return base.rstrip("/") + url
    return None


def dub_key_of(text):
    """Dub key for a heading/context string (extension's ``dubKeyOf``)."""
    t = (text or "").lower()
    if ("cartoon network" in t or "caroon network" in t or "cn dub" in t
            or re.search(r"(?<![a-z])cn(?![a-z])", t)):
        return "cn"
    if "hungama" in t or "disney xd" in t or "marvel hq" in t:
        return "xd"
    found = set()
    if "tamil" in t:
        found.add("ta")
    if "telugu" in t:
        found.add("te")
    if "english" in t:
        found.add("en")
    if "bengali" in t:
        found.add("be")
    if "hindi" in t:
        found.add("hi")
    if len(found) == 1:
        return next(iter(found))
    if len(found) > 1:
        return "multi"
    return ""


def language_from_text(text):
    """Language code from a row's language span/text (extension's version)."""
    t = (text or "").lower()
    if "telugu" in t:
        return "te"
    if "tamil" in t:
        return "ta"
    if "bengali" in t:
        return "be"
    if "english" in t:
        return "en"
    if "hindi" in t:
        return "hi"
    return ""


def dub_label(key):
    return _DUB_LABELS.get(key or "", "Main")


def variants_json(variants):
    """The extension's wire format for episode data."""
    return json.dumps(
        {"v": [
            {"n": v.get("n", ""), "u": v.get("u", ""), "k": v.get("k", "")}
            for v in variants
        ]},
        separators=(",", ":"),
        ensure_ascii=False,
    )


def parse_variants(data):
    """Parse episode ``data`` back into a variant list."""
    if not data:
        return []
    try:
        parsed = json.loads(data)
        variants = parsed.get("v")
        if isinstance(variants, list):
            return [v for v in variants if isinstance(v, dict) and v.get("u")]
    except Exception:
        pass
    # Fallback (extension behaviour): treat data itself as a single URL.
    if isinstance(data, str) and data.startswith("http"):
        return [{"n": "Default", "u": data, "k": ""}]
    return []


def parse_episode_number(text):
    """(season, episode) from e.g. ``S2E05`` / ``Season 2 Episode 5``."""
    if not text:
        return None, None
    m = _SEASON_EP_RE.search(text)
    if m:
        return int(m.group(1)), int(m.group(2))
    season = None
    m = re.search(r"Seasons?\s*(\d{1,2})", text, re.IGNORECASE)
    if m:
        season = int(m.group(1))
    m = re.search(r"(?:E|Episode)\s*(\d{1,3})", text, re.IGNORECASE)
    episode = int(m.group(1)) if m else None
    return season, episode


def _is_internal_post_link(href, base):
    if not href or base not in href:
        return False
    low = href.lower()
    if "discord" in low or "?s=" in low or "#" in low:
        return False
    path = href.split(base, 1)[1] if base in href else href
    if path.startswith(("/hindi/category/", "/category/", "/tag/",
                        "/author/", "/page/", "/home")):
        return False
    if re.search(r"all-(movies|seasons?|series|episodes?)-", path):
        return False
    return len(path) > 8


class RareAnimes(Source):
    id = "rareanimes"
    name = "Rare Toons India"
    language = "hindi"
    domain_key = "rareanimes"
    default_url = "https://www.rareanimes.fans"

    # -- fetching ----------------------------------------------------------

    def _soup(self, url):
        resp = cf_get(url, timeout=30)
        if is_cf_blocked(resp):
            raise RuntimeError(
                "Cloudflare blocked %s (HTTP %s)" % (url, resp.status_code)
            )
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")

    def _parse_listings(self, soup):
        base = self.base_url
        items, seen = [], set()
        for article in soup.select("article"):
            try:
                link = article.select_one("h2.entry-title a, .entry-title a")
                if link is None:
                    continue
                href = _abs_url(link.get("href"), base)
                if not href or base not in href or href in seen:
                    continue
                seen.add(href)
                title_el = article.select_one("h2.entry-title, .entry-title")
                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue
                img = article.select_one("img")
                poster = None
                if img is not None:
                    poster = _abs_url(
                        img.get("src") or img.get("data-src"), base)
                items.append({
                    "id": href,
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

    def home(self, section, page=1):
        data = _HOME_SECTIONS.get(section, "hindi-dub")
        if page is None or page < 1:
            page = 1
        if page <= 1:
            url = "%s/category/%s/" % (self.base_url, data)
        else:
            url = "%s/category/%s/page/%d/" % (self.base_url, data, page)
        try:
            return self._parse_listings(self._soup(url))
        except Exception:
            return []

    def search(self, query, page=1):
        if page is None or page < 1:
            page = 1
        encoded = quote_plus(query)
        if page <= 1:
            url = "%s/?s=%s" % (self.base_url, encoded)
        else:
            url = "%s/page/%d/?s=%s" % (self.base_url, page, encoded)
        try:
            return self._parse_listings(self._soup(url))
        except Exception:
            return []

    def details(self, item_id):
        try:
            soup = self._soup(item_id)
        except Exception:
            return None
        title_el = soup.select_one("h1.entry-title, h1")
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            return None
        poster = None
        og = soup.select_one('meta[property="og:image"]')
        if og and og.get("content"):
            poster = og.get("content")
        else:
            img = soup.select_one(
                ".herald-post-thumbnail img, img.wp-post-image")
            if img is not None:
                poster = _abs_url(img.get("src"), self.base_url)

        content = soup.select_one("div.entry-content")
        content_text = content.get_text(" ", strip=True) if content else ""
        year = None
        m = re.search(r"Release\s*Year[.:]?\s*(\d{4})", content_text)
        if m:
            year = int(m.group(1))
        default_season = 1
        m = re.search(r"Season\s*No[.:]?\s*(\d{1,2})", content_text)
        if m:
            default_season = int(m.group(1))

        plot = None
        if content is not None:
            for p in content.select("p"):
                text = p.get_text(" ", strip=True)
                if not text:
                    continue
                for prefix in ("Synopsis", "Storyline", "Story:"):
                    if text.startswith(prefix):
                        plot = text.split(":", 1)[1].strip() if ":" in text else text
                        break
                if plot:
                    break
            if not plot:
                longest = ""
                for p in content.select("p"):
                    text = p.get_text(" ", strip=True)
                    if len(text) > 120 and len(text) > len(longest):
                        longest = text
                plot = longest or None

        genres = []
        for a in soup.select(".meta-category a, .herald-meta a[href*='category']"):
            text = a.get_text(strip=True)
            if text and text not in genres:
                genres.append(text)
            if len(genres) >= 8:
                break

        base_result = {
            "id": item_id,
            "title": title,
            "poster": poster,
            "banner": None,
            "plot": plot,
            "genres": genres,
            "year": year,
            "status": None,
            "score": None,
            # Hindi source: everything is dubbed. Type is "movie" when the
            # hub links contain a movie entry, else "anime".
            "audio": ["dub"],
        }

        hub_links = self._parse_hub_headings(soup)
        is_hub = len(hub_links) >= 2
        base_result["type"] = (
            "movie" if any(k == "movie" for k, _, _, _ in hub_links)
            else "anime"
        )
        if not is_hub:
            # Paragraph-hub fallback: only when no direct content exists.
            direct = self._parse_page_content(soup, default_season, depth=0)
            if not direct["episodes"] and not direct["orphans"] \
                    and not direct["sources"]:
                para_links = self._parse_paragraph_hub_links(soup)
                if len(para_links) >= 4:
                    hub_links = para_links
                    is_hub = True
            if not is_hub:
                seasons = self._build_normal_seasons(direct, title)
                base_result["seasons"] = seasons
                return base_result

        seasons = self._build_hub_response(hub_links, title)
        base_result["seasons"] = seasons
        return base_result

    def streams(self, episode_data):
        variants = parse_variants(episode_data)
        streams = []
        for variant in variants:
            try:
                sub, _ = codedew.resolve_url(
                    variant.get("u", ""),
                    suffix=dub_label(variant.get("k", "")),
                )
                streams.extend(sub)
            except Exception:
                continue
        # Best quality first when known (None sorts last).
        streams.sort(key=lambda s: -(s.get("quality") or 0))
        return {"streams": streams, "subtitles": []}

    # -- hub pages ---------------------------------------------------------

    def _parse_hub_headings(self, soup):
        """[(kind, season_no, text, href)] for season/movie hub links."""
        base = self.base_url
        content = soup.select_one("div.entry-content") or soup
        links = []
        seen = set()
        for el in content.select("h2, h3, h4, li"):
            for a in el.select("a[href]"):
                href = _abs_url(a.get("href"), base)
                if not href or href in seen:
                    continue
                if not _is_internal_post_link(href, base):
                    continue
                seen.add(href)
                text = a.get_text(" ", strip=True)
                heading = el.get_text(" ", strip=True)
                probe = (text + " " + heading)
                m = _SEASON_RE.search(probe)
                if m:
                    links.append(("season", int(m.group(1)), text, href))
                    continue
                m = _MOVIE_RE.search(probe)
                if m:
                    links.append(("movie", int(m.group(1)), text, href))
                    continue
                links.append(("extra", None, text, href))
        # The extension only treats season/movie links as hub links;
        # "extra" links count only via the paragraph fallback.
        return [l for l in links if l[0] in ("season", "movie")]

    def _parse_paragraph_hub_links(self, soup):
        base = self.base_url
        content = soup.select_one("div.entry-content") or soup
        links = []
        seen = set()
        for p in content.select("p"):
            anchors = p.select("a[href]")
            if len(anchors) != 1:
                continue
            a = anchors[0]
            href = _abs_url(a.get("href"), base)
            if not href or href in seen:
                continue
            if not _is_internal_post_link(href, base):
                continue
            text = a.get_text(" ", strip=True)
            if len(text) < 8:
                continue
            rest = p.get_text(" ", strip=True).replace(text, "", 1)
            if len(rest.strip()) > 15:
                continue
            seen.add(href)
            m = _SEASON_RE.search(text)
            kind = "season"
            num = int(m.group(1)) if m else None
            if num is None:
                m = _MOVIE_RE.search(text)
                if m:
                    kind, num = "movie", int(m.group(1))
                else:
                    kind = "extra"
            links.append((kind, num, text, href))
        return links

    def _is_hub_page(self, soup):
        return len(self._parse_hub_headings(soup)) >= 2

    def _load_hub_sub_page(self, url):
        """Load one hub sub-page; returns episode dicts (or [] if nested hub)."""
        try:
            soup = self._soup(url)
        except Exception:
            return []
        if self._is_hub_page(soup):
            return []
        content = soup.select_one("div.entry-content")
        default_season = 1
        if content:
            m = re.search(
                r"Season\s*No[.:]?\s*(\d{1,2})",
                content.get_text(" ", strip=True))
            if m:
                default_season = int(m.group(1))
        parsed = self._parse_page_content(soup, default_season, depth=0)
        episodes = list(parsed["episodes"])
        if not episodes and (parsed["sources"] or parsed["orphans"]):
            # Movie-style sub-page: one synthetic episode with all variants.
            variants = []
            for src in parsed["sources"]:
                variants.append(src["variant"])
            for orphan in parsed["orphans"]:
                variants.append(orphan)
            if variants:
                episodes.append({
                    "season": default_season,
                    "episode": 1,
                    "title": "Full",
                    "variants": variants,
                })
        return episodes

    def _build_hub_response(self, hub_links, title):
        """Load up to 40 sub-pages (chunks of 6) and merge by season:episode."""
        merged = {}  # (season, episode) -> episode dict
        movie_eps = []
        extra_seasons = {}
        max_season = 0

        def _load_one(link):
            kind, num, text, href = link
            eps = self._load_hub_sub_page(href)
            return (kind, num, text, eps)

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(_load_one, hub_links[:40]))

        for kind, num, text, eps in results:
            if kind == "movie" and not any(
                    e.get("episode") and e.get("episode") > 1 for e in eps):
                # Movie link: its episodes go to the synthetic Movies season.
                for idx, ep in enumerate(eps, start=1):
                    movie_eps.append({
                        "season": None,
                        "episode": num if num and len(eps) == 1 else idx,
                        "title": text or ep.get("title") or "Movie",
                        "variants": ep.get("variants", []),
                    })
                continue
            season_no = num
            if kind == "extra" or season_no is None:
                season_no = extra_seasons.get(text)
                if season_no is None:
                    season_no = (max_season or 0) + 100
                    # Renumbered below once the real max is known.
                    extra_seasons[text] = season_no
            if season_no and season_no < 100:
                max_season = max(max_season, season_no)
            for ep in eps:
                ep_no = ep.get("episode") or 1
                key = (season_no, ep_no)
                if key in merged:
                    existing_urls = {
                        v.get("u") for v in merged[key]["variants"]}
                    for v in ep.get("variants", []):
                        if v.get("u") not in existing_urls:
                            merged[key]["variants"].append(v)
                else:
                    merged[key] = {
                        "season": season_no,
                        "episode": ep_no,
                        "title": ep.get("title") or "Episode %d" % ep_no,
                        "variants": list(ep.get("variants", [])),
                    }

        # Extra seasons sit after the highest real season.
        renumber = {}
        next_extra = (max_season or 0) + 1
        for text, placeholder in sorted(extra_seasons.items()):
            renumber[placeholder] = next_extra
            next_extra += 1
        seasons = {}
        for (season_no, _ep_no), ep in sorted(merged.items()):
            real = renumber.get(season_no, season_no)
            seasons.setdefault(real, []).append(ep)
        out = []
        for season_no in sorted(seasons):
            eps = sorted(seasons[season_no], key=lambda e: e["episode"])
            out.append({
                "number": season_no,
                "name": "Season %d" % season_no,
                "episodes": [self._episode_dict(e) for e in eps],
            })
        if movie_eps:
            movie_season = (max(seasons) if seasons else 0) + 1
            movie_eps.sort(key=lambda e: e["episode"])
            out.append({
                "number": movie_season,
                "name": "Movies",
                "episodes": [self._episode_dict(e) for e in movie_eps],
            })
        if not out:
            out = [{
                "number": 1,
                "name": "Season 1",
                "episodes": [],
            }]
        return out

    @staticmethod
    def _episode_dict(ep):
        return {
            "number": ep.get("episode") or 1,
            "title": ep.get("title") or "Episode %d" % (ep.get("episode") or 1),
            "data": variants_json(ep.get("variants", [])),
        }

    # -- normal pages ------------------------------------------------------

    def _parse_page_content(self, soup, default_season, depth):
        """Return {sources, episodes, orphans} for a normal (non-hub) page.

        sources: [{label, variant}] from extractSources (archives/zipper).
        episodes: [{season, episode, title, variants}] from direct rows.
        orphans: [variant] links with no current episode row.
        """
        content = soup.select_one("div.entry-content")
        sources = []
        episodes = []
        orphans = []
        if content is None:
            return {"sources": sources, "episodes": episodes, "orphans": orphans}
        sources = self._extract_sources(content)
        ep_list, orphans = self._parse_direct_episodes(content, default_season)
        episodes.extend(ep_list)
        # Archives are resolved eagerly (max depth 2) into episodes.
        for src in list(sources):
            variant = src["variant"]
            if "/archives/" not in variant.get("u", ""):
                continue
            for ep in self._load_archive(
                    variant["u"], src.get("label", ""), src["variant"].get("k", ""),
                    depth):
                episodes.append(ep)
        return {"sources": sources, "episodes": episodes, "orphans": orphans}

    def _extract_sources(self, content):
        """Walk div.entry-content; keep archive/zipper/zipcloud links."""
        sources = []
        context = ""
        for el in content.find_all(True):
            if el.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                context = el.get_text(" ", strip=True)
                continue
            if el.name != "a":
                continue
            href = el.get("href") or ""
            text = el.get_text(" ", strip=True)
            ctx = context or ""
            if (text or "").lower() in _INFO_LABELS or \
                    ctx.lower() in _INFO_LABELS:
                continue
            if self._is_prose_row(el):
                continue
            kind = None
            if "store.animetoonhindi.com/archives/" in href:
                kind = "archive"
            elif "codedew.com/zipper/" in href:
                kind = "zipper"
            elif "codedew.com/zipcloud/" in href:
                kind = "zipcloud"
            if kind is None:
                continue
            sources.append({
                "label": text or kind,
                "variant": {
                    "n": text or kind,
                    "u": href,
                    "k": dub_key_of(ctx),
                },
            })
        return sources

    def _is_prose_row(self, anchor):
        """True for SEO keyword links inside long prose (<p>/<li> > 80 chars
        where not every link is bracket-wrapped [<a>])."""
        block = anchor.find_parent(["p", "li"])
        if block is None:
            return False
        if len(block.get_text(" ", strip=True)) <= 80:
            return False
        for link in block.find_all("a", href=True):
            prev = link.previous_sibling
            nxt = link.next_sibling
            before_ok = isinstance(prev, str) and prev.rstrip().endswith("[")
            after_ok = isinstance(nxt, str) and nxt.lstrip().startswith("]")
            if not (before_ok and after_ok):
                return True
        return False

    def _parse_direct_episodes(self, content, default_season):
        """Flatten entry-content rows; Episode rows start new episodes."""
        episodes = []
        orphans = []
        current = None
        current_season = default_season
        current_key = dub_key_of("")
        block_tags = ["p", "div", "ul", "ol", "li", "table", "tr", "td",
                      "h1", "h2", "h3", "h4", "h5", "h6"]
        rows = []
        for el in content.find_all(block_tags):
            # Only top-most blocks (skip blocks nested in another row block
            # other than the entry-content container itself).
            parent = el.find_parent(block_tags)
            if parent is not None and parent is not content:
                continue
            rows.append(el)
        for row in rows:
            text = row.get_text(" ", strip=True)
            if not text:
                continue
            if row.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                m = _SEASON_ROW_RE.match(text)
                if m:
                    current_season = int(m.group(1))
                    current_key = dub_key_of(text)
                    continue
            m = _SEASON_ROW_RE.match(text)
            if m:
                current_season = int(m.group(1))
                current_key = dub_key_of(text)
                continue
            m = _EP_ROW_RE.match(text)
            if m:
                current = {
                    "season": current_season,
                    "episode": int(m.group(1)),
                    "title": "Episode %s" % m.group(1),
                    "variants": [],
                }
                episodes.append(current)
            links = row.select('a[href*="codedew.com/zipper/"], '
                               'a[href*="codedew.com/zipcloud/"]')
            if not links:
                continue
            if self._is_prose_row(links[0]):
                continue
            lang = ""
            span = row.select_one("span:not(.ra-serv-txt)")
            if span:
                lang = language_from_text(span.get_text(" ", strip=True))
            if not lang:
                before = text.split("[", 1)[0]
                lang = language_from_text(before)
            key = current_key or lang
            for a in links:
                href = a.get("href") or ""
                if not href:
                    continue
                variant = {
                    "n": a.get_text(" ", strip=True) or "Watch",
                    "u": href,
                    "k": key,
                }
                if current is None:
                    orphans.append(variant)
                else:
                    current["variants"].append(variant)
        return episodes, orphans

    def _load_archive(self, url, label, context_key, depth):
        """Load a store archive page; returns episode dicts (depth <= 2)."""
        if depth >= 2:
            return []
        try:
            soup = self._soup(url)
        except Exception:
            return []
        title = soup.title.get_text(strip=True) if soup.title else ""
        key = dub_key_of(title) or context_key
        lower_title = title.lower()
        if "multiquality" in lower_title:
            source_name = "WatchMultiQuality"
        elif "hubcloud" in lower_title:
            source_name = "HubCloud"
        elif "watchnow" in lower_title:
            source_name = "WatchNow"
        else:
            source_name = label or "Archive"
        content = soup.select_one("div.entry-content")
        found = []
        if content is not None:
            for a in content.select("a[href]"):
                href = a.get("href") or ""
                if "codedew.com/zipper/" not in href and \
                        "codedew.com/zipcloud/" not in href:
                    continue
                name = a.get_text(" ", strip=True)
                if not name:
                    continue
                found.append((name, href))
        if len(found) > 1:
            episodes = []
            for name, href in found:
                _s, ep_no = parse_episode_number(name)
                episodes.append({
                    "season": 1,
                    "episode": ep_no or len(episodes) + 1,
                    "title": name,
                    "variants": [{
                        "n": source_name, "u": href, "k": key,
                    }],
                })
            return episodes
        if len(found) == 1:
            name, href = found[0]
            sub, _ = codedew.resolve_url(href, suffix=dub_label(key))
            if sub:
                return [{
                    "season": 1,
                    "episode": 1,
                    "title": name,
                    "variants": [{"n": source_name, "u": href, "k": key}],
                }]
            return []
        if content is not None:
            first = content.select_one('a[href*="codedew.com"]')
            if first is not None:
                href = first.get("href") or ""
                if href:
                    sub, _ = codedew.resolve_url(href, suffix=dub_label(key))
                    if sub:
                        return [{
                            "season": 1,
                            "episode": 1,
                            "title": "Full",
                            "variants": [{
                                "n": source_name, "u": href, "k": key,
                            }],
                        }]
        return []

    def _build_normal_seasons(self, parsed, title):
        """Assemble seasons for a normal page from parsed content."""
        episodes = list(parsed["episodes"])
        all_variants = []
        for src in parsed["sources"]:
            all_variants.append(src["variant"])
        all_variants.extend(parsed["orphans"])

        numbered = [e for e in episodes if e.get("episode")]
        if not numbered:
            # Movie: every variant in one synthetic episode.
            if not all_variants:
                return [{
                    "number": 1,
                    "name": "Season 1",
                    "episodes": [],
                }]
            return [{
                "number": 1,
                "name": "Season 1",
                "episodes": [{
                    "number": 1,
                    "title": title,
                    "data": variants_json(all_variants),
                }],
            }]

        # Attach source variants with no episode to the first episode —
        # but only when the URL is not already claimed by any episode
        # (extractSources sees the same <a> elements the episode rows do).
        known_urls = set()
        for ep in numbered:
            for v in ep.get("variants", []):
                if v.get("u"):
                    known_urls.add(v["u"])
        for variant in all_variants:
            if variant.get("u") and variant["u"] not in known_urls:
                known_urls.add(variant["u"])
                numbered[0].setdefault("variants", []).append(variant)

        dub_keys = set()
        for ep in numbered:
            for v in ep.get("variants", []):
                if v.get("k"):
                    dub_keys.add(v.get("k"))
        out = []
        if len(dub_keys) >= 2:
            # Each dub becomes its own synthetic season.
            ordered_keys = sorted(dub_keys)
            for idx, key in enumerate(ordered_keys, start=1):
                eps = []
                for ep in numbered:
                    vs = [v for v in ep.get("variants", [])
                          if v.get("k") == key]
                    if not vs:
                        continue
                    eps.append({
                        "number": ep["episode"],
                        "title": ep.get("title") or "Episode %d" % ep["episode"],
                        "data": variants_json(vs),
                    })
                if eps:
                    eps.sort(key=lambda e: e["number"])
                    out.append({
                        "number": idx,
                        "name": dub_label(key),
                        "episodes": eps,
                    })
            return out or [{
                "number": 1, "name": "Season 1", "episodes": [],
            }]

        seasons = {}
        for ep in numbered:
            seasons.setdefault(ep.get("season") or 1, []).append(ep)
        for season_no in sorted(seasons):
            eps = []
            for ep in seasons[season_no]:
                eps.append({
                    "number": ep["episode"],
                    "title": ep.get("title") or "Episode %d" % ep["episode"],
                    "data": variants_json(ep.get("variants", [])),
                })
            eps.sort(key=lambda e: e["number"])
            out.append({
                "number": season_no,
                "name": "Season %d" % season_no,
                "episodes": eps,
            })
        return out
