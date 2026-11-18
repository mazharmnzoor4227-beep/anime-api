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

## Source status — live-tested 2026-11-18 (v1.5.0)

Full per-endpoint results: `TEST-REPORT.md` (81/90 endpoints passed).

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
| Vegamovies (`vegamovies`) | Hindi | ✅ Working — search, home, details, streams (direct G-Drive file + V-Cloud R2) |
| Multimovies (`multimovies`) | Hindi | ✅ Working — search, home, details, streams (Cineverse m3u8 1080p, Hindi audio default) |
| IndStream (`indstream`) | Hindi | ✅ Working — search, home, details, streams (Vidly m3u8 1080p, Hindi audio track) |
| CKDub (`ckdub`) | Hindi | ✅ Working — K-drama Hindi dub; search, home, details, streams (`embed` player) |
| DramaCool (`dramacool`) | English | ✅ Working — K/C-drama English sub; search, home, details, streams (**direct HLS 720p**, `proxy=true`, `type: "hls"` — v1.4.1, no embeds) |
| PKDramas (`pkdramas`) | Hindi | ⚠️ **Unplayable via this API** — catalogue (search/home/details) works, but `streams` is always empty: episodes are official YouTube uploads geo-blocked in India (server country), and embeds are never returned (v1.4.1) |
| MovieBox (`moviebox`) | Hindi | ✅ Working — Hollywood/Hindi-dub movies; search, home, details, streams (MP4 360p–1080p, `proxy=true`); `hasResource: false` titles filtered out of results (v1.4.1) |
| HentaiHaven (`hentaihaven`) | English | ✅ Working — adult animation (**18+, key-gated in the app, never in home/search rails**); search, details, streams (direct HLS m3u8, `proxy=true`, English Sub); via AniWorld `aniworld` backend (v1.5.0) |

### v1.5 changes (2026-11-18) — HentaiHaven (18+, key-gated)

New source, verified live from the Mumbai server before wiring (search
`elf` → 9 results, details → 2 episodes, streams → HLS master via
`/api/proxy` 200 + variant playlist 200):

- **HentaiHaven** (`hentaihaven`, English, series) — AniWorld Downloader
  backend (`aniworld` PyPI package, `query_hentaihaven` + `HentaiHavenSeries`
  / `HentaiHavenEpisode.refresh_stream_url()`). Direct HLS master
  (octopusmanifest.org `playlist.m3u8`, English audio + subtitles).
  English Sub only — Hindi dub is NOT offered by this source.
  Served ONLY behind the StreamHub app's key-gated adult section.

### v1.4 changes (2026-11-18) — catalog expansion + auto-update + MovieBox

New sources (all verified live from the Mumbai server before wiring;
see `TEST-REPORT.md` for the per-source verification, and
`MOVIEBOX-EVALUATION.md` for the MovieBox research):

- **DramaCool** (`dramacool`, English, series, categories `kdrama` /
  `cdrama`) — `dramaacool.best` (the `dramacool.surf` domain is a static
  SEO doorway with no catalogue — not used). Home/details/streams parse
  the HTML cards; search parses the Angular SSR transfer-cache record
  embedded in `/search?q=` (the `api.dramacool.rest` endpoint 403s
  behind Cloudflare for plain server-side GETs, but the page embeds its
  own response). Card titles come from the poster img `alt` (SEO spam
  unwrapped); link text is only a fallback, and bare status badges
  ("Completed"/"Ongoing") plus "EP 11 … 3h ago" affixes are stripped —
  the first version returned badge words as titles. Streams are the
  episode page's video-host `<iframe>` (vidmoly etc.) as `embed`.
- **PKDramas** (`pkdramas`, Hindi/Urdu, series, category `pakistani`) —
  `pkdramas.com` catalogues Pakistani serials (Hum TV, ARY Digital,
  Har Pal Geo, …) and plays each episode from the broadcaster's
  official YouTube upload. The video id lives in the Next.js RSC
  payload with escaped quotes (`\"videoId\":\"...\"`) and in the
  JSON-LD `embedUrl` — both are tried. Episode links are absolute on
  some drama pages (no `www`), so hrefs are normalised to site paths
  before matching. Streams are `https://www.youtube.com/embed/<id>`
  (`embed`, `proxy: false`).
- **MovieBox** (`moviebox`, Hindi, movie, categories `hollywood` /
  `bollywood` / `movies`) — the MovieBox app backend (`api3.aoneroom.com`
  native BFF + H5 play on `movie-box.co`), signed requests
  (HMAC-MD5, bootstrap Bearer token from the `x-user` header). **The
  Simatwa `moviebox-api` library (Option A as first named) was evaluated
  and is NOT usable: its GitHub repo is unreachable and its only PyPI
  release (0.6.0) is an empty 58-byte stub requiring Python ≥3.14 —
  so the protocol was ported natively (see `MOVIEBOX-EVALUATION.md`).
  Movies only (`subjectType == 1`): series return `hasResource: false`
  from the guest H5 play path, so they are filtered from search/home.
  Streams are full-length MP4s (360p–1080p, `proxy: true` with a
  `Referer: https://movie-box.co/` — the CDN 429s without it) plus up
  to 28 subtitles. **Hindi-dub truth:** Hollywood Hindi-dub movies
  play ("The Avengers [Hindi]" → 2 MP4s, Range 206 + `ftyp`); Hindi-dub
  K-drama and Pakistani drama *subjects* exist in the catalogue but are
  series and do NOT play via the guest path — those still come from
  CKDub/DramaCool and PKDramas. DASH is not emitted (its host 429s
  from the server IP); the native `play-info` endpoint is a 23-second
  preview trap and is never used.

**Auto-update (Task 2):** the 5-minute pre-warm is now joined by a
**30-minute background refresh job** (`REFRESH_INTERVAL_SECONDS =
1800`): every 30 minutes it sweeps latest/trending/popular for every
lang × type, every declared category, and every source's latest key
(>50 jobs) and rewrites the cache, so new releases appear in the app
with no redeploy and no manual step. `GET /health` now reports
`{"refresh": {"runs", "last_run", "last_duration_s", "last_items",
"last_errors"}, "refresh_interval_s": 1800, "prewarm_interval_s": 300}`.

**Fixes found by live-testing the new code (not by reading it):**
MovieBox POSTs 407'd "Signature invalid" because `post_json`
re-serialises the body with spaces — the module now sends the exact
compact string that was signed (unit test asserts the bytes).
DramaCool search returned 0 until the SSR record's real shape
(`"b":{"body":[...]}` paginated object, not a bare array) was read
from the page. PKDramas streams returned 0 until the escaped RSC
`videoId` and absolute episode hrefs were handled.

- Tests: **198/198 unit** (13 cache + 34 animedekho + 46 hindi + 16
  proxy-rewrite + 47 movies + 25 v14 + 17 moviebox, new). Live suite:
  **81/90** (was 66/72) — the 9 failures are RareAnimes 0/6 (markup
  drift, unchanged) and PKDramas 3/6 only because the generic suite
  searches "naruto", which a Pakistani-drama catalogue does not carry
  (its own live test with "tere bin" is 7/7); movies live 25/25,
  moviebox live 9/9, v14 live 17/17.

Rejected (not wired, with reasons — see `TEST-REPORT.md`):
dramacool.surf (SEO doorway, no catalogue), hdhub4u (WordPress REST
disabled, JS-rendered grid), hianime.to (521), animekai.to (connection
reset), myasiantv.cx (410), KissKH (403 Cloudflare). No new anime
source verified; no additional Hollywood source beyond MovieBox +
the existing movie sources.

### v1.4.1 changes (2026-11-18) — three gaps found by live verification

The v1.4 report's claims were re-checked firsthand against the LIVE API
and three gaps were real. Before → after (all numbers measured live
from the Mumbai server, see `TEST-REPORT.md`):

- **GAP 1 — category + lang filter dropped real items.** Before:
  `/api/latest?lang=hindi&category=cdrama` → 0 items + `no source
  supports category: cdrama`; `lang=hindi&category=kdrama` → 39 items
  (CKDub only). Cause: `_lang_sources('hindi')` excluded DramaCool
  (an English source) before the category filter ran. After: a
  category query returns that category's items regardless of the lang
  filter — `lang=hindi&category=cdrama` → **30 items**,
  `lang=hindi&category=kdrama` → **69 items** (CKDub + DramaCool),
  `pakistani` → 20, `hollywood` → 18; an unknown category still
  returns empty results + an `errors` entry, never other items.
- **GAP 2 — DramaCool + PKDramas streams were embed-only.** The v1.4
  "first-frame proof" was only the embed page loading HTTP 200, not a
  playing frame — and StreamHub plays nothing through iframes.
  After: **DramaCool resolves to direct HLS.** The embed host
  (hglink.to / hgcloud.to) is only a JS redirector to a JWPlayer page
  (hanerix.com etc.) whose stream URL sits in a Dean Edwards
  `eval(p,a,c,k,e,d)` packed block; the module unpacks it server-side
  (no JS engine) and returns the direct `master.txt` HLS URL as
  `type: "hls"`, `proxy: true`, with the player-page Referer (the CDN
  404s without it). First-frame proof, live through `/api/proxy`:
  master playlist 200 → variant playlist 200 → first segment 200
  (`video/MP2T`, 1,302,840 bytes, MPEG-TS sync byte). **PKDramas
  cannot direct-play from this server and is reported honestly:**
  every probed episode (Tere Bin ep 1–4) answers via yt-dlp 2026.10.26
  `Video unavailable. This content is currently unavailable in this
  country because of an order from the government related to national
  security or public order` — the official YouTube uploads are
  geo-blocked in India, where the server runs. No fake was wired:
  `streams()` returns empty so the app drops those items instead of
  showing a dead Play button.
- **GAP 3 — MovieBox streams empty for 3 of 12 search results.**
  Diagnosis (not a `streams()` bug): those titles carry
  `hasResource: false` + an empty `detailUrl` in the native API —
  they have no playable resource at all. After: `_subject_to_item`
  filters `hasResource is False` out of search/home, and `details()`
  returns an error for them. The "Avengers Hindi" search now returns
  9 playable movies (was 12 with 3 dead); the first result
  ("The Avengers [Hindi]") returns 2 MP4s, first frame 206 + `ftyp`
  via `/api/proxy`. Also: empty `/api/streams` results are no longer
  cached, so a transient upstream blip can't poison the key for 10
  minutes.
- Tests: **220/220 unit** (13 cache + 34 animedekho + 46 hindi + 16
  proxy-rewrite + 47 movies + 25 v14 + 19 moviebox + 20 v1.4.1, new),
  no regressions. New: `tests/test_v141_unit.py` (category+lang
  combinations, packer unpack against the real saved player page
  `tests/fixtures/dc_hg_player.html`, embed→direct resolution,
  hasResource filtering, empty-streams cache behaviour).

### v1.3 changes (2026-11-18) — Hindi-dub MOVIES + K-drama

New sources (all verified live from the Mumbai server before wiring;
see `TEST-REPORT.md` for the per-source verification):

- **Vegamovies** (`vegamovies`, Hindi, movie) — `ts-search.php` Typesense
  JSON search, `div.poster-card` home rows, detail pages carry nexdrive
  gateways that expand to fastdl direct Google Drive files and V-Cloud
  R2 files. Details emit one episode per download-quality group.
- **Multimovies** (`multimovies`, Hindi, movie) — `/api/search` JSON,
  `article.poster-card` rows, `watchConfig.initialServers` + server-chip
  buttons. The Cineverse server resolves to a direct m3u8 master whose
  Hindi audio rendition is the default; other servers fall back to
  `embed` player URLs.
- **IndStream** (`indstream`, Hindi, movie) — keyless public APIs only:
  IMDb suggestion search, Cinemeta catalogs/meta, Vidly embed → m3u8
  master (1080p) with a Hindi audio track. Vidrift has no m3u8 and is
  skipped; VidLink (libsodium token) is not ported.
- **CKDub** (`ckdub`, Hindi, series, category `kdrama`) — Hindi-dubbed
  Korean dramas; `/category/korean`, `/drama/<slug>/`,
  `/drama/<slug>/watch/<n>` → playmogo `embed` player. No server-side
  search endpoint exists, so search filters the small browse/category
  catalogues client-side.

New/changed endpoints (existing ones unchanged):

- `GET /api/movies?lang=&source=&page=&section=latest` — fan-out over
  movie sources only (112 items for `lang=hindi`).
- `GET /api/title?source=&id=` — generic details for ANY source
  (same handler as `/api/anime`, which keeps working as-is).
- `/api/search` and `/api/trending|popular|latest` gain `&type=movie|series|all`
  (filters by `Source.media_type`, default `"series"`).
- `?category=` is generalized: any source declaring the category in
  `Source.categories` serves it (AnimeDekho declares `tamil`/`telugu`,
  CKDub declares `kdrama`). A category no source supports — or a
  `source` the lang/type/category filters exclude — returns empty
  results **with an `errors` entry**, never other sources' items.
- Pre-warm also refreshes movies latest (hindi + all) and latest kdrama;
  list/search cache keys now include `type`.
- **`/api/proxy` defaults the upstream User-Agent to the browser UA**
  when no `?ua=` is given: the Cineverse stream proxy 403s the
  python-requests default (live 502 before the fix; master + variant
  200 after, 1087 segment URLs rewritten). The Cineverse/IndStream
  streams also carry the browser UA in their `headers`.
- Tests: **156/156 unit** (13 cache + 34 animedekho + 46 hindi + 16
  proxy-rewrite + 47 movies, new). Live suite: **66/72** (was 42/48) —
  the 4 new sources are 6/6 each; only RareAnimes still drops.

### v1.2 changes (2026-11-18) — speed + AnimeDekho watch gate

Why: the KAZE website felt slow on the user's phone (home ~10s, play 20–30s,
Hindi dub missing). Measured on the server: the scrapers themselves were fast
(trending ~1s, latest hindi ~0.6s) — the slowness was no caching (every load
re-scraped 8 sources), a 45s fan-out ceiling, and AnimeDekho's watch endpoint
going ad-gated for datacenter IPs (`{"gated": true}` — the site's own
"skip the ad once per 24h" wall, which must NOT be automated around).

- **Response cache** (`anime_api/cache.py`, thread-safe TTL): lists 10 min,
  search 5 min, details 30 min, streams 10 min (v1.2.1: was 2 min — stream
  tokens live for days, so repeat episode views start fast), widgets 30 min;
  key includes lang/source/query/page/category; responses carry
  `X-Cache: HIT|MISS`.
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

### v1.2.2 changes (2026-11-18) — AnimeWorld CORS + detail fields

- **Zephyrix extractor now proxies** (`"proxy": False` → `True`): the
  `play.zephyrix.org` CDN sends no CORS headers, so the browser's hls.js
  was blocked fetching the AnimeWorld Hindi master playlist — Hindi-dub
  playback never started in the clone. `/api/proxy` serves it same-origin
  (200, ~0.3s). Unit test asserts `proxy` is True.
- **AnimeDekho `details()` now returns `runtime` (minutes), `age_rating`
  and `studio`** (from the data-snapshot / `.dgt-fact` blocks) **and
  `links`** `{tmdb, mal, anilist}` — the fields the real site's detail
  page shows. Verified live: JoJo → runtime 24, age "R", studio
  "David Production", all three links.
- **Episodes now carry `filler` (bool), `still` (TMDB w300 URL) and
  `air_date`** from the dgt episodes endpoint — the clone's 5-column
  episode grid highlights filler episodes with an orange border. Verified
  live: Naruto Shippuden → 18 seasons, 390 episodes, 146 fillers, 390 stills.
- **Pre-warm also refreshes `("latest", "english", ...)`** for the
  English Sub rail.
- Tests: **107/107 unit** (13 cache + 34 animedekho + 45 hindi + 15
  proxy-rewrite), no regressions. Live suite unchanged: 42/48.

### v1.2.3 changes (2026-11-18) — proxy playlist detection + cold stream resolve

- **`/api/proxy` now detects playlists by content, not extension**: some
  CDNs serve HLS manifests as extensionless / `.txt` URLs with a plain
  `text/plain` content-type (zephyrix `master.txt`, its `/m3/<token>`
  variants and audio playlists). The old check (`.m3u8` extension or
  `mpegurl` content-type) let those manifests pass through raw, so their
  relative `/m3/...` URIs resolved against the website's own origin
  (404) — hls.js raised a fatal error and AnimeWorld Hindi-dub playback
  never started, even though the master itself loaded fine (found by
  Playwright, run 9). The proxy now peeks at the first chunk: a body
  starting with `#EXTM3U` is buffered and rewritten. Verified live:
  proxied master 9/9 URIs rewritten (0 bare `/m3/` left), variant
  playlist 140/140 segment URLs rewritten. New unit test
  (`test_proxy_rewrite.py`, now 16 tests).
- **AniSuge `streams()` resolves its two paths in parallel**
  (`ThreadPoolExecutor`, legacy + mapper are independent — both parse
  only from `episode_data`). Measured cold on the server: **4.36s →
  2.12s**, same 3 streams returned. This is what puts a cold first
  frame under the 5s target (was 5.74s in run 9).
- Tests: **108/108 unit** (13 cache + 34 animedekho + 45 hindi + 16
  proxy-rewrite), no regressions. Live suite unchanged: 42/48.

### v1.2.4 changes (2026-11-18) — zephyrix segment Referer

- **Zephyrix streams now carry `Referer: {playerBase}/`** (the
  extractor's docstring already claimed this, the code didn't set it):
  the segment CDN (`s11.zn-grid01.top`) 403s without that Referer,
  which the proxy turned into a 502 and hls.js failed fatally — so
  AnimeWorld Hindi-dub playback still never started even after the
  v1.2.3 playlist fix (found by Playwright, run 10: two proxy 502s).
  The proxy carries the Referer into every rewritten playlist/segment
  URL, so one header covers the whole chain. Verified live through
  the clone proxy: master 200 → variant 200 (697 proxy links) →
  **segments HTTP 200**.
- Tests: **109/109 unit** (13 cache + 34 animedekho + 46 hindi + 16
  proxy-rewrite), no regressions. Live suite unchanged: 42/48.

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
{"ok": true, "sources": ["reanime", "xanime"],
 "refresh": {"runs": 3, "last_run": "2026-11-18T11:00:00",
             "last_duration_s": 12.4, "last_items": 54, "last_errors": 0},
 "prewarm_interval_s": 300, "refresh_interval_s": 1800}
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

Same fan-out shape as search, one section at a time. `&type=movie|series|all`
(v1.3) filters by source media type; `&category=tamil|telugu|kdrama` restricts
the fan-out to sources declaring that category.

```sh
curl "http://localhost:8000/api/trending?lang=english&source=xanime"
curl "http://localhost:8000/api/popular?lang=all&page=2"
curl "http://localhost:8000/api/latest?lang=hindi&category=kdrama"
```

### `GET /api/movies?lang=&source=&page=1&section=latest` (v1.3, +moviebox in v1.4)

Movie lists — the same fan-out, but only over movie sources
(`vegamovies`, `multimovies`, `indstream`, `moviebox`). `section` picks the row
(`latest` default, `trending`, `popular`).

```sh
curl "http://localhost:8000/api/movies?lang=hindi"
curl "http://localhost:8000/api/movies?section=trending&lang=all"
```

### `GET /api/anime?source=<id>&id=<item_id>`

Details for one title. `id` is the source's own identifier from a
search/home result (a slug for JSON sources, a full detail URL for HTML
sources). `GET /api/title?source=<id>&id=<item_id>` (v1.3) is the same
endpoint under a generic name — use it for movies and K-drama; `/api/anime`
keeps working as-is.

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
