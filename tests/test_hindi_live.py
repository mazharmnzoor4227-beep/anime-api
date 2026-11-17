"""Live test for the Hindi sources against the REAL sites.

Run: ANIME_API_CF_PROXY=http://127.0.0.1:8899 \
     ~/workspace/anime-api-work/venv/bin/python tests/test_hindi_live.py

(ANIME_API_CF_PROXY points the Playwright solver at the sandbox CONNECT
relay; omit it on a normal host.  Each source is exercised end to end:
search -> home -> details -> streams.  A source that fails EVERY endpoint
is reported as DROPPED with the reason.)
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anime_api.sources.animeworld import AnimeWorld
from anime_api.sources.rareanimes import RareAnimes


def run_source(src, query):
    print("=" * 70)
    print("SOURCE %s (%s) base=%s" % (src.id, src.name, src.base_url))
    results = {}

    t0 = time.time()
    try:
        items = src.search(query, page=1)
        results["search"] = (bool(items), "%d items, first=%r (%.1fs)" % (
            len(items), items[0]["title"] if items else None, time.time() - t0))
    except Exception as exc:
        results["search"] = (False, "EXC %r" % (exc,))
    print("  search %r: %s" % (query, results["search"]))

    t0 = time.time()
    try:
        items = src.home("latest", page=1)
        results["home"] = (bool(items), "%d items, first=%r (%.1fs)" % (
            len(items), items[0]["title"] if items else None, time.time() - t0))
    except Exception as exc:
        results["home"] = (False, "EXC %r" % (exc,))
    print("  home latest: %s" % (results["home"],))

    first_id = None
    try:
        items = src.search(query, page=1)
        if items:
            first_id = items[0]["id"]
    except Exception:
        pass
    if not first_id:
        try:
            items = src.home("latest", page=1)
            if items:
                first_id = items[0]["id"]
        except Exception:
            pass

    detail = None
    if first_id:
        t0 = time.time()
        try:
            detail = src.details(first_id)
            n_eps = sum(len(s["episodes"]) for s in detail["seasons"]) \
                if detail else 0
            results["details"] = (bool(detail), "title=%r seasons=%d eps=%d (%.1fs)" % (
                detail["title"] if detail else None,
                len(detail["seasons"]) if detail else 0, n_eps,
                time.time() - t0))
        except Exception as exc:
            results["details"] = (False, "EXC %r" % (exc,))
        print("  details %s: %s" % (first_id, results["details"]))
    else:
        results["details"] = (False, "no item id to load")
        print("  details: SKIP (no item id)")

    if detail:
        ep_data = None
        for season in detail["seasons"]:
            if season["episodes"]:
                ep_data = season["episodes"][0]["data"]
                break
        if ep_data:
            t0 = time.time()
            try:
                out = src.streams(ep_data)
                n = len(out.get("streams", []))
                results["streams"] = (n > 0, "%d streams%s (%.1fs)" % (
                    n, (" first=%r" % out["streams"][0]["url"][:80])
                    if n else "", time.time() - t0))
            except Exception as exc:
                results["streams"] = (False, "EXC %r" % (exc,))
            print("  streams: %s" % (results["streams"],))
        else:
            results["streams"] = (False, "no episode data")
            print("  streams: SKIP (no episode data)")
    else:
        results["streams"] = (False, "no details")
        print("  streams: SKIP (no details)")

    ok = sum(1 for v in results.values() if v[0])
    print("  => %s: %d/4 endpoints OK" % (src.id, ok))
    if ok == 0:
        print("  => DROPPED: %s fails every endpoint" % src.id)
    return results


if __name__ == "__main__":
    run_source(AnimeWorld(), "naruto hindi")
    run_source(RareAnimes(), "naruto hindi")
