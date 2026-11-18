"""HentaiHaven source (18+ adult animation).

Ports the AniWorld Downloader backend (phoenixthrush/AniWorld-Downloader,
PyPI ``aniworld``) for hentaihaven.xxx — search + series/episodes + direct
HLS streams. Verified live 2026-11-18 from the Mumbai server:
``query_hentaihaven('elf')`` returns real titles with posters, and
``HentaiHavenEpisode.refresh_stream_url()`` resolves a real HLS master
(octopusmanifest.org playlist.m3u8, HEAD 200, valid #EXTM3U with English
audio + subtitle tracks).

Episode ``data`` format: the episode page URL
(``https://hentaihaven.xxx/watch/<slug>/episode-N/``).
Default audio is English Sub — Hindi dub is NOT offered by this source.

ADULT (18+): this source is served ONLY behind the app's key-gated adult
section. It must never appear in home/search/trending rails — the app
queries it only with an explicit ``?source=hentaihaven``.
"""

from anime_api.sources.base import Source

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_REFERER = "https://hentaihaven.xxx/"


class HentaiHavenSource(Source):
    id = "hentaihaven"
    name = "HentaiHaven"
    language = "english"
    domain_key = ""
    default_url = "https://hentaihaven.xxx/"
    media_type = "series"
    categories = ()

    def search(self, query, page=1):
        if page != 1 or not query:
            return []
        try:
            from aniworld.search import query_hentaihaven

            results = query_hentaihaven(query, limit=30) or []
        except Exception:
            return []
        items = []
        for r in results:
            try:
                url = r.get("url") or r.get("link")
                title = r.get("title")
                if not url or not title:
                    continue
                items.append({
                    "id": url,
                    "title": title,
                    "poster": r.get("poster"),
                    "year": None,
                    "type": "anime",
                    "audio": ["sub"],
                    "source": self.id,
                })
            except Exception:
                continue
        return items

    def home(self, section, page=1):
        # No browse/latest endpoint in the AniWorld backend — search only.
        return []

    def details(self, item_id):
        try:
            from aniworld import HentaiHavenSeries

            series = HentaiHavenSeries(item_id)
            episodes = list(getattr(series, "episodes", []) or [])
        except Exception:
            return None
        if not episodes:
            return None
        eps = []
        title = None
        poster = None
        plot = None
        genres = []
        for ep in episodes:
            try:
                eps.append({
                    "number": int(getattr(ep, "episode_number", len(eps) + 1) or len(eps) + 1),
                    "title": getattr(ep, "title", None) or "",
                    "data": getattr(ep, "url", None),
                })
                if title is None:
                    title = getattr(ep, "series_title", None)
                if poster is None:
                    poster = getattr(ep, "poster_url", None)
                if plot is None:
                    plot = getattr(ep, "description", None)
                if not genres:
                    genres = list(getattr(ep, "genres", []) or [])
            except Exception:
                continue
        eps = [e for e in eps if e.get("data")]
        if not eps:
            return None
        if not title:
            title = item_id.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()
        return {
            "id": item_id,
            "title": title,
            "poster": poster,
            "banner": None,
            "plot": plot,
            "genres": genres,
            "year": None,
            "status": None,
            "score": None,
            "type": "anime",
            "audio": ["sub"],
            "seasons": [{"number": 1, "name": "Season 1", "episodes": eps}],
        }

    def streams(self, episode_data):
        try:
            from aniworld.models.hentaihaven.episode import HentaiHavenEpisode

            ep = HentaiHavenEpisode(episode_data)
            ep.refresh_stream_url()
            url = str(getattr(ep, "stream_url", "") or "")
        except Exception:
            return {"streams": [], "subtitles": []}
        if not url.startswith("http"):
            return {"streams": [], "subtitles": []}
        streams = [{
            "name": "HentaiHaven",
            "url": url,
            "quality": None,
            "type": "m3u8",
            "headers": {"Referer": _REFERER, "User-Agent": _BROWSER_UA},
            "proxy": True,
        }]
        subtitles = []
        try:
            sub = str(getattr(ep, "subtitle_url", "") or "")
            if sub.startswith("http"):
                subtitles.append({"label": "English", "url": sub})
        except Exception:
            pass
        return {"streams": streams, "subtitles": subtitles}
