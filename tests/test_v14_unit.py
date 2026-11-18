"""Unit + fixture tests for the v1.4 sources and auto-update.

DramaCool (K/C-drama, English sub), PKDramas (Pakistani dramas via
official YouTube), the 30-minute refresh job, and /health refresh
fields.

No live network (HTML sources use fixtures). Run:
  ~/workspace/anime-api-work/venv/bin/python tests/test_v14_unit.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest import mock

from bs4 import BeautifulSoup  # noqa: E402

from anime_api.sources.dramacool import DramaCool, _clean_card_text  # noqa: E402
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


def _soup(html):
    return BeautifulSoup(html, "lxml")


# ---------------------------------------------------------------- DramaCool
check("dc clean card text unwraps seo spam",
      _clean_card_text("Watch the latest show The Substitute with "
                       "English subtitles for free in Dramacool")
      == "The Substitute")
check("dc clean card text cuts year tail",
      _clean_card_text("Happy Boys 2007 Completed") == "Happy Boys")
check("dc clean card text watch now is empty",
      _clean_card_text("Watch now") == "")
check("dc clean card text status badge alone is not a title",
      _clean_card_text("Completed") == ""
      and _clean_card_text("Ongoing") == "")
check("dc clean card text strips EP prefix + recency suffix",
      _clean_card_text("EP 11 Blossom in Darkness 3h ago")
      == "Blossom in Darkness"
      and _clean_card_text("EP 38 Mission: Mompossible 2 days ago")
      == "Mission: Mompossible")

DC_SEARCH = """
<html><body>
<a href="/drama/boys-mind-camp"><img src="https://cdn1.asiaflix.net/images/boys.png" alt="Watch the latest show Boys' Mind Camp with English subtitles for free in Dramacool"></a>
<a href="/drama/boys-mind-camp">Boys' Mind Camp</a>
<a href="/drama/boys-mind-camp">Watch now</a>
<a href="/drama/boys-mind-camp">Ongoing</a>
<a href="/drama/happy-boys"><img src="https://cdn1.asiaflix.net/images/happy.png"></a>
<a href="/drama/happy-boys">Happy Boys 2007 Completed</a>
<a href="/drama/blossom-in-darkness-2"><img src="https://cdn1.asiaflix.net/images/blossom.png" alt="Watch the latest show Blossom in Darkness with English subtitles for free in Dramacool"></a>
<a href="/drama/blossom-in-darkness-2">EP 11 Blossom in Darkness 3h ago</a>
</body></html>
"""
DC_DETAIL = """
<html><head>
<meta property="og:title" content="Blossom in Darkness (2026) English Sub - Dramacool">
<meta property="og:image" content="https://dramizo.com/wp-content/uploads/2026/11/blossom.jpg">
<meta name="description" content="A demon falls in love.">
</head><body>
<div>Blossom in Darkness (2026) China 2026 Ongoing TVSeries Genres: Fantasy • Romance • Wuxia Synopsis Big Demon Qi Feng Yin is locked away.</div>
<a href="/drama/blossom-in-darkness-2/episode-1">Episode 1</a>
<a href="/drama/blossom-in-darkness-2/episode-2">Episode 2</a>
<a href="/drama/blossom-in-darkness-2/episode-2">Episode 2</a>
</body></html>
"""
DC_EPISODE = """
<html><body><iframe src="https://vidmoly.org/embed-21w3v6zebhw9.html"></iframe>
<a href="https://streamtape.com/e/abc123">Streamtape</a>
</body></html>
"""

dc = DramaCool()


def _dc_search_cards_get(url, headers=None, timeout=30):
    m = mock.Mock()
    m.text = DC_SEARCH
    m.raise_for_status = mock.Mock()
    return m


# No transfer-cache record in this fixture -> card-parsing fallback.
# The Boys' Mind Camp card also carries a bare "Ongoing" badge link
# on the same URL — the title must still be the drama name, and the
# EP/recency text on the Blossom card must be stripped to the title.
with mock.patch("anime_api.sources.dramacool.get",
                side_effect=_dc_search_cards_get):
    hits = dc.search("boys")
    check("dc search cards deduped, spam alt unwrapped, badge ignored",
          len(hits) == 3 and hits[0]["title"] == "Boys' Mind Camp"
          and hits[0]["poster"] is not None
          and hits[1]["title"] == "Happy Boys" and hits[1]["year"] == 2007
          and hits[2]["title"] == "Blossom in Darkness",
          repr(hits))

with mock.patch.object(DramaCool, "_soup", return_value=_soup(DC_SEARCH)):
    home = dc.home("latest", category="cdrama")
    check("dc home category cdrama parses same cards",
          len(home) == 3 and home[2]["title"] == "Blossom in Darkness",
          repr(home))
DC_SEARCH_SSR = (
    '<html><body><script>window.__x={"t":{},"b":{'
    '"currentPage":1,"nextPage":2,"hasNext":true,"hasPrevious":false,'
    '"totalPages":14,"totalItems":139,"body":['
    '{"name":"Boys Over Flowers","normalizedName":"boys-over-flowers",'
    '"image":"https://cdn1.asiaflix.net/images/bof.png",'
    '"coverImage":"https://image.tmdb.org/t/p/w1280/xx.jpg",'
    '"status":"Completed","releaseYear":"2009","casts":[],'
    '"slug":"boys-over-flowers-2009"},'
    '{"name":"Water Boys","normalizedName":"water-boys",'
    '"image":"https://cdn1.asiaflix.net/images/wb.png",'
    '"status":"Completed","releaseYear":"2021","casts":[],'
    '"slug":"water-boys-2"}]},'
    '"h":{},"s":200,"st":"OK",'
    '"u":"https://api.dramacool.rest/v1/drama/search?q=boys&page=1",'
    '"rt":"json"}</script></body></html>'
)


def _dc_search_get(url, headers=None, timeout=30):
    m = mock.Mock()
    m.text = DC_SEARCH_SSR
    m.raise_for_status = mock.Mock()
    return m


with mock.patch("anime_api.sources.dramacool.get",
                side_effect=_dc_search_get):
    hits = dc.search("boys")
    check("dc search parses SSR transfer-cache record",
          len(hits) == 2
          and hits[0]["title"] == "Boys Over Flowers"
          and hits[0]["year"] == 2009
          and hits[0]["id"].endswith("/drama/boys-over-flowers-2009")
          and hits[1]["title"] == "Water Boys"
          and hits[1]["id"].endswith("/drama/water-boys-2"),
          repr(hits))

with mock.patch.object(DramaCool, "_soup", return_value=_soup(DC_DETAIL)):
    d = dc.details("https://dramaacool.best/drama/blossom-in-darkness-2")
    check("dc details title/genres/status/episodes",
          d["title"] == "Blossom in Darkness (2026)"
          and d["genres"] == ["Fantasy", "Romance", "Wuxia"]
          and d["status"] == "ongoing" and d["year"] == 2026
          and len(d["seasons"][0]["episodes"]) == 2
          and d["seasons"][0]["episodes"][1]["data"].endswith("/episode-2"),
          repr(d))


def _dc_get(url, headers=None, timeout=30):
    m = mock.Mock()
    m.text = DC_EPISODE
    m.raise_for_status = mock.Mock()
    return m


with mock.patch("anime_api.sources.dramacool.get", side_effect=_dc_get):
    s = dc.streams("https://dramaacool.best/drama/blossom-in-darkness-2/episode-1")
    # v1.4.1: an embed-only page (vidmoly iframe, no direct file)
    # yields NO streams — embeds are never returned any more.
    check("dc streams embed-only page yields no streams",
          s == {"streams": [], "subtitles": []},
          repr(s["streams"]))

# ---------------------------------------------------------------- PKDramas
PK_SEARCH = """
<html><body>
<a href="/drama/323-tere-bin"><img src="https://cdn.pkdramas.com/uploads/tere.jpg">Tere Bin</a>
<a href="/drama/863-tere-bina-mein-nahi">Tere Bina Mein Nahi</a>
<a href="/drama/323-tere-bin">Tere Bin</a>
</body></html>
"""
PK_DETAIL = """
<html><head>
<meta property="og:title" content="Hurmat Full Episodes — Hum TV | Pakistani Dramas">
<meta property="og:image" content="https://i.ytimg.com/vi/GT35OUCEk4M/maxresdefault.jpg">
<meta name="description" content="Hurmat is a Hum TV drama.">
</head><body>
<a href="/drama/3771-hurmat/episode/98539-hurmat-episode-14">Hurmat Episode 14</a>
<a href="/drama/3771-hurmat/episode/98518-hurmat-episode-13">Hurmat Episode 13</a>
</body></html>
"""
PK_EPISODE = ('<html><head><meta property="og:image" content='
              '"https://i.ytimg.com/vi/GT35OUCEk4M/maxresdefault.jpg"/>'
              '</head><body><script>{"videoId":"GT35OUCEk4M",'
              '"episodeId":98539}</script></body></html>')
# Same id, but inside the Next.js RSC payload with escaped quotes —
# the live shape (Tere Bin ep 9, 2026-11-18).
PK_EPISODE_ESC = ('<script>self.__next_f.push([1,\\"21:[\\"$\\",\\"div\\",'
                'null,{\\"videoId\\":\\"FOayEzY3C3o\\",'
                '\\"episodeId\\":14857}]\\"])</script>')
# Episode links as absolute URLs (no www) — the live Hurmat shape.
PK_DETAIL_ABS = """
<html><head>
<meta property="og:title" content="Hurmat Full Episodes — Hum TV | Pakistani Dramas">
</head><body>
<a href="https://pkdramas.com/drama/3771-hurmat/episode/98539-hurmat-episode-14">Hurmat Episode 14</a>
<a href="https://pkdramas.com/drama/3771-hurmat/episode/98518-hurmat-episode-13">Hurmat Episode 13</a>
</body></html>
"""

from anime_api.sources.pkdramas import _path_of  # noqa: E402
check("pk path_of strips absolute origin",
      _path_of("https://pkdramas.com/drama/3771-hurmat/episode/98539-x")
      == "/drama/3771-hurmat/episode/98539-x"
      and _path_of("/drama/3771-hurmat/episode/98539-x")
      == "/drama/3771-hurmat/episode/98539-x")

pk = PKDramas()
with mock.patch.object(PKDramas, "_soup", return_value=_soup(PK_SEARCH)):
    hits = pk.search("tere bin")
    check("pk search cards deduped",
          len(hits) == 2 and hits[0]["title"] == "Tere Bin"
          and hits[0]["id"].endswith("/drama/323-tere-bin"),
          repr(hits))

with mock.patch.object(PKDramas, "_soup", return_value=_soup(PK_DETAIL)):
    d = pk.details("https://www.pkdramas.com/drama/3771-hurmat")
    check("pk details title/episodes sorted",
          d["title"] == "Hurmat"
          and len(d["seasons"][0]["episodes"]) == 2
          and d["seasons"][0]["episodes"][0]["number"] == 13
          and d["seasons"][0]["episodes"][1]["number"] == 14,
          repr(d))


with mock.patch.object(PKDramas, "_soup", return_value=_soup(PK_DETAIL_ABS)):
    d = pk.details("https://www.pkdramas.com/drama/3771-hurmat")
    check("pk details absolute episode hrefs parse",
          len(d["seasons"][0]["episodes"]) == 2
          and d["seasons"][0]["episodes"][1]["number"] == 14,
          repr(d["seasons"]))


def _pk_get_esc(url, headers=None, timeout=30):
    m = mock.Mock()
    m.text = PK_EPISODE_ESC
    m.raise_for_status = mock.Mock()
    return m


def _pk_get(url, headers=None, timeout=30):
    m = mock.Mock()
    m.text = PK_EPISODE
    m.raise_for_status = mock.Mock()
    return m


with mock.patch("anime_api.sources.pkdramas.get",
                side_effect=_pk_get_esc):
    s = pk.streams("https://www.pkdramas.com/drama/323-tere-bin/episode/14857-x")
    # v1.4.1: YouTube uploads are geo-blocked from the server and
    # embeds are never returned — streams are always empty.
    check("pk streams returns empty (no embeds, youtube geo-blocked)",
          s == {"streams": [], "subtitles": []},
          repr(s["streams"]))


with mock.patch("anime_api.sources.pkdramas.get", side_effect=_pk_get):
    s = pk.streams("https://www.pkdramas.com/drama/3771-hurmat/episode/98539-x")
    check("pk streams returns empty (no embeds, youtube geo-blocked)",
          s == {"streams": [], "subtitles": []},
          repr(s["streams"]))

# ---------------------------------------------------------------- registry
from anime_api.sources import get_source, source_ids  # noqa: E402
check("registry has v1.4 sources",
      all(s in source_ids() for s in ("dramacool", "pkdramas")),
      repr(source_ids()))
check("v1.4 media_type + categories attrs",
      get_source("dramacool").media_type == "series"
      and get_source("dramacool").categories == ("kdrama", "cdrama")
      and get_source("pkdramas").media_type == "series"
      and get_source("pkdramas").categories == ("pakistani",))

# ---------------------------------------------------------------- refresh job + health
import app as app_module  # noqa: E402
from app import app  # noqa: E402

jobs = app_module._refresh_jobs()
check("refresh jobs cover sections/langs/types/categories/sources",
      ("latest", "all", "all", 1, None, "movie") in jobs
      and ("trending", "hindi", "all", 1, None, "all") in jobs
      and ("latest", "all", "all", 1, "pakistani", "all") in jobs
      and ("latest", "all", "all", 1, "cdrama", "all") in jobs
      and ("latest", "all", "all", 1, "kdrama", "all") in jobs
      and ("latest", "all", "pkdramas", 1, None, "all") in jobs
      and len(jobs) > 50,
      "jobs=%d" % len(jobs))

with mock.patch.object(app_module, "_compute_list",
                       return_value=([{"id": "x", "title": "T",
                                       "poster": None, "year": None,
                                       "type": "movie", "audio": [],
                                       "source": "vegamovies"}], [])):
    before = app_module.REFRESH_STATE["runs"]
    items, errors = app_module._refresh_once()
    check("refresh run updates state + counts items",
          app_module.REFRESH_STATE["runs"] == before + 1
          and app_module.REFRESH_STATE["last_run"] is not None
          and app_module.REFRESH_STATE["last_items"] == len(jobs)
          and app_module.REFRESH_STATE["last_duration_s"] is not None,
          repr(app_module.REFRESH_STATE))
# The refresh run above wrote mocked payloads into the real cache —
# clear it so the route tests below hit the mocked sources, not
# the mocked refresh data.
app_module.CACHE.clear()

client = app.test_client()
r = client.get("/health")
body = r.get_json()
check("GET /health reports refresh state + intervals",
      r.status_code == 200 and body["ok"] is True
      and "dramacool" in body["sources"]
      and "pkdramas" in body["sources"]
      and body["refresh"]["runs"] >= 1
      and body["refresh_interval_s"] == 1800
      and body["prewarm_interval_s"] == 300,
      repr(body))

# ---------------------------------------------------------------- routes: new categories
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
from contextlib import ExitStack  # noqa: E402

_ALL = [DramaCool, PKDramas, Vegamovies, Multimovies, IndStream,
        CKDub, AnimeDekho, AnimeWorld, RareAnimes, XanimeSource,
        ReanimeSource, NineAnime, AniKoto, AniSugeSource]


def _fake_home_cat(self, section, page=1, **kw):
    cat = kw.get("category")
    if cat == "pakistani" and self.id == "pkdramas":
        return [{"id": "https://www.pkdramas.com/drama/1-x", "title": "Drama X",
                 "poster": None, "year": None, "type": "anime",
                 "audio": [], "source": "pkdramas"}]
    if cat == "cdrama" and self.id == "dramacool":
        return [{"id": "https://dramaacool.best/drama/x", "title": "C-Drama X",
                 "poster": None, "year": 2026, "type": "anime",
                 "audio": ["sub"], "source": "dramacool"}]
    if cat == "kdrama" and self.id == "dramacool":
        return [{"id": "https://dramaacool.best/drama/y", "title": "K-Drama Y",
                 "poster": None, "year": 2026, "type": "anime",
                 "audio": ["sub"], "source": "dramacool"}]
    if cat == "kdrama" and self.id == "ckdub":
        return [{"id": "https://www.ckdub.com/drama/x", "title": "Drama X",
                 "poster": None, "year": None, "type": "anime",
                 "audio": ["dub"], "source": "ckdub"}]
    return []


with ExitStack() as stack:
    for _cls in _ALL:
        stack.enter_context(mock.patch.object(_cls, "home", _fake_home_cat))
    r = client.get("/api/latest?category=pakistani")
    body = r.get_json()
    check("GET /api/latest?category=pakistani fans out to pkdramas",
          r.status_code == 200 and len(body["results"]) == 1
          and body["results"][0]["source"] == "pkdramas", repr(body))
    r = client.get("/api/latest?category=cdrama")
    body = r.get_json()
    check("GET /api/latest?category=cdrama fans out to dramacool",
          r.status_code == 200 and len(body["results"]) == 1
          and body["results"][0]["source"] == "dramacool", repr(body))
    r = client.get("/api/latest?category=kdrama")
    body = r.get_json()
    check("GET /api/latest?category=kdrama fans out to ckdub+dramacool",
          r.status_code == 200 and len(body["results"]) == 2
          and {it["source"] for it in body["results"]}
          == {"ckdub", "dramacool"}, repr(body))

with mock.patch.object(PKDramas, "details",
                       lambda self, item_id: {
                           "id": item_id, "title": "Drama X", "poster": None,
                           "banner": None, "plot": None, "genres": [],
                           "year": None, "status": None, "score": None,
                           "type": "anime", "audio": [],
                           "seasons": [{"number": 1, "name": "Season 1",
                                        "episodes": [{"number": 1,
                                                      "title": "Ep 1",
                                                      "data": "{}"}]}]}):
    r = client.get("/api/title?source=pkdramas&id=https://www.pkdramas.com/drama/1-x")
    body = r.get_json()
    check("GET /api/title works for pkdramas",
          r.status_code == 200 and body["title"] == "Drama X"
          and body["type"] == "anime", repr(body))

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
