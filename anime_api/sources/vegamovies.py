"""Vegamovies source — Hindi / dual-audio movies (+ web series).

Site: ``https://vegamovies.lease`` (WordPress; live domain via the
Firebase map key ``vegamovies``). Ported from the Vegamovies provider
in the CINEMORA Android app (itself a port of the Vegamovies
CloudStream plugin in dipender98/Indflix, GPL-3.0).

Endpoints used (all public, no login):

* ``search`` — ``GET {host}/ts-search.php?q=<query>&page=1`` returns
  Typesense-style JSON ``{"hits": [{"document": {"permalink",
  "post_title", "post_thumbnail"}}]}``. ``permalink`` may be
  relative — it is absolutized against the base. Fallback: the plain
  WordPress search page ``GET {host}/?s=<query>`` parsed as a listing.
* ``home`` — poster-cards (``div.poster-card``) on ``GET {host}/``
  (``latest``), ``/dual-audio-movies/`` (``trending``) and
  ``/hindi-dubbed-movies/`` (``popular``). Page > 1 appends
  ``page/<n>/`` (WordPress pagination).
* ``details`` — ``GET <detail URL>`` (``/download-<slug>/``). The
  ``div.entry-content`` carries download groups: an ``<h*>`` heading
  (quality, e.g. "720p [2.3GB]") followed by ``nexdrive`` gateway
  links (``...nexdrive.<tld>/genxfm...``). One episode is emitted per
  download group so the user picks a quality; episode ``data`` is a
  JSON string ``{"page": <detail url>, "gateways": [<gateway urls>],
  "heading": <group heading>}``.
* ``streams`` — each gateway expands (``GET`` the gateway page with
  the detail page as Referer) to ``fastdl`` embed links and ``vcloud``
  links. A fastdl embed (``fastdl.<tld>/embed.php?download=...``)
  resolves to a direct ``video-downloads.googleusercontent.com``
  file URL (``type: "video"``). A vcloud link resolves via the
  double-``atob`` token page to direct R2 file links (``type:
  "video"``). Verified live 2026-11-18 from the Mumbai server:
  search "avengers" 11 hits; detail carries 8 gateways; gateway
  expands to fastdl + vcloud; fastdl direct file HEAD 200
  (940,129,536 bytes).
"""

import base64
import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from anime_api.http import get, get_json
from anime_api.sources.base import Source

_YEAR_RE = re.compile(r"\((\d{4})")
_QUALITY_RE = re.compile(r"(?i)\b(\d{3,4})p\b")
_GENXFM_RE = re.compile(
    r"https?://[a-z0-9.\-]*nexdrive\.[a-z]{2,10}/genxfm[^\s\"'<>\\]+",
    re.IGNORECASE,
)
_FASTDL_RE = re.compile(
    r"https?://fastdl\.[a-z]{2,10}/embed(?:\.php)?\?download=[A-Za-z0-9_\-]+",
    re.IGNORECASE,
)
_VCLOUD_RE = re.compile(
    r"https?://vcloud\.[a-z]{2,10}/[A-Za-z0-9_\-]{6,}",
    re.IGNORECASE,
)
_DIRECT_RE = re.compile(r"https://video-downloads\.googleusercontent\.com/\S+")
_ATOB_RE = re.compile(
    r"var\s+url\s*=\s*atob\s*\(\s*atob\s*\(\s*['\"]([A-Za-z0-9+/=]{16,})['\"]\s*\)\s*\)"
)
_BTN_RE = re.compile(
    r"<a\b[^>]*href=\"([^\"]+)\"[^>]*>\s*(?:<[^>]+>\s*)*([^<]*(?:Download|Server|File)[^<]*)(?:<[^>]+>\s*)*</a>",
    re.IGNORECASE,
)
_STREAMABLE_RE = re.compile(r"(r2\.cloudflarestorage\.com|r2\.dev)", re.IGNORECASE)
_DOWNLOAD_HEADING_RE = re.compile(
    r"(?i)(\d{3,4}p\b|4K|WEB[\s-]?DL|WEBRip|Blu\s?Ray|BD-?Rip|HD-?Rip|DVDRip|x26[45]|HEVC|AVC\b|\d+(?:\.\d+)?\s?(?:GB|MB)(?:/|\b)|/ZiP|/ZIP|\bZIP\b|Batch|Season\s*\d|\bPack\b|Complete|DUAL\s*[- ]?AUDIO|HINDI|TAMIL|TELUGU|\bEP(?:\.|ISODE)?\s*\d|S\d{1,2}[\s._-]?E\d{1,3})"
)

_HOME_URLS = {
    "latest": "/",
    "trending": "/dual-audio-movies/",
    "popular": "/hindi-dubbed-movies/",
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


def _quality_of(heading):
    if not heading:
        return None
    found = _QUALITY_RE.findall(heading)
    if found:
        try:
            return max(int(q) for q in found)
        except ValueError:
            return None
    if re.search(r"(?i)\b4K\b", heading):
        return 2160
    return None


def _clean_title(raw):
    """Port of the Cinemora provider's cleanSearchTitle."""
    t = (raw or "").strip()
    t = t[len("Download"):].strip() if t.lower().startswith("download") else t
    m = re.search(r"(.*?\(\d{4}[^)]*\))", t)
    if m:
        return m.group(1).strip().strip(" -|:,")
    t = re.sub(
        r"(?i)\)\s*(\d{3,4}p[\s\S]*|WEB[\s-]?DL.*|BluRay.*|HDTS.*|HDTV.*|4K.*|Dual Audio.*|Hindi.*|S\d{2}E\d{2,}.*)$",
        "", t,
    ).strip()
    # Titles without a (year) still carry a trailing quality/audio tail
    # ("Some Movie Dual Audio Hindi" -> "Some Movie").
    t = re.sub(
        r"(?i)\s+(\d{3,4}p.*|WEB[\s-]?DL.*|BluRay.*|Dual Audio.*|Hindi.*|S\d{2}E\d{2,}.*)$",
        "", t,
    ).strip()
    return t.strip(" -|:,") or (raw or "").strip()[:80]


class Vegamovies(Source):
    id = "vegamovies"
    name = "Vegamovies"
    language = "hindi"
    domain_key = "vegamovies"
    default_url = "https://vegamovies.lease"
    media_type = "movie"

    # -- fetching ----------------------------------------------------------

    def _soup(self, url, referer=None):
        headers = {"Referer": referer} if referer else None
        resp = get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")

    def _parse_listing(self, soup):
        """div.poster-card elements -> item dicts (deduped, order kept)."""
        base = self.base_url
        items, seen = [], set()
        for card in soup.select("div.poster-card"):
            try:
                href = None
                meta = card.select_one("meta[itemprop=url]")
                if meta and meta.get("content"):
                    href = _abs_url(meta.get("content"), base)
                if not href:
                    a = card.select_one('a[href*="/download-"]')
                    if a:
                        href = _abs_url(a.get("href"), base)
                if not href or "/download-" not in href or href in seen:
                    continue
                img = card.select_one("img")
                raw = ""
                if img is not None:
                    raw = img.get("alt") or ""
                if not raw:
                    t = card.select_one(".poster-title, h2, h3")
                    raw = t.get_text(strip=True) if t else ""
                if not raw:
                    continue
                seen.add(href)
                poster = None
                if img is not None:
                    for attr in ("data-src", "data-lazy-src", "src"):
                        v = img.get(attr)
                        if v and not v.startswith("data:"):
                            poster = _abs_url(v, base)
                            break
                year = None
                m = _YEAR_RE.search(raw)
                if m:
                    try:
                        year = int(m.group(1))
                    except ValueError:
                        year = None
                items.append({
                    "id": href,
                    "title": _clean_title(raw),
                    "poster": poster,
                    "year": year,
                    # The home rows mix web series in with the movies
                    # ("... {S03E06 Added}", "Web Series"); label those
                    # as series so clients don't file them as movies.
                    "type": ("anime" if re.search(
                        r"(?i)S\d{1,2}E\d{1,3}|web[- ]?series|season\s*\d",
                        raw) else "movie"),
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
        try:
            url = "%s/ts-search.php?q=%s&page=%d" % (
                base, quote_plus(query.strip()), page)
            data = get_json(url, headers={"Referer": base + "/"}, timeout=30)
            items = []
            for hit in (data or {}).get("hits") or []:
                try:
                    doc = (hit or {}).get("document") or {}
                    permalink = _abs_url(doc.get("permalink"), base)
                    raw = (doc.get("post_title") or "").strip()
                    if not permalink or not raw:
                        continue
                    year = None
                    m = _YEAR_RE.search(raw)
                    if m:
                        try:
                            year = int(m.group(1))
                        except ValueError:
                            year = None
                    items.append({
                        "id": permalink,
                        "title": _clean_title(raw),
                        "poster": _abs_url(doc.get("post_thumbnail"), base),
                        "year": year,
                        "type": "movie",
                        "audio": ["dub"],
                        "source": self.id,
                    })
                except Exception:
                    continue
            if items:
                return items
        except Exception:
            pass
        # Fallback: plain WordPress search page.
        try:
            soup = self._soup(
                "%s/?s=%s" % (base, quote_plus(query.strip())),
                referer=base + "/")
            return self._parse_listing(soup)
        except Exception:
            return []

    def home(self, section, page=1):
        try:
            path = _HOME_URLS.get(section, _HOME_URLS["latest"])
            url = self.base_url + path
            if page > 1:
                url = url + "page/%d/" % page
            soup = self._soup(url)
            return self._parse_listing(soup)
        except Exception:
            return []

    def details(self, item_id):
        try:
            soup = self._soup(item_id)
        except Exception:
            return {"error": "movie not found"}
        h1 = soup.select_one("h1, .entry-title, .post-title")
        raw_title = h1.get_text(strip=True) if h1 else ""
        if not raw_title:
            og = soup.select_one('meta[property="og:title"]')
            raw_title = og.get("content", "").strip() if og else ""
        if not raw_title:
            return {"error": "movie not found"}
        title = _clean_title(raw_title)
        year = None
        m = _YEAR_RE.search(raw_title)
        if m:
            try:
                year = int(m.group(1))
            except ValueError:
                year = None
        poster = None
        og_img = soup.select_one('meta[property="og:image"]')
        if og_img and og_img.get("content"):
            poster = _abs_url(og_img.get("content"), self.base_url)
        plot = None
        entry = soup.select_one("div.entry-content")
        entry_text = (entry.get_text(" ", strip=True) if entry is not None
                      else (soup.body.get_text(" ", strip=True)
                            if soup.body else ""))
        syn = re.search(r"(?i)SYNOPSIS[^:]*:\s*(.*)", entry_text)
        if syn:
            plot = syn.group(1).strip()
            # The synopsis runs into the next section (Screenshots /
            # download groups) in the flattened text — cut there.
            cut = re.search(
                r"(?i)screenshots|download |movie info:|watch online", plot)
            if cut:
                plot = plot[:cut.start()].strip()
            plot = plot[:1200] or None
        genres = []
        if entry is not None:
            for p in entry.select("p, li"):
                m = re.match(r"(?i)Language:\s*(.+)",
                            p.get_text(" ", strip=True))
                if m:
                    genres = [m.group(1).strip()]
                    break
        groups = self._parse_groups(soup)
        episodes = []
        for idx, (heading, gateways) in enumerate(groups, start=1):
            episodes.append({
                "number": idx,
                "title": heading.strip()[:120] or "Download %d" % idx,
                "data": json.dumps({
                    "page": item_id,
                    "gateways": gateways,
                    "heading": heading,
                }),
            })
        if not episodes:
            episodes = [{
                "number": 1,
                "title": title,
                "data": json.dumps({"page": item_id, "gateways": [],
                                    "heading": ""}),
            }]
        return {
            "id": item_id,
            "title": title,
            "poster": poster,
            "banner": poster,
            "plot": plot,
            "genres": genres,
            "year": year,
            "status": "completed",
            "score": None,
            "type": "movie",
            "audio": ["dub"],
            "seasons": [{
                "number": 1,
                "name": "Movie",
                "episodes": episodes,
            }],
        }

    def _parse_groups(self, soup):
        """(heading, [gateway urls]) per download group in entry-content."""
        groups = []
        heading = ""
        anchors = []

        def close():
            if anchors and heading.strip():
                groups.append((heading, sorted(set(anchors))))

        root = soup.select_one("div.entry-content, article, main") or soup.body
        if root is None:
            return []
        for el in root.find_all(True):
            try:
                tag = el.name or ""
                if re.match(r"h[1-6]$", tag):
                    t = el.get_text(" ", strip=True)
                    if t and len(t) < 220:
                        if anchors:
                            close()
                            anchors = []
                        heading = t if _DOWNLOAD_HEADING_RE.search(t) else ""
                elif tag == "a":
                    href = el.get("href") or ""
                    if _GENXFM_RE.search(href):
                        anchors.append(href.strip().rstrip("/") + "/")
            except Exception:
                continue
        close()
        # Merge groups sharing a heading (the same quality listed twice).
        merged = {}
        order = []
        for heading, links in groups:
            if heading not in merged:
                merged[heading] = []
                order.append(heading)
            for link in links:
                if link not in merged[heading]:
                    merged[heading].append(link)
        return [(h, merged[h]) for h in order if merged[h]]

    # -- streams -----------------------------------------------------------

    def streams(self, episode_data):
        try:
            parsed = json.loads(str(episode_data or ""))
            gateways = parsed.get("gateways") or []
            page = parsed.get("page") or self.base_url + "/"
            heading = parsed.get("heading") or ""
        except Exception:
            return {"streams": [], "subtitles": []}
        if not gateways:
            return {"streams": [], "subtitles": []}
        streams = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(
                lambda g: self._expand_gateway(g, page, heading), gateways))
        for found in results:
            streams.extend(found)
        streams.sort(key=lambda s: -(s.get("quality") or 0))
        seen, unique = set(), []
        for s in streams:
            if s["url"] not in seen:
                seen.add(s["url"])
                unique.append(s)
        return {"streams": unique, "subtitles": []}

    def _expand_gateway(self, gateway_url, referer, heading):
        """One nexdrive gateway -> fastdl direct file + vcloud R2 files."""
        out = []
        try:
            resp = get(gateway_url,
                       headers={"Referer": referer,
                                "Accept": "text/html,application/xhtml+xml"},
                       timeout=30)
            html = resp.text
        except Exception:
            return out
        quality = _quality_of(heading)
        for embed in _FASTDL_RE.findall(html):
            try:
                body = get(embed, headers={"Referer": gateway_url,
                                           "Accept": "text/html,application/xhtml+xml"},
                           timeout=30).text
            except Exception:
                continue
            m = _DIRECT_RE.search(body)
            if m:
                out.append({
                    "name": "Vegamovies G-Drive",
                    "url": m.group(0).rstrip("\"'"),
                    "quality": quality,
                    "type": "video",
                    "headers": {"Referer": "https://fastdl.zip/"},
                    "proxy": False,
                    "label": "G-Drive %s" % (heading.strip()[:40] or "Movie"),
                })
        for vcloud in _VCLOUD_RE.findall(html):
            out.extend(self._resolve_vcloud(vcloud, gateway_url, quality,
                                            heading))
        return out

    def _resolve_vcloud(self, vcloud_url, referer, quality, heading):
        """Vcloud: double-atob token page -> R2 file links."""
        out = []
        try:
            page = get(vcloud_url, headers={"Referer": referer},
                       timeout=30).text
        except Exception:
            return out
        m = _ATOB_RE.search(page)
        if not m:
            return out
        try:
            inner = base64.b64decode(m.group(1)).decode()
            token_url = base64.b64decode(inner).decode()
        except Exception:
            return out
        if not token_url.startswith("http"):
            return out
        try:
            token_html = get(token_url, headers={"Referer": vcloud_url},
                             timeout=30).text
        except Exception:
            return out
        seen = set()
        for href, label in _BTN_RE.findall(token_html):
            href = href.strip()
            if not _STREAMABLE_RE.search(href) or href in seen:
                continue
            seen.add(href)
            tag = re.search(r"\[([^\]]+)\]", label or "")
            out.append({
                "name": "Vegamovies V-Cloud",
                "url": href,
                "quality": quality,
                "type": "video",
                "headers": {"Referer": vcloud_url},
                "proxy": False,
                "label": "V-Cloud %s" % (tag.group(1).strip() if tag
                                         else (heading.strip()[:40] or "Movie")),
            })
        return out
