# anime-api — live test report

Date: 2026-11-18 (PKT). Run: `tests/test_live.py` (all sources, real sites).
Result: **81/90 endpoints passed** — 13 of 15 sources fully working, 1 dropped, 1 query artifact.

## v1.4 — catalog expansion + auto-update + MovieBox, verified live on the deployed server (Oracle Mumbai)

Unit suites: cache 13/13, animedekho 34/34, hindi 46/46,
proxy-rewrite 16/16, movies 47/47, v14 25/25 (new), moviebox 17/17 (new)
— **198/198, no regressions**.

Live suites: full `tests/test_live.py` **81/90** (was 66/72); movies
`tests/test_movies_live.py` **25/25**; hindi `tests/test_hindi_live.py`
**3/8** (animeworld 3/4, rareanimes 0/4 — see below); moviebox
`tests/test_moviebox_live.py` **9/9**; v14 `tests/test_v14_live.py`
**17/17**. The 9 failures in the full suite are RareAnimes 0/6
(markup drift, unchanged since v1.1) and PKDramas 3/6 — the generic
suite searches "naruto", which a Pakistani-drama catalogue does not
carry (its own live test with "tere bin" is 7/7). AnimeWorld search
"naruto" works (2 items); only its "naruto hindi" query returns 0.

### Per-source verification (live, from the server IP, before wiring)

| Source | search | home | details | streams | Verdict |
|---|---|---|---|---|---|
| dramacool | 10 items, first "Boys Over Flowers Season 2" | 30–102/section | 1 season, 11 eps ("Blossom in Darkness (2026)") | 4 streams, vidmoly `embed` (page 200, 71,870 bytes) | ✅ 7/7 |
| pkdramas | 6 items, first "Tere Bin Har Pal Geo" | 20–48/section | 1 season, 50 eps ("Tere Bin") | 1 stream, YouTube `embed/FOayEzY3C3o` (page 200, 149,554 bytes) | ✅ 7/7 |
| moviebox | 18 items, first "The Avengers"; "avengers hindi" → 5 Hindi of 11 | 5–20/section; hollywood 18 | 1 season, 1 ep, dubs=4 | 4 streams, MP4 1080p first, 28 subtitles; Range GET 206 + `ftyp` | ✅ 9/9 |
| kdrama category | — | 30 items, first "The Substitute" (dramacool) | — | — | ✅ |
| cdrama category | — | 30 items, first "The Confession Truth" (dramacool) | — | — | ✅ |
| pakistani category | — | 20 items (pkdramas) | — | — | ✅ |
| hollywood category | — | 18 items, first "Avengers Endgame: Encore [Hindi]" (moviebox) | — | — | ✅ |

Verification notes:
- DramaCool: the site is an Angular SPA — `/search?q=` returns the app
  shell with no cards, and `api.dramacool.rest` 403s Cloudflare for
  plain server-side GETs (even with browser Referer/Origin). The search
  page embeds the API's own response in an Angular HTTP transfer-cache
  record (`"b":{"currentPage":1,...,"body":[...]}`, 10/page, 139 total
  for "boys"); search parses that record. Home cards: 102 items on `/`,
  30 on `/explore`; the first version returned status badges
  ("Completed"/"Ongoing") as titles and search returned 0 — both fixed
  live (alt-preferred titles, EP/time stripping, `"b":{"body":...}`
  shape). `dramacool.surf` is a static SEO doorway (anchor links only,
  `/search` 404) — rejected.
- PKDramas: search `/search?q=tere+bin` → 6 items; detail "Tere Bin"
  → 50 episodes; episode 9 page carries `videoId FOayEzY3C3o` in the
  escaped RSC payload + JSON-LD `embedUrl` (the first version missed it
  because the quotes are backslash-escaped). Hurmat detail → 15 episode
  links (absolute `https://pkdramas.com/...` hrefs, normalised before
  matching). Streams are official YouTube uploads; the site hosts no
  video itself.
- MovieBox: full evaluation in `MOVIEBOX-EVALUATION.md`. Simatwa's
  `moviebox-api` (Option A as first named) is an empty PyPI stub with a
  dead repo — the port implements the app backend natively. Search
  "avengers" → 18 items; H5 play for The Avengers → 4 MP4s (360p–1080p)
  + 1 DASH; 1080p MP4 HEADs 200 only with `Referer:
  https://movie-box.co/` (429 without); Range GET 0–262143 → 206 with
  `ftyp`. Hindi-dub movie "The Avengers [Hindi]" → 2 MP4s, same 206 +
  `ftyp`. Series do NOT play via the guest path (`hasResource: false`
  for Squid Game [Hindi] / Breaking Bad [Hindi]) — movies only.
  DASH host 429s from the server IP — not emitted. Native `play-info`
  returns a 23s preview clip for every title — never used.
- Rejected this round: hdhub4u (WordPress REST disabled for guests,
  JS-rendered grid, search redirects to homepage), hianime.to (521),
  animekai.to (connection reset), myasiantv.cx (410), KissKH (403
  Cloudflare). No new anime source verified; no additional Hollywood
  source beyond MovieBox + the existing movie sources.

### Auto-update (Task 2) — 30-minute refresh job

`_refresh_jobs()` builds >50 jobs (sections × langs × types + every
declared category + per-source latest keys). `_refresh_once()` sweeps
them all into the cache and updates `REFRESH_STATE` (runs, last_run,
last_duration_s, last_items, last_errors); `_refresh_loop()` runs the
first sweep 10s after startup, then every 1800s. `/health` exposes the
state (see README). Verified after deploy (see "Server timings" below):
refresh runs increment and the new sources' titles appear through
`/api/latest` with no redeploy.

### Server timings (curl, direct to 127.0.0.1:8000), before → after

v1.3 baseline → v1.4 (same server, same method):
- trending (all): 324 items, 0.003s warm (unchanged)
- latest hindi: 184 items, 0.002s warm (unchanged)
- movies latest hindi: 112 items → **~130 items, 0.002s warm**
  (moviebox now included)
- latest kdrama: 39 items → **69 items, 0.002s warm** (ckdub 39 + dramacool 30)
- latest cdrama (new): **30 items, 0.002s warm** (dramacool)
- latest pakistani (new): **20 items, 0.002s warm** (pkdramas)
- latest hollywood (new): **18 items, 0.002s warm** (moviebox)
- search "avengers" type=movie: 26 items → **~37 items, 0.54s cold**
  (moviebox adds 11 Hindi-dub titles)
- live suite: **81/90** (was 66/72) — only RareAnimes drops + the
  pkdramas "naruto" query artifact.

### Contract fixes (frontend report, verified live after deploy)

- `GET /api/latest?lang=hindi&category=kdrama` returns CKDub + DramaCool
  items; `category=cdrama` returns DramaCool only; `category=pakistani`
  returns PKDramas only; `category=hollywood` returns MovieBox only.
- `GET /api/title?source=moviebox&id=5154075108704669480` returns The
  Avengers with `dubs` (4 audio versions as their own subjectIds).
- `GET /api/streams?source=moviebox&data={...}` returns 4 MP4 streams
  (`proxy: true`) + subtitles; the 1080p MP4 plays its first frame
  through `/api/proxy` (Range 206 + `ftyp`, verified live).

## v1.3 — Hindi-dub movies + K-drama, verified live on the deployed server (Oracle Mumbai)

Unit suites: cache 13/13, animedekho 34/34, hindi 46/46,
proxy-rewrite 16/16, movies 47/47 (new) — **156/156, no regressions**.

Live suites: full `tests/test_live.py` **66/72** (was 42/48); movies
`tests/test_movies_live.py` **25/25**. The 4 new sources are 6/6 each;
only RareAnimes still drops (markup drift, 0 items — unchanged).

### Per-source verification (live, from the server IP, before wiring)

| Source | search | home | details | streams | Verdict |
|---|---|---|---|---|---|
| vegamovies | 11 items, first "Avengers Endgame : Encore (2026)" | 18–19/section | 1 season, 8 eps (quality groups) | 2 streams, direct G-Drive file (HEAD 200, 940 MB) + V-Cloud R2 | ✅ 6/6 |
| multimovies | 9 items, first "Avengers: Endgame" | 30–43/section | 1 season, 1 ep, score 8.2 | 6 streams, Cineverse m3u8 1080p (Hindi audio default) + embed fallbacks | ✅ 6/6 |
| indstream | 2 items, first "Avengers: Endgame" | 50–100/section | 1 season, 1 ep, score 8.4 | 1 stream, Vidly m3u8 1080p + English subtitle | ✅ 6/6 |
| ckdub | 1 item, "Boys Over Flowers" | 18–39/section | 1 season, 25 eps | 1 stream, playmogo `embed` | ✅ 6/6 |
| kdrama category | — | 39 items, all `ckdub` | — | — | ✅ |

Verification notes:
- Vegamovies: search index → detail (8 nexdrive gateways) → gateway
  expands to fastdl + vcloud → fastdl resolves to a direct
  `video-downloads.googleusercontent.com` file (HEAD 200, 940,129,536
  bytes); vcloud double-atob token page yields R2 file links.
- Multimovies: detail carries 6 server chips; Cineverse embed →
  proxy.php player → `stream_proxy.php` master playlist (`#EXTM3U`,
  Hindi audio `NAME="हिन्दी", LANGUAGE="hi", DEFAULT=YES`). The master
  **502'd through `/api/proxy` until the proxy defaulted to a browser
  UA** (the host 403s python-requests UA) — fixed in v1.3; after the
  fix master 200 + variant 200 with 1,087 segment URLs rewritten.
  Other servers (GD mirror, Nexus 429, Vidrift, VIDOUT, Vidbolt) are JS
  player shells — returned as `embed` fallbacks.
- IndStream: IMDb suggest → Cinemeta meta (moviedb_id 299534) → Vidly
  embed → m3u8 master with a Hindi audio rendition (`LANGUAGE="hin"`).
  Vidrift's embed page carries no m3u8 (skipped); VidLink needs a
  libsodium token (not ported). The first "avengers" search hit is the
  unreleased Avengers: Doomsday (tmdb 1003596) — Vidly has no file for
  it yet, so the live query is "avengers endgame"; Doomsday failing
  streams is a missing file, not a source bug.
- CKDub: home/category/detail/watch all 200; the watch page's iframe is
  a playmogo embed — returned as `embed` (same contract as AnimeDekho).
  Playmogo itself 403s Cloudflare "Just a moment..." from the server IP,
  so the embed could not be resolved further server-side; on a normal
  (phone) network it loads like any video-host embed. The site has no
  server-side search endpoint (`/search`, `/api/search` 404;
  `/browse?q=` returns empty) — search filters the small browse/category
  catalogues client-side.

### Server timings (curl, direct to 127.0.0.1:8000), before → after

v1.2.4 baseline → v1.3 (same server, same method):
- trending (all): 1.9s → 3ms warm (186 items) → **324 items, 0.003s warm**
- latest hindi: 0.68s → 2ms warm (52 items) → **184 items, 0.002s warm**
  (movies + K-drama now included)
- movies latest hindi (new): **112 items, 0.002s warm** (pre-warmed)
- latest kdrama (new): **39 items, 0.49s cold / 0.002s warm**, all `ckdub`
- search "avengers" type=movie (new): **26 items, 0.54s cold**, movie sources only
- details vegamovies via /api/title (new): **0.11s cold / 0.002s warm**
- search "naruto": 1.78s → 0.79s cold / 0.002s warm (unchanged)
- details JoJo (5 seasons): 3.38s → 1.5s cold / 0.002s warm (unchanged)
- live suite: **66/72** (was 42/48) — only RareAnimes drops.

### Contract fixes (frontend report, verified live after deploy)

- `GET /api/title?source=&id=` exists and returns the same shape as
  `/api/anime` for ANY source (verified: multimovies Endgame 200,
  animedekho Naruto Shippūden 200, vegamovies Encore 200).
- `GET /api/latest?lang=hindi&category=kdrama` returns **only** CKDub
  items (39, `sources: ["ckdub"]`). An unknown category returns empty
  results with `errors: [{"source": "category:<name>", "error": "no
  source supports category: <name>"}]`; a `source` the lang/type/category
  filters exclude returns empty results with an `errors` entry naming
  the source — never another source's items.

## v1.2 — speed, verified live on the deployed server (Oracle Mumbai)

Unit suites: cache 13/13 (new), animedekho 32/32, hindi 44/44,
proxy-rewrite 15/15 — **104/104, no regressions**.

Server timings (curl, direct to 127.0.0.1:8000), before → after:
- trending: 1.9s → **0.003s warm** (pre-warmed, X-Cache HIT, 186 items)
- latest hindi: 0.68s → **0.002s warm** (52 items)
- popular: 1.14–2.88s → **0.002s warm** (174 items)
- search "naruto": 1.78s → **0.79s cold / 0.002s warm**
- details JoJo (5 seasons): 3.38s → 1.5s cold (Demon Slayer) / **0.002s warm**;
  seasons=5, eps s1=26, characters=10, voice_cast=21
- streams animedekho: 3.11–5.31s + gated-empty → **0.002s** (direct embed URL,
  no watch call): `https://animedekho.tv/embed/10145/1-1`
- widgets: 0.49s cold / 0.001s warm; category tamil: 24 items, warm 0.002s
- live suite: **42/48** (was 36/48) — only RareAnimes drops (markup drift,
  0 items on every endpoint; same as v1.1, needs a look later).

## v1.2.2 — AnimeWorld CORS + detail fields, verified live on the server

Unit suites: cache 13/13, animedekho 34/34, hindi 45/45, proxy-rewrite 15/15
— **107/107, no regressions**.

- Zephyrix `proxy: True` (was False): browser hls.js was CORS-blocked on
  `play.zephyrix.org` master playlists (no Access-Control-Allow-Origin from
  the CDN); `/api/proxy` serves them same-origin, 200 in ~0.3s. This was
  the reason Hindi-dub AnimeWorld never played in the clone.
- AnimeDekho details: JoJo → runtime 24, age "R", studio "David
  Production", links TMDB/MAL/AniList all present; Naruto Shippuden →
  18 seasons, 390 episodes, 146 fillers, 390 stills (per-episode
  `filler`/`still`/`air_date` verified live).
- Live suite unchanged: **42/48** — only RareAnimes drops.

## v1.2.4 — zephyrix segment Referer

Unit suites: cache 13/13, animedekho 34/34, hindi 46/46, proxy-rewrite
16/16 — **109/109, no regressions**.

- Zephyrix streams carry `Referer: {playerBase}/`: the segment CDN
  403s without it (proxy → 502 → hls.js fatal). Verified live through
  the clone proxy: master 200, variant 200 (697 proxy links), segments
  HTTP 200 — AnimeWorld Hindi-dub playback now works end to end.
- Live suite unchanged: **42/48** — only RareAnimes drops.

## v1.2.3 — proxy playlist detection + cold stream resolve

Unit suites: cache 13/13, animedekho 34/34, hindi 45/45, proxy-rewrite
16/16 — **108/108, no regressions**.

- `/api/proxy` content-detects playlists (`#EXTM3U` first bytes): zephyrix
  `master.txt` + `/m3/<token>` variants/audio now rewrite fully (master
  9/9, variant 140/140 URLs through the proxy, 0 bare `/m3/` left).
  Before the fix, AnimeWorld Hindi playback failed in the browser with
  an hls.js fatal error even though the master loaded (run 9 diagnosis).
- AniSuge `streams()` parallel legacy+mapper: cold **4.36s → 2.12s**,
  same 3 streams ([800, 800, 480]).
- Live suite unchanged: **42/48** — only RareAnimes drops.

## v1.1.1 — playback fix, verified live on the deployed server

Direct browser playback of anisuge/MegaPlay m3u8 streams 403'd (Cloudflare
hotlink check needs the site Referer). After the fix (streams `proxy: true`,
`/api/proxy` m3u8 rewrite, subtitles via `/api/proxy`): Playwright against
the public tunnel link — **12/12 checks passed** (home: real posters, 48/241
loaded in-browser; Latest Hindi Dub 52 items; browse naruto; detail 5 eps;
watch: real stream URL via proxy, metadata loads, no "didn't load", zero
console errors, zero failed requests). Unit: 15/15 proxy-rewrite tests.

Mumbai server IP results (the sandbox-blocked Hindi sources re-tested):
animeworld search "naruto" → 2 results (WORKS from the server IP);
rareanimes → 0 results on search + latest with no error (site responds,
returns nothing — likely markup/domain drift, needs a look);
`/api/latest?lang=hindi` → 52 items (animedekho 32 + animeworld 20).

## Per-source results (query: "naruto" unless noted)

| Source | search | home trending | home popular | home latest | details | streams | Verdict |
|---|---|---|---|---|---|---|---|
| xanime | 24 items, first "NARUTO - 20th anniversary" | 24 | 24 | 24 | 1 season, 1 ep, score 8.2 | 1 stream, m3u8 | ✅ 6/6 |
| reanime | 38 items, first "Naruto" | 40 | 40 | 40 | 2 seasons, 440 eps, score 8.0 | 1 stream, flixcloud file, 480p, proxy=true | ✅ 6/6 |
| nineanime | 10 items, first "Naruto Spin-Off: Rock Lee" | 34 | 34 | 34 | 1 season, 51 eps | 1 stream, MegaPlay 1080p, 1 subtitle | ✅ 6/6 |
| anikoto | 26 items, first "Naruto" | 30 | 30 | 30 | 2 seasons, 440 eps | 5 streams, MegaPlay 800p, 4 subtitles | ✅ 6/6 |
| anisuge | 26 items, first "Road of Naruto" | 21 | 24 | 12 | 1 season, 1 ep | 2 streams, MegaPlay 1080p | ✅ 6/6 |
| animedekho | 3 items, first "Naruto Shippūden" | 20 | 16 | 32 | 18 seasons, 390 eps, score 9.7 | 8 streams, embed iframes | ✅ 6/6 |
| animeworld | 0 items | 0 | 0 | 0 | skipped | skipped | ❌ 0/6 DROPPED |
| rareanimes | 0 items | 0 | 0 | 0 | skipped | skipped | ❌ 0/6 DROPPED |

Extra live checks (not in the table):
- AniSuge "one piece": 28 results; 1,180 sub + 1,160 dub episodes; ep 1 → 5 streams (1080p/720p/480p) + 3 subtitles.
- Flask app verified live: `/health` lists 8 sources; `/api/trending` → 166 items, 0 duplicates, 0 poster nulls; `/api/latest?lang=hindi` → 32 items, all AnimeDekho; `/api/search?q=naruto&lang=all` → 119 results (website browse); `/api/proxy` Range test against a real flixcloud file → HTTP 206, `Content-Range: bytes 0-99/189492877`.
- Fan-out fix verified: `/api/search?q=naruto&lang=hindi` → HTTP 200 with `errors: [{timeout after 45s, animeworld}, {timeout after 45s, rareanimes}]` instead of a 500 (a slow/blocked source never fails the whole request).
- AnimeDekho streams verified twice via real episode data from `/api/anime`
  (Naruto Shippūden E01, `{"post_id": 4959, "episode_id": 35182, ...}`) → 8
  embed streams, first `https://animedekho.tv/embed/31910/1-1`; the website's
  watch page renders the embed in an `<iframe>` with a server picker
  (HydraX/OPlayer/NeoCDN/SRuby, 1080p).
- Poster CDNs spot-checked from this sandbox: TMDB `image.tmdb.org` → 200
  image/jpeg; anipixcdn → 200 image/jpeg; AniList `s4.anilist.co` → 403 on
  every sampled URL (the CDN blocks this sandbox's egress IP, not a deleted
  file — reanime posters are AniList-hosted, so they show blank here but load
  on a normal network).

## Fixture/unit tests (no network)

- Hindi modules (`tests/test_hindi_unit.py`): **44 passed, 0 failed** — JuicyCodes
  encode→decode round-trip, all `classify_url` cases, Zephyrix POST shape
  (mocked), PixelDrain direct emit, Mega→empty, GoFile `wt` format, dub keys,
  `variantsJson` round-trip, AnimeWorld + RareAnimes parsing against fixture
  HTML, registry pickup (7 sources).
- AnimeDekho (`tests/test_animedekho_unit.py`): **34 passed, 0 failed** —
  quality parsing, card parsing (dedupe), row selection, search/details/streams
  against fixtures (nonce header, gated retry, rank order), details
  `type`/`audio` fields, **nonce scraped from the episode page** (the
  homepage carries no `dgt-store` script — found 2026-11-18 when live streams
  calls started returning 0; fixed by trying the episode/referer page first,
  homepage only as fallback), registry pickup (8 sources).
- **Nonce fix verified live** (2026-11-18, after the fix): fresh Flask server,
  real episode data from `/api/anime` → `/api/streams` returns **8 embed
  streams**; the website watch page renders the embed in an `<iframe>` with a
  4+ server picker and zero ≥400 responses (Playwright, `verify/watch2.png`).

## Why the Hindi sources are dropped (verified, not guessed)

1. Plain requests: `watchanimeworld.one` → 403 Cloudflare "Attention
   Required!" block page; `rareanimes.fans` → 403 bare "Your request was
   blocked." (also on `.mov` / `.foo`).
2. Headless Chromium (Playwright, browsers cached) **cannot reach the
   internet directly** in this sandbox (egress proxy MITMs TLS); with a local
   CONNECT relay it loads pages fine.
3. With the relay, headless Chromium **does obtain a `cf_clearance` cookie
   for AnimeWorld** — but the browser **still shows the 403 block page** with
   the cookie present, and `requests` with that same cached clearance still
   gets 403. For RareAnimes, no clearance is ever issued in 90s (browser
   redirected `.fans` → `.foo`, still 403).
4. Conclusion: both sites hard-block this sandbox's egress IP at the WAF-rule
   level. There is **no JS challenge to solve**, and a clearance cookie does
   not lift the block. This is an IP-reputation problem, not a solver problem.
   `anime_api/cf.py` implements the correct design for a host with a clean IP
   (solve → cache 15h → requests with cookies; env/file fallback documented
   in its docstring). No clearance cookie was hardcoded anywhere.

## Known limitations (honest)

- Kwik/Pahe download path (AniSuge mapper `download` entries): code follows
  the extension contract exactly; the packer unpacker was verified against a
  generated `function(p,a,c,k,e,d)` snippet, but no live mapper response
  carried `download` entries during testing — treat as unit-verified only.
- NineAnime Moon (`bysesayeveum.com`) is WebView-only — skipped.
- Non-MegaPlay embed hosts on AniKoto fall back to a best-effort plain GET +
  `.m3u8` regex (CloudStream's generic `loadExtractor` has no server-side
  equivalent).
- Re:ANIME stream tokens are IP-bound — play via `/api/proxy`, never direct.
- Sources are unofficial and change layout without notice; scrapers need
  maintenance when a site changes.
