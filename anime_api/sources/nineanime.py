"""9anime source (NineAnime, com.laddu100.NineAnime).

Ports the Raghav CloudStream NineAnime provider. Plain HTML scraping,
no Cloudflare bypass, no custom UA, no cookies, no POST.

Site: https://9anime.org.lv (domain resolved via Firebase key "nineanime",
fallback to the default URL).

Episode ``data`` format: the episode page URL (a full ``https://...`` URL).
``streams()`` takes that URL, reads the ``select.mirror`` Base64 iframe
options, unwraps gogoanime ``newplayer.php``, and dispatches by host:
``plyr.php#`` (KiwiK Base64 fragment), ``megaplay.buzz`` (MegaPlay),
``vidmoly.biz`` (regex ``file: ... .m3u8``), anything else (best-effort
plain GET + ``.m3u8`` regex).
``bysesayeveum.com`` (Moon) is WebView-only in the original plugin and is
SKIPPED server-side — there is no HTTP equivalent.
"""

import base64
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    from anime_api.http import BROWSER_UA, get, get_soup, resolve_domain
    from anime_api.sources.base import Source
except Exception:  # scaffold files not present yet — standalone fallback
    BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

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
        r = requests.get(url, headers=headers or {"User-Agent": BROWSER_UA},
                         timeout=timeout, allow_redirects=allow_redirects)
        r.raise_for_status()
        return r

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


def _abs(href, base):
    if not href:
        return None
    return urljoin(base + "/", href)


def _poster(img):
    if img is None:
        return None
    return img.get("data-src") or img.get("src") or None


def _parse_items(soup, base_url, source_id):
    items = []
    for art in soup.select("article.bs"):
        try:
            a = art.select_one("a[href]")
            if not a:
                continue
            href = _abs(a.get("href"), base_url)
            title_el = art.select_one(".entry-title") or art.select_one("h2")
            title = (title_el.get_text(strip=True) if title_el
                     else a.get_text(strip=True))
            if not href or not title:
                continue
            audio = ["dub"] if ("(dub)" in title.lower()
                                or "-dub" in href.lower()) else ["sub"]
            items.append({
                "id": href, "title": title,
                "poster": _poster(art.select_one("img")),
                "year": None,
                "type": "movie" if "movie" in title.lower() else "anime",
                "audio": audio, "source": source_id,
            })
        except Exception:
            continue
    return items


class NineAnime(Source):
    id = "nineanime"
    name = "9anime"
    language = "english"
    domain_key = "nineanime"
    default_url = "https://9anime.org.lv"

    # -- lists ---------------------------------------------------------
    def home(self, section, page=1):
        # Single section only: "Latest Releases" for trending/popular/latest.
        try:
            url = self.base_url + ("/" if page <= 1 else "/page/%d/" % page)
            return _parse_items(get_soup(url), self.base_url, self.id)
        except Exception:
            return []

    def search(self, query, page=1):
        try:
            url = "%s/?s=%s" % (self.base_url, query.replace(" ", "+"))
            return _parse_items(get_soup(url), self.base_url, self.id)
        except Exception:
            return []

    # -- details -------------------------------------------------------
    def details(self, item_id):
        url = item_id
        try:
            if "/anime/" not in url:
                soup = get_soup(url)
                for a in soup.select("a[href*='/anime/']"):
                    path = a["href"].split("/anime/", 1)[1].split("?")[0].strip("/")
                    if path and "/" not in path:
                        url = _abs(a["href"], self.base_url)
                        break
            soup = get_soup(url)
        except Exception:
            return {"id": item_id, "title": "Unknown", "poster": None,
                    "banner": None, "plot": None, "genres": [], "year": None,
                    "status": None, "score": None, "type": "anime",
                    "audio": ["sub"],
                    "seasons": [{"number": 1, "name": "Season 1", "episodes": []}]}
        title_el = soup.select_one("h1.entry-title") or soup.select_one("h1")
        title = title_el.get_text(strip=True) if title_el else "Unknown"
        poster_el = (soup.select_one(".thumb img") or soup.select_one(".poster img")
                     or soup.select_one("img"))
        plot_el = (soup.select_one(".entry-content") or soup.select_one(".desc")
                   or soup.select_one(".story"))
        info = ""
        info_el = soup.select_one(".info-content")
        if info_el:
            info = info_el.get_text(" ", strip=True)
        if "Ongoing" in info:
            status = "ongoing"
        elif "Completed" in info:
            status = "completed"
        else:
            status = None
        if "Movie" in info:
            mtype = "movie"
        elif "OVA" in info or "ONA" in info:
            mtype = "ova"
        else:
            mtype = "anime"
        is_dub = ("(dub)" in title.lower()) or ("-dub" in url.lower())
        episodes = []
        for li in soup.select(".eplister li"):
            try:
                a = li.select_one("a[href]")
                if not a:
                    continue
                num_el = li.select_one(".epl-num")
                num_txt = num_el.get_text(strip=True) if num_el else ""
                m = re.search(r"\d+", num_txt) or re.search(r"\d+", a.get_text())
                number = int(m.group(0)) if m else 1
                title_el2 = li.select_one(".epl-title")
                ep_title = (title_el2.get_text(strip=True) if title_el2
                            else "Episode %d" % number)
                episodes.append({"number": number, "title": ep_title,
                                 "data": _abs(a.get("href"), self.base_url)})
            except Exception:
                continue
        episodes.reverse()  # site lists newest-first
        if not episodes:
            episodes = [{"number": 1, "title": title, "data": url}]
        season_name = "Dubbed" if is_dub else "Season 1"
        return {"id": url, "title": title, "poster": _poster(poster_el),
                "banner": None,
                "plot": plot_el.get_text(" ", strip=True) if plot_el else None,
                "genres": [a.get_text(strip=True) for a in soup.select(".genxed a")],
                "year": None, "status": status, "score": None,
                "type": mtype, "audio": ["dub"] if is_dub else ["sub"],
                "seasons": [{"number": 1, "name": season_name,
                             "episodes": episodes}]}

    # -- streams -------------------------------------------------------
    def streams(self, episode_data):
        streams, subtitles = [], []
        try:
            soup = get_soup(episode_data)
        except Exception:
            return {"streams": streams, "subtitles": subtitles}
        iframe_urls = []
        for opt in soup.select("select.mirror option"):
            val = (opt.get("value") or "").strip()
            if not val or val == "...":
                continue
            try:
                snippet = base64.b64decode(val).decode("utf-8", "ignore")
                frag = BeautifulSoup(snippet, "html.parser")
                iframe = frag.select_one("iframe[src]")
                if iframe:
                    iframe_urls.append(iframe["src"])
            except Exception:
                continue
        # gogoanime newplayer.php unwrap
        expanded = []
        for u in iframe_urls:
            if "gogoanime.me.uk/newplayer.php" in u:
                try:
                    inner = get_soup(u, headers={"Referer": episode_data})
                    inners = [i["src"] for i in inner.select("iframe[src]")]
                    expanded.extend(inners or [u])
                except Exception:
                    expanded.append(u)
            else:
                expanded.append(u)
        seen = set()
        for embed in expanded:
            if embed in seen:
                continue
            seen.add(embed)
            try:
                s, sub = self._resolve_embed(embed, episode_data)
                streams.extend(s)
                subtitles.extend(sub)
            except Exception:
                continue
        streams.sort(key=lambda x: -(x.get("quality") or 0))
        return {"streams": streams, "subtitles": subtitles}

    def _resolve_embed(self, embed_url, episode_url):
        if "plyr.php#" in embed_url:
            frag = embed_url.split("#", 1)[1].split("#")[0]
            link = base64.b64decode(frag).decode("utf-8", "ignore")
            return ([{"name": "KiwiK", "url": link, "quality": None,
                      "type": "m3u8" if ".m3u8" in link else "video",
                      "headers": {"Referer": "https://gogoanime.me.uk/"},
                      "proxy": False}], [])
        if "megaplay.buzz" in embed_url and resolve_megaplay:
            return resolve_megaplay(embed_url, episode_url)
        if "vidmoly.biz" in embed_url:
            try:
                html = get(embed_url, headers={
                    "User-Agent": BROWSER_UA, "Referer": episode_url}).text
            except Exception:
                return [], []
            m = re.search(r"file\s*:\s*['\"](https?://[^'\"]+?\.m3u8[^'\"]*)['\"]", html)
            if not m:
                m = re.search(r"(https?://[^\s'\"<>]+\.m3u8[^\s'\"<>]*)", html)
            if m:
                return ([{"name": "Vidmoly", "url": m.group(1), "quality": None,
                          "type": "m3u8",
                          "headers": {"User-Agent": BROWSER_UA,
                                      "Referer": "https://vidmoly.biz/",
                                      "Origin": "https://vidmoly.biz"},
                          "proxy": False}], [])
            return [], []
        if "bysesayeveum.com" in embed_url:
            # Moon is WebView-only in the original plugin — skipped.
            return [], []
        # Generic best-effort: plain GET + .m3u8 regex.
        try:
            html = get(embed_url, headers={
                "User-Agent": BROWSER_UA, "Referer": episode_url}, timeout=15).text
        except Exception:
            return [], []
        m = re.search(r"(https?://[^\s'\"<>]+\.m3u8[^\s'\"<>]*)", html)
        if m:
            return ([{"name": "Embed", "url": m.group(1), "quality": None,
                      "type": "m3u8",
                      "headers": {"Referer": embed_url}, "proxy": False}], [])
        return [], []
