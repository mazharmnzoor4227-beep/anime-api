"""Live test for the v1.3 movie / K-drama sources against the REAL sites.

Run ON the server (clean IP — Vegamovies/Multimovies are WAF-sensitive):
    ~/workspace/anime-api-work/venv/bin/python tests/test_movies_live.py
(or: python3 tests/test_movies_live.py on the deployed tree).

Each source is exercised end to end: search -> home -> details ->
streams, plus the kdrama category for CKDub. A source that fails
EVERY endpoint is reported as DROPPED with the reason.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anime_api.sources.ckdub import CKDub
from anime_api.sources.indstream import IndStream
from anime_api.sources.multimovies import Multimovies
from anime_api.sources.vegamovies import Vegamovies


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

    for section in ("trending", "popular", "latest"):
        t0 = time.time()
        try:
            items = src.home(section, page=1)
            results["home/%s" % section] = (bool(items), "%d items, first=%r (%.1fs)" % (
                len(items), items[0]["title"] if items else None, time.time() - t0))
        except Exception as exc:
            results["home/%s" % section] = (False, "EXC %r" % (exc,))
        print("  home %s: %s" % (section, results["home/%s" % section]))

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
            if isinstance(detail, dict) and detail.get("error"):
                results["details"] = (False, "error: %s" % detail["error"])
                detail = None
            else:
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
                    n, (" first=%r type=%s quality=%s" % (
                        out["streams"][0]["url"][:90],
                        out["streams"][0].get("type"),
                        out["streams"][0].get("quality")))
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
    print("  => %s: %d/%d endpoints OK" % (src.id, ok, len(results)))
    if ok == 0:
        print("  => DROPPED: %s fails every endpoint" % src.id)
    return results


if __name__ == "__main__":
    all_results = {}
    all_results["vegamovies"] = run_source(Vegamovies(), "avengers")
    all_results["multimovies"] = run_source(Multimovies(), "avengers")
    # "avengers" first hit is the unreleased Doomsday (no Vidly file
    # yet); "avengers endgame" hits the released film instead.
    all_results["indstream"] = run_source(IndStream(), "avengers endgame")
    all_results["ckdub"] = run_source(CKDub(), "boys over flowers")
    # K-drama category check (CKDub only).
    print("=" * 70)
    print("CATEGORY kdrama (ckdub)")
    try:
        items = CKDub().home("latest", page=1, category="kdrama")
        print("  home latest category=kdrama: %d items, first=%r" % (
            len(items), items[0]["title"] if items else None))
        all_results["ckdub"]["category/kdrama"] = (
            bool(items), "%d items" % len(items))
    except Exception as exc:
        print("  EXC %r" % (exc,))
        all_results["ckdub"]["category/kdrama"] = (False, "EXC %r" % (exc,))
    total_pass = sum(1 for res in all_results.values()
                     for ok, _ in res.values() if ok)
    total = sum(len(res) for res in all_results.values())
    print("TOTAL: %d/%d endpoints passed" % (total_pass, total))
