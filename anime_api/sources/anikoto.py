"""AniKoto source (com.anikoto).

Ports the AniKoto CloudStream provider. Plain HTML + the site's own
AJAX JSON endpoints. All requests are GET; no POST, no cookies, no
Cloudflare-bypass code in the original.

Site: https://anikototv.to (domain resolved via Firebase key "anikoto",
fallback to the default URL).

Episode ``data`` format: ``anikoto|<detailUrl>|<serverIds>|<sub|dub>``
(the base64 server-ids blob from the episode list), or — for the
details-page fallback — a direct episode page URL.
``streams()`` resolves servers via ``/ajax/server/list?servers=`` (URL-
encoded!) then ``/ajax/server?get=``, applies the /sub <-> /dub
audio-path fix, and dispatches embeds via ``resolveEmbedInline``:
``#``-fragment Base64 hash -> direct m3u8 fast path (with
proxyPlayerHost mirror rewrites), ``megaplay``/``vidwish``/``vidtube``
domains -> MegaPlay, everything else -> best-effort plain GET of the
embed URL + ``.m3u8`` regex. CloudStream's generic ``loadExtractor``
has no server-side equivalent, so non-MegaPlay hosts that need a
host-specific extractor cannot be resolved — recorded here, not
silently claimed.
"""

import base64
import json
import re
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

try:
    from anime_api.http import ANDROID_UA, get, get_json, get_soup, resolve_domain
    from anime_api.sources.base import Source
except Exception:  # scaffold files not present yet — standalone fallback
    ANDROID_UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36")

    _DOMAIN_CACHE = {"ts": 0.0, "map": {}}
    import time as _time

    def resolve_domain(key, default):
        try:
            if _time.time() - _DOMAIN_CACHE["ts"] > 300:
                r = requests.get(
                    "https://cloudstreampluginhelper-default-rtdb.firebaseio.com/.json",
                    timeout=5)
                if r.ok and isinstance(r.json(), dict):
                    _DOMAIN_CACHE["map"] = r.json()
                    _DOMAIN_CACHE["ts"] = _time.time()
            for k in (key, key + "_url", key + "_domain"):
                v = _DOMAIN_CACHE["map"].get(k)
                if v:
                    return str(v).rstrip("/")
        except Exception:
            pass
        return default

    def get(url, headers=None, timeout=30, allow_redirects=True):
        r = requests.get(url, headers=headers or {"User-Agent": ANDROID_UA},
                         timeout=timeout, allow_redirects=allow_redirects)
        r.raise_for_status()
        return r

    def get_json(url, headers=None, timeout=30):
        return get(url, headers, timeout).json()

    def get_soup(url, headers=None, timeout=30):
        return BeautifulSoup(get(url, headers, timeout).text, "html.parser")

    class Source:
        id = ""
        name = ""
        language = ""
        domain_key = ""
        default_url = ""

        @property
        def base_url(self):
            return resolve_domain(self.domain_key, self.default_url)

try:
    from anime_api.extractors.megaplay import resolve_megaplay
except Exception:
    resolve_megaplay = None

_BROWSER_HEADERS = {
    "User-Agent": ANDROID_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _ajax_headers(referer):
    return {"User-Agent": ANDROID_UA,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": referer}


def _proxy_player_host(url):
    """Rewrite player hosts to the permissive bigdreamsmalldih.site mirrors."""
    def _vault(m):
        n = m.group(1)
        cdn = m.group(2)
        if cdn == "uwucdn.top":
            return "uwu%d.bigdreamsmalldih.site" % (int(n) + 1 if n != "99" else 17)
        return "%s.bigdreamsmalldih.site" % n
    url = re.sub(r"vault-(\d+)\.(uwucdn|owocdn)\.top",
                 lambda m: _vault(m), url)
    url = url.replace("vibeplayer.site", "nanobyte.bigdreamsmalldih.site")
    return url


class AniKoto(Source):
    id = "anikoto"
    name = "AniKoto"
    language = "english"
    domain_key = "anikoto"
    default_url = "https://anikototv.to"

    _SECTIONS = {"trending": "latest-updated",
                 "popular": "most-viewed",
                 "latest": "latest-updated"}

    # -- lists ---------------------------------------------------------
    def _parse_items(self, soup):
        items = []
        for el in soup.select("div.ani.items > div.item"):
            try:
                a = (el.select_one("a.name.d-title") or el.select_one("a[title]")
                     or el.select_one("a[href*='/watch/']"))
                if a is None:
                    continue
                title = a.get_text(strip=True) or a.get("title") or ""
                href = a.get("href") or ""
                if not href or not title:
                    continue
                href = urljoin(self.base_url + "/", href)
                img = el.select_one("div.poster img, img")
                poster = None
                if img is not None:
                    poster = img.get("data-src") or img.get("src")
                meta = " ".join(e.get_text(" ", strip=True) for e in
                                el.select(".meta, .info, .type, .right"))
                is_movie = bool(re.search(r"movie", meta, re.I))
                dub = (el.select_one(".dub, i.dub, .fa-microphone") is not None
                       or "dub" in meta.lower())
                sub = (el.select_one(".sub, i.sub, .fa-closed-captioning") is not None
                       or "sub" in meta.lower() or not dub)
                audio = []
                if sub:
                    audio.append("sub")
                if dub:
                    audio.append("dub")
                items.append({"id": href, "title": title, "poster": poster,
                              "year": None,
                              "type": "movie" if is_movie else "anime",
                              "audio": audio, "source": self.id})
            except Exception:
                continue
        return items

    def home(self, section, page=1):
        slug = self._SECTIONS.get(section, "latest-updated")
        try:
            url = "%s/%s?page=%d" % (self.base_url, slug, page)
            return self._parse_items(get_soup(url, headers=_BROWSER_HEADERS))
        except Exception:
            return []

    def search(self, query, page=1):
        try:
            url = "%s/filter?keyword=%s" % (self.base_url, quote(query))
            return self._parse_items(get_soup(url, headers=_BROWSER_HEADERS))
        except Exception:
            return []

    # -- details -------------------------------------------------------
    def _episode_list(self, anime_id, detail_url):
        """GET /ajax/episode/list/{id} -> list of (num, title, ids, sub, dub)."""
        url = "%s/ajax/episode/list/%s" % (self.base_url, anime_id)
        data = get_json(url, headers=_ajax_headers(detail_url))
        if data.get("status") != 200:
            return []
        frag = BeautifulSoup(data.get("result") or "", "html.parser")
        eps = []
        for a in frag.select("a[data-ids]"):
            ids = a.get("data-ids") or ""
            if not ids:
                continue
            try:
                num = int(a.get("data-num") or 0)
            except ValueError:
                num = 0
            if not num:
                continue
            title_el = a.select_one(".d-title")
            title = (title_el.get_text(strip=True) if title_el
                     else a.get("title") or "Episode %d" % num)
            eps.append({"number": num, "title": title, "ids": ids,
                        "sub": a.get("data-sub") == "1",
                        "dub": a.get("data-dub") == "1"})
        return eps

    def details(self, item_id):
        url = item_id
        try:
            soup = get_soup(url, headers=_BROWSER_HEADERS)
        except Exception:
            return {"id": item_id, "title": "Unknown", "poster": None,
                    "banner": None, "plot": None, "genres": [], "year": None,
                    "status": None, "score": None, "type": "anime",
                    "audio": ["sub"],
                    "seasons": [{"number": 1, "name": "Season 1", "episodes": []}]}
        title_el = (soup.select_one("#w-info h1.title")
                    or soup.select_one("h1[itemprop=name]")
                    or soup.select_one(".title[itemprop=name]")
                    or soup.select_one("h1.title"))
        title = title_el.get_text(strip=True) if title_el else "Unknown"
        poster_el = (soup.select_one("#w-info .poster img")
                     or soup.select_one("img[itemprop=image]")
                     or soup.select_one(".poster img"))
        poster = None
        if poster_el is not None:
            poster = poster_el.get("data-src") or poster_el.get("src")
        syn = (soup.select_one("#w-info .synopsis .content")
               or soup.select_one("#w-info .synopsis")
               or soup.select_one(".synopsis .content"))
        plot = syn.get_text(" ", strip=True) if syn else None
        genres = [a.get_text(strip=True) for a in
                  soup.select("#w-info a[href*='/genre/'], .meta a[href*='/genre/']")]
        anime_id = None
        watch_main = soup.select_one("#watch-main[data-id]")
        if watch_main is not None:
            anime_id = watch_main.get("data-id")
        if not anime_id:
            any_id = soup.select_one("[data-id]")
            if any_id is not None:
                anime_id = any_id.get("data-id")
        if not anime_id:
            m = re.search(r'data-id=["\'](\d+)["\']', str(soup))
            anime_id = m.group(1) if m else None
        sub_eps, dub_eps = [], []
        if anime_id:
            try:
                for ep in self._episode_list(anime_id, url):
                    if ep["sub"] or not ep["dub"]:
                        sub_eps.append({
                            "number": ep["number"], "title": ep["title"],
                            "data": "anikoto|%s|%s|sub" % (url, ep["ids"])})
                    if ep["dub"]:
                        dub_eps.append({
                            "number": ep["number"], "title": ep["title"],
                            "data": "anikoto|%s|%s|dub" % (url, ep["ids"])})
            except Exception:
                pass
        if not sub_eps and not dub_eps:
            # Fallback: direct episode links on the details page.
            for i, a in enumerate(soup.select("a[href*='/ep-']")):
                href = urljoin(self.base_url + "/", a.get("href") or "")
                sub_eps.append({"number": i + 1,
                                "title": a.get_text(strip=True) or "Episode %d" % (i + 1),
                                "data": href})
        seasons = []
        if sub_eps:
            seasons.append({"number": 1, "name": "Season 1", "episodes": sub_eps})
        if dub_eps:
            seasons.append({"number": 2 if sub_eps else 1, "name": "Dubbed",
                            "episodes": dub_eps})
        if not seasons:
            seasons = [{"number": 1, "name": "Season 1", "episodes": []}]
        # Type: same "movie" heuristic the list parser uses on the card
        # meta text (".meta/.info/.type/.right").
        meta_text = " ".join(
            e.get_text(" ", strip=True)
            for e in soup.select("#w-info .meta, #w-info .info, #w-info .type, #w-info .right")
        )
        mtype = "movie" if re.search(r"movie", meta_text, re.I) else "anime"
        audio = (["sub"] if sub_eps else []) + (["dub"] if dub_eps else [])
        return {"id": url, "title": title, "poster": poster, "banner": None,
                "plot": plot, "genres": genres, "year": None, "status": None,
                "score": None, "type": mtype, "audio": audio or ["sub"],
                "seasons": seasons}

    # -- streams -------------------------------------------------------
    def streams(self, episode_data):
        streams, subtitles = [], []
        try:
            if episode_data.startswith("anikoto|"):
                parts = episode_data.split("|", 3)
                referer = parts[1] if len(parts) > 1 else self.base_url + "/"
                server_ids = parts[2] if len(parts) > 2 else ""
                audio = parts[3] if len(parts) > 3 and parts[3] else "sub"
                s, sub = self._resolve_servers(server_ids, referer, audio)
                streams.extend(s)
                subtitles.extend(sub)
            else:
                # Direct episode URL fallback: re-extract animeId + epNum.
                s, sub = self._streams_from_episode_url(episode_data)
                streams.extend(s)
                subtitles.extend(sub)
        except Exception:
            pass
        streams.sort(key=lambda x: -(x.get("quality") or 0))
        return {"streams": streams, "subtitles": subtitles}

    def _streams_from_episode_url(self, episode_url):
        soup = get_soup(episode_url, headers=_BROWSER_HEADERS)
        anime_id = None
        watch_main = soup.select_one("#watch-main[data-id]")
        if watch_main is not None:
            anime_id = watch_main.get("data-id")
        if not anime_id:
            m = re.search(r'data-id=["\'](\d+)["\']', str(soup))
            anime_id = m.group(1) if m else None
        if not anime_id:
            return [], []
        m = re.search(r"/ep-(\d+)", episode_url)
        ep_num = int(m.group(1)) if m else 1
        eps = self._episode_list(anime_id, episode_url)
        chosen = next((e for e in eps if e["number"] == ep_num), eps[0] if eps else None)
        if not chosen:
            return [], []
        audio = "dub" if chosen["dub"] else "sub"
        return self._resolve_servers(chosen["ids"], episode_url, audio)

    def _resolve_servers(self, server_ids, referer, audio_type):
        streams, subtitles = [], []
        url = "%s/ajax/server/list?servers=%s" % (
            self.base_url, quote(server_ids, safe=""))
        data = get_json(url, headers=_ajax_headers(referer))
        if data.get("status") != 200:
            return [], []
        frag = BeautifulSoup(data.get("result") or "", "html.parser")
        if audio_type == "dub":
            items = frag.select("div.type[data-type=dub] li[data-link-id]")
        else:
            items = frag.select(
                "div.type[data-type=sub] li[data-link-id], "
                "div.type[data-type=hsub] li[data-link-id]")
        if not items:
            items = frag.select("li[data-link-id]")
        seen = set()
        for li in items:
            link_id = li.get("data-link-id")
            if not link_id or link_id in seen:
                continue
            seen.add(link_id)
            name = li.get_text(strip=True) or "Server"
            try:
                s, sub = self._resolve_server(link_id, name, referer, audio_type)
                streams.extend(s)
                subtitles.extend(sub)
            except Exception:
                continue
        return streams, subtitles

    def _resolve_server(self, link_id, server_name, referer, audio_type):
        url = "%s/ajax/server?get=%s" % (self.base_url, quote(link_id, safe=""))
        data = get_json(url, headers=_ajax_headers(referer))
        result = data.get("result") or {}
        embed_url = result.get("url") if isinstance(result, dict) else None
        if not embed_url:
            return [], []
        if audio_type == "dub" and "/sub" in embed_url:
            embed_url = embed_url.replace("/sub", "/dub")
        elif audio_type == "sub" and "/dub" in embed_url:
            embed_url = embed_url.replace("/dub", "/sub")
        return self._resolve_embed_inline(embed_url, server_name, referer, audio_type)

    def _resolve_embed_inline(self, embed_url, server_name, referer, audio_type):
        if embed_url.startswith("//"):
            embed_url = "https:" + embed_url
        elif embed_url.startswith("/"):
            embed_url = self.base_url + embed_url
        # Fast path: #-fragment Base64 hash -> direct m3u8.
        if "#" in embed_url:
            try:
                frag = embed_url.split("#", 1)[1].split("#")[0]
                decoded = base64.b64decode(frag).decode("utf-8", "ignore")
                decoded = _proxy_player_host(decoded)
                if decoded.startswith("http") and ".m3u8" in decoded:
                    return ([{"name": "AniKoto %s" % server_name, "url": decoded,
                              "quality": None, "type": "m3u8",
                              "headers": {"Referer": embed_url,
                                          "Origin": "https://mewcdn.online"},
                              "proxy": False}], [])
            except Exception:
                pass
        host = embed_url.lower()
        if ("megaplay" in host or "vidwish" in host or "vidtube" in host) \
                and resolve_megaplay:
            streams, subtitles = resolve_megaplay(embed_url, referer)
            for s in streams:
                s["name"] = "%s %s" % (s.get("name", "MegaPlay"), server_name)
            return streams, subtitles
        # Best-effort generic: plain GET + .m3u8 regex.
        try:
            html = get(embed_url, headers={
                "User-Agent": ANDROID_UA, "Referer": referer}, timeout=15).text
        except Exception:
            return [], []
        m = re.search(r"(https?://[^\s'\"<>]+\.m3u8[^\s'\"<>]*)", html)
        if m:
            return ([{"name": "AniKoto %s" % server_name, "url": m.group(1),
                      "quality": None, "type": "m3u8",
                      "headers": {"Referer": embed_url}, "proxy": False}], [])
        return [], []
