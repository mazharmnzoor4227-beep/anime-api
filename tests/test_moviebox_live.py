"""Live test for the MovieBox source against the REAL backend.

Run ON the server (clean IP):
    ~/anime-api/.venv/bin/python tests/test_moviebox_live.py

Exercises search -> home (trending/popular/latest + hollywood
category) -> details -> streams end to end, plus the Hindi-dub
movie check ("avengers hindi" -> The Avengers [Hindi] -> H5 play
-> Range GET of the first bytes, expecting 206 + ftyp).
A source that fails EVERY endpoint is reported as DROPPED.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from anime_api.sources.moviebox import MovieBox  # noqa: E402


def run():
    src = MovieBox()
    print("=" * 70)
    print("SOURCE moviebox (%s) native=%s" % (src.name, src.base_url))
    results = {}

    t0 = time.time()
    try:
        items = src.search("avengers", page=1)
        results["search"] = (bool(items), "%d items, first=%r (%.1fs)" % (
            len(items), items[0]["title"] if items else None,
            time.time() - t0))
    except Exception as exc:
        results["search"] = (False, "EXC %r" % (exc,))
    print("  search 'avengers': %s" % (results["search"],))

    t0 = time.time()
    try:
        items = src.search("avengers hindi", page=1)
        hindi = [it for it in items if "[Hindi]" in it["title"]]
        results["search/hindi"] = (bool(hindi),
                                   "%d hindi items of %d, first=%r (%.1fs)"
                                   % (len(hindi), len(items),
                                      hindi[0]["title"] if hindi else None,
                                      time.time() - t0))
    except Exception as exc:
        results["search/hindi"] = (False, "EXC %r" % (exc,))
    print("  search 'avengers hindi': %s" % (results["search/hindi"],))

    for section in ("trending", "popular", "latest"):
        t0 = time.time()
        try:
            items = src.home(section, page=1)
            results["home/%s" % section] = (
                bool(items), "%d items, first=%r (%.1fs)" % (
                    len(items), items[0]["title"] if items else None,
                    time.time() - t0))
        except Exception as exc:
            results["home/%s" % section] = (False, "EXC %r" % (exc,))
        print("  home %s: %s" % (section, results["home/%s" % section]))

    t0 = time.time()
    try:
        items = src.home("latest", page=1, category="hollywood")
        results["category/hollywood"] = (
            bool(items), "%d items, first=%r (%.1fs)" % (
                len(items), items[0]["title"] if items else None,
                time.time() - t0))
    except Exception as exc:
        results["category/hollywood"] = (False, "EXC %r" % (exc,))
    print("  category hollywood: %s" % (results["category/hollywood"],))

    first_id = None
    try:
        items = src.search("avengers", page=1)
        if items:
            first_id = items[0]["id"]
    except Exception:
        pass
    detail = None
    if first_id:
        t0 = time.time()
        try:
            detail = src.details(first_id)
            if isinstance(detail, dict) and detail.get("error"):
                results["details"] = (False, "error: %s" % detail["error"])
                detail = None
            else:
                n_eps = sum(len(s["episodes"]) for s in detail["seasons"])
                results["details"] = (
                    bool(detail), "title=%r dubs=%d eps=%d (%.1fs)" % (
                        detail["title"],
                        len(detail.get("dubs") or []), n_eps,
                        time.time() - t0))
        except Exception as exc:
            results["details"] = (False, "EXC %r" % (exc,))
        print("  details %s: %s" % (first_id, results["details"]))
    else:
        results["details"] = (False, "no item id to load")
        print("  details: SKIP (no item id)")

    if detail:
        ep_data = detail["seasons"][0]["episodes"][0]["data"]
        t0 = time.time()
        try:
            out = src.streams(ep_data)
            streams = out.get("streams", [])
            n = len(streams)
            results["streams"] = (n > 0, "%d streams%s subtitles=%d (%.1fs)"
                                  % (n, (" first=%r quality=%s" % (
                                      streams[0]["url"][:80],
                                      streams[0].get("quality")))
                                  if n else "",
                                  len(out.get("subtitles", [])),
                                  time.time() - t0))
        except Exception as exc:
            results["streams"] = (False, "EXC %r" % (exc,))
            streams = []
        print("  streams: %s" % (results["streams"],))
        # First-frame check: Range GET the best stream's first bytes.
        if streams:
            t0 = time.time()
            try:
                url = streams[0]["url"]
                hdrs = dict(streams[0].get("headers") or {})
                hdrs["Range"] = "bytes=0-262143"
                r = requests.get(url, headers=hdrs, timeout=20)
                ok = (r.status_code in (200, 206)
                      and len(r.content) > 1000
                      and b"ftyp" in r.content[:16])
                results["first-frame"] = (
                    ok, "HTTP %d, %d bytes, ftyp=%s (%.1fs)" % (
                        r.status_code, len(r.content),
                        b"ftyp" in r.content[:16], time.time() - t0))
            except Exception as exc:
                results["first-frame"] = (False, "EXC %r" % (exc,))
            print("  first-frame: %s" % (results["first-frame"],))
    else:
        results["streams"] = (False, "no details")
        print("  streams: SKIP (no details)")

    ok = sum(1 for v in results.values() if v[0])
    print("  => moviebox: %d/%d endpoints OK" % (ok, len(results)))
    if ok == 0:
        print("  => DROPPED: moviebox fails every endpoint")
    return results


if __name__ == "__main__":
    res = run()
    total_pass = sum(1 for v in res.values() if v[0])
    print("TOTAL: %d/%d endpoints passed" % (total_pass, len(res)))
