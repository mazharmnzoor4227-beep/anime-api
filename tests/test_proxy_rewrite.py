"""Unit tests for the /api/proxy m3u8 rewrite + proxy=true stream flags.

No live network. Run:
  ~/workspace/anime-api-work/venv/bin/python tests/test_proxy_rewrite.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import _proxy_url_for, _public_base, _rewrite_m3u8, app  # noqa: E402
from anime_api.extractors.megaplay import _parse_master  # noqa: E402
from anime_api.sources.anisuge import AniSugeSource  # noqa: E402

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


MASTER = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=1280x720
https://cdn.example.com/v/720/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=400000,RESOLUTION=854x480
https://cdn.example.com/v/480/index.m3u8
"""

VARIANT = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:10
#EXT-X-KEY:METHOD=AES-128,URI="https://cdn.example.com/key.bin"
#EXTINF:10.0,
seg-1.ts
#EXTINF:10.0,
https://cdn.example.com/v/720/seg-2.ts
#EXTINF:10.0,
"""

with app.test_request_context("/", base_url="https://kaze.example/"):
    # --- _proxy_url_for ---
    u = _proxy_url_for("https://cdn.example.com/v/720/seg-1.ts",
                       "https://megaplay.buzz/", "UA-TEST")
    check("proxy url keeps host + params",
          u.startswith("https://kaze.example/api/proxy?url=")
          and "referer=https%3A%2F%2Fmegaplay.buzz%2F" in u
          and "ua=UA-TEST" in u, u)
    u2 = _proxy_url_for("https://cdn.example.com/x.ts")
    check("proxy url without headers has no referer/ua",
          "referer=" not in u2 and "ua=" not in u2, u2)

    # --- _rewrite_m3u8 ---
    out = _rewrite_m3u8(VARIANT, "https://cdn.example.com/v/720/index.m3u8",
                        "https://megaplay.buzz/", "UA-TEST")
    check("absolute segment rewritten to proxy",
          "https://kaze.example/api/proxy?url=https%3A%2F%2Fcdn.example.com%2Fv%2F720%2Fseg-2.ts" in out, out)
    check("relative segment resolved + proxied",
          "url=https%3A%2F%2Fcdn.example.com%2Fv%2F720%2Fseg-1.ts" in out, out)
    check("EXT-X-KEY URI rewritten",
          'URI="https://kaze.example/api/proxy?url=https%3A%2F%2Fcdn.example.com%2Fkey.bin' in out, out)
    check("comment lines untouched",
          "#EXTM3U" in out and "#EXT-X-VERSION:3" in out and "#EXTINF:10.0," in out, out)
    check("no raw cdn segment URL leaks",
          "https://cdn.example.com/v/720/seg-2.ts" not in out.replace(
              "url=https%3A%2F%2Fcdn.example.com%2Fv%2F720%2Fseg-2.ts", ""), out)

# --- megaplay streams are proxy=true ---
streams = _parse_master(MASTER, "https://cdn.example.com/master.m3u8", "sub", "megaplay.buzz")
check("megaplay variants proxy=true",
      len(streams) == 2 and all(s.get("proxy") is True for s in streams),
      str(streams))
check("megaplay keeps Referer header",
      all(s.get("headers", {}).get("Referer") == "https://megaplay.buzz/"
          for s in streams), str(streams))

# --- anisuge _add_stream defaults to proxy=true ---
src = AniSugeSource()
src._streams = []
src._add_stream("Test 720p", "https://cdn.example.com/x.m3u8", quality=720,
                headers={"Referer": "https://example.test/"})
check("anisuge _add_stream defaults proxy=true",
      len(src._streams) == 1 and src._streams[0].get("proxy") is True,
      str(src._streams))

# --- /api/proxy: Range on a playlist still rewrites (Chromium sends
# Range even for playlists; a partial playlist cannot be rewritten) ---
from unittest import mock  # noqa: E402


class _FakeResp:
    def __init__(self, status=200, body=b"", content_type="application/vnd.apple.mpegurl"):
        self.status_code = status
        self._body = body
        self.headers = {"content-type": content_type,
                        "content-length": str(len(body))}

    @property
    def text(self):
        return self._body.decode("utf-8")

    def iter_content(self, chunk_size=65536):
        yield self._body


PLAYLIST = (b"#EXTM3U\n#EXT-X-VERSION:3\n#EXTINF:10.0,\n"
            b"https://cdn.example.com/v/seg-1.ts\n")
calls = {}


def _fake_get(url, headers=None, stream=True, timeout=30):
    calls["url"] = url
    calls["headers"] = dict(headers or {})
    return _FakeResp(200, PLAYLIST)


with mock.patch.object(__import__("app").requests, "get", _fake_get):
    client = app.test_client()
    r = client.get("/api/proxy?url=https%3A%2F%2Fcdn.example.com%2Fv%2Findex.m3u8"
                   "&referer=https%3A%2F%2Fmegaplay.buzz%2F&ua=UA-TEST",
                   headers={"Range": "bytes=0-"})
    check("playlist + Range returns 200 (not 206)",
          r.status_code == 200, str(r.status_code))
    check("playlist + Range does not forward Range upstream",
          "Range" not in calls["headers"], str(calls["headers"]))
    check("playlist + Range body is rewritten",
          b"/api/proxy?url=https%3A%2F%2Fcdn.example.com%2Fv%2Fseg-1.ts" in r.data
          and b"https://cdn.example.com/v/seg-1.ts\n" not in r.data, r.data[:200])
    r2 = client.get("/api/proxy?url=https%3A%2F%2Fcdn.example.com%2Fv%2Fseg-1.ts",
                    headers={"Range": "bytes=0-99"})
    check("non-playlist + Range forwards Range upstream",
          calls["headers"].get("Range") == "bytes=0-99", str(calls["headers"]))

with app.test_request_context("/", base_url="http://kaze.internal/",
                               headers={"X-Forwarded-Proto": "https"}):
    check("public base prefers X-Forwarded-Proto",
          _public_base() == "https://kaze.internal", _public_base())

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
