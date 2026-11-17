"""Unit + fixture tests for the Hindi sources/extractors (no live network
except the PixelDrain direct-emit path, which needs none).

Run: ~/workspace/anime-api-work/venv/bin/python tests/test_hindi_unit.py
"""

import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest import mock

from anime_api.extractors import juicycodes, zephyrix, codedew
from anime_api.sources.animeworld import AnimeWorld
from anime_api.sources.rareanimes import (
    RareAnimes, dub_key_of, parse_variants, variants_json,
)

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


# ---------------------------------------------------------------- juicycodes
# Encoder mirroring the decoder (test-only): plaintext -> payload.

_SYMBOLS = "`%-+*$!_^="


def juicy_encode(plain, salt="def", offset=None):
    if offset is None:
        offset = int("".join(str(ord(c) - 100) for c in salt))
    digits = ""
    for ch in plain:
        n = ord(ch) + offset
        digits += "%04d" % (n % 1000)
    syms = "".join(_SYMBOLS[int(d)] for d in digits)
    b64 = base64.b64encode(syms.encode("iso-8859-1")).decode()
    b64 = b64.replace("+", "_").replace("/", "-").rstrip("=")
    return b64 + salt


cfg = '{"file": "https://cdn.example.com/hls/master.m3u8", "x": 1}'
payload = juicy_encode(cfg, salt="def")
html = '<script>_juicycodes("%s")</script>' % payload
check("juicycodes round-trip", juicycodes.decode_from_html(html) == cfg,
      repr(juicycodes.decode_from_html(html)))
check("juicycodes no payload", juicycodes.decode_from_html("<html/>") is None)
check("juicycodes bad payload",
      juicycodes.decode_from_html('_juicycodes("!!!!")') is None)

# ---------------------------------------------------------------- codedew classify
cases = [
    ("https://codedew.com/streambeta/?url=abc123", ("StreamBeta", "abc123")),
    ("https://gofile.io/d/AbCdEf", ("GoFile", "AbCdEf")),
    ("https://codedew.com/multiquality/?url=xyz", ("Argon", "xyz")),
    ("https://codedew.com/cdn/ziptron.php/ZZZ9", ("ArgonDownload", "ZZZ9")),
    ("https://codedew.com/watchbeta/?url=qwerty", ("PixelDrain", "qwerty")),
    ("https://hubcloud.ist/drive/DRV1", ("HubCloud", "DRV1")),
    ("https://pixeldrain.net/u/AbC123", ("PixelDrain", "AbC123")),
    ("https://argon.razorshell.space/embed/EMB1", ("Argon", "EMB1")),
    ("https://argon.razorshell.space/downlead/DL1", ("ArgonDownload", "DL1")),
    ("https://www.mediafire.com/file/abc/file.mkv", ("MediaFire", "https://www.mediafire.com/file/abc/file.mkv")),
    ("https://store.animetoonhindi.com/archives/123", ("Archive", "https://store.animetoonhindi.com/archives/123")),
    ("https://codedew.com/zipper/abc", None),
    ("https://example.com/video.mp4", None),
]
for url, want in cases:
    got = codedew.classify_url(url)
    check("classify %s" % url, got == want, "got %r want %r" % (got, want))

check("classify mega", codedew.classify_url(
    "https://mega.nz/file/abc#key") == ("Mega", "https://mega.nz/file/abc"))
check("resolve mega -> empty",
      codedew.resolve_url("https://mega.nz/file/abc") == ([], []))
streams, _ = codedew.resolve_url("https://pixeldrain.net/u/AbC123", "Hindi")
check("resolve pixeldrain direct",
      len(streams) == 1 and streams[0]["url"] == "https://pixeldrain.net/api/file/AbC123",
      repr(streams))
check("quality_from_label",
      codedew.quality_from_label("1080p") == 1080
      and codedew.quality_from_label("HD") is None)
check("gofile wt is sha256 hex",
      len(codedew._gofile_wt("tok")) == 64
      and all(c in "0123456789abcdef" for c in codedew._gofile_wt("tok")))

# ---------------------------------------------------------------- zephyrix (mocked POST)
fake_resp = mock.Mock()
fake_resp.json.return_value = {"videoSource": "/hls/master.txt"}
fake_resp.raise_for_status.return_value = None
with mock.patch("anime_api.extractors.zephyrix.requests.post",
                return_value=fake_resp) as post:
    streams, subs = zephyrix.resolve_zephyrix(
        "https://zephyrix.example/video/abcdef01", "https://watchanimeworld.one")
    check("zephyrix resolves", len(streams) == 1
          and streams[0]["url"] == "https://zephyrix.example/hls/master.txt"
          and streams[0]["type"] == "m3u8" and subs == [], repr(streams))
    args, kwargs = post.call_args
    check("zephyrix POST shape",
          args[0] == "https://zephyrix.example/player/index.php?data=abcdef01&do=getVideo"
          and kwargs["data"] == {"hash": "abcdef01", "r": "https://watchanimeworld.one/"}
          and kwargs["headers"]["X-Requested-With"] == "XMLHttpRequest",
          repr(post.call_args))
check("zephyrix no video id",
      zephyrix.resolve_zephyrix("https://zephyrix.example/watch", "https://x") == ([], []))

# ---------------------------------------------------------------- dub keys / variants
check("dub_key cn", dub_key_of("Cartoon Network Dub") == "cn")
check("dub_key xd", dub_key_of("Hungama Dub") == "xd")
check("dub_key multi", dub_key_of("Hindi Tamil Dub") == "multi")
check("dub_key hi", dub_key_of("Hindi Dub") == "hi")
check("dub_key empty", dub_key_of("Watch Online") == "")
v = [{"n": "EP1", "u": "https://codedew.com/zipper/abc", "k": "cn"}]
check("variants json round-trip", parse_variants(variants_json(v)) == v,
      variants_json(v))
check("variants fallback url",
      parse_variants("https://pixeldrain.net/u/AbC123")[0]["u"].endswith("AbC123"))

# ---------------------------------------------------------------- AnimeWorld fixtures
AW_HOME = """
<html><body><ul>
<li class="post"><a href="https://watchanimeworld.one/series/naruto/"><h2>Naruto</h2>
<img data-src="https://img.example/n.jpg"></a></li>
<li class="post"><a href="https://watchanimeworld.one/movies/spirited-away/"><h3>Spirited Away</h3>
<img src="https://img.example/s.jpg"></a></li>
<li class="post"><a href="https://watchanimeworld.one/series/"><h2>Index</h2></a></li>
</ul>
<a href="https://watchanimeworld.one/category/franchise/naruto/">Naruto Franchise</a>
</body></html>
"""

AW_DETAIL = """
<html><body>
<h1>Naruto</h1>
<div class="poster"><img data-src="https://img.example/poster.jpg"></div>
<div class="description"><p>A young ninja story.</p></div>
<a href="/genre/action/">Action</a>
<div data-post="42"></div>
<div data-season="1">Season 1</div>
<div data-season="2">Season 2</div>
<a href="https://watchanimeworld.one/episode/naruto-1x1/">ep</a>
<a href="https://watchanimeworld.one/episode/naruto-1x2/">ep</a>
</body></html>
"""

AW_EP = """
<html><body>
<iframe data-src="https://zephyrix.example/video/abcdef01"></iframe>
<iframe src="https://vidhide.example/e/xyz"></iframe>
</body></html>
"""

from bs4 import BeautifulSoup  # noqa: E402


def _soup(html):
    return BeautifulSoup(html, "lxml")


aw = AnimeWorld()
with mock.patch.object(AnimeWorld, "_soup", side_effect=lambda u: _soup(
        AW_HOME if u == aw.base_url else AW_DETAIL)):
    home = aw.home("latest")
    check("AW home latest", len(home) == 2 and home[0]["title"] == "Naruto"
          and home[1]["type"] == "movie", repr(home))
    check("AW home popular reversed",
          aw.home("popular")[0]["title"] == "Spirited Away")
    check("AW home trending len", len(aw.home("trending")) == 2)
    check("AW home franchise",
          len(aw.home("franchise")) == 1
          and aw.home("franchise")[0]["title"] == "Naruto Franchise")

with mock.patch.object(AnimeWorld, "_soup", return_value=_soup(AW_DETAIL)):
    with mock.patch.object(AnimeWorld, "_fetch_season_episodes",
                           return_value=[
                               "https://watchanimeworld.one/episode/naruto-2x1/",
                               "https://watchanimeworld.one/episode/naruto-2x2/",
                           ]):
        d = aw.details("https://watchanimeworld.one/series/naruto/")
        check("AW details title/plot/genres",
              d["title"] == "Naruto" and d["plot"] == "A young ninja story."
              and d["genres"] == ["Action"], repr(d))
        check("AW details seasons",
              len(d["seasons"]) == 2
              and len(d["seasons"][0]["episodes"]) == 2
              and d["seasons"][1]["episodes"][0]["number"] == 1
              and d["seasons"][1]["episodes"][0]["data"].endswith("naruto-2x1/"),
              repr(d["seasons"]))

with mock.patch.object(AnimeWorld, "_soup", return_value=_soup(AW_EP)):
    with mock.patch("anime_api.sources.animeworld.zephyrix.resolve_zephyrix",
                    return_value=([{"name": "AW", "url": "https://cdn/x.m3u8",
                                    "quality": None, "type": "m3u8",
                                    "headers": {}, "proxy": False}], [])):
        s = aw.streams("https://watchanimeworld.one/episode/naruto-1x1/")
        check("AW streams only zephyrix",
              len(s["streams"]) == 1 and s["subtitles"] == [], repr(s))

# ---------------------------------------------------------------- RareAnimes fixtures
RAI_LIST = """
<html><body>
<article><h2 class="entry-title"><a href="https://www.rareanimes.fans/naruto-hindi-dubbed/">
Naruto Hindi Dubbed</a></h2><img src="https://img.example/n.jpg"></article>
<article><h2 class="entry-title"><a href="https://other.example/x/">Other</a></h2></article>
</body></html>
"""

RAI_DETAIL = """
<html><body>
<h1 class="entry-title">Naruto Hindi Dubbed</h1>
<meta property="og:image" content="https://img.example/poster.jpg">
<div class="entry-content">
<p>Season No: 1</p><p>Release Year: 2002</p><p>Episodes: 220</p>
<p>Synopsis: A young ninja dreams of becoming Hokage in a long story that keeps going.</p>
<p>Episode 1</p>
<p><span>Hindi</span> <a href="https://codedew.com/zipper/nar1">[Watch]</a></p>
<p>Episode 2</p>
<p><span>Hindi</span> <a href="https://codedew.com/zipper/nar2">[Watch]</a></p>
</div>
<div class="meta-category"><a href="/category/hindi-dub/">Hindi Dub</a></div>
</body></html>
"""

rai = RareAnimes()
with mock.patch.object(RareAnimes, "_soup", return_value=_soup(RAI_LIST)):
    items = rai._parse_listings(_soup(RAI_LIST))
    check("RAI listings (drops foreign link)",
          len(items) == 1 and items[0]["title"] == "Naruto Hindi Dubbed",
          repr(items))

with mock.patch.object(RareAnimes, "_soup", return_value=_soup(RAI_DETAIL)):
    d = rai.details("https://www.rareanimes.fans/naruto-hindi-dubbed/")
    check("RAI details meta",
          d["title"] == "Naruto Hindi Dubbed" and d["year"] == 2002
          and d["plot"] and d["plot"].startswith("A young ninja"),
          repr(d))
    check("RAI details episodes",
          len(d["seasons"]) == 1 and len(d["seasons"][0]["episodes"]) == 2
          and d["seasons"][0]["episodes"][0]["number"] == 1,
          repr(d["seasons"]))
    data = d["seasons"][0]["episodes"][0]["data"]
    check("RAI episode data is variantsJson",
          parse_variants(data)[0]["u"] == "https://codedew.com/zipper/nar1",
          data)

with mock.patch("anime_api.sources.rareanimes.codedew.resolve_url",
                return_value=([{"name": "PixelDrain", "url": "https://pixeldrain.net/api/file/AbC123",
                                "quality": None, "type": "video", "headers": {},
                                "proxy": False}], [])):
    s = rai.streams(data)
    check("RAI streams via codedew",
          len(s["streams"]) == 1 and s["subtitles"] == [], repr(s))

# Registry picks both sources up.
from anime_api.sources import source_ids  # noqa: E402
check("registry has hindi sources",
      "animeworld" in source_ids() and "rareanimes" in source_ids(),
      repr(source_ids()))

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
