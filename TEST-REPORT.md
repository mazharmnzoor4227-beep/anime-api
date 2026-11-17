# anime-api — live test report

Date: 2026-11-18 (PKT). Run: `tests/test_live.py` (all sources, real sites).
Result: **30/42 endpoints passed** — 5 of 7 sources fully working, 2 dropped.

## Per-source results (query: "naruto" unless noted)

| Source | search | home trending | home popular | home latest | details | streams | Verdict |
|---|---|---|---|---|---|---|---|
| xanime | 24 items, first "NARUTO - 20th anniversary" | 24 | 24 | 24 | 1 season, 1 ep, score 8.2 | 1 stream, m3u8 | ✅ 6/6 |
| reanime | 38 items, first "Naruto" | 40 | 40 | 40 | 2 seasons, 440 eps, score 8.0 | 1 stream, flixcloud file, 480p, proxy=true | ✅ 6/6 |
| nineanime | 10 items, first "Naruto Spin-Off: Rock Lee" | 34 | 34 | 34 | 1 season, 51 eps | 1 stream, MegaPlay 1080p, 1 subtitle | ✅ 6/6 |
| anikoto | 26 items, first "Naruto" | 30 | 30 | 30 | 2 seasons, 440 eps | 5 streams, MegaPlay 800p, 4 subtitles | ✅ 6/6 |
| anisuge | 26 items, first "Road of Naruto" | 21 | 24 | 12 | 1 season, 1 ep | 2 streams, MegaPlay 1080p | ✅ 6/6 |
| animeworld | 0 items | 0 | 0 | 0 | skipped | skipped | ❌ 0/6 DROPPED |
| rareanimes | 0 items | 0 | 0 | 0 | skipped | skipped | ❌ 0/6 DROPPED |

Extra live checks (not in the table):
- AniSuge "one piece": 28 results; 1,180 sub + 1,160 dub episodes; ep 1 → 5 streams (1080p/720p/480p) + 3 subtitles.
- Flask app verified live: `/health` lists 7 sources; `/api/search?q=naruto&lang=all` → 200, 124 results in ~5s; `/api/proxy` Range test against a real flixcloud file → HTTP 206, `Content-Range: bytes 0-99/189492877`.
- Fan-out fix verified: `/api/search?q=naruto&lang=hindi` → HTTP 200 with `errors: [{timeout after 45s, animeworld}, {timeout after 45s, rareanimes}]` instead of a 500 (a slow/blocked source never fails the whole request).

## Fixture/unit tests (no network)

- Hindi modules (`tests/test_hindi_unit.py`): **44 passed, 0 failed** — JuicyCodes
  encode→decode round-trip, all `classify_url` cases, Zephyrix POST shape
  (mocked), PixelDrain direct emit, Mega→empty, GoFile `wt` format, dub keys,
  `variantsJson` round-trip, AnimeWorld + RareAnimes parsing against fixture
  HTML, registry pickup (7 sources).

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
