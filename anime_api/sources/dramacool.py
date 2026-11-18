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
  streamtape servers) — then resolve it to a DIRECT HLS file (v1.4.1).
  The embed host (hglink.to / hgcloud.to / dhcplay.com) is only a
  JS redirector: its ``main.js`` sends the browser to a random
  main domain (hanerix.com / audinifer.com / vibuxer.com), which
  serves a JWPlayer page whose stream URL sits inside a Dean
  Edwards ``eval(p,a,c,k,e,d)`` packed block. This module unpacks
  that block server-side (no JS engine) and returns the direct
  ``master.txt``/``.m3u8`` URL as ``type: "hls"`` with ``proxy:
  true`` — the CDN 404s without the player-page ``Referer``, so the
  stream carries it in ``headers`` and must be played through
  ``/api/proxy``. If no direct file is found the episode returns
  NO streams at all (never an ``embed`` — StreamHub plays nothing
  through iframes).

Verified live 2026-11-18 from the Mumbai server: episode 1 of
"The Confession Truth" (cdrama) -> hgcloud embed
``https://hgcloud.to/e/exu5fvn2tqdg`` -> hanerix player ->
direct HLS ``https://cwfuommwagyrfcg6.retailplatform.shop/
dwjdqozeoybz/hls3/01/15268/2xxqmkpq929u_n/master.txt`` (720p,
1080s); master playlist 200 + variant playlist 200 + first
segment 200 (video/MP2T, 1,302,840 bytes) through ``/api/proxy``
with the player Referer (direct fetch without it 404s).
"""

import base64
import html
import json
import re
from urllib.parse import quote_plus, unquote, urljoin, urlsplit

import json
import re
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from anime_api.http import BROWSER_UA, get
from anime_api.sources.base import Source

_SEARCH_API_MARKER = '"u":"https://api.dramacool.rest/v1/drama/search'

_DRAMA_RE = re.compile(r"^/drama/([a-z0-9][a-z0-9\-]*)/?$")
_EPISODE_RE = re.compile(r"^/drama/[a-z0-9][a-z0-9\-]*/episode-(\d+)/?$")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_EMBED_RE = re.compile(
    r"https?://[a-z0-9.\-]*(?:vidmoly|streamtape|dood|filemoon|voe|mixdrop"
    r"|upstream|streamwish|vidhide|filelions|vidbasic|hgcloud|hglink"
    r"|dhcplay)\.[a-z]{2,10}/[^\s\"'<>]+",
    re.IGNORECASE,
)

_COUNTRY_URLS = {
    "kdrama": "/explore?country=South%20Korea",
    "cdrama": "/explore?country=China",
}

# Embed-host redirect (deobfuscated from hgcloud.to/main.js, 2026-11-18):
# hglink.to / hgcloud.to / dhcplay.com embed pages JS-redirect to a
# random one of these main domains, which serve the real JWPlayer page.
_REDIRECT_HOSTS = ("hglink.to", "hgcloud.to", "dhcplay.com")
_MAIN_HOSTS = ("hanerix.com", "audinifer.com", "vibuxer.com")
_PACKER_MARKER = "eval(function(p,a,c,k,e,d){"

# vidbasic 3rd-party player (deobfuscated 2026-11-18): the file URL
# is AES-256-CBC encrypted in the player page's
# <script data-name="crypto" data-value="..."> (the same base64 value
# is also the player URL's ?key= param). The key/iv below are the
# player page's own public constants (visible in its JS) — if the
# player rotates them, vidbasic extraction breaks and they must be
# re-derived from the live player JS.
_VB_KEY = b"94588293375053432799222445521289"
_VB_IV = b"5259228356829423"
_VB_CRYPTO_RE = re.compile(
    r"""data-name=['"]crypto['"][^>]*data-value=['"]([^'"]+)""")
_FILE_RE = re.compile(r"""file\s*:\s*["'](https?://[^"']+)["']""")
_MEDIA_RE = re.compile(
    r"https?://[^\s\"'<>]+\.(?:m3u8|mp4|txt)\b[^\s\"'<>]*")
_QUALITY_RE = re.compile(r"['\"](\d+)['\"]\s*:\s*['\"](\d+)p['\"]")


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


def _skip_js_string(s, i):
    """Index just past a JS string literal starting at ``s[i]``."""
    q = s[i]
    i += 1
    while i < len(s):
        ch = s[i]
        if ch == "\\":
            i += 2
            continue
        if ch == q:
            return i + 1
        i += 1
    return i


def _match_brace(s, i):
    """``s[i] == '{'`` -> index just past the matching ``}``."""
    depth = 0
    while i < len(s):
        ch = s[i]
        if ch in ("'", '"', "`"):
            i = _skip_js_string(s, i)
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def _match_paren(s, i):
    """``s[i] == '('`` -> index just past the matching ``)``."""
    depth = 0
    while i < len(s):
        ch = s[i]
        if ch in ("'", '"', "`"):
            i = _skip_js_string(s, i)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def _parse_js_string(s, i):
    """JS string literal at ``s[i]`` -> (value, index just past it)."""
    q = s[i]
    i += 1
    out = []
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == "n":
                out.append("\n")
            elif nxt == "r":
                out.append("\r")
            elif nxt == "t":
                out.append("\t")
            elif nxt == "u" and i + 5 < len(s):
                try:
                    out.append(chr(int(s[i + 2:i + 6], 16)))
                except ValueError:
                    out.append(nxt)
                i += 4
            else:
                out.append(nxt)
            i += 2
            continue
        if ch == q:
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    raise ValueError("unterminated string")


def _split_top_level(s):
    """Split a JS call-argument list on top-level commas."""
    parts, depth, i, cur = [], 0, 0, ""
    in_str = None
    while i < len(s):
        ch = s[i]
        if in_str:
            cur += ch
            if ch == "\\" and i + 1 < len(s):
                cur += s[i + 1]
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in ("'", '"'):
            in_str = ch
            cur += ch
        elif ch in ("([{"):
            depth += 1
            cur += ch
        elif ch in (")]}"):
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
        i += 1
    if cur.strip():
        parts.append(cur.strip())
    return parts


def _encode_base(num, base):
    """Packer token for ``num`` in base ``base`` (0-9a-zA-Z)."""
    chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if num < base:
        return chars[num]
    out = ""
    while num:
        out = chars[num % base] + out
        num //= base
    return out or "0"


def _unpack_packer(html):
    """Unpack every Dean Edwards ``eval(p,a,c,k,e,d)`` block in ``html``.

    The packed call is ``eval(function(p,a,c,k,e,d){...}('payload',
    base, count, 'w1|w2|...'.split('|'), 0, {}))`` — a regex cannot
    find the argument list (the payload itself contains ``))``), so
    the function body and the argument list are matched with
    string-aware brace/paren scanners. Returns the unpacked JS
    strings (possibly empty).
    """
    unpacked = []
    start = 0
    while True:
        at = html.find(_PACKER_MARKER, start)
        if at < 0:
            break
        brace_open = at + len(_PACKER_MARKER) - 1
        body_end = _match_brace(html, brace_open)
        if body_end < 0:
            break
        j = body_end
        while j < len(html) and html[j] in " \t\r\n":
            j += 1
        if j >= len(html) or html[j] != "(":
            start = body_end
            continue
        args_end = _match_paren(html, j)
        if args_end < 0:
            break
        try:
            parts = _split_top_level(html[j + 1:args_end - 1])
            if len(parts) >= 4:
                payload, _ = _parse_js_string(parts[0].strip(), 0)
                base = int(parts[1].strip())
                count = int(parts[2].strip())
                k_str, _ = _parse_js_string(parts[3].strip(), 0)
                words = k_str.split("|")
                result = payload
                n = count
                while n:
                    n -= 1
                    if n < len(words) and words[n]:
                        result = re.sub(
                            r"\b" + _encode_base(n, base) + r"\b",
                            lambda m, w=words[n]: w, result)
                unpacked.append(result)
        except Exception:
            pass
        start = args_end
    return unpacked


def _vb_decrypt(cipher_b64):
    """AES-256-CBC decrypt a vidbasic crypto payload -> file URL or None."""
    try:
        from cryptography.hazmat.primitives.ciphers import (
            Cipher, algorithms, modes)
        raw = base64.b64decode(cipher_b64)
        cipher = Cipher(algorithms.AES(_VB_KEY), modes.CBC(_VB_IV))
        dec = cipher.decryptor()
        plain = dec.update(raw) + dec.finalize()
        pad = plain[-1]
        if 0 < pad <= 16:
            plain = plain[:-pad]
        return plain.decode("utf-8", "replace").strip()
    except Exception:
        return None


def _episode_stream_urls(page_html, ep_url):
    """This episode's server URLs from the page's embedded episodes JSON.

    The episode page carries a JSON blob with one entry per episode
    (``"episodes":[{"number":1,"streamUrls":[{"source":...,"url":...},
    ...]}, ...]``). Only the CURRENT episode's URLs are returned —
    the page also matches the site-wide embed regex for every other
    episode, and playing another episode's server would be the wrong
    content. Returns [] when the blob is absent/unparseable.
    """
    num = None
    m = re.search(r"/episode-(\d+)", ep_url or "")
    if m:
        try:
            num = int(m.group(1))
        except ValueError:
            num = None
    at = page_html.find('"episodes":[')
    if at < 0:
        return []
    try:
        arr, _ = json.JSONDecoder().raw_decode(
            page_html[at + len('"episodes":'):])
    except Exception:
        return []
    if not isinstance(arr, list):
        return []
    for entry in arr:
        if not isinstance(entry, dict):
            continue
        if num is not None and entry.get("number") != num:
            continue
        urls = []
        for s in entry.get("streamUrls") or []:
            u = (s or {}).get("url") or ""
            if u.startswith("http") and u not in urls:
                urls.append(u)
        if urls:
            return urls
        if num is None:
            break
    return []
    """Direct media URL out of a player page -> (url, quality) or None.

    Tries a plain ``file: "https://...m3u8"`` first, then the same
    search inside every unpacked ``eval(p,a,c,k,e,d)`` block. The
    quality comes from the JWPlayer ``qualityLabels`` map
    (``{"815": "720p"}``) when present.
    """
    candidates = [html] + _unpack_packer(html)
    for text in candidates:
        quals = [int(q) for _, q in _QUALITY_RE.findall(text)]
        quality = max(quals) if quals else None
        for m in _FILE_RE.finditer(text):
            if re.search(r"\.(m3u8|mp4|txt)\b", m.group(1)):
                return m.group(1), quality
        for m in _MEDIA_RE.finditer(text):
            return m.group(0), quality
    return None


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

    def _direct_from_vidbasic(self, embed_url, ep_url):
        """vidbasic embed -> direct HLS/MP4 via its AES 3rd-party player.

        ``/embed/<id>`` loads ``/3rdplayer.html?key=<cipher>&id=<id>``;
        the player page carries the same base64 ciphertext in
        ``<script data-name="crypto" data-value="...">``; AES-256-CBC
        decrypting it (player constants ``_VB_KEY``/``_VB_IV``) yields
        the direct ``index.m3u8`` URL. Verified live 2026-11-18
        ("Pieces of Guilt" ep 1 -> ``https://hls.vidbasic.top/
        1f412d05-.../index.m3u8``; master 200 + variant 200 + first
        segment 200 fMP4 through ``/api/proxy``, no Referer needed).
        """
        try:
            resp = get(embed_url, headers={"Referer": ep_url}, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception:
            return None
        player_url = None
        iframe = soup.select_one("iframe[src*='3rdplayer.html']")
        if iframe and iframe.get("src"):
            player_url = urljoin(embed_url, iframe.get("src").strip())
        if not player_url:
            m = re.search(r'data-video="([^"]*3rdplayer\.html[^"]*)"',
                          resp.text)
            if m:
                player_url = urljoin(embed_url, html.unescape(m.group(1)))
        if not player_url:
            return None
        try:
            resp = get(player_url, headers={"Referer": embed_url},
                       timeout=15)
            resp.raise_for_status()
        except Exception:
            return None
        cipher_b64 = None
        m = _VB_CRYPTO_RE.search(resp.text)
        if m:
            cipher_b64 = m.group(1)
        if not cipher_b64:
            m = re.search(r"[?&]key=([^&\s\"']+)", player_url)
            if m:
                cipher_b64 = unquote(m.group(1))
        if not cipher_b64:
            return None
        file_url = _vb_decrypt(cipher_b64)
        if not file_url or not file_url.startswith("http"):
            return None
        is_hls = ".m3u8" in file_url
        return {
            "name": "DramaCool",
            "url": file_url,
            "quality": None,
            "type": "hls" if is_hls else "video",
            "headers": {"Referer": player_url,
                        "User-Agent": BROWSER_UA},
            "proxy": True,
            "label": "DramaCool Player",
        }

    def _direct_from_embed(self, embed_url, ep_url):
        """One embed URL -> direct HLS stream dict, or None.

        The embed host itself serves only a JS redirector / loader,
        so the real player page is fetched — directly for hosts that
        serve it, or via the redirector's main domains for the
        hglink/hgcloud/dhcplay family — and its packed JWPlayer
        block is unpacked for the direct file URL. The CDN 404s
        without the player-page Referer, so the stream carries it.
        """
        try:
            host = urlsplit(embed_url).hostname or ""
        except Exception:
            host = ""
        if host == "vidbasic.top":
            return self._direct_from_vidbasic(embed_url, ep_url)
        candidates = [embed_url]
        try:
            parts = urlsplit(embed_url)
            if parts.hostname in _REDIRECT_HOSTS:
                for host in _MAIN_HOSTS:
                    candidates.append("https://%s%s"
                                      % (host, parts.path or "/"))
        except Exception:
            pass
        for url in candidates:
            try:
                resp = get(url, headers={"Referer": ep_url}, timeout=15)
                resp.raise_for_status()
                found = _extract_file_url(resp.text)
            except Exception:
                continue
            if not found:
                continue
            file_url, quality = found
            is_hls = bool(re.search(r"\.(m3u8|txt)\b", file_url))
            return {
                "name": "DramaCool",
                "url": file_url,
                "quality": quality,
                "type": "hls" if is_hls else "video",
                # The CDN 404s without a Referer (verified live) —
                # play through /api/proxy, which forwards Referer + UA.
                "headers": {"Referer": url, "User-Agent": BROWSER_UA},
                "proxy": True,
                "label": "DramaCool %s" % (
                    "%dp" % quality if quality else "Player"),
            }
        return None

    def streams(self, episode_data):
        """Episode page -> DIRECT HLS stream (never an embed).

        Each iframe/server link on the episode page is resolved to
        its direct file URL; the first that resolves wins. An
        episode whose hosts yield no direct file returns no streams
        — the app drops it instead of showing a dead Play button.
        """
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
        # The page's embedded episodes JSON lists THIS episode's
        # servers exactly (the site-wide embed regex also matches
        # every other episode's servers — never use those).
        for href in _episode_stream_urls(resp.text, ep_url):
            if href not in seen:
                seen.add(href)
                urls.append(href)
        if not urls:
            for href in _EMBED_RE.findall(resp.text):
                if href not in seen:
                    seen.add(href)
                    urls.append(href)
        streams = []
        # The episode page lists several servers (hgcloud, hglink,
        # vidbasic, mixdrop, dood, ...); try each in order until one
        # yields a direct file. Servers this module cannot resolve
        # (e.g. mixdrop/dood) are skipped, never returned as embeds.
        for url in urls[:6]:
            direct = self._direct_from_embed(url, ep_url)
            if direct:
                streams.append(direct)
                break
        return {"streams": streams, "subtitles": []}
