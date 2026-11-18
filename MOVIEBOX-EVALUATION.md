# MovieBox evaluation — for the StreamHub v1.4 record

Date: 2026-11-18. Status: **Option A APPROVED by the user ("port it, port
it") and PORTED** — `anime_api/sources/moviebox.py` is wired in v1.4.
This file records what was evaluated, what was chosen and why, and the
honest limits — so a later reader does not re-litigate the same ground.

## The user question

"Can we get MovieBox's extension, everything in it, and put MovieBox's
extension in?" — with the standing rule that everything is inbuilt
(no extension installs for the user). The answer: MovieBox itself is
**proprietary (COIHUB Technology)** — there is NO official "MovieBox
extension". What exists are unofficial projects that talk to MovieBox's
own backend. The user approved **Option A (Simatwa/moviebox-api)** as an
inbuilt source module, expecting Hindi dub etc. to be available in it.

## Option A as first named: Simatwa `moviebox-api` — EVALUATED, NOT USABLE

Tested live 2026-11-18 from the sandbox AND the Mumbai server:

1. **GitHub repo unreachable.** `git clone https://github.com/simatwa/moviebox-api.git`
   prompts for credentials on both machines (`fatal: could not read Username
   for 'https://github.com'`) — the repo is private, renamed or deleted.
   The coordinator's earlier note that it is "actively maintained" could
   not be verified against any reachable repo.
2. **PyPI release is an empty stub.** `moviebox-api` on PyPI has exactly
   ONE release, 0.6.0 (2026-07-13): a 1,665-byte wheel whose
   `moviebox_api/__init__.py` is 58 bytes —
   `def main(): print("Hello from moviebox-api!")` — with no search,
   stream, download or API code at all. The sdist is 664 bytes of
   packaging files only.
3. **It cannot even install on the server.** 0.6.0 declares
   `requires-python: >=3.14`; the server runs Python 3.12.3 — pip
   reports "No matching distribution found".

There is nothing to test and nothing to port from Simatwa's package.
Related projects that cite it (`mesamirh/MovieBox-Tui`,
`mesamirh/stremio-moviebox`) were not themselves tested — they are
clients of the same (now empty) library.

## What was ported instead: the MovieBox app backend (native API)

The port implements the protocol of the MovieBox Android app itself —
the same catalogue the user asked for — following two MIT reference
implementations that WERE reachable and live-verified:

* `walterwhite-69/Moviebox-API` (★101, updated 2026-11-16) — signed
  native requests, bootstrap token, H5 play endpoint.
* `ferelking242/watchtower-extensions` (`moviebox_app.js` v2.0.0) —
  native `play-info` first, H5 fallback, `dubsList`, caption endpoints.
* `solo12345689/moviebox-internal-api` (★40, updated 2026-11-17) —
  protocol/architecture analysis (read as reference; not used directly).

Protocol (all public, no login; guest Bearer token bootstrapped per
instance, 25-min TTL):

* Bootstrap: `GET https://apig.inmoviebox.com/wefeed-mobile-bff/tab/ranking-list?tabId=0&categoryType=4516404531735022304&page=1&perPage=1`
  with signed headers; the `x-user` response header is JSON
  `{"token": ...}` (163-char Bearer token).
* Signing: `x-client-token` = `{ts_ms},{md5(reversed_ts)}`;
  `x-tr-signature` = `{ts}|2|{base64(HMAC-MD5(key, canonical))}` where
  canonical = `METHOD\naccept\ncontent-type\nbody_len\nts\nbody_md5\npath?sorted-query`;
  key = double-base64-decoded
  `NzZpUmwwN3MweFNOOWpxbUVXQXQ3OUVCSlp1bElRSXNWNjRGWnIyTw==`
  (as published in walterwhite-69/Moviebox-API).
* Native base `https://api3.aoneroom.com`: `POST
  /wefeed-mobile-bff/subject-api/search` `{keyword,page,perPage}`;
  `GET subject-api/get?subjectId=`; `GET subject-api/season-info`;
  `GET subject-api/trending/v2`; `GET tab/ranking-list?categoryType=`;
  `GET get-stream-captions` / `get-ext-captions`.
* H5 play: `GET https://movie-box.co/wefeed-h5api-bff/subject/play?subjectId=&se=&ep=&detailPath=&streamSignType=1&supportCodecs[hevc]=1&supportCodecs[h264]=1`
  with Bearer + `x-request-lang`.

**Critical implementation detail (found live):** the signature is
computed over the EXACT compact JSON string
(`json.dumps(body, separators=(",", ":"))`). Sending the same dict via
`requests.post(json=...)` re-serialises with spaces after `,` and `:`,
changing the wire body — the API answers **407 "Signature invalid"**.
The module therefore sends the pre-serialised bytes as `data=`. Unit
test `test_moviebox_unit.py` asserts the exact compact body.

## Verified live (Mumbai server, 2026-11-18)

* Search "avengers" → 18 items, first "The Avengers" (subjectId
  5154075108704669480); "avengers hindi" → 11 items, 5 with "[Hindi]",
  first "The Avengers [Hindi]".
* Ranking lists: Hollywood 18 items (first "Avengers Endgame: Encore
  [Hindi]"), TOP Movies 20, New Release 20, Bollywood 20.
* Details: The Avengers → dubs=4 (Original Audio, Hindi dub, esla dub,
  ptbr dub — each with its own subjectId), score 8.0.
* Streams (H5 play, movie): 4 MP4s — 360p ~500MB, 480p ~535MB, 720p
  ~1.4GB, 1080p ~2.3GB, each with `?sign=` + `&t=` tokens — plus 1 DASH
  manifest with a signCookie. The 1080p MP4 HEADs 200 ONLY with
  `Referer: https://movie-box.co/` (429 without it); Range GET bytes
  0–262143 → **206 with a real `ftyp` box** — the first frame plays
  through `/api/proxy` (streams are `proxy: true` with that Referer +
  browser UA). Captions: 28 subtitles (English verified, SRT URLs with
  CloudFront Policy/Signature params).
* Live suite `tests/test_moviebox_live.py`: **9/9 endpoints**.

## Hindi-dub truth table (live — do not overpromise)

| Category | In MovieBox? | Playable via guest path? |
|---|---|---|
| Hollywood Hindi-dub MOVIES | YES — "The Avengers [Hindi]" H5 play → 2 MP4s (480p 435MB, 720p 1.1GB); Range GET 206 + `ftyp` | **YES** |
| Hindi-dub K-Drama | Subjects EXIST ("Boys Over Flowers [Hindi]", "Crash Landing on You [Hindi]") | **NO** — series (type 2), H5 returns `hasResource: false` |
| Hindi-dub C-Drama / vertical drama | Subjects exist (type 7 dubbed shorts) | Not a catalogue category here |
| Pakistani dramas | Subjects EXIST ("Tere Bin" Urdu/Pakistan, "Dar E Nijaat [Urdu]", "Mitti De Baway", "Nashtar") | **NO** — series (type 2), H5 returns `hasResource: false` |

**MovieBox is EXTRA Hollywood/Hindi-dub-movie breadth.** Hindi-dub
coverage overall still comes primarily from AnimeWorld, Vegamovies,
Multimovies, IndStream and the other Hindi sources. K-drama Hindi dub
still comes from CKDub/DramaCool; Pakistani dramas still come from
PKDramas. Nothing in this file promises otherwise.

## Deliberate limits (not bugs)

* **MOVIES ONLY** (`media_type="movie"`, `subjectType == 1` filter).
  Series are filtered out of search/home because the H5 play endpoint
  answers `{"hasResource": false, "streams": [], "dash": [], "hls": []}`
  for every series probed (Squid Game [Hindi] S1E1/E3, Breaking Bad
  [Hindi] S1E1 — also with a `/tv/detail` Referer and on
  `h5-api.aoneroom.com`). Series subjects DO carry `resourceDetectors`
  (community uploads), but the guest H5 play path does not resolve them.
  `details()` still lists a series' seasons if called directly, but
  `streams()` returns empty for it.
* **The native `play-info` endpoint is a TRAP and is never used**: it
  returns one 824,720-byte MP4 (`duration: 23`) at the SAME URL for every
  title — a 23-second preview clip, not the title. H5 play is the only
  full-length path.
* **DASH is NOT emitted in v1.4**: the DASH manifest host (`sbcdnw...`)
  answered HTTP 429 on every fetch from the server IP (with and without
  the `signCookie`, even after a 20s pause), while the MP4 CDN serves
  fine with a Referer. MP4 covers 360p–1080p, so nothing is lost for
  playback. The `signCookie` parse (`_policy_resource`) is kept and
  unit-tested for a future DASH path.
* **Signed-cookie proxying was evaluated and is NOT needed for the
  shipped path**: the MP4 streams need only a Referer (+ browser UA),
  which `/api/proxy` already forwards. No cookie forwarding was added
  to the proxy. If DASH is ever emitted, its `signCookie` (Edge-Cache-
  Cookie + CloudFront-Policy/Signature/Key-Pair-Id) would need proxy
  support — that is the MovieBox-Tui loopback-proxy pattern, and it is
  NOT implemented here.

## Rejected / dead ends

* **KissKH** (kisskh.co/.is/.do): 403 Cloudflare "Just a moment..."
  from the server IP — rejected, no K-drama source from it.
* **simatwa/moviebox-api**: see "Option A" above — stub package, dead repo.
* **walterwhite-69 REST API as a deployed sidecar**: not used — the
  protocol was ported natively into `moviebox.py` instead, so the API
  has no new runtime dependency (no extra service, no curl_cffi — the
  server venv has neither).
