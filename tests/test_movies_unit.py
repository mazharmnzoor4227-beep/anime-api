"""Unit + fixture tests for the v1.3 movie / K-drama sources and routes.

No live network (one Firebase domain lookup happens via base_url, as in
the existing hindi unit tests). Run:
  ~/workspace/anime-api-work/venv/bin/python tests/test_movies_unit.py
"""

import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest import mock

from bs4 import BeautifulSoup  # noqa: E402

from anime_api.sources.ckdub import CKDub  # noqa: E402
from anime_api.sources.indstream import IndStream  # noqa: E402
from anime_api.sources.multimovies import Multimovies  # noqa: E402
from anime_api.sources.vegamovies import Vegamovies, _clean_title  # noqa: E402
from anime_api.http import BROWSER_UA  # noqa: E402

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


# ---------------------------------------------------------------- title cleaning
check("vega clean title",
      _clean_title("Download Avengers Endgame (2019) Hindi Dubbed 720p")
      == "Avengers Endgame (2019)")
check("vega clean title no year",
      _clean_title("Download Some Movie Dual Audio Hindi") == "Some Movie")

# ---------------------------------------------------------------- Vegamovies
VEGA_SEARCH = {"hits": [{"document": {
    "permalink": "/download-avengers-endgame-2019-hindi/",
    "post_title": "Download Avengers Endgame (2019) Hindi Dubbed 720p",
    "post_thumbnail": "https://img.example/a.jpg",
}}]}

VEGA_LIST = """
<html><body>
<div class="poster-card">
<meta itemprop="url" content="https://vegamovies.lease/download-avengers-endgame-2019-hindi/">
<img alt="Download Avengers Endgame (2019) Hindi Dubbed 720p" data-src="https://img.example/a.jpg">
</div>
<div class="poster-card">
<a href="https://vegamovies.lease/download-other-2024/"><img alt="Other (2024)"></a>
</div>
<div class="poster-card"><a href="https://vegamovies.lease/page/2/"><img alt="Nav"></a></div>
</body></html>
"""

VEGA_DETAIL = """
<html><head><title>Download Avengers Endgame (2019) Hindi Dubbed | Vega</title>
<meta property="og:image" content="https://img.example/poster.jpg"></head>
<body><h1>Download Avengers Endgame (2019) Hindi Dubbed 720p</h1>
<div class="entry-content">
<p>Language: Hindi-English</p>
<p>Movie-SYNOPSIS/PLOT: Earth's mightiest heroes assemble.</p>
<h3>Download Avengers Endgame (2019) Hindi 720p [2.3GB]</h3>
<p><a href="https://nexdrive.beer/genxfm111/">G-Drive 720p</a></p>
<p><a href="https://nexdrive.beer/genxfm222/">V-Cloud 720p</a></p>
<h3>Download Avengers Endgame (2019) Hindi 480p [900MB]</h3>
<p><a href="https://nexdrive.beer/genxfm333/">G-Drive 480p</a></p>
</div></body></html>
"""

VEGA_GATEWAY = """
<html><body>
<a href="https://fastdl.zip/embed.php?download=ABC123">fastdl</a>
<a href="https://vcloud.lol/XYZ789">vcloud</a>
</body></html>
"""

VEGA_FASTDL = '<html><body><a href="https://video-downloads.googleusercontent.com/FILETOKEN123">dl</a></body></html>'

_token_inner = base64.b64encode(
    b"https://token.example.com/page1").decode()
_token_outer = base64.b64encode(_token_inner.encode()).decode()
VEGA_VCLOUD = '<html><body><script>var url = atob(atob("%s"));</script></body></html>' % _token_outer
VEGA_TOKEN = """
<html><body>
<a href="https://abc.r2.cloudflarestorage.com/file-720p.mp4">[FSL] Download File</a>
<a href="https://example.com/other">Other</a>
</body></html>
"""

vega = Vegamovies()
with mock.patch("anime_api.sources.vegamovies.get_json",
                return_value=VEGA_SEARCH):
    hits = vega.search("avengers")
    check("vega search index",
          len(hits) == 1 and hits[0]["title"] == "Avengers Endgame (2019)"
          and hits[0]["id"].startswith("https://vegamovies.lease/download-")
          and hits[0]["type"] == "movie" and hits[0]["year"] == 2019,
          repr(hits))

with mock.patch.object(Vegamovies, "_soup", return_value=_soup(VEGA_LIST)):
    home = vega.home("latest")
    check("vega home listing",
          len(home) == 2 and home[0]["title"] == "Avengers Endgame (2019)"
          and home[1]["title"] == "Other (2024)", repr(home))

with mock.patch.object(Vegamovies, "_soup", return_value=_soup(VEGA_DETAIL)):
    d = vega.details("https://vegamovies.lease/download-avengers-endgame-2019-hindi/")
    check("vega details title/plot/year",
          d["title"] == "Avengers Endgame (2019)"
          and d["plot"] == "Earth's mightiest heroes assemble."
          and d["year"] == 2019 and d["type"] == "movie",
          repr(d))
    check("vega details one episode per quality group",
          len(d["seasons"]) == 1 and len(d["seasons"][0]["episodes"]) == 2
          and len(json.loads(d["seasons"][0]["episodes"][0]["data"])["gateways"]) == 2,
          repr(d["seasons"]))


def _vega_get(url, headers=None, timeout=30):
    m = mock.Mock()
    if "genxfm111" in url or "genxfm222" in url or "genxfm333" in url:
        m.text = VEGA_GATEWAY
    elif "fastdl" in url:
        m.text = VEGA_FASTDL
    elif "vcloud" in url:
        m.text = VEGA_VCLOUD
    elif "token.example.com" in url:
        m.text = VEGA_TOKEN
    else:
        m.text = ""
    return m


with mock.patch("anime_api.sources.vegamovies.get",
                side_effect=_vega_get):
    data = json.dumps({"page": "https://vegamovies.lease/download-x/",
                       "gateways": ["https://nexdrive.beer/genxfm111/",
                                    "https://nexdrive.beer/genxfm222/"],
                       "heading": "720p [2.3GB]"})
    s = vega.streams(data)
    urls = [st["url"] for st in s["streams"]]
    check("vega streams fastdl direct file",
          any("video-downloads.googleusercontent.com/FILETOKEN123" in u
              for u in urls), repr(urls))
    check("vega streams vcloud r2 file",
          any("r2.cloudflarestorage.com/file-720p.mp4" in u for u in urls),
          repr(urls))
    check("vega streams quality from heading",
          all(st["quality"] == 720 for st in s["streams"]), repr(s))

# ---------------------------------------------------------------- Multimovies
MM_API = {"results": [
    {"id": 809, "title": "Avengers: Endgame", "type": "movie", "year": 2019,
     "rating": 8.2, "quality": "1080p",
     "poster": "https://image.tmdb.org/t/p/w185/x.jpg",
     "url": "/movie/avengers-endgame-809"},
    {"id": 810, "title": "Some Series", "type": "tv", "year": 2020,
     "url": "/series/some-series-810"},
]}

MM_LIST = """
<html><body>
<article class="poster-card">
<a class="poster-art" href="/movie/avengers-endgame-809"><img src="https://img.example/a.jpg"></a>
<div class="poster-caption"><a href="/movie/avengers-endgame-809">Avengers: Endgame</a></div>
<p class="poster-meta">2019</p>
</article>
</body></html>
"""

MM_DETAIL = """
<html><head><meta property="og:image" content="https://img.example/poster.jpg"></head>
<body>
<h1 class="cinejoy-detail-title">Avengers: Endgame</h1>
<p class="cinejoy-detail-overview">The Avengers assemble once more.</p>
<div class="cinejoy-detail-genres">Action • Adventure</div>
<script>watchConfig = {"initialServers": [
  {"name": "Cineverse", "url": "https://rozgarlelo.modiplay.xyz/embed/tmdb/movie?id=299534"},
  {"name": "Other", "url": "https://example.com/embed/{tmdbId}"}
]};</script>
<button class="server-chip" data-url="https://embed.vidrift.net/embed/movie/299534">
<span class="server-name">Vidrift</span></button>
</body></html>
"""

MM_EMBED = """
<html><body><iframe src="/proxy.php?p=streamhg&amp;c=ABC&amp;title=X"></iframe></body></html>
"""
MM_PROXY = r"""
<html><body><script>var src="\/stream_proxy.php?url=https%3A%2F%2Fvibuxer.com%2Fstream%2Fabc%2Fmaster.m3u8&ref=https%3A%2F%2Fvibuxer.com%2Fe%2FABC&tok=TOK123";</script></body></html>
"""
MM_MASTER = """#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio0",NAME="हिन्दी",LANGUAGE="hi",DEFAULT=YES,URI="/stream_proxy.php?url=x/index-f1-a1.m3u8"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",LANGUAGE="eng",URI="subtitles_english.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=1280x720
https://cdn.example.com/v/720/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=400000,RESOLUTION=854x480
https://cdn.example.com/v/480/index.m3u8
"""

mm = Multimovies()
with mock.patch("anime_api.sources.multimovies.get_json",
                return_value=MM_API):
    hits = mm.search("avengers")
    check("mm search api (movies only)",
          len(hits) == 1 and hits[0]["title"] == "Avengers: Endgame"
          and hits[0]["id"].endswith("/movie/avengers-endgame-809")
          and hits[0]["type"] == "movie", repr(hits))

with mock.patch.object(Multimovies, "_soup", return_value=_soup(MM_LIST)):
    home = mm.home("latest")
    check("mm home cards",
          len(home) == 1 and home[0]["title"] == "Avengers: Endgame"
          and home[0]["year"] == 2019, repr(home))

with mock.patch.object(Multimovies, "_soup", return_value=_soup(MM_DETAIL)):
    d = mm.details("https://m1.multimovies.courses/movie/avengers-endgame-809")
    check("mm details title/plot/genres",
          d["title"] == "Avengers: Endgame"
          and d["plot"] == "The Avengers assemble once more."
          and d["genres"] == ["Action", "Adventure"], repr(d))
    check("mm details servers (config + chips, tmdb filled)",
          len(d["seasons"]) == 1 and len(d["seasons"][0]["episodes"]) == 1
          and len(json.loads(d["seasons"][0]["episodes"][0]["data"])["servers"]) == 3
          and "299534" in json.loads(d["seasons"][0]["episodes"][0]["data"])["servers"][1]["u"],
          repr(d["seasons"]))


def _mm_get(url, headers=None, timeout=30):
    m = mock.Mock()
    # NOTE: check stream_proxy.php BEFORE proxy.php — the stream-proxy
    # URL contains "proxy.php" as a substring.
    if "stream_proxy.php" in url:
        m.text = MM_MASTER
    elif "modiplay" in url and "proxy.php" not in url:
        m.text = MM_EMBED
    elif "proxy.php" in url:
        m.text = MM_PROXY
    else:
        m.text = ""
    return m


with mock.patch("anime_api.sources.multimovies.get", side_effect=_mm_get):
    data = json.dumps({"page": "https://m1.multimovies.courses/movie/avengers-endgame-809",
                       "servers": [
                           {"n": "Cineverse", "u": "https://rozgarlelo.modiplay.xyz/embed/tmdb/movie?id=299534"},
                           {"n": "Vidrift", "u": "https://embed.vidrift.net/embed/movie/299534"},
                       ]})
    s = mm.streams(data)
    m3u8 = [st for st in s["streams"] if st["type"] == "m3u8"]
    check("mm streams cineverse master m3u8",
          len(m3u8) == 1 and "stream_proxy.php" in m3u8[0]["url"]
          and m3u8[0]["quality"] == 720 and m3u8[0]["proxy"] is True,
          repr(s["streams"]))
    check("mm cineverse stream carries browser UA",
          m3u8 and m3u8[0]["headers"].get("User-Agent") == BROWSER_UA,
          repr(m3u8[0]["headers"]) if m3u8 else "no m3u8")
    check("mm streams subtitle from master",
          len(s["subtitles"]) == 1 and s["subtitles"][0]["label"] == "English",
          repr(s["subtitles"]))
    check("mm streams other server as embed fallback",
          any(st["type"] == "embed" and "vidrift" in st["url"]
              for st in s["streams"]), repr(s["streams"]))

# ---------------------------------------------------------------- IndStream
IS_IMDB = {"d": [
    {"id": "tt4154796", "l": "Avengers: Endgame", "q": "feature", "y": 2019,
     "i": {"imageUrl": "https://img.example/p.jpg"}},
    {"id": "tt9999999", "l": "Some Series", "q": "TV series", "y": 2020},
]}
IS_CATALOG = {"metas": [
    {"id": "tt4154796", "name": "Avengers: Endgame",
     "poster": "https://img.example/p.jpg", "year": "2019",
     "imdbRating": "8.4"},
]}
IS_META = {"meta": {
    "name": "Avengers: Endgame", "poster": "https://img.example/p.jpg",
    "background": "https://img.example/bg.jpg",
    "description": "After the Snap, the Avengers assemble.",
    "genre": ["Action", "Adventure"], "year": "2019",
    "imdbRating": "8.4", "moviedb_id": 299534,
}}
IS_VIDLY = '<html><body><script>var src="https://img.rousav.tech/media/abc/index.m3u8";</script></body></html>'
IS_MASTER = """#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aac",LANGUAGE="hin",NAME="Hindi",DEFAULT=NO,URI="track_hindi.m3u8"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",LANGUAGE="eng",URI="subtitles_english.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=1280x720
https://cdn.example.com/v/720/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1920x1080
https://cdn.example.com/v/1080/index.m3u8
"""

ind = IndStream()
with mock.patch("anime_api.sources.indstream.get_json",
                return_value=IS_IMDB):
    hits = ind.search("avengers")
    check("indstream search imdb (features only)",
          len(hits) == 1 and hits[0]["id"] == "imdb:tt4154796"
          and hits[0]["title"] == "Avengers: Endgame", repr(hits))

with mock.patch("anime_api.sources.indstream.get_json",
                return_value=IS_CATALOG):
    home = ind.home("latest")
    check("indstream home cinemeta",
          len(home) == 1 and home[0]["title"] == "Avengers: Endgame"
          and home[0]["year"] == 2019, repr(home))

with mock.patch("anime_api.sources.indstream.get_json",
                return_value=IS_META):
    d = ind.details("imdb:tt4154796")
    check("indstream details cinemeta",
          d["title"] == "Avengers: Endgame" and d["year"] == 2019
          and d["genres"] == ["Action", "Adventure"]
          and d["score"] == 8.4 and d["type"] == "movie", repr(d))
    check("indstream episode data carries tmdb",
          json.loads(d["seasons"][0]["episodes"][0]["data"])["tmdb"] == 299534,
          repr(d["seasons"]))


def _is_get(url, headers=None, timeout=30):
    m = mock.Mock()
    m.text = IS_VIDLY if "vidly.pro/embed" in url else IS_MASTER
    return m


with mock.patch("anime_api.sources.indstream.get", side_effect=_is_get):
    s = ind.streams(json.dumps({"tmdb": 299534, "imdb": "tt4154796",
                                "title": "Avengers: Endgame"}))
    check("indstream streams vidly m3u8 1080p",
          len(s["streams"]) == 1 and s["streams"][0]["quality"] == 1080
          and s["streams"][0]["type"] == "m3u8"
          and s["streams"][0]["proxy"] is True, repr(s))
    check("indstream stream carries browser UA",
          s["streams"][0]["headers"].get("User-Agent") == BROWSER_UA,
          repr(s["streams"][0]["headers"]))
    check("indstream streams subtitle from master",
          len(s["subtitles"]) == 1 and s["subtitles"][0]["label"] == "English",
          repr(s["subtitles"]))

# ---------------------------------------------------------------- CKDub
CK_BROWSE = """
<html><body>
<a href="/drama/boys-over-flowers"><img alt="Boys Over Flowers Hindi Dubbed poster" src="https://ik.imagekit.io/x/bof.jpg"></a>
<a href="/drama/boys-over-flowers/watch/1">watch</a>
<a href="/category/korean">Korean</a>
</body></html>
"""
CK_DETAIL = """
<html><head>
<meta property="og:title" content="Boys Over Flowers Hindi Dubbed">
<meta property="og:image" content="https://ik.imagekit.io/x/bof.jpg">
<meta name="description" content="A poor girl meets rich boys.">
<title>Boys Over Flowers Hindi Dubbed (All Episodes) - Watch Online | CKDub</title>
</head><body>
<a href="/drama/boys-over-flowers/watch/1">Episode 1</a>
<a href="/drama/boys-over-flowers/watch/2">Episode 2</a>
<a href="/drama/boys-over-flowers/watch/2?server=1">Episode 2 alt</a>
</body></html>
"""
CK_WATCH = '<html><body><iframe src="https://playmogo.com/e/27vbex3tlf6j"></iframe></body></html>'

ck = CKDub()
with mock.patch.object(CKDub, "_soup", return_value=_soup(CK_BROWSE)):
    home = ck.home("latest", category="kdrama")
    check("ckdub home cards",
          len(home) == 1 and home[0]["title"] == "Boys Over Flowers Hindi Dubbed"
          and home[0]["type"] == "anime" and home[0]["audio"] == ["dub"],
          repr(home))
    hits = ck.search("boys over flowers")
    check("ckdub search filters browse list",
          len(hits) == 1 and hits[0]["id"].endswith("/drama/boys-over-flowers"),
          repr(hits))
    check("ckdub search no match",
          ck.search("zzz-no-such-drama") == [])

with mock.patch.object(CKDub, "_soup", return_value=_soup(CK_DETAIL)):
    d = ck.details("https://www.ckdub.com/drama/boys-over-flowers")
    check("ckdub details episodes deduped",
          d["title"] == "Boys Over Flowers Hindi Dubbed"
          and len(d["seasons"][0]["episodes"]) == 2
          and d["seasons"][0]["episodes"][1]["data"].endswith("/watch/2"),
          repr(d))

with mock.patch.object(CKDub, "_soup", return_value=_soup(CK_WATCH)):
    s = ck.streams("https://www.ckdub.com/drama/boys-over-flowers/watch/1")
    check("ckdub streams embed iframe",
          len(s["streams"]) == 1
          and s["streams"][0]["url"] == "https://playmogo.com/e/27vbex3tlf6j"
          and s["streams"][0]["type"] == "embed", repr(s))

# ---------------------------------------------------------------- registry
from anime_api.sources import source_ids  # noqa: E402
check("registry has movie + kdrama sources",
      all(s in source_ids() for s in
          ("vegamovies", "multimovies", "indstream", "ckdub")),
      repr(source_ids()))

from anime_api.sources import get_source  # noqa: E402
check("media_type attrs",
      get_source("vegamovies").media_type == "movie"
      and get_source("multimovies").media_type == "movie"
      and get_source("indstream").media_type == "movie"
      and get_source("ckdub").media_type == "series"
      and get_source("xanime").media_type == "series")
check("categories attrs",
      get_source("ckdub").categories == ("kdrama",)
      and get_source("animedekho").categories == ("tamil", "telugu")
      and get_source("xanime").categories == ())

# ---------------------------------------------------------------- Flask routes
from contextlib import ExitStack  # noqa: E402

from anime_api.sources.anikoto import AniKoto  # noqa: E402
from anime_api.sources.animedekho import AnimeDekho  # noqa: E402
from anime_api.sources.animeworld import AnimeWorld  # noqa: E402
from anime_api.sources.anisuge import AniSugeSource  # noqa: E402
from anime_api.sources.nineanime import NineAnime  # noqa: E402
from anime_api.sources.rareanimes import RareAnimes  # noqa: E402
from anime_api.sources.reanime import ReanimeSource  # noqa: E402
from anime_api.sources.xanime import XanimeSource  # noqa: E402
from app import app  # noqa: E402

_ALL_SOURCES = [Vegamovies, Multimovies, IndStream, CKDub, AnimeDekho,
                AnimeWorld, RareAnimes, XanimeSource, ReanimeSource,
                NineAnime, AniKoto, AniSugeSource]

client = app.test_client()

_MOVIE_HOME = {
    "vegamovies": [{"id": "https://vegamovies.lease/download-a/", "title": "Movie A",
                    "poster": None, "year": 2024, "type": "movie",
                    "audio": ["dub"], "source": "vegamovies"}],
    "multimovies": [{"id": "https://m1.multimovies.courses/movie/b-1", "title": "Movie B",
                     "poster": None, "year": 2023, "type": "movie",
                     "audio": ["dub"], "source": "multimovies"}],
    "indstream": [{"id": "imdb:tt1111111", "title": "Movie C",
                   "poster": None, "year": 2022, "type": "movie",
                   "audio": ["dub"], "source": "indstream"}],
}


def _fake_home(self, section, page=1, **kw):
    return list(_MOVIE_HOME.get(self.id, []))


def _fake_search(self, query, page=1):
    return list(_MOVIE_HOME.get(self.id, []))


# Route tests patch home/search on EVERY source class, so no test ever
# touches the live network (an unpatched source would scrape for real).
with ExitStack() as stack:
    for _cls in _ALL_SOURCES:
        stack.enter_context(mock.patch.object(_cls, "home", _fake_home))
    r = client.get("/api/movies?lang=hindi")
    body = r.get_json()
    check("GET /api/movies returns movie sources only",
          r.status_code == 200 and len(body["results"]) == 3
          and {it["source"] for it in body["results"]}
          == {"vegamovies", "multimovies", "indstream"}, repr(body))
    check("GET /api/movies cache header",
          r.headers.get("X-Cache") == "MISS")
    r2 = client.get("/api/movies?lang=hindi")
    check("GET /api/movies warm is HIT",
          r2.headers.get("X-Cache") == "HIT")

with ExitStack() as stack:
    for _cls in _ALL_SOURCES:
        stack.enter_context(mock.patch.object(_cls, "search", _fake_search))
    r = client.get("/api/search?q=avengers&type=movie")
    body = r.get_json()
    check("GET /api/search?type=movie filters to movies",
          r.status_code == 200
          and {it["source"] for it in body["results"]}
          == {"vegamovies", "multimovies", "indstream"}, repr(body))
    r = client.get("/api/search?q=avengers&type=series")
    body = r.get_json()
    check("GET /api/search?type=series excludes movies",
          r.status_code == 200 and body["results"] == [], repr(body))
    r = client.get("/api/search?q=avengers&source=xanime&lang=hindi&type=movie")
    body = r.get_json()
    check("GET /api/search source/lang/type mismatch reports error",
          r.status_code == 200 and body["results"] == []
          and any("xanime" in e.get("error", "") for e in body["errors"]),
          repr(body))

with mock.patch.object(CKDub, "home",
                       lambda self, section, page=1, category=None:
                       [{"id": "https://www.ckdub.com/drama/x", "title": "Drama X",
                         "poster": None, "year": None, "type": "anime",
                         "audio": ["dub"], "source": "ckdub"}]
                       if category == "kdrama" else []):
    r = client.get("/api/latest?category=kdrama")
    body = r.get_json()
    check("GET /api/latest?category=kdrama fans out to ckdub",
          r.status_code == 200 and len(body["results"]) == 1
          and body["results"][0]["source"] == "ckdub", repr(body))

with mock.patch("anime_api.sources.animedekho.AnimeDekho.home",
                lambda self, section, page=1, category=None:
                [{"id": "https://animedekho.tv/series-hindi/x/", "title": "Tamil X",
                  "poster": None, "year": None, "type": "anime",
                  "audio": ["dub"], "source": "animedekho"}]
                if category == "tamil" else []):
    r = client.get("/api/latest?category=tamil")
    body = r.get_json()
    check("GET /api/latest?category=tamil still works (animedekho)",
          r.status_code == 200 and len(body["results"]) == 1
          and body["results"][0]["source"] == "animedekho", repr(body))

r = client.get("/api/latest?category=nosuchcategory")
body = r.get_json()
check("GET /api/latest?category=unknown reports error, empty results",
      r.status_code == 200 and body["results"] == []
      and any("nosuchcategory" in e.get("error", "") for e in body["errors"]),
      repr(body))

r = client.get("/api/latest?source=animedekho&category=kdrama")
body = r.get_json()
check("GET /api/latest source/category mismatch reports error, no anime",
      r.status_code == 200 and body["results"] == []
      and any("animedekho" in e.get("error", "") for e in body["errors"]),
      repr(body))

with mock.patch.object(Vegamovies, "details",
                       lambda self, item_id: {
                           "id": item_id, "title": "Movie A", "poster": None,
                           "banner": None, "plot": None, "genres": [],
                           "year": 2024, "status": "completed", "score": None,
                           "type": "movie", "audio": ["dub"],
                           "seasons": [{"number": 1, "name": "Movie",
                                        "episodes": [{"number": 1,
                                                      "title": "Movie A",
                                                      "data": "{}"}]}]}):
    r = client.get("/api/title?source=vegamovies&id=https://vegamovies.lease/download-a/")
    body = r.get_json()
    check("GET /api/title works for movies",
          r.status_code == 200 and body["title"] == "Movie A"
          and body["type"] == "movie", repr(body))
    r = client.get("/api/anime?source=vegamovies&id=https://vegamovies.lease/download-a/")
    check("GET /api/anime still works (alias)",
          r.status_code == 200 and r.get_json()["title"] == "Movie A")

# ---------------------------------------------------------------- /api/proxy default UA
# The Cineverse stream_proxy host 403s python-requests UA (verified live
# 2026-11-18: /api/proxy 502'd the master with no ?ua=), so the proxy
# must send a browser UA unless the caller overrides it.

class _Upstream:
    status_code = 200
    headers = {"content-type": "video/mp2t"}

    def iter_content(self, chunk_size=65536):
        yield b"\x00\x01\x02"


_seen = {}


def _spy_get(url, headers=None, stream=True, timeout=30):
    _seen["url"] = url
    _seen["headers"] = dict(headers or {})
    return _Upstream()


with mock.patch("app.requests.get", side_effect=_spy_get):
    r = client.get("/api/proxy?url=https://cdn.example.com/v.mp4")
    _ = r.data  # consume the streaming body before the next request
    check("proxy defaults upstream UA to browser UA",
          r.status_code == 200
          and _seen["headers"].get("User-Agent") == BROWSER_UA,
          repr(_seen["headers"]))
    r = client.get("/api/proxy?url=https://cdn.example.com/v.mp4&ua=CustomAgent/1.0")
    _ = r.data
    check("proxy honors ?ua= override",
          _seen["headers"].get("User-Agent") == "CustomAgent/1.0",
          repr(_seen["headers"]))
    r = client.get("/api/proxy?url=https://cdn.example.com/v.mp4&referer=https://example.com/")
    _ = r.data
    check("proxy still forwards Referer with default UA",
          _seen["headers"].get("Referer") == "https://example.com/"
          and _seen["headers"].get("User-Agent") == BROWSER_UA,
          repr(_seen["headers"]))

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
