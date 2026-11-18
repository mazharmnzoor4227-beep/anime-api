"""Re:ANIME source — ports ReAnimeProvider.kt / ReAnimeApi.kt / FlixDownload.kt.

Site: https://reanime.cz (live host resolved via Firebase key ``reanime``).
Pure JSON API — no HTML scraping except regexes inside the flixcloud step:
  GET /api/v1/search?q=...&limit=40&offset=...
  GET /api/v1/search?limit=40&offset=...&sort=popularity_desc
  GET /api/v1/home/{latest-aired|new-on-site|upcoming}?limit=40[&cursor=...]
  GET /api/v1/anime/{slug}
  GET /api/v1/anime/{slug}/episodes?limit=2000
  GET /api/flix/{anilistId}/{episode}
      or /api/flix/0/{episode}?tmdb={tmdbId}&season={season}
Streams come from flixcloud.cc direct files:
  GET https://flixcloud.cc/d/{embedId}/__data.json (regex file UUID + JWT
  token + host) -> readiness gate
  GET {host}/download/{fileId}/progress?token=... (body must contain "ready")
  -> final file {host}/download/{fileId}?token=...

CAVEAT: the flixcloud token is bound to the IP that requested it, so the
final file URL only plays from this server's IP. Streams are therefore
marked proxy=true — the website MUST play them via /api/proxy, not
directly in the browser. Subtitles are inside the MKV (none emitted).

Episode ``data`` format (JSON string):
  {"slug": ..., "ep": <int>, "lang": "sub"|"dub",
   "anilistId": <int>, "tmdbId": <int>, "season": <int>}
"""

import json
import re
import urllib.parse

import requests

from anime_api.http import ANDROID_UA, get_json
from anime_api.sources.base import Source

FLIX_EMBED_BASE = "https://flixcloud.cc"
_EMBED_ID_RE = re.compile(r"/e/([a-z0-9]+)", re.IGNORECASE)
_FILE_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
_JWT_RE = re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+")
_HOST_RE = re.compile(r"https://[a-z0-9-]+\.flixcloud\.cc")
_QUALITY_RE = re.compile(r"(\d{3,4})p")
_SIZE_RE = re.compile(r"(\d+(\.\d+)?\s*[KMG]B)")

_BROWSER_HEADERS = {
    "User-Agent": ANDROID_UA,
    "Accept": "application/json",
}

# In-memory cursor store for homeSection pagination (page N+1 needs the
# next_cursor returned by the previous page's response).
_home_cursors = {}


def _strip_html(text):
    if not text:
        return None
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.strip()
    return text or None


def _title_display(title):
    if not isinstance(title, dict):
        return title if isinstance(title, str) and title.strip() else None
    for key in ("english", "romaji", "native", "user_preferred"):
        value = title.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _cover_best(cover):
    if not isinstance(cover, dict):
        return cover if isinstance(cover, str) else None
    for key in ("extra_large", "large", "medium"):
        value = cover.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _to_int(value):
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _item_type(fmt):
    fmt = str(fmt or "").upper()
    if fmt == "MOVIE":
        return "movie"
    if fmt in ("OVA", "ONA", "SPECIAL"):
        return "ova"
    return "anime"


class ReanimeSource(Source):
    id = "reanime"
    name = "Re:ANIME"
    language = "english"
    domain_key = "reanime"
    default_url = "https://reanime.cz"

    # -- helpers ---------------------------------------------------------
    def _headers(self, referer_path="/"):
        headers = dict(_BROWSER_HEADERS)
        headers["Referer"] = self.base_url.rstrip("/") + referer_path
        return headers

    def _get(self, path, headers=None):
        return get_json(
            self.base_url.rstrip("/") + path,
            headers=headers or self._headers(),
            timeout=30,
        )

    @staticmethod
    def _parse_item(raw):
        if not isinstance(raw, dict):
            return None
        slug = raw.get("anime_id") or raw.get("slug") or raw.get("id")
        title = _title_display(raw.get("title"))
        if not slug or not title:
            return None
        audio = []
        if raw.get("subbed"):
            audio.append("sub")
        if raw.get("dubbed"):
            audio.append("dub")
        return {
            "id": str(slug),
            "title": str(title),
            "poster": _cover_best(raw.get("cover_image")) or None,
            "year": _to_int(raw.get("season_year")),
            "type": _item_type(raw.get("format")),
            "audio": audio,
            "source": "reanime",
        }

    def _parse_list(self, envelope):
        items = []
        if not isinstance(envelope, dict):
            return items
        raw_list = envelope.get("results")
        if raw_list is None:
            raw_list = envelope.get("data") or []
        for raw in raw_list or []:
            try:
                parsed = self._parse_item(raw)
                if parsed:
                    items.append(parsed)
            except Exception:
                continue
        return items

    def _search_sorted(self, sort, page=1, limit=40):
        offset = (page - 1) * limit
        path = "/api/v1/search?limit=%d&offset=%d&sort=%s" % (
            limit, offset, urllib.parse.quote(sort),
        )
        return self._parse_list(self._get(path))

    def _home_section(self, section, page=1, limit=40):
        if page > 1:
            cursor = _home_cursors.get(section)
            if cursor:
                path = "/api/v1/home/%s?limit=%d&cursor=%s" % (
                    section, limit, urllib.parse.quote(cursor),
                )
            else:
                path = "/api/v1/home/%s?limit=%d" % (section, limit)
        else:
            path = "/api/v1/home/%s?limit=%d" % (section, limit)
        envelope = self._get(path)
        if isinstance(envelope, dict) and envelope.get("next_cursor"):
            _home_cursors[section] = envelope["next_cursor"]
        return self._parse_list(envelope)

    # -- Source interface ----------------------------------------------
    def search(self, query, page=1):
        if not query or not str(query).strip():
            return []
        limit = 40
        offset = (page - 1) * limit
        path = "/api/v1/search?q=%s&limit=%d&offset=%d" % (
            urllib.parse.quote(str(query)), limit, offset,
        )
        try:
            return self._parse_list(self._get(path))
        except Exception:
            return []

    def home(self, section, page=1):
        try:
            if section == "trending":
                return self._home_section("latest-aired", page=page)
            if section == "popular":
                return self._search_sorted("popularity_desc", page=page)
            if section == "latest":
                return self._home_section("new-on-site", page=page)
            return self._home_section("latest-aired", page=page)
        except Exception:
            return []

    def details(self, item_id):
        slug = str(item_id or "").strip()
        slug = slug.split("?")[0].strip("/")
        if slug.startswith("anime/"):
            slug = slug[len("anime/"):]
        if slug.startswith("http"):
            slug = slug.rstrip("/").split("/")[-1]
        if not slug:
            return {"error": "empty id"}
        try:
            detail = self._get(
                "/api/v1/anime/%s" % urllib.parse.quote(slug)
            )
            try:
                eps_env = self._get(
                    "/api/v1/anime/%s/episodes?limit=2000"
                    % urllib.parse.quote(slug)
                )
            except Exception:
                eps_env = {}
        except Exception as exc:
            return {"error": str(exc)}
        if not isinstance(detail, dict):
            return {"error": "anime not found"}
        title = _title_display(detail.get("title"))
        if not title:
            return {"error": "anime not found"}
        score_raw = detail.get("average_score")
        score = None
        if isinstance(score_raw, (int, float)) and score_raw > 0:
            score = round(float(score_raw) / 10.0, 2)
        status_raw = str(detail.get("status") or "").upper()
        status = None
        if status_raw == "RELEASING":
            status = "ongoing"
        elif status_raw == "FINISHED":
            status = "completed"
        genres = list(detail.get("genres") or [])
        if not genres:
            genres = [
                t.get("name") for t in (detail.get("tags") or [])
                if isinstance(t, dict) and t.get("name")
            ]
        anilist_id = _to_int(detail.get("anilist_id")) or 0
        tmdb_id = _to_int(detail.get("themoviedb_id")) or 0
        ext_seasons = detail.get("external_seasons") or {}
        season = _to_int(ext_seasons.get("tmdb")) or 1

        sub_eps, dub_eps = [], []
        entries = []
        if isinstance(eps_env, dict):
            entries = eps_env.get("data") or eps_env.get("episodes") or []
        for entry in entries or []:
            try:
                if not isinstance(entry, dict):
                    continue
                ep_num = _to_int(entry.get("episode_number"))
                if not ep_num:
                    continue
                ep_title = entry.get("title")
                if not ep_title or str(ep_title).startswith("Episode "):
                    ep_title = "Episode %d" % ep_num
                has_sub = bool(entry.get("subbed"))
                has_dub = bool(entry.get("dubbed"))
                if not has_sub and not has_dub:
                    has_sub = True
                base_ref = {
                    "slug": slug, "ep": ep_num,
                    "anilistId": anilist_id, "tmdbId": tmdb_id,
                    "season": season,
                }
                if has_sub:
                    ref = dict(base_ref, lang="sub")
                    sub_eps.append({
                        "number": ep_num, "title": str(ep_title),
                        "data": json.dumps(ref, separators=(",", ":")),
                    })
                if has_dub:
                    ref = dict(base_ref, lang="dub")
                    dub_eps.append({
                        "number": ep_num, "title": str(ep_title),
                        "data": json.dumps(ref, separators=(",", ":")),
                    })
            except Exception:
                continue
        sub_eps.sort(key=lambda e: e["number"])
        dub_eps.sort(key=lambda e: e["number"])
        seasons = []
        if sub_eps:
            seasons.append(
                {"number": 1, "name": "Season 1", "episodes": sub_eps}
            )
        if dub_eps:
            seasons.append(
                {"number": 2 if sub_eps else 1, "name": "Dubbed",
                 "episodes": dub_eps}
            )
        if not seasons:
            seasons = [{"number": 1, "name": "Season 1", "episodes": []}]
        return {
            "id": slug,
            "title": str(title),
            "poster": _cover_best(detail.get("cover_image")) or None,
            "banner": detail.get("banner_image") or None,
            "plot": _strip_html(detail.get("description")),
            "genres": [str(g) for g in genres],
            "year": _to_int(detail.get("season_year")),
            "status": status,
            "score": score,
            "type": _item_type(detail.get("format")),
            "audio": (["sub"] if sub_eps else []) + (["dub"] if dub_eps else []),
            "seasons": seasons,
        }

    def streams(self, episode_data):
        try:
            ref = json.loads(episode_data)
        except Exception:
            return {"streams": [], "subtitles": []}
        ep = _to_int(ref.get("ep"))
        if not ep or ep <= 0:
            return {"streams": [], "subtitles": []}
        anilist_id = _to_int(ref.get("anilistId")) or 0
        tmdb_id = _to_int(ref.get("tmdbId")) or 0
        season = _to_int(ref.get("season")) or 1
        try:
            servers = self._flix_servers(anilist_id, tmdb_id, season, ep)
        except Exception:
            return {"streams": [], "subtitles": []}
        streams = []
        seen_embeds = set()
        for server in servers:
            try:
                link = (server or {}).get("dataLink") or ""
                if not link.startswith("http"):
                    continue
                match = _EMBED_ID_RE.search(link)
                if not match:
                    continue
                embed_id = match.group(1)
                if embed_id in seen_embeds:
                    continue
                seen_embeds.add(embed_id)
                stream = self._flix_download(embed_id)
                if stream:
                    streams.append(stream)
            except Exception:
                continue
        return {"streams": streams, "subtitles": []}

    def _flix_servers(self, anilist_id, tmdb_id, season, episode):
        if anilist_id > 0:
            path = "/api/flix/%d/%d" % (anilist_id, episode)
        elif tmdb_id > 0:
            path = "/api/flix/0/%d?tmdb=%d&season=%d" % (
                episode, tmdb_id, season,
            )
        else:
            return []
        resp = self._get(path, headers=self._headers("/watch/"))
        if not isinstance(resp, dict) or not resp.get("success"):
            return []
        return resp.get("servers") or []

    def _flix_download(self, embed_id):
        """Resolve one flixcloud embed to a direct file stream (or None)."""
        headers = {
            "User-Agent": ANDROID_UA,
            "Referer": "https://flixcloud.cc/",
            "Accept": "*/*",
        }
        try:
            resp = requests.get(
                "%s/d/%s/__data.json" % (FLIX_EMBED_BASE, embed_id),
                headers=headers, timeout=30,
            )
            if not resp.ok:
                return None
            body = resp.text
        except Exception:
            return None
        file_match = _FILE_UUID_RE.search(body)
        token_match = _JWT_RE.search(body)
        if not file_match or not token_match:
            return None
        file_id = file_match.group(0)
        token = token_match.group(0)
        host_match = _HOST_RE.search(body)
        host = host_match.group(0) if host_match else FLIX_EMBED_BASE
        # Readiness gate: progress endpoint must say "ready".
        try:
            prog = requests.get(
                "%s/download/%s/progress?token=%s"
                % (host, file_id, token),
                headers=headers, timeout=30,
            )
            if not prog.ok or "ready" not in prog.text:
                return None
        except Exception:
            return None
        quality_match = _QUALITY_RE.search(body)
        quality = int(quality_match.group(1)) if quality_match else None
        size_match = _SIZE_RE.search(body)
        name = "Re:ANIME - Sub & Dub"
        if size_match:
            name += " (%s)" % size_match.group(1)
        return {
            "name": name,
            "url": "%s/download/%s?token=%s" % (host, file_id, token),
            "quality": quality,
            "type": "video",
            "headers": {
                "User-Agent": ANDROID_UA,
                "Referer": "https://flixcloud.cc/",
            },
            # Token is IP-bound: the website must play via /api/proxy.
            "proxy": True,
        }
