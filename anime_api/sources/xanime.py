"""Xanime source — ports XanimeProvider.kt / XanimeApi.kt (CloudStream).

Site: https://xanime.me (live host resolved via Firebase key ``xanime``).
Pure JSON API: every operation is a GraphQL-style query POSTed to the
single endpoint ``POST {host}/z2/`` inside an AES-GCM envelope sealed with
SHA-256("xanime-ph25-obfuscation-secret-key-2026") as the key, a fresh
random 12-byte IV per request, IV + ciphertext Base64-encoded as
``{"v": 1, "iv": ..., "ct": ...}``. Responses are decrypted the same way
(if the JSON has ``ct``) or treated as plain JSON. No cookies, no auth.

Episode ``data`` format: ``"<epId>|<sub|dub|raw>"``.
"""

import base64
import hashlib
import json
import os
import re

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from anime_api.http import ANDROID_UA
from anime_api.sources.base import Source

SECRET = "xanime-ph25-obfuscation-secret-key-2026"
_KEY = hashlib.sha256(SECRET.encode("utf-8")).digest()

XANIME_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
)

_Q27 = """query get_q27($select: SearchAnime_Select) {
  get_q27(select: $select) {
    items { id data { ani_id info_title urlCover600 info_meta_type info_meta_year info_sou_types } }
  }
}"""

_Q02 = """query Get_animesNode($getAnimesNodeId: String!) {
  get_q02(id: $getAnimesNodeId) {
    id data { info_title urlCover600 urlCoverOri info_meta_year info_meta_type
      info_meta_genre info_meta_scores info_meta_status info_filmdesc info_sou_types }
  }
}"""

_Q01 = """query get_q01($select: AnimesEpisodesList_Select) {
  get_q01(select: $select) {
    paging { total pages page init size }
    items { id data { ep_id ep_index ep_title sourcesNode_list { id data { src_type } } } }
  }
}"""

_Q07 = """query get_q07($select: Episodes_Select) {
  get_q07(select: $select) {
    id data { ep_id sourcesNode_list { id data { src_name src_type souPath track { label trackPath } } } }
  }
}"""


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.b64decode(text)


def _seal(payload: dict) -> dict:
    iv = os.urandom(12)
    ct = AESGCM(_KEY).encrypt(iv, json.dumps(payload).encode("utf-8"), None)
    return {"v": 1, "iv": _b64e(iv), "ct": _b64e(ct)}


def _unseal(body: dict) -> dict:
    if isinstance(body, dict) and body.get("ct"):
        raw = AESGCM(_KEY).decrypt(_b64d(body["iv"]), _b64d(body["ct"]), None)
        return json.loads(raw.decode("utf-8"))
    return body


def _to_int(value):
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _audio_from_types(types):
    audio = []
    lowered = [str(t).lower() for t in (types or [])]
    if "dub" in lowered:
        audio.append("dub")
    if not lowered or "sub" in lowered or "raw" in lowered:
        audio.append("sub")
    return audio


def _item_type(types):
    lowered = [str(t).lower() for t in (types or [])]
    for t in lowered:
        if t == "movie":
            return "movie"
        if t in ("ova", "ona", "special"):
            return "ova"
    return "anime"


class XanimeSource(Source):
    id = "xanime"
    name = "Xanime"
    language = "english"
    domain_key = "xanime"
    default_url = "https://xanime.me"

    # -- transport -----------------------------------------------------
    def _headers(self):
        host = self.base_url
        return {
            "User-Agent": XANIME_UA,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": host,
            "Referer": host + "/",
        }

    def _query(self, query, variables):
        """POST one GraphQL query to {host}/z2/; return the get_* node or None."""
        url = self.base_url.rstrip("/") + "/z2/"
        body = _seal({"query": query, "variables": variables})
        last_exc = None
        for _attempt in range(2):  # post, retry once
            try:
                resp = requests.post(
                    url, json=body, headers=self._headers(), timeout=30
                )
                if not (200 <= resp.status_code < 400):
                    last_exc = RuntimeError(
                        "xanime API HTTP %s" % resp.status_code
                    )
                    continue
                data = _unseal(resp.json())
                if isinstance(data, dict) and data.get("errors"):
                    return None
                node = data.get("data") if isinstance(data, dict) else None
                if not isinstance(node, dict):
                    return None
                for key, value in node.items():
                    if key.startswith(("get_", "set_", "put_", "mut_")):
                        return value
                return None
            except Exception as exc:  # noqa: BLE001 - retry once, then fail
                last_exc = exc
        if last_exc is not None:
            raise last_exc
        return None

    def _browse(self, select, page=1):
        sel = {"where": "browse", "word": "", "page": page, "size": 24}
        sel.update(select)
        node = self._query(_Q27, {"select": sel})
        if not node:
            return []
        return [self._parse_item(it) for it in node.get("items") or []]

    @staticmethod
    def _parse_item(item):
        if not isinstance(item, dict):
            return None
        data = item.get("data") or {}
        ani_id = data.get("ani_id") or item.get("id")
        title = data.get("info_title")
        if not ani_id or not title:
            return None
        types = data.get("info_meta_type") or []
        return {
            "id": str(ani_id),
            "title": str(title),
            "poster": data.get("urlCover600") or None,
            "year": _to_int(data.get("info_meta_year")),
            "type": _item_type(types),
            "audio": _audio_from_types(data.get("info_sou_types") or []),
            "source": "xanime",
        }

    # -- Source interface ----------------------------------------------
    def search(self, query, page=1):
        if not query:
            return []
        try:
            node = self._query(
                _Q27,
                {"select": {"word": query, "sortby": "field_score",
                            "page": 1, "size": 24}},
            )
        except Exception:
            return []
        if not node:
            return []
        items = []
        for it in node.get("items") or []:
            try:
                parsed = self._parse_item(it)
                if parsed:
                    items.append(parsed)
            except Exception:
                continue
        return items

    def home(self, section, page=1):
        sort_map = {
            "trending": "field_update",       # Latest Updates
            "popular": "field_score",         # Top Rated
            "latest": "field_date_create",    # Recently Added
        }
        sortby = sort_map.get(section, "field_update")
        try:
            raw = self._browse({"sortby": sortby}, page=page)
        except Exception:
            return []
        return [it for it in raw if it]

    def details(self, item_id):
        ani_id = str(item_id).split("?")[0].rstrip("/").split("/")[-1]
        if not ani_id:
            return {"error": "empty id"}
        try:
            node = self._query(_Q02, {"getAnimesNodeId": ani_id})
        except Exception as exc:
            return {"error": str(exc)}
        if not node:
            return {"error": "anime not found"}
        data = node.get("data") or {}
        title = data.get("info_title")
        if not title:
            return {"error": "anime not found"}
        score_raw = data.get("info_meta_scores")
        score = None
        if isinstance(score_raw, (int, float)) and score_raw > 0:
            score = round(float(score_raw) / 10.0, 2)
        status_raw = str(data.get("info_meta_status") or "").lower()
        status = None
        if status_raw == "currently_airing":
            status = "ongoing"
        elif status_raw == "finished_airing":
            status = "completed"
        genres = []
        for tag in data.get("info_meta_genre") or []:
            tag = str(tag).replace("_", " ").strip()
            if tag:
                genres.append(tag[:1].upper() + tag[1:])
        seasons = self._episodes(ani_id)
        return {
            "id": str(ani_id),
            "title": str(title),
            "poster": data.get("urlCover600") or None,
            "banner": data.get("urlCoverOri") or None,
            "plot": data.get("info_filmdesc") or None,
            "genres": genres,
            "year": _to_int(data.get("info_meta_year")),
            "status": status,
            "score": score,
            "seasons": seasons,
        }

    def _episodes(self, ani_id):
        """Fetch all episode pages; split into Subbed (season 1) / Dubbed (season 2)."""
        sub_eps, dub_eps = [], []
        page = 1
        total_pages = 1
        seen = set()
        while page <= total_pages:
            try:
                node = self._query(
                    _Q01,
                    {"select": {"ani_id": ani_id, "init": 60,
                                "size": 60, "page": page}},
                )
            except Exception:
                break
            if not node:
                break
            paging = node.get("paging") or {}
            try:
                total_pages = max(1, int(paging.get("pages") or 1))
            except (TypeError, ValueError):
                total_pages = 1
            for item in node.get("items") or []:
                try:
                    data = item.get("data") or {}
                    ep_id = data.get("ep_id") or item.get("id")
                    if not ep_id or str(ep_id) in seen:
                        continue
                    seen.add(str(ep_id))
                    index = _to_int(data.get("ep_index")) or 0
                    number = index if index > 0 else len(sub_eps) + len(dub_eps) + 1
                    title = data.get("ep_title") or "Episode %s" % number
                    audio = [
                        str(s.get("data", {}).get("src_type") or "").lower()
                        for s in data.get("sourcesNode_list") or []
                    ]
                    entry_sub = {
                        "number": number,
                        "title": str(title),
                        "data": "%s|%s" % (ep_id, "sub" if "sub" in audio else "raw"),
                    }
                    entry_dub = {
                        "number": number,
                        "title": str(title),
                        "data": "%s|dub" % ep_id,
                    }
                    has_dub = "dub" in audio
                    has_sub = "sub" in audio or ("raw" in audio and not has_dub)
                    if has_sub:
                        sub_eps.append(entry_sub)
                    if has_dub:
                        dub_eps.append(entry_dub)
                    if not has_sub and not has_dub:
                        sub_eps.append(entry_sub)
                except Exception:
                    continue
            page += 1
            if page > 50:  # safety cap (~3000 episodes)
                break
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
        return seasons

    def streams(self, episode_data):
        data = str(episode_data or "")
        # Strip a CloudStream-style mainUrl/ prefix if present.
        prefix = self.base_url.rstrip("/") + "/"
        if data.startswith(prefix):
            data = data[len(prefix):]
        parts = data.split("|")
        if len(parts) != 2:
            return {"streams": [], "subtitles": []}
        ep_id, audio = parts[0].strip(), parts[1].strip().lower()
        if not ep_id or audio not in ("sub", "dub", "raw"):
            return {"streams": [], "subtitles": []}
        try:
            node = self._query(_Q07, {"select": {"id": ep_id}})
        except Exception:
            return {"streams": [], "subtitles": []}
        if not node:
            return {"streams": [], "subtitles": []}
        data_node = node.get("data") or {}
        streams, subtitles = [], []
        seen_sub_urls = set()
        name_counts = {}
        for src in data_node.get("sourcesNode_list") or []:
            try:
                sdata = src.get("data") or {}
                if str(sdata.get("src_type") or "").lower() != audio:
                    continue
                sou_path = sdata.get("souPath") or ""
                if not sou_path.startswith("http"):
                    continue
                # Dead-CDN probe: only emit if the playlist is really M3U8.
                try:
                    probe = requests.get(
                        sou_path,
                        headers={"User-Agent": XANIME_UA},
                        timeout=(10, 15),
                    )
                    if not (200 <= probe.status_code < 400):
                        continue
                    if "#EXTM3U" not in probe.text:
                        continue
                except Exception:
                    continue
                raw_name = str(sdata.get("src_name") or "Server").strip() or "Server"
                if re.fullmatch(r"\d+", raw_name):
                    server_name = "Server %s" % raw_name
                else:
                    server_name = raw_name
                count = name_counts.get(server_name, 0) + 1
                name_counts[server_name] = count
                label_name = (
                    server_name if count == 1 else "%s %d" % (server_name, count)
                )
                streams.append({
                    "name": "Xanime",
                    "url": sou_path,
                    "quality": None,
                    "type": "m3u8",
                    "headers": {"User-Agent": XANIME_UA},
                    "proxy": False,
                    "label": "Xanime %s (%s)" % (label_name, audio.upper()),
                })
                tracks = sdata.get("track") or []
                if isinstance(tracks, dict):
                    tracks = [tracks]
                track_urls = [
                    (t.get("label") or "Subtitle", t.get("trackPath"))
                    for t in tracks
                    if isinstance(t, dict) and (t.get("trackPath") or "").startswith("http")
                ]
                if track_urls:
                    # tracksAreReal: first track must actually be WEBVTT.
                    try:
                        check = requests.get(
                            track_urls[0][1],
                            headers={"User-Agent": XANIME_UA},
                            timeout=(10, 15),
                        )
                        if 200 <= check.status_code < 400 and "WEBVTT" in check.text:
                            for label, turl in track_urls:
                                if turl in seen_sub_urls:
                                    continue
                                seen_sub_urls.add(turl)
                                subtitles.append(
                                    {"label": label or "Subtitle", "url": turl}
                                )
                    except Exception:
                        pass
            except Exception:
                continue
        return {"streams": streams, "subtitles": subtitles}
