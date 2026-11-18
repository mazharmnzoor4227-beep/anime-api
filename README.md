# anime-api

A small Python/Flask JSON API that wraps several anime streaming sites behind
one stable interface, so a website (or app) can search, browse, get details
and resolve playable streams without scraping each site itself.

Stack: Python 3.10+, Flask, requests, beautifulsoup4, cryptography.

## Layout

```
anime-api/
  README.md  requirements.txt  run.sh  app.py
  anime_api/
    __init__.py  config.py  http.py
    sources/__init__.py  sources/base.py  sources/<id>.py   (one file per source)
    extractors/__init__.py  extractors/megaplay.py  ...
  tests/test_live.py
```

The shared contract every source follows lives in
`INTERFACE.md` (in this repo).

## Source status — live-tested 2026-11-18 (v1.2)

Full per-endpoint results: `TEST-REPORT.md` (42/48 endpoints passed).

| Source | Language | Status |
|---|---|---|
| Xanime (`xanime`) | English | ✅ Working — search, home, details, streams (direct M3U8) |
| Re:ANIME (`reanime`) | English | ✅ Working — search, home, details, streams (flixcloud file, `proxy=true`) |
| 9anime (`nineanime`) | English | ✅ Working — search, home, details, streams (MegaPlay 1080p) |
| AniKoto (`anikoto`) | English | ✅ Working — search, home, details, streams (MegaPlay 800p) |
| AniSuge (`anisuge`) | English | ✅ Working — search, home, details, streams (MegaPlay 1080p, `proxy=true`) |
| AnimeDekho (`animedekho`) | Hindi | ✅ Working — search, home, details, streams (direct `embed` URL, no watch call) |
| Anime World India (`animeworld`) | Hindi | ✅ Working from the Mumbai server IP (was degraded from the sandbox IP) |
| Rare Toons India (`rareanimes`) | Hindi | ⚠️ **Degraded** — see below |

### v1.2 changes (2026-11-18) — speed + AnimeDekho watch gate

Why: the KAZE website felt slow on the user's phone (home ~10s, play 20–30s,
Hindi dub missing). Measured on the server: the scrapers themselves were fast
(trending ~1s, latest hindi ~0.6s) — the slowness was no caching (every load
re-scraped 8 sources), a 45s fan-out ceiling, and AnimeDekho's watch endpoint
going ad-gated for datacenter IPs (`{"gated": true}` — the site's own
"skip the ad once per 24h" wall, which must NOT be automated around).

- **Response cache** (`anime_api/cache.py`, thread-safe TTL): lists 10 min,
  search 5 min, details 30 min, streams 2 min, widgets 30 min; key includes
  lang/source/query/page/category; responses carry `X-Cache: HIT|MISS`.
  Measured on the deployed server: trending 1.9s → **3ms warm**,
  latest hindi 0.68s → **2ms warm**, search "naruto" 1.78s → **0.79s cold /
  2ms warm**, details (JoJo, 5 seasons) 3.38s → **1.5s cold / 2ms warm**.
- **Background pre-warm thread**: refreshes trending/popular/latest (all),
  latest hindi, and tamil/telugu category keys every 5 min from startup.
- **Fan-out timeout 45s → 12s**; a slow source is listed in `errors` and
  never gates the response (was the 10s home load).
- **Singleton source instances** (`sources/__init__.py`): per-instance caches
  (e.g. AnimeDekho nonce) no longer thrown away per request.
- **AnimeDekho `streams()` no longer calls the watch endpoint**: the embed URL
  is built directly (`{host}/embed/<post_id>/<season>-<episode>`, HTTP 200
  verified) — stream resolve is now ~2ms and needs no network. Episode `data`
  now carries `season` + `number`; old-format data falls back to the episode
  page URL as the embed target. The `_watch`/`_nonce_value`/`_quality` code
  and their unit tests are removed.
- **AnimeDekho `details()` fetches seasons in parallel** (ThreadPoolExecutor,
  5 workers) and now also parses **Characters** (`.dgt-cast`) and **Hindi
  Voice Cast** (`.dgt-vcast__grid`).
- **New `home(category=...)`** (tamil/telugu) + **`GET /api/widgets`**
  (Other updates / Release schedule / Upcoming shows from the site sidebar).
- **`None` details/streams now return HTTP 502** `{"error": ...}` instead of
  JSON `null` with 200.
- Tests: new `tests/test_cache.py` 13/13; animedekho unit 32/32 (rewritten
  streams/category/cast tests); hindi unit 44/44; proxy-rewrite 15/15 —
  **104/104 unit, no regressions**. Live suite on the server: **42/48**
  (was 36/48; only RareAnimes still drops — markup drift, 0 items).

### v1.1.1 changes (2026-11-18) — playback fix, found by live testing

Direct browser playback of MegaPlay/anisuge m3u8 streams 403'd: the video
CDNs sit behind Cloudflare and reject requests without the site Referer,
which a browser never sends for a cross-origin `<video>` fetch. Fixes:

- **MegaPlay extractor + anisuge now mark direct streams `proxy: true`**
  (reanime.py precedent) with the right `Referer`/`User-Agent` headers, so
  the website plays them via `/api/proxy` instead of directly.
- **`/api/proxy` rewrites HLS playlists**: variant/segment/key URLs inside
  an m3u8 are rewritten to absolute `/api/proxy` URLs (same origin, headers
  preserved), because the browser fetches them straight from the playlist —
  proxying only the master link was not enough. Playlists are fetched whole
  even when Chromium sends `Range` (a partial playlist cannot be rewritten).
- **Subtitles are rewritten to absolute `/api/proxy` URLs** in
  `/api/streams` (the subtitle CDN 403s without the MegaPlay host Referer
  too); the base URL is scheme-aware via `X-Forwarded-Proto` so https pages
  don't get http:// links (mixed content).
- Tests: `tests/test_proxy_rewrite.py` — 15 passed, 0 failed (rewrite,
  Range-on-playlist, proxy flags, scheme handling). Full unit suite:
  34/34 animedekho + 44/44 hindi, no regressions.
- Live-verified on the deployed server (Oracle Mumbai): Playwright against
  the public link — 12/12 checks (home/browse/detail/watch, real playback
  with metadata loading, zero console errors, zero failed requests).

### v1.1 changes (2026-11-18)

- **New source: AnimeDekho** (`animedekho`, Hindi dub) — live site
  https://animedekho.tv (WordPress + `dgt` theme). Search/latest/details/streams
  via its public `wp-json/dgt/v1/*` endpoints; a nonce (scraped from any site
  page's inline `DGT={...}` config) is required for the watch call, cached and
  refreshed once on a gated response. Streams are `type: "embed"` iframe pages
  (`player.php?url=…`, `/embed/<post>/<season>-<ep>`) — the video host behind
  them (AbyssPlayer/Ravok) assembles its file URL in JS, so there is no direct
  file URL server-side; the website plays them in an `<iframe>`.
  Live-tested 6/6 from this sandbox; 31 fixture unit tests pass.
  (Superseded in v1.2: the watch call is gone — the site ad-gated it for
  datacenter IPs, so streams() now builds the embed URL directly.)
- **Details now include `type` + `audio`** in every source (the website needs
  them for Continue/Library snapshots). `streams` gains the `"embed"` type.
- **Fan-out dedupes `(source, id)`** — sites repeat cards in one list, which
  used to render the same title twice.

### Why one Hindi source is still degraded (v1.2 update)

AnimeWorld India now works from the deployed Mumbai server IP (live suite
6/6 in v1.2) — only the sandbox's egress IP is WAF-blocked there. RareAnimes
still returns 0 items from every IP (markup drift, not a block): it responds
but its pages no longer match the parser. Its code is complete and
unit-tested (44 fixture tests pass), but no live data can be fetched until
the parser is updated for the site's current markup.

For reference, the sandbox-IP block on both sites (v1.0 finding): HTTP 403 on
every request, even from a real headless browser — there is no JS challenge
to solve and a `cf_clearance` cookie does not lift it. On a host with a clean
IP they should work — `anime_api/cf.py` already implements the clearance flow
(Playwright solve → 15h cookie cache → requests with cookies).

To enable them on your server, either:

- run the API from an IP the sites do not block, or
- paste a `cf_clearance` cookie obtained once in a real browser:

```sh
export CF_CLEARANCE_WATCHANIMEWORLD_ONE="<cookie value>"
export CF_CLEARANCE_WWW_RAREANIMES_FANS="<cookie value>"
# matching browser User-Agent, if the cookie was issued for one:
export CF_UA_WATCHANIMEWORLD_ONE="Mozilla/5.0 ..."
```

(Cookies can also be seeded from a JSON file via `ANIME_API_CF_COOKIES` —
see the `anime_api/cf.py` docstring.)

## Honest caveats

- The sources are **unofficial** fan sites. They change their HTML/layout
  without notice, so scrapers need maintenance when a site changes.
- Some stream links need the `/api/proxy` endpoint to play in a browser
  (hotlink protection; Re:ANIME's flixcloud tokens are bound to the IP that
  requested them).
- A few streams can only be resolved in a real browser (WebView-only hosts)
  and are skipped server-side — see each source module's docstring.

## How to run locally

```sh
cd ~/workspace/anime-api
./run.sh
# server listens on http://localhost:8000
```

`run.sh` starts the server with the project venv
(`~/workspace/anime-api-work/venv/bin/python`). To run manually:

```sh
~/workspace/anime-api-work/venv/bin/python app.py
# or: ANIME_API_PORT=8000 ~/workspace/anime-api-work/venv/bin/python app.py
```

Install dependencies (already present in the venv) with:

```sh
~/workspace/anime-api-work/venv/bin/pip install -r requirements.txt
```

## API

All responses are JSON and CORS is enabled (`Access-Control-Allow-Origin: *`).
Errors are `{"error": "<message>", "source": "<id>"}` with HTTP 502 on
upstream failure, 400 on bad params, 404 on unknown source.

### `GET /health`

```json
{"ok": true, "sources": ["reanime", "xanime"]}
```

### `GET /api/sources`

```json
[{"id": "xanime", "name": "Xanime", "language": "english"}]
```

### `GET /api/search?q=<query>&lang=<hindi|english|japanese|all>&source=<id|all>&page=1`

Fans out to the matching sources in parallel threads and merges results.
`lang` filter: `hindi` → only Hindi sources; `english` → only English
sources; `japanese` → English sources, items whose `audio` contains `"sub"`
(Japanese audio + subtitles); `all` → every source. A failing source does
not kill the rest — it appears in `errors`.

```sh
curl "http://localhost:8000/api/search?q=naruto&lang=english"
```

```json
{
  "results": [
    {"id": "naruto", "title": "Naruto", "poster": "https://...",
     "year": 2002, "type": "anime", "audio": ["sub", "dub"], "source": "xanime"}
  ],
  "errors": []
}
```

### `GET /api/trending|popular|latest?lang=&source=&page=1`

Same fan-out shape as search, one section at a time.

```sh
curl "http://localhost:8000/api/trending?lang=english&source=xanime"
curl "http://localhost:8000/api/popular?lang=all&page=2"
```

### `GET /api/anime?source=<id>&id=<item_id>`

Details for one title. `id` is the source's own identifier from a
search/home result (a slug for JSON sources, a full detail URL for HTML
sources).

```sh
curl "http://localhost:8000/api/anime?source=xanime&id=naruto"
```

```json
{
  "id": "naruto", "title": "Naruto", "poster": "...", "banner": "...",
  "plot": "...", "genres": ["Action"], "year": 2002,
  "status": "completed", "score": 8.1,
  "type": "anime", "audio": ["sub", "dub"],
  "seasons": [
    {"number": 1, "name": "Season 1", "episodes": [
      {"number": 1, "title": "Episode 1", "data": "<opaque episode data>"}
    ]},
    {"number": 2, "name": "Dubbed", "episodes": [...]}
  ]
}
```

`episode.data` is an opaque string the website passes back unchanged to
`/api/streams`. Its format is per-source — see the module docstring of each
source (e.g. Xanime: `"<epId>|<sub|dub|raw>"`; Re:ANIME: a JSON string
`{"slug","ep","lang","anilistId","tmdbId","season"}`).

If a source has no real seasons it returns one season (`number: 1`,
`name: "Season 1"`). If episodes split sub/dub with no seasons, sub
episodes go in season 1 and dub episodes in season 2 named `"Dubbed"`.

### `GET /api/streams?source=<id>&data=<episode_data>`

```sh
curl "http://localhost:8000/api/streams?source=xanime&data=<epId>%7Csub"
```

```json
{
  "streams": [
    {"name": "Xanime", "url": "https://.../master.m3u8", "quality": 1080,
     "type": "m3u8", "headers": {"User-Agent": "..."}, "proxy": false,
     "label": "Xanime Server 1 (SUB)"}
  ],
  "subtitles": [{"label": "English", "url": "https://.../sub.vtt"}]
}
```

`type` is `"m3u8"`, `"video"` (direct file), or `"embed"` (the source site's
own iframe player page — play it in an `<iframe>`, exactly like the source
site does; no direct file URL exists for it). Streams are sorted best
quality first when quality is known. `headers` are the Referer/User-Agent
to play the URL with. If `proxy` is `true`, the URL will not play directly
from the visitor's browser (hotlink protection / IP-bound token) — play it
through `/api/proxy` instead.

### `GET /api/proxy?url=<url-encoded>&ua=&referer=`

Range-capable passthrough for hotlink-protected / IP-bound links. Forwards
the client's `Range` header plus `User-Agent` / `Referer` from the `ua` /
`referer` query params, and streams the upstream response back (including
`Content-Range` so seeking works). `url` must start with `http://` or
`https://`.

```sh
# Play a proxy=true stream from Re:ANIME through the API server:
curl "http://localhost:8000/api/proxy?url=<url-encoded flixcloud file>&referer=https%3A%2F%2Fflixcloud.cc%2F" -o ep1.mkv
```

In a `<video>` / player, use the `/api/proxy?url=...` URL as the source
instead of the raw stream URL.

## How the website calls it

Typical flow (all calls are plain GETs, no auth):

1. **Home rows** — `GET /api/trending?lang=english`,
   `GET /api/popular?lang=english`, `GET /api/latest?lang=english`.
   Each returns `{"results": [...items...], "errors": [...]}`.
2. **Search box** — `GET /api/search?q=<user text>&lang=<lang>`.
3. **Detail page** — `GET /api/anime?source=<item.source>&id=<item.id>`
   (URL-encode the id). Render seasons/episodes from the response.
4. **Player** — `GET /api/streams?source=<id>&data=<episode.data>`
   (URL-encode `data`). Pick the best stream; if `stream.proxy` is true,
   set the player source to
   `/api/proxy?url=<encodeURIComponent(stream.url)>` (+ `&ua=` /
   `&referer=` from `stream.headers` when present), otherwise use
   `stream.url` directly with `stream.headers`. Attach `subtitles` as
   `<track>` elements.

Example (JavaScript):

```js
const API = "http://localhost:8000"; // your deployed base URL in production

async function searchAnime(q) {
  const r = await fetch(`${API}/api/search?q=${encodeURIComponent(q)}&lang=english`);
  const { results, errors } = await r.json();
  return results; // [{id, title, poster, year, type, audio, source}]
}

async function getStreams(source, episodeData) {
  const r = await fetch(
    `${API}/api/streams?source=${source}&data=${encodeURIComponent(episodeData)}`
  );
  const { streams, subtitles } = await r.json();
  return streams.map((s) => ({
    ...s,
    playUrl: s.proxy
      ? `${API}/api/proxy?url=${encodeURIComponent(s.url)}`
          + (s.headers?.Referer ? `&referer=${encodeURIComponent(s.headers.Referer)}` : "")
          + (s.headers?.["User-Agent"] ? `&ua=${encodeURIComponent(s.headers["User-Agent"])}` : "")
      : s.url,
  }));
}
```

Notes for the website:

- Treat `episode.data` as opaque — never parse or build it yourself; always
  take it from a `/api/anime` response.
- `lang=japanese` means "Japanese audio with subtitles" (English sources
  filtered to subbed items).
- Always handle the `errors` array on search/home — a source can be down
  while the others still return results.
- Never expose stream URLs' tokens: proxy=true URLs carry IP-bound tokens,
  so route them through `/api/proxy` on your own server, never link them
  directly.

## How to add a new source

1. Create `anime_api/sources/<id>.py` with a class subclassing
   `anime_api.sources.base.Source`:

   ```python
   """<Site> source — what it ports, the site, episode data format."""
   from anime_api.sources.base import Source

   class MySource(Source):
       id = "mysite"              # URL-safe, used in ?source=
       name = "My Site"
       language = "hindi"         # "hindi" | "english"
       domain_key = "mysite"      # Firebase key ("" if none)
       default_url = "https://mysite.example"

       def search(self, query, page=1): ...
       def home(self, section, page=1): ...   # trending|popular|latest
       def details(self, item_id): ...
       def streams(self, episode_data): ...
   ```

   The registry (`anime_api/sources/__init__.py`) auto-discovers the file —
   no other file needs editing. `base_url` already resolves the live host
   via the Firebase domain map (`resolve_domain(domain_key, default_url)`).

2. Follow the return shapes in `INTERFACE.md` exactly (item dicts,
   details dict with `seasons`, streams dict with `streams`/`subtitles`).
   Return JSON-serializable dicts/lists only.
3. Catch per-item errors inside each method — one bad card must not kill a
   list. Put a timeout on every request (default 30s, 15s for link probes).
   Never raise on a single bad server in `streams()` — collect what works.
4. Keep the module importable without network access (network only inside
   method calls). No credentials, no API keys. Document the episode `data`
   format in the module docstring.
5. Live-test it before finishing:

   ```sh
   ~/workspace/anime-api-work/venv/bin/python tests/test_live.py --source mysite
   ```

## Live testing

```sh
~/workspace/anime-api-work/venv/bin/python tests/test_live.py [--source <id>]
```

Runs each registered source's search/home/details/streams against the real
sites and prints PASS/FAIL per endpoint with a one-line real-data summary.
A source failing every endpoint is reported as DROPPED with the reason.
