"""Unit + fixture tests for the AnimeDekho source (no live network).

Run: ~/workspace/anime-api-work/venv/bin/python tests/test_animedekho_unit.py
"""

import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anime_api.sources.animedekho import AnimeDekho  # noqa: E402

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
<span class="dgt-fact"><small>Age rating</small><b class="dgt-age">R</b></span>
<span class="dgt-fact"><small>Studio</small><b class="dgt-fact__links"><a href="https://animedekho.tv/browse/?studio=david-production">David Production</a></b></span>
<a class="dgt-ext__btn dgt-ext__btn--tmdb" href="https://www.themoviedb.org/tv/45790" target="_blank">TMDB</a>
<a class="dgt-ext__btn dgt-ext__btn--mal" href="https://myanimelist.net/anime/48661" target="_blank">MyAnimeList</a>
<a class="dgt-ext__btn dgt-ext__btn--anilist" href="https://anilist.co/anime/131942" target="_blank">AniList</a>
<div class="dgt-overview">Follow the feud between the Joestar Family and Dio Brando.</div>
<button class="dgt-tab" data-season="1">Season 1 (26)</button>
<button class="dgt-tab" data-season="2">Season 2 (48)</button>
<h2>Characters</h2>
<div class="dgt-cast">
<span class="dgt-cast__item"><span class="dgt-cast__img"><img data-src="https://s4.anilist.co/file/anilistcdn/character/large/b11222.png"></span><span>Jolyne Kuujou</span><small class="dgt-cast__role is-main">Main</small></span>
</div>
<h2>Hindi Voice Cast</h2>
<div class="dgt-vcast__grid"><div class="dgt-vcast__item"><span class="dgt-vcast__img"><img data-src="https://animedekho.tv/wp-content/uploads/va/krutarth-trivedi.jpg"></span><span class="dgt-vcast__txt"><span class="dgt-vcast__char">Gyro Zeppeli<span class="dgt-vcast__badge">Main</span></span><span class="dgt-vcast__va"><a href="#">Krutarth Trivedi</a></span></span></div></div>
</body></html>
""" % json.dumps(SNAPSHOT).replace("'", "&#x27;")

EPISODES_JSON = {"series_id": 10145, "season": 1, "episodes": [
    {"id": 59687, "series_id": 10145, "season": 1, "episode": 1,
     "name": "Dio the Invader", "overview": "England, 1868.",
     "air_date": "2012-10-06", "still": "https://image.tmdb.org/t/p/w300/x.jpg",
     "url": "https://animedekho.tv/epi/jojos-bizarre-adventure-1x1/"},
    {"id": 59688, "series_id": 10145, "season": 1, "episode": 2,
     "name": "A Letter from the Past", "overview": "",
     "air_date": "2012-10-13", "still": "", "filler": True,
     "url": "https://animedekho.tv/epi/jojos-bizarre-adventure-1x2/"},
]}

# WATCH_JSON / NONCE_HTML fixtures removed in v1.2: streams() no longer
# calls the (ad-gated) watch endpoint, it builds the embed URL directly.


# _quality helper removed in v1.2 (streams are direct embeds now;
# no server/language quality strings to parse).

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
        "post_id": 10145, "episode_id": 59687, "season": 1, "number": 1,
        "url": "https://animedekho.tv/epi/jojos-bizarre-adventure-1x1/"},
        repr(data))
    check("details: ep title", eps[0]["title"] == "Dio the Invader")
    check("details: ep still/air_date/filler",
          eps[0].get("still") == "https://image.tmdb.org/t/p/w300/x.jpg"
          and eps[0].get("air_date") == "2012-10-06"
          and eps[0].get("filler") is False
          and eps[1].get("filler") is True, repr(eps))
check("details: runtime/age/studio/links",
      det.get("runtime") == 24 and det.get("age_rating") == "R"
      and det.get("studio") == "David Production"
      and det.get("links") == {
          "tmdb": "https://www.themoviedb.org/tv/45790",
          "mal": "https://myanimelist.net/anime/48661",
          "anilist": "https://anilist.co/anime/131942"}, repr(det))
check("details: characters", len(det.get("characters") or []) == 1
      and det["characters"][0]["name"] == "Jolyne Kuujou"
      and det["characters"][0]["role"] == "Main", repr(det.get("characters")))
check("details: voice cast", len(det.get("voice_cast") or []) == 1
      and det["voice_cast"][0]["character"] == "Gyro Zeppeli"
      and det["voice_cast"][0]["actor"] == "Krutarth Trivedi",
      repr(det.get("voice_cast")))

# ---------------------------------------------------------------- streams
# v1.2: NO watch call any more (the watch endpoint is ad-gated for
# datacenter IPs). streams() builds the embed URL directly from the
# episode data: {host}/embed/<post_id>/<season>-<episode>.
out = src.streams(json.dumps({
    "post_id": 10145, "episode_id": 59928, "season": 4, "number": 38,
    "url": "https://animedekho.tv/epi/jojos-bizarre-adventure-4x38/"}))
check("streams: 1 direct embed",
      len(out.get("streams") or []) == 1, repr(out))
if out.get("streams"):
    first = out["streams"][0]
    check("streams: embed url built from season/episode",
          first["url"] == "https://animedekho.tv/embed/10145/4-38"
          and first["type"] == "embed" and first["proxy"] is False,
          repr(first))
    check("streams: referer header kept",
          first["headers"] == {
              "Referer": "https://animedekho.tv/epi/jojos-bizarre-adventure-4x38/"},
          repr(first))
check("streams: no subtitles", out.get("subtitles") == [])
check("streams: bad data empty",
      src.streams("not-json") == {"streams": [], "subtitles": []})
check("streams: no post_id empty",
      src.streams(json.dumps({"episode_id": 1})) == {
          "streams": [], "subtitles": []})
# old-format data (no season/number) falls back to the episode page
# URL itself as the embed target.
out_old = src.streams(json.dumps({
    "post_id": 10145, "episode_id": 59928,
    "url": "https://animedekho.tv/epi/jojos-bizarre-adventure-4x38/"}))
check("streams: legacy data falls back to episode page",
      len(out_old.get("streams") or []) == 1
      and out_old["streams"][0]["url"] ==
      "https://animedekho.tv/epi/jojos-bizarre-adventure-4x38/",
      repr(out_old))

# ---------------------------------------------------------------- home category
cat_resp = mock.Mock()
cat_resp.text = ROW_HTML
cat_resp.raise_for_status = mock.Mock()
with mock.patch("anime_api.sources.animedekho.get",
                return_value=cat_resp) as fake_get:
    tamil = src.home("latest", category="tamil")
    called_url = fake_get.call_args[0][0]
check("home: category hits /category/tamil/",
      "/category/tamil/" in called_url, called_url)
check("home: category items tagged audio_lang",
      len(tamil) == 2 and all(
          it.get("audio_lang") == "tamil" for it in tamil), repr(tamil))

# ---------------------------------------------------------------- registry
from anime_api.sources import get_source, list_sources  # noqa: E402

check("registry: animedekho listed",
      "animedekho" in [s.id for s in list_sources()])
reg = get_source("animedekho")
check("registry: language hindi", reg is not None and reg.language == "hindi")
check("registry: 15 sources total (v1.4: +dramacool, pkdramas, moviebox)",
      len(list_sources()) == 15,
      str([s.id for s in list_sources()]))

print()
print("TOTAL: %d passed, %d failed" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
