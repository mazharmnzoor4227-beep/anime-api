"""Unit + fixture tests for the AnimeDekho source (no live network).

Run: ~/workspace/anime-api-work/venv/bin/python tests/test_animedekho_unit.py
"""

import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anime_api.sources.animedekho import AnimeDekho, _quality  # noqa: E402

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


# ---------------------------------------------------------------- fixtures
ROW_HTML = """
<div class="dgt-row"><div class="dgt-row__head">New series</div>
<div class="dgt-row__scroller">
<a class="dgt-card" data-id="10145" href="https://animedekho.tv/series-hindi/jojos-bizarre-adventure/">
 <div class="dgt-card__poster"><img data-src="https://image.tmdb.org/t/p/w342/abc.jpg" src="data:image/svg+xml;base64,xxx"></div>
 <div class="dgt-card__title">JoJo\u2019s Bizarre Adventure</div>
 <div class="dgt-card__meta">2012 \u00b7 Series</div></a>
<a class="dgt-card" data-id="11448" href="https://animedekho.tv/movie-hindi/narudo-ninja-clash/">
 <div class="dgt-card__poster"><img data-src="https://image.tmdb.org/t/p/w342/def.jpg" src="data:image/svg+xml;base64,xxx"></div>
 <div class="dgt-card__title">Naruto the Movie: Ninja Clash in the Land of Snow</div>
 <div class="dgt-card__meta">2004 \u00b7 Movie</div></a>
<a class="dgt-card" data-id="10145" href="https://animedekho.tv/series-hindi/jojos-bizarre-adventure/">
 <div class="dgt-card__poster"><img data-src="https://image.tmdb.org/t/p/w342/abc.jpg"></div>
 <div class="dgt-card__title">JoJo\u2019s Bizarre Adventure</div>
 <div class="dgt-card__meta">2012 \u00b7 Series</div></a>
</div></div>
"""

SUGGEST_JSON = {"items": [
    {"id": 4959, "title": "Naruto Shipp\u016bden", "year": 2007,
     "type": "series",
     "url": "https://animedekho.tv/series-hindi/aruto-hippuden/",
     "poster": "https://image.tmdb.org/t/p/w342/rXD6lcg6zhRE8NDRVlQPNkViC3s.jpg"},
    {"id": 11448, "title": "Naruto the Movie: Ninja Clash in the Land of Snow",
     "year": 2004, "type": "movie",
     "url": "https://animedekho.tv/movie-hindi/narudo-ninja-clash/",
     "poster": "https://image.tmdb.org/t/p/w342/eUNRUeSNzm8LktH4HRaYiAReB6R.jpg"},
    {"id": 1, "title": "", "year": None, "type": "series",
     "url": "", "poster": None},
]}

SNAPSHOT = {
    "id": 10145, "type": "series",
    "title": "JoJo\u2019s Bizarre Adventure",
    "url": "https://animedekho.tv/series-hindi/jojos-bizarre-adventure/",
    "poster": "https://image.tmdb.org/t/p/w342/1HXdeK67pYSAukeZDhS3GJU8nIC.jpg",
    "backdrop": "https://image.tmdb.org/t/p/w1280/mLKN1dsimKPiXCZ48KED0X8a02t.jpg",
    "year": 2012, "rating": 8, "audio": "Hindi Dub", "runtime": 24,
    "genres": ["Action", "Adventure", "Anime"],
    "total": 160,
}
DETAIL_HTML = """
<html><body>
<div data-post="10145"></div>
<div data-snapshot='%s'></div>
<div class="dgt-meta">\u2605 8.0 \u00b7 2012 \u00b7 24 min \u00b7 160 episodes \u00b7 Returning Series \u00b7 Series</div>
<div class="dgt-overview">Follow the feud between the Joestar Family and Dio Brando.</div>
<button class="dgt-tab" data-season="1">Season 1 (26)</button>
<button class="dgt-tab" data-season="2">Season 2 (48)</button>
</body></html>
""" % json.dumps(SNAPSHOT).replace("'", "&#x27;")

EPISODES_JSON = {"series_id": 10145, "season": 1, "episodes": [
    {"id": 59687, "series_id": 10145, "season": 1, "episode": 1,
     "name": "Dio the Invader", "overview": "England, 1868.",
     "air_date": "2012-10-06", "still": "https://image.tmdb.org/t/p/w300/x.jpg",
     "url": "https://animedekho.tv/epi/jojos-bizarre-adventure-1x1/"},
    {"id": 59688, "series_id": 10145, "season": 1, "episode": 2,
     "name": "A Letter from the Past", "overview": "",
     "air_date": "2012-10-13", "still": "",
     "url": "https://animedekho.tv/epi/jojos-bizarre-adventure-1x2/"},
]}

WATCH_JSON = {"gated": False, "sources": [
    {"id": 0, "kind": "embed", "server": "HydraX", "language": "1080p",
     "quality": "Hindi Dub",
     "embed": "https://animedekho.tv/player.php?url=TOKEN1",
     "download": "https://animedekho.tv/download.php?url=TOKEN1",
     "show_embed": True, "show_download": True, "rank_embed": 3},
    {"id": 1, "kind": "embed", "server": "VidSrc-480p", "language": "1080p",
     "quality": "Hindi Dub",
     "embed": "https://animedekho.tv/player.php?url=TOKEN2",
     "download": "https://animedekho.tv/download.php?url=TOKEN2",
     "show_embed": False, "show_download": True, "rank_embed": 11},
    {"id": 4, "kind": "download", "server": "GDFlix-480p", "language": "1080p",
     "quality": "Hindi Dub",
     "embed": "", "download": "https://animedekho.tv/download.php?url=TOKEN3",
     "show_embed": False, "show_download": True, "rank_embed": 9999},
    {"id": 5, "kind": "embed", "server": "Vidstream", "language": "",
     "quality": "",
     "embed": "https://animedekho.tv/embed/45790/4-38",
     "download": "", "show_embed": True, "rank_embed": 0},
]}

NONCE_HTML = '<script>var DGT={"rest":"https://animedekho.tv/wp-json/dgt/v1/","nonce":"97f7371006","userId":"0"};</script>'

# ---------------------------------------------------------------- quality
check("quality from language 1080p", _quality("HydraX", "1080p") == 1080)
check("quality from server suffix", _quality("HubCopy-720p", "") == 720)
check("quality none", _quality("Vidstream", "") is None)
check("quality prefers language", _quality("HubCopy-480p", "1080p") == 1080)

# ---------------------------------------------------------------- cards
from bs4 import BeautifulSoup  # noqa: E402

src = AnimeDekho()
soup = BeautifulSoup(ROW_HTML, "lxml")
items = src._parse_cards(soup)
check("cards: 2 unique (dup removed)", len(items) == 2, repr(items))
check("cards: series first", items[0]["title"] == "JoJo\u2019s Bizarre Adventure"
      and items[0]["type"] == "anime" and items[0]["year"] == 2012
      and items[0]["poster"] == "https://image.tmdb.org/t/p/w342/abc.jpg"
      and items[0]["audio"] == ["dub"], repr(items[0]))
check("cards: movie second", items[1]["type"] == "movie"
      and items[1]["year"] == 2004, repr(items[1]))
check("row select latest", len(src._row_cards(soup, ("New series",))) == 2)
check("row select miss", src._row_cards(soup, ("Top rated",)) == [])

# ---------------------------------------------------------------- search
with mock.patch("anime_api.sources.animedekho.get_json",
                return_value=SUGGEST_JSON):
    results = src.search("naruto")
check("search: 2 items (empty dropped)", len(results) == 2, repr(results))
check("search: first is shippuden", results[0]["title"] == "Naruto Shipp\u016bden"
      and results[0]["id"] == "https://animedekho.tv/series-hindi/aruto-hippuden/"
      and results[0]["year"] == 2007, repr(results[0]))
check("search: movie type", results[1]["type"] == "movie")
check("search: page 2 empty", src.search("naruto", page=2) == [])

# ---------------------------------------------------------------- details
resp = mock.Mock()
resp.text = DETAIL_HTML
resp.raise_for_status = mock.Mock()
episodes_calls = []


def _fake_get_json(url, timeout=30):
    episodes_calls.append(url)
    return EPISODES_JSON


with mock.patch("anime_api.sources.animedekho.get", return_value=resp), \
        mock.patch("anime_api.sources.animedekho.get_json",
                   side_effect=_fake_get_json):
    det = src.details("https://animedekho.tv/series-hindi/jojos-bizarre-adventure/")
check("details: title", det.get("title") == "JoJo\u2019s Bizarre Adventure",
      repr(det.get("title")))
check("details: poster/banner", det.get("poster", "").endswith("1HXdeK67pYSAukeZDhS3GJU8nIC.jpg")
      and det.get("banner", "").endswith("mLKN1dsimKPiXCZ48KED0X8a02t.jpg"))
check("details: year/score/genres/status",
      det.get("year") == 2012 and det.get("score") == 8.0
      and det.get("genres") == ["Action", "Adventure", "Anime"]
      and det.get("status") == "ongoing", repr(det))
check("details: type/audio", det.get("type") == "anime"
      and det.get("audio") == ["dub"], repr(det))
check("details: plot", det.get("plot", "").startswith("Follow the feud"))
check("details: 2 seasons", len(det.get("seasons") or []) == 2,
      repr(det.get("seasons")))
if det.get("seasons"):
    eps = det["seasons"][0]["episodes"]
    check("details: season 1 has 2 eps", len(eps) == 2, repr(eps))
    data = json.loads(eps[0]["data"])
    check("details: ep data json", data == {
        "post_id": 10145, "episode_id": 59687,
        "url": "https://animedekho.tv/epi/jojos-bizarre-adventure-1x1/"},
        repr(data))
    check("details: ep title", eps[0]["title"] == "Dio the Invader")

# ---------------------------------------------------------------- streams
watch_resp = mock.Mock()
watch_resp.status_code = 200
watch_resp.json = mock.Mock(return_value=WATCH_JSON)
nonce_resp = mock.Mock()
nonce_resp.text = NONCE_HTML
nonce_resp.raise_for_status = mock.Mock()
with mock.patch("anime_api.sources.animedekho.get",
                return_value=nonce_resp), \
        mock.patch("requests.post", return_value=watch_resp) as post:
    out = src.streams(json.dumps({
        "post_id": 10145, "episode_id": 59928,
        "url": "https://animedekho.tv/epi/jojos-bizarre-adventure-4x38/"}))
    _args, kwargs = post.call_args
    check("streams: nonce header sent",
          kwargs.get("headers", {}).get("X-WP-Nonce") == "97f7371006",
          repr(kwargs.get("headers")))
check("streams: 2 embeds (hidden + download skipped)",
      len(out.get("streams") or []) == 2, repr(out))
if out.get("streams"):
    first = out["streams"][0]
    check("streams: rank order (Vidstream first)",
          first["url"] == "https://animedekho.tv/embed/45790/4-38"
          and first["type"] == "embed" and first["proxy"] is False,
          repr(first))
    second = out["streams"][1]
    check("streams: HydraX 1080p label",
          second["quality"] == 1080
          and second["label"] == "AnimeDekho HydraX (1080p)"
          and second["headers"] == {
              "Referer": "https://animedekho.tv/epi/jojos-bizarre-adventure-4x38/"},
          repr(second))
check("streams: no subtitles", out.get("subtitles") == [])
check("streams: bad data empty",
      src.streams("not-json") == {"streams": [], "subtitles": []})

# gated retry: first attempt gated, second (fresh nonce) works
gated_resp = mock.Mock()
gated_resp.status_code = 200
gated_resp.json = mock.Mock(return_value={"gated": True, "sources": []})
calls = {"n": 0}


def _post_seq(url, json=None, headers=None, timeout=30):
    calls["n"] += 1
    return gated_resp if calls["n"] == 1 else watch_resp


with mock.patch("anime_api.sources.animedekho.get",
                return_value=nonce_resp), \
        mock.patch("requests.post", side_effect=_post_seq):
    out2 = src.streams(json.dumps({"post_id": 10145, "episode_id": 1, "url": ""}))
check("streams: gated retry succeeds", len(out2.get("streams") or []) == 2,
      repr(out2))

# nonce lives on episode pages, NOT the homepage (2026-11-18: the cached
# homepage has no dgt-store script). streams() must scrape the referer
# episode page first, homepage only as fallback.
home_resp = mock.Mock()
home_resp.text = "<html><body>no nonce here</body></html>"
home_resp.raise_for_status = mock.Mock()


def _get_seq(url, timeout=30, **kwargs):
    return nonce_resp if "/epi/" in str(url) else home_resp


src2 = AnimeDekho()
with mock.patch("anime_api.sources.animedekho.get",
                side_effect=_get_seq), \
        mock.patch("requests.post", return_value=watch_resp) as post2:
    out3 = src2.streams(json.dumps({
        "post_id": 10145, "episode_id": 59928,
        "url": "https://animedekho.tv/epi/jojos-bizarre-adventure-4x38/"}))
    _args, kwargs = post2.call_args
    check("streams: nonce from episode page, not homepage",
          kwargs.get("headers", {}).get("X-WP-Nonce") == "97f7371006",
          repr(kwargs.get("headers")))
check("streams: episode-page nonce yields streams",
      len(out3.get("streams") or []) == 2, repr(out3))

# ---------------------------------------------------------------- registry
from anime_api.sources import get_source, list_sources  # noqa: E402

check("registry: animedekho listed",
      "animedekho" in [s.id for s in list_sources()])
reg = get_source("animedekho")
check("registry: language hindi", reg is not None and reg.language == "hindi")
check("registry: 8 sources total", len(list_sources()) == 8,
      str([s.id for s in list_sources()]))

print()
print("TOTAL: %d passed, %d failed" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
