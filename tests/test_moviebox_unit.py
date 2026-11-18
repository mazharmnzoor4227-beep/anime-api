"""Unit + fixture tests for the MovieBox source (v1.4).

No live network (native API calls are mocked). Run:
  ~/workspace/anime-api-work/venv/bin/python tests/test_moviebox_unit.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest import mock

from anime_api.sources.moviebox import (  # noqa: E402
    MovieBox, _policy_resource, _quality_of, _subject_to_item)

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


check("mb quality from resolutions",
      _quality_of("1080,720,480") == 1080
      and _quality_of("480") == 480
      and _quality_of("") is None)
check("mb policy resource from edge cookie",
      _policy_resource(
          "Edge-Cache-Cookie=urlprefix=aHR0cHM6Ly9jZG4uZXhhbXBsZS5jb20vZGFzaC94"
          "eA==; CloudFront-Policy=zzz")
      == "https://cdn.example.com/dash/xx/index.mpd")
check("mb policy resource empty",
      _policy_resource("") is None
      and _policy_resource("nonsense") is None)
check("mb subject to item (movie, hindi dub)",
      (_subject_to_item({
          "subjectId": "5154075108704669480", "subjectType": 1,
          "title": "The Avengers [Hindi]", "releaseDate": "2012-04-25",
          "cover": {"url": "https://img.example/av.jpg"},
          "language": "Hindi"}) or {}).get("audio") == ["dub"])
check("mb subject to item filters series",
      _subject_to_item({"subjectId": "999", "subjectType": 2,
                        "title": "Some Series"}) is None)
check("mb subject to item filters hasResource false (v1.4.1)",
      _subject_to_item({"subjectId": "6891610990048693368",
                        "subjectType": 1, "title": "Avengers",
                        "hasResource": False, "detailUrl": ""}) is None
      and _subject_to_item({"subjectId": "4744425413315887552",
                            "subjectType": 1,
                            "title": "Captain America: The First "
                            "Avenger - The Transformation",
                            "hasResource": False}) is None)
check("mb subject to item keeps hasResource true / missing key",
      _subject_to_item({"subjectId": "7463045102144291536",
                        "subjectType": 1, "title": "The Avengers [Hindi]",
                        "hasResource": True}) is not None
      and _subject_to_item({"subjectId": "5154075108704669480",
                            "subjectType": 1,
                            "title": "The Avengers"}) is not None)

MB_SEARCH = {"code": 0, "data": {"items": [
    {"subject": {"subjectId": "5154075108704669480", "subjectType": 1,
                 "title": "The Avengers", "releaseDate": "2012-04-25",
                 "imdbRatingValue": "8.0", "genre": "Action",
                 "cover": {"url": "https://img.example/av.jpg"},
                 "detailPath": "the-avengers-ChBgfByIJ86",
                 "language": "English"}},
    {"subject": {"subjectId": "999", "subjectType": 2,
                 "title": "Some Series", "releaseDate": "2021-01-01",
                 "cover": {}}},
]}}

MB_GET = {"code": 0, "data": {
    "subjectId": "5154075108704669480", "subjectType": 1,
    "title": "The Avengers",
    "description": "Earth's mightiest heroes assemble.",
    "releaseDate": "2012-04-25", "genre": "Action, Adventure",
    "imdbRatingValue": "8.0", "countryName": "USA",
    "language": "English",
    "cover": {"url": "https://img.example/av.jpg"},
    "detailUrl": "https://movie-box.co/detail/the-avengers-ChBgfByIJ86",
    "dubs": [{"subjectId": "777", "lanName": "Hindi", "language": "hi"}],
}}

MB_SEASON = {"code": 0, "data": {"seasons": [{"se": 0, "maxEp": 0}]}}

MB_PLAY = {"code": 0, "data": {"streams": [
    {"id": "111", "format": "MP4",
     "url": "https://cdn.example.com/a720.mp4?sign=y",
     "resolutions": "720", "size": "1372949905"},
    {"id": "112", "format": "MP4",
     "url": "https://cdn.example.com/a1080.mp4?sign=x",
     "resolutions": "1080", "size": "2285401354"},
    {"id": "113", "format": "MP4", "url": "",
     "resolutions": "480", "size": "1"},
], "dash": [
    {"url": "https://cdn.example.com/index.mpd",
     "signCookie": "Edge-Cookie"},
]}}

MB_CAP1 = {"code": 0, "data": {"extCaptions": [
    {"id": "1", "lan": "en", "lanName": "English",
     "url": "https://sub.example.com/en.srt"},
]}}
MB_CAP2 = {"code": 0, "data": {"extCaptions": [
    {"id": "2", "lan": "ar", "lanName": "Arabic",
     "url": "https://sub.example.com/ar.srt"},
    {"id": "1", "lan": "en", "lanName": "English",
     "url": "https://sub.example.com/en.srt"},
]}}


def _mb_api(self, method, path, body=None, retry=True):
    if "/subject-api/search" in path:
        return MB_SEARCH
    if "/subject-api/get?" in path:
        return MB_GET
    if "/subject-api/season-info" in path:
        return MB_SEASON
    if "get-stream-captions" in path:
        return MB_CAP1
    if "get-ext-captions" in path:
        return MB_CAP2
    raise AssertionError("unexpected api path %s" % path)


mb = MovieBox()
with mock.patch.object(MovieBox, "_api", _mb_api):
    hits = mb.search("avengers")
    check("mb search movies only (series filtered)",
          len(hits) == 1 and hits[0]["title"] == "The Avengers"
          and hits[0]["id"] == "5154075108704669480"
          and hits[0]["type"] == "movie" and hits[0]["year"] == 2012,
          repr(hits))
    d = mb.details("5154075108704669480")
    check("mb details title/plot/genres/score/dubs",
          d["title"] == "The Avengers"
          and d["plot"] == "Earth's mightiest heroes assemble."
          and d["genres"] == ["Action", "Adventure"]
          and d["score"] == 8.0 and d["type"] == "movie"
          and d.get("dubs") == [{"subject_id": "777",
                                 "lang_name": "Hindi", "language": "hi"}],
          repr(d))
    check("mb details one movie episode with detailPath",
          len(d["seasons"]) == 1
          and len(d["seasons"][0]["episodes"]) == 1
          and json.loads(d["seasons"][0]["episodes"][0]["data"])["dp"]
          == "the-avengers-ChBgfByIJ86",
          repr(d["seasons"]))


def _mb_get_json(url, headers=None, timeout=30):
    assert "subject/play" in url, url
    return MB_PLAY


with mock.patch.object(MovieBox, "_bootstrap", return_value="TOK"), \
        mock.patch.object(MovieBox, "_api", _mb_api), \
        mock.patch("anime_api.sources.moviebox.get_json",
                   side_effect=_mb_get_json):
    s = mb.streams(json.dumps({"sid": "5154075108704669480", "se": 0,
                               "ep": 0, "dp": "the-avengers-ChBgfByIJ86"}))
    check("mb streams mp4 sorted best first, proxy, referer",
          len(s["streams"]) == 2
          and s["streams"][0]["quality"] == 1080
          and s["streams"][1]["quality"] == 720
          and all(st["type"] == "video" and st["proxy"] is True
                  and st["headers"].get("Referer") == "https://movie-box.co/"
                  for st in s["streams"]),
          repr(s["streams"]))
    check("mb streams captions merged + deduped",
          len(s["subtitles"]) == 2
          and {sub["label"] for sub in s["subtitles"]}
          == {"English", "Arabic"},
          repr(s["subtitles"]))
    check("mb streams empty episode data",
          mb.streams("not json") == {"streams": [], "subtitles": []})

# POST body must be the EXACT compact string that was signed —
# http.post_json re-serialises with spaces and the API answers 407
# "Signature invalid" (verified live 2026-11-18).
captured = {}


def _fake_post(url, data=None, headers=None, timeout=25):
    captured["data"] = data
    captured["headers"] = headers
    m = mock.Mock()
    m.raise_for_status = mock.Mock()
    m.json = mock.Mock(return_value={"code": 0, "data": {"items": []}})
    return m


with mock.patch.object(MovieBox, "_bootstrap", return_value="TOK"), \
        mock.patch("anime_api.sources.moviebox.requests.post",
                   side_effect=_fake_post):
    MovieBox()._api("POST", "/wefeed-mobile-bff/subject-api/search",
                    {"keyword": "avengers", "page": 1, "perPage": 5})
    check("mb post sends exact compact signed body (no spaces)",
          captured["data"]
          == b'{"keyword":"avengers","page":1,"perPage":5}',
          repr(captured.get("data")))
    check("mb post carries signed headers",
          "X-Tr-Signature" in (captured.get("headers") or {})
          and "X-Client-Token" in (captured.get("headers") or {}))

# ---------------------------------------------------------------- registry + routes
from anime_api.sources import get_source, source_ids  # noqa: E402
check("registry has moviebox",
      "moviebox" in source_ids(), repr(source_ids()))
check("mb media_type + categories attrs",
      get_source("moviebox").media_type == "movie"
      and get_source("moviebox").categories
      == ("hollywood", "bollywood", "movies"))

from app import app  # noqa: E402
client = app.test_client()

with mock.patch.object(MovieBox, "home",
                       lambda self, section, page=1, category=None:
                       [{"id": "7463045102144291536",
                         "title": "The Avengers [Hindi]",
                         "poster": None, "year": 2012, "type": "movie",
                         "audio": ["dub"], "source": "moviebox"}]
                       if category == "hollywood" else []):
    r = client.get("/api/latest?category=hollywood")
    body = r.get_json()
    check("GET /api/latest?category=hollywood fans out to moviebox",
          r.status_code == 200 and len(body["results"]) == 1
          and body["results"][0]["source"] == "moviebox", repr(body))

with mock.patch.object(MovieBox, "details",
                       lambda self, item_id: {
                           "id": item_id, "title": "Movie X", "poster": None,
                           "banner": None, "plot": None, "genres": [],
                           "year": 2024, "status": "completed", "score": 8.0,
                           "type": "movie", "audio": ["dub"],
                           "seasons": [{"number": 1, "name": "Movie",
                                        "episodes": [{"number": 1,
                                                      "title": "Movie X",
                                                      "data": "{}"}]}]}):
    r = client.get("/api/title?source=moviebox&id=5154075108704669480")
    body = r.get_json()
    check("GET /api/title works for moviebox",
          r.status_code == 200 and body["title"] == "Movie X"
          and body["type"] == "movie", repr(body))

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
