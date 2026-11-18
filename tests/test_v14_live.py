"""Live test for the v1.4 drama sources against the REAL sites.

Run ON the server (clean IP):
    ~/anime-api/.venv/bin/python tests/test_v14_live.py

Each source is exercised end to end: search -> home -> details ->
streams, plus its category check. A source that fails EVERY endpoint
is reported as DROPPED with the reason.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from anime_api.sources.dramacool import DramaCool  # noqa: E402
from anime_api.sources.pkdramas import PKDramas  # noqa: E402


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
                    n, (" first=%r type=%s" % (
                        out["streams"][0]["url"][:90],
                        out["streams"][0].get("type")))
                    if n else "", time.time() - t0))
            except Exception as exc:
                results["streams"] = (False, "EXC %r" % (exc,))
                out = {"streams": []}
            print("  streams: %s" % (results["streams"],))
            # Embed check: the embed page itself must load (the player
            # surface the website iframes).
            if out.get("streams"):
                t0 = time.time()
                try:
                    url = out["streams"][0]["url"]
                    hdrs = dict(out["streams"][0].get("headers") or {})
                    hdrs.setdefault("User-Agent",
                                    "Mozilla/5.0 (Windows NT 10.0; Win64; "
                                    "x64) AppleWebKit/537.36 (KHTML, like "
                                    "Gecko) Chrome/126.0.0.0 Safari/537.36")
                    r = requests.get(url, headers=hdrs, timeout=20)
                    results["embed-loads"] = (
                        r.status_code == 200,
                        "HTTP %d, %d bytes (%.1fs)" % (
                            r.status_code, len(r.content), time.time() - t0))
                except Exception as exc:
                    results["embed-loads"] = (False, "EXC %r" % (exc,))
                print("  embed-loads: %s" % (results["embed-loads"],))
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
    all_results["dramacool"] = run_source(DramaCool(), "boys over flowers")
    all_results["pkdramas"] = run_source(PKDramas(), "tere bin")
    # Category checks.
    print("=" * 70)
    print("CATEGORY kdrama (dramacool) / cdrama (dramacool) / "
          "pakistani (pkdramas)")
    for label, src, cat in [
            ("kdrama", DramaCool(), "kdrama"),
            ("cdrama", DramaCool(), "cdrama"),
            ("pakistani", PKDramas(), "pakistani")]:
        try:
            items = src.home("latest", page=1, category=cat)
            print("  home latest category=%s: %d items, first=%r" % (
                cat, len(items), items[0]["title"] if items else None))
            all_results[src.id]["category/%s" % cat] = (
                bool(items), "%d items" % len(items))
        except Exception as exc:
            print("  EXC %r" % (exc,))
            all_results[src.id]["category/%s" % cat] = (
                False, "EXC %r" % (exc,))
    total_pass = sum(1 for res in all_results.values()
                     for ok, _ in res.values() if ok)
    total = sum(len(res) for res in all_results.values())
    print("TOTAL: %d/%d endpoints passed" % (total_pass, total))
