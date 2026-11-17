# anime-api — shared interface (ALL source modules MUST follow this exactly)

Stack: Python 3.10+, Flask, requests, beautifulsoup4, cryptography.
Package root: `~/workspace/anime-api/` — final layout:

```
anime-api/
  README.md  requirements.txt  run.sh  app.py
  anime_api/
    __init__.py  config.py  http.py
    sources/__init__.py  sources/base.py  sources/<id>.py   (one file per source)
    extractors/__init__.py  extractors/megaplay.py  extractors/zephyrix.py
    extractors/codedew.py  extractors/juicycodes.py
  tests/test_live.py
```

## `anime_api/http.py` — shared helpers (scaffold agent owns this file)
- `BROWSER_UA` = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
- `ANDROID_UA` = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
- `get(url, headers=None, timeout=30, allow_redirects=True) -> requests.Response` (raise on HTTP >= 400)
- `get_json(url, headers=None, timeout=30) -> dict`
- `post_form(url, data, headers=None, timeout=30) -> requests.Response`
- `get_soup(url, headers=None, timeout=30) -> BeautifulSoup`
- `resolve_domain(key, default) -> str`: GET https://cloudstreampluginhelper-default-rtdb.firebaseio.com/.json
  (5-min in-memory cache), lookup order key, key+"_url", key+"_domain", strip trailing "/".
  On any failure return `default`. (The Firebase map is the live domain source the extensions use.)

## `anime_api/sources/base.py` — every source subclasses this (scaffold agent owns this file)
```python
class Source:
    id = ""          # e.g. "animeworld"  (URL-safe, used in ?source=)
    name = ""        # display name, e.g. "Anime World India"
    language = ""    # "hindi" | "english"
    domain_key = ""  # Firebase key, e.g. "animeworldindia" ("" if none)
    default_url = "" # static fallback host, e.g. "https://watchanimeworld.one"

    @property
    def base_url(self):  # resolved via resolve_domain(domain_key, default_url)
        ...

    def search(self, query, page=1): ...
    def home(self, section, page=1): ...
    def details(self, item_id): ...
    def streams(self, episode_data): ...
```

### Return shapes (JSON-serializable dicts/lists ONLY, no objects)
- `search()` / `home()` -> list of items:
  `{ "id": str, "title": str, "poster": str|None, "year": int|None,
     "type": "anime"|"movie"|"ova", "audio": ["sub","dub"] (subset, may be empty),
     "source": "<id>" }`
  `id` = the source's own detail identifier: for HTML sources the FULL detail URL;
  for JSON sources the slug (details() accepts it).
  `home(section, page)`: section in {"trending","popular","latest"}. Map to the
  provider's real sections (see per-source contract). page>=1.
- `details(item_id)` -> dict:
  `{ "id": str, "title": str, "poster": str|None, "banner": str|None,
     "plot": str|None, "genres": [str], "year": int|None, "status": "ongoing"|"completed"|None,
     "score": float|None (0-10), "seasons": [ {"number": int, "name": str,
         "episodes": [ {"number": int, "title": str, "data": str} ]} ] }`
  `episode.data` = OPAQUE string the website passes back to /streams (URL, pipe-string,
  or JSON — the source module's choice; document it in the module docstring).
  If the source has no real seasons, return ONE season number=1 name="Season 1".
  If episodes split sub/dub with no seasons, put sub episodes in season 1 and dub
  episodes in season 2 named "Dubbed" (or mirror the provider's own split).
- `streams(episode_data)` -> dict:
  `{ "streams": [ {"name": str, "url": str, "quality": int|None (e.g. 1080),
                  "type": "m3u8"|"video", "headers": {str:str} (referer/UA to play with),
                  "proxy": bool (True if the URL likely needs the /proxy endpoint) } ],
     "subtitles": [ {"label": str, "url": str} ] }`
  Sort streams best quality first when known. Never raise on a single bad server —
  collect what works, skip what fails.

### Rules
- Every public method catches its own per-item errors (one bad card must not kill a list).
- Timeouts on ALL requests (default 30s, 15s for link probes).
- No credentials, no API keys. No writing outside the package.
- Each module has a docstring: what it ports, the source site, and the episode `data` format.
- A module must be importable WITHOUT network access (network only inside method calls).

## `anime_api/extractors/megaplay.py` (owned by the NineAnime+AniKoto agent)
```python
def resolve_megaplay(embed_url, referer) -> (streams, subtitles)
# streams/subtitles use the same dict shapes as above.
# Implements: GET embed page -> stream id (data-id/data-realid//stream/s-\d+/(\d+)/)
# -> GET https://<host>/stream/getSourcesNew?id=<id>&type=<sub|dub> (fallback getSources)
# -> sources.file (object or [0].file) else enc -> AES/CBC decrypt with seeds from
#    {host}/lib/newclient.min.js (regex [A-Za-z]\w*="([^"]{16})",[A-Za-z]\w*="([^"]{16})",
#    fallback key "i?LMTAx0Q6,:}50U" iv "W0;27ToaUpl_P%'c", seeds padded/truncated to 32/16 bytes)
# -> signUrl HMAC (only if URL matches /([a-f0-9]{32})/([a-f0-9]{32})/ :
#    expires=now+7d, payload="<expires>|<id1>/<id2>" lowercased,
#    HmacSHA256 key "MpCdnT0k3n!9f2K#xQ7vL5mR8wN1pY4s", ?token=<b64url(payload)>.<b64url(sig)>)
# -> parse master #EXT-X-STREAM-INF variants (RESOLUTION -> quality); if audio-only variants
#    present (#EXT-X-MEDIA:TYPE=AUDIO) emit one master link with ?t=sub|dub.
# -> subtitles from tracks[] where kind in (captions, subtitles).
```
Other agents: `from anime_api.extractors.megaplay import resolve_megaplay` — do NOT reimplement.

## Flask app (`app.py`, scaffold agent owns it)
Routes (all JSON, CORS enabled):
- `GET /health` -> {"ok": true, "sources": [...ids...]}
- `GET /api/sources` -> [{id, name, language}]
- `GET /api/search?q=<query>&lang=<hindi|english|japanese|all>&source=<id|all>&page=1`
  (unified: fan out to matching sources in parallel threads, merge; lang filter:
   hindi -> only hindi sources; english -> only english sources; japanese -> english
   sources with audio containing "sub" (Japanese audio + subtitles); all -> all sources.
   On a source error, include it in "errors": [{source, error}] and keep the rest.)
- `GET /api/trending|popular|latest?lang=&source=&page=1` (same fan-out)
- `GET /api/anime?source=<id>&id=<item_id>` -> details()
- `GET /api/streams?source=<id>&data=<episode_data>` -> streams()
- `GET /api/proxy?url=<url-encoded>` -> Range-capable passthrough (streaming response,
  forwards Range + User-Agent + Referer headers from query params `ua`/`referer`,
  for hotlink-protected / IP-bound links). Must validate url starts with http(s).
- Errors: {"error": "<message>", "source": "<id>"} with HTTP 502 on upstream failure,
  400 on bad params, 404 on unknown source.

## Live testing (every agent tests its own modules before finishing)
`tests/test_live.py` (scaffold agent creates it; each agent adds tests for its sources):
runs each source's search/home/details/streams against the REAL sites and prints
PASS/FAIL per endpoint with a one-line real-data summary (e.g. "search naruto: 10 items,
first='Naruto'"). A source that fails EVERY endpoint is reported as DROPPED with the reason.
Run with: `~/workspace/anime-api-work/venv/bin/python tests/test_live.py`
