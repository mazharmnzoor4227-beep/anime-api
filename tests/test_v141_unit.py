"""Unit + fixture tests for the v1.4.1 fixes.

GAP 1 — category queries ignore the lang filter (a category's own
sources are never dropped by it).
GAP 2 — DramaCool embeds resolve to direct HLS (packer unpack);
PKDramas streams are always empty (YouTube geo-blocked, no embeds).
GAP 3 — MovieBox filters hasResource=false titles out of results
+ details; empty /api/streams results are never cached.

No live network (player page is a saved fixture). Run:
  ~/workspace/anime-api-work/venv/bin/python tests/test_v141_unit.py
"""

import json
import os
import sys
from contextlib import ExitStack
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest import mock

from anime_api.sources.dramacool import (  # noqa: E402
    DramaCool, _extract_file_url, _unpack_packer)
from anime_api.sources.moviebox import (  # noqa: E402
    MovieBox, _subject_to_item)
from anime_api.sources.pkdramas import PKDramas  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS %s" % name)
    else:
        FAIL += 1
        print("FAIL %s %s" % (name, extra))


_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "fixtures", "dc_hg_player.html")
with open(_FIXTURE, encoding="utf-8") as fh:
    DC_PLAYER_HTML = fh.read()

# The direct HLS URL verified live 2026-11-18 (master.txt 200 +
# variant 200 + first segment 200 video/MP2T through /api/proxy).
DC_DIRECT = ("https://cwfuommwagyrfcg6.retailplatform.shop/dwjdqozeoybz/"
             "hls3/01/15268/2xxqmkpq929u_n/master.txt")

# ---------------------------------------------------------------- unpacker
unpacked = _unpack_packer(DC_PLAYER_HTML)
check("dc unpacker unpacks the real packed player block",
      len(unpacked) == 1 and DC_DIRECT in unpacked[0]
      and "jwplayer" in unpacked[0].lower(),
      "blocks=%d" % len(unpacked))
found = _extract_file_url(DC_PLAYER_HTML)
check("dc extract file url finds direct HLS + 720p",
      found == (DC_DIRECT, 720), repr(found))
check("dc extract file url empty on plain page",
      _extract_file_url("<html><body>no player here</body></html>") is None)
check("dc unpacker ignores pages without a packed block",
      _unpack_packer("<html><body>plain</body></html>") == [])

# ------------------------------------------------------- dramacool streams
DC_EPISODE_HG = """
<html><body><iframe src="https://hgcloud.to/e/exu5fvn2tqdg"></iframe>
</body></html>
"""
HG_LOADING = """
<html><head><title>Loading...</title></head><body>
<div class="loading-text">Page is loading, please wait...</div>
<script src="/main.js?v=1.1.9"></script></body></html>
"""

dc = DramaCool()


def _dc_route_get(url, headers=None, timeout=30):
    m = mock.Mock()
    if "hanerix.com" in url:
        m.text = DC_PLAYER_HTML
    elif "hgcloud.to" in url:
        # The embed host itself is only a JS redirector shell.
        m.text = HG_LOADING
    else:
        m.text = DC_EPISODE_HG
    m.raise_for_status = mock.Mock()
    return m


with mock.patch("anime_api.sources.dramacool.get",
                side_effect=_dc_route_get):
    s = dc.streams("https://dramaacool.best/drama/the-confession-truth/episode-1")
    check("dc streams hgcloud embed resolves to direct HLS via hanerix",
          len(s["streams"]) == 1
          and s["streams"][0]["url"] == DC_DIRECT
          and s["streams"][0]["type"] == "hls"
          and s["streams"][0]["proxy"] is True
          and s["streams"][0]["quality"] == 720
          and s["streams"][0]["headers"].get("Referer")
          == "https://hanerix.com/e/exu5fvn2tqdg"
          and s["streams"][0]["label"] == "DramaCool 720p",
          repr(s["streams"]))


def _dc_direct_host_get(url, headers=None, timeout=30):
    # A host that serves the player page itself (no redirect hop).
    m = mock.Mock()
    m.text = DC_PLAYER_HTML if "vidmoly" in url else DC_EPISODE_HG
    m.raise_for_status = mock.Mock()
    return m


with mock.patch("anime_api.sources.dramacool.get",
                side_effect=_dc_direct_host_get):
    direct = dc._direct_from_embed(
        "https://vidmoly.org/embed-21w3v6zebhw9.html",
        "https://dramaacool.best/drama/x/episode-1")
    check("dc direct from embed page that serves the player itself",
          direct is not None and direct["url"] == DC_DIRECT
          and direct["proxy"] is True, repr(direct))


def _dc_no_file_get(url, headers=None, timeout=30):
    m = mock.Mock()
    m.text = "<html><body>no video here</body></html>"
    m.raise_for_status = mock.Mock()
    return m


with mock.patch("anime_api.sources.dramacool.get",
                side_effect=_dc_no_file_get):
    s = dc.streams("https://dramaacool.best/drama/x/episode-1")
    check("dc streams empty when no host yields a direct file",
          s == {"streams": [], "subtitles": []}, repr(s["streams"]))
    check("dc streams empty for non-http data",
          dc.streams("not a url") == {"streams": [], "subtitles": []})

# ---------------------------------------------------------------- pkdramas
pk = PKDramas()
check("pk streams always empty (no embeds, youtube geo-blocked)",
      pk.streams("https://www.pkdramas.com/drama/323-tere-bin/episode/14857-x")
      == {"streams": [], "subtitles": []}
      and pk.streams("https://www.pkdramas.com/drama/3771-hurmat/episode/98539-x")
      == {"streams": [], "subtitles": []}
      and pk.streams("") == {"streams": [], "subtitles": []})

# ---------------------------------------------------------------- moviebox
MB_GET_NORES = {"code": 0, "data": {
    "subjectId": "6891610990048693368", "subjectType": 1,
    "title": "Avengers", "hasResource": False, "detailUrl": "",
    "description": "", "releaseDate": "2024-01-01", "genre": "",
    "cover": {}, "language": "English", "dubs": [],
}}
MB_SEASON_EMPTY = {"code": 0, "data": {"seasons": []}}


def _mb_api_nores(self, method, path, body=None, retry=True):
    if "/subject-api/get?" in path:
        return MB_GET_NORES
    if "/subject-api/season-info" in path:
        return MB_SEASON_EMPTY
    raise AssertionError("unexpected api path %s" % path)


mb = MovieBox()
with mock.patch.object(MovieBox, "_api", _mb_api_nores):
    d = mb.details("6891610990048693368")
    check("mb details hasResource false returns error, not episodes",
          isinstance(d, dict) and "error" in d
          and "no playable resource" in d["error"], repr(d))
check("mb subject to item drops hasResource false in search/home",
      _subject_to_item({"subjectId": "6891610990048693368",
                        "subjectType": 1, "title": "Avengers",
                        "hasResource": False}) is None)

# ------------------------------------------------- GAP 1: category + lang
from anime_api.sources.animedekho import AnimeDekho  # noqa: E402
from anime_api.sources.anikoto import AniKoto  # noqa: E402
from anime_api.sources.animeworld import AnimeWorld  # noqa: E402
from anime_api.sources.anisuge import AniSugeSource  # noqa: E402
from anime_api.sources.ckdub import CKDub  # noqa: E402
from anime_api.sources.indstream import IndStream  # noqa: E402
from anime_api.sources.multimovies import Multimovies  # noqa: E402
from anime_api.sources.nineanime import NineAnime  # noqa: E402
from anime_api.sources.rareanimes import RareAnimes  # noqa: E402
from anime_api.sources.reanime import ReanimeSource  # noqa: E402
from anime_api.sources.vegamovies import Vegamovies  # noqa: E402
from anime_api.sources.xanime import XanimeSource  # noqa: E402

import app as app_module  # noqa: E402
from app import _cache_key, app  # noqa: E402
from anime_api.cache import CACHE  # noqa: E402

_ALL = [DramaCool, PKDramas, Vegamovies, Multimovies, IndStream,
        CKDub, AnimeDekho, AnimeWorld, RareAnimes, XanimeSource,
        ReanimeSource, NineAnime, AniKoto, AniSugeSource, MovieBox]


def _fake_home_lang(self, section, page=1, **kw):
    cat = kw.get("category")
    item = {"id": "https://example.com/%s" % self.id,
            "title": "Item %s" % self.id, "poster": None, "year": None,
            "type": "movie" if self.id == "moviebox" else "anime",
            "audio": [], "source": self.id}
    if cat == "cdrama" and self.id == "dramacool":
        return [item]
    if cat == "kdrama" and self.id in ("dramacool", "ckdub"):
        return [item]
    if cat == "pakistani" and self.id == "pkdramas":
        return [item]
    if cat == "hollywood" and self.id == "moviebox":
        return [item]
    return []


client = app.test_client()
with ExitStack() as stack:
    for _cls in _ALL:
        stack.enter_context(mock.patch.object(_cls, "home", _fake_home_lang))
    r = client.get("/api/latest?lang=hindi&category=cdrama")
    body = r.get_json()
    check("GAP1 lang=hindi&category=cdrama returns dramacool (was 0)",
          r.status_code == 200 and len(body["results"]) == 1
          and body["results"][0]["source"] == "dramacool"
          and not body["errors"], repr(body))
    r = client.get("/api/latest?lang=hindi&category=kdrama")
    body = r.get_json()
    check("GAP1 lang=hindi&category=kdrama returns ckdub+dramacool",
          r.status_code == 200 and len(body["results"]) == 2
          and {it["source"] for it in body["results"]}
          == {"ckdub", "dramacool"}, repr(body))
    r = client.get("/api/latest?lang=hindi&category=pakistani")
    body = r.get_json()
    check("GAP1 lang=hindi&category=pakistani still returns pkdramas",
          r.status_code == 200 and len(body["results"]) == 1
          and body["results"][0]["source"] == "pkdramas", repr(body))
    r = client.get("/api/latest?lang=hindi&category=hollywood")
    body = r.get_json()
    check("GAP1 lang=hindi&category=hollywood still returns moviebox",
          r.status_code == 200 and len(body["results"]) == 1
          and body["results"][0]["source"] == "moviebox", repr(body))
    r = client.get("/api/latest?lang=hindi&category=nope")
    body = r.get_json()
    check("GAP1 unknown category stays empty + errors entry",
          r.status_code == 200 and body["results"] == []
          and len(body["errors"]) == 1
          and "nope" in body["errors"][0]["error"], repr(body))
    r = client.get("/api/latest?lang=hindi&category=cdrama&source=dramacool")
    body = r.get_json()
    check("GAP1 named source serving the category works under lang filter",
          r.status_code == 200 and len(body["results"]) == 1
          and body["results"][0]["source"] == "dramacool", repr(body))
    r = client.get("/api/latest?lang=hindi&category=cdrama&source=ckdub")
    body = r.get_json()
    check("GAP1 named source NOT serving the category: empty, no others",
          r.status_code == 200 and body["results"] == []
          and len(body["errors"]) == 1, repr(body))

# ------------------------------------------- empty streams are not cached
CACHE.clear()
_data = json.dumps({"sid": "1", "se": 0, "ep": 0, "dp": "x"})
_key = _cache_key("streams", "moviebox", _data)
with mock.patch.object(MovieBox, "streams",
                       return_value={"streams": [], "subtitles": []}):
    r = client.get("/api/streams?source=moviebox&data=" + quote(_data))
    _, hit_empty = CACHE.get(_key)
    check("GAP3 empty streams result is not cached",
          r.status_code == 200 and r.get_json()["streams"] == []
          and hit_empty is False, repr(r.get_json()))
with mock.patch.object(
        MovieBox, "streams",
        return_value={"streams": [{
            "name": "MovieBox",
            "url": "https://cdn.example.com/a1080.mp4?sign=x",
            "quality": 1080, "type": "video",
            "headers": {"Referer": "https://movie-box.co/"},
            "proxy": True, "label": "MovieBox 1080p"}],
            "subtitles": []}):
    r = client.get("/api/streams?source=moviebox&data=" + quote(_data))
    _, hit_full = CACHE.get(_key)
    check("GAP3 retry after empty returns the real stream (no poison)",
          r.status_code == 200 and len(r.get_json()["streams"]) == 1
          and hit_full is True, repr(r.get_json()))

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
