"""Zephyrix / ZephyrFlick extractor (ported from the AnimeWorldIndia
extension's ``resolveZephyrix``).

``resolve_zephyrix(iframe_url, main_url)`` -> ``(streams, subtitles)``.

Flow (exactly as in the extension):

* ``videoId`` = regex ``/video/([a-f0-9]+)`` on the iframe URL;
  ``playerBase`` = the origin of the iframe URL.
* ``POST {playerBase}/player/index.php?data={videoId}&do=getVideo``,
  form ``hash={videoId}``, ``r={main_url}/``; headers
  ``X-Requested-With: XMLHttpRequest``, ``Origin: {playerBase}``,
  ``Referer: {playerBase}/video/{videoId}``,
  ``Accept: application/json, text/javascript, */*; q=0.01``; 30 s timeout.
* Response JSON: ``videoSource`` preferred, else ``securedLink``.  A
  relative URL is prefixed with ``playerBase``.
* Emits one M3U8 stream (quality Unknown), referer ``{playerBase}/``,
  headers ``Accept: */*`` plus a browser UA (the stream CDN rejects
  requests lacking a browser UA and Accept header).  The URL is a
  ``master.txt`` playlist containing all audio renditions (hin/tam/tel/
  eng/jpn); it is returned as-is, not parsed.
* No subtitles (the provider never invokes a subtitle callback).
"""

import re

import requests

_VIDEO_ID_RE = re.compile(r"/video/([a-f0-9]+)")
_ORIGIN_RE = re.compile(r"(https?://[^/]+)")

_PLAYER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def resolve_zephyrix(iframe_url, main_url):
    """Resolve a Zephyrix/ZephyrFlick iframe URL.

    Returns ``(streams, subtitles)`` using the shared stream-dict shape
    (``name``/``url``/``quality``/``type``/``headers``/``proxy``).
    Returns ``([], [])`` when the iframe URL has no video id or the
    player API gives no usable source — never raises.
    """
    if not iframe_url:
        return [], []
    match = _VIDEO_ID_RE.search(iframe_url)
    origin = _ORIGIN_RE.search(iframe_url)
    if not match or not origin:
        return [], []
    video_id = match.group(1)
    player_base = origin.group(1)
    try:
        resp = requests.post(
            "%s/player/index.php?data=%s&do=getVideo" % (player_base, video_id),
            data={"hash": video_id, "r": main_url.rstrip("/") + "/"},
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Origin": player_base,
                "Referer": "%s/video/%s" % (player_base, video_id),
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return [], []
    source = (data or {}).get("videoSource") or (data or {}).get("securedLink")
    if not source:
        return [], []
    if source.startswith("/"):
        source = player_base + source
    elif not source.startswith("http"):
        source = player_base + "/" + source
    stream = {
        "name": "Anime World India",
        "url": source,
        "quality": None,
        "type": "m3u8",
        # Referer {playerBase}/ is REQUIRED by the segment CDN
        # (s11.zn-grid01.top 403s without it; the proxy turns that into
        # a 502, and hls.js fails fatally — verified 2026-11-18, run 10).
        # The proxy carries it into every rewritten playlist/segment URL,
        # so one header here covers the whole chain.
        "headers": {"Accept": "*/*", "User-Agent": _PLAYER_UA,
                    "Referer": player_base + "/"},
        # proxy=True (was False): the zephyrix CDN sends no
        # Access-Control-Allow-Origin, so a browser hls.js XHR to the
        # direct URL is CORS-blocked and the Hindi-dub stream never plays
        # (verified 2026-11-18, run 8). /api/proxy serves it same-origin
        # with the headers attached, and the proxy fetch is fast (200 in
        # ~0.3s from the server).
        "proxy": True,
    }
    return [stream], []
