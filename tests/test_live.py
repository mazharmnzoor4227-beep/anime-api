"""Live test runner: exercises each registered source against the REAL sites.

Usage:
    ~/workspace/anime-api-work/venv/bin/python tests/test_live.py [--source <id>]

For each source it runs, in order:
  search("naruto") -> details(first search hit) -> streams(first episode)
  home(trending) / home(popular) / home(latest)
and prints PASS/FAIL per endpoint with a one-line real-data summary.
A source that fails EVERY endpoint is reported as DROPPED with the reason.
Exit code 0 if at least one source passed at least one endpoint, else 1.
"""

import argparse
import sys
import traceback

sys.path.insert(0, __file__.rsplit("/tests/", 1)[0])

from anime_api.sources import get_source, list_sources  # noqa: E402


def _summarise_items(items):
    if not items:
        return "0 items"
    first = items[0]
    return "%d items, first='%s' (id=%s)" % (
        len(items), first.get("title"), first.get("id"),
    )


def _first_episode(details):
    for season in details.get("seasons") or []:
        for ep in season.get("episodes") or []:
            return season, ep
    return None, None


def test_source(src, verbose=True):
    """Return dict endpoint -> (passed, summary)."""
    results = {}

    # search
    try:
        items = src.search("naruto", page=1) or []
        ok = len(items) > 0
        results["search"] = (ok, _summarise_items(items))
    except Exception as exc:
        results["search"] = (False, "exception: %s" % exc)
        items = []

    # home sections
    for section in ("trending", "popular", "latest"):
        try:
            home_items = src.home(section, page=1) or []
            results["home/%s" % section] = (
                len(home_items) > 0, _summarise_items(home_items),
            )
        except Exception as exc:
            results["home/%s" % section] = (False, "exception: %s" % exc)

    # details on the first search hit
    details = None
    if items:
        try:
            details = src.details(items[0]["id"])
            if isinstance(details, dict) and details.get("error"):
                results["details"] = (False, "error: %s" % details["error"])
                details = None
            else:
                n_eps = sum(
                    len(s.get("episodes") or [])
                    for s in details.get("seasons") or []
                )
                results["details"] = (
                    True,
                    "title='%s' seasons=%d episodes=%d score=%s"
                    % (
                        details.get("title"),
                        len(details.get("seasons") or []),
                        n_eps, details.get("score"),
                    ),
                )
        except Exception as exc:
            results["details"] = (False, "exception: %s" % exc)
    else:
        results["details"] = (False, "skipped: no search hit")

    # streams for the first episode
    if details:
        _season, ep = _first_episode(details)
        if ep:
            try:
                out = src.streams(ep["data"]) or {}
                streams = out.get("streams") or []
                ok = len(streams) > 0
                first = streams[0] if streams else {}
                results["streams"] = (
                    ok,
                    "%d stream(s), first url=%s type=%s quality=%s proxy=%s"
                    % (
                        len(streams), (first.get("url") or "")[:90],
                        first.get("type"), first.get("quality"),
                        first.get("proxy"),
                    ) if ok else "0 streams (ep data=%s)" % str(ep["data"])[:80],
                )
            except Exception as exc:
                results["streams"] = (False, "exception: %s" % exc)
                if verbose:
                    traceback.print_exc()
        else:
            results["streams"] = (False, "skipped: details had no episodes")
    else:
        results["streams"] = (False, "skipped: no details")

    if verbose:
        print("== %s (%s) ==" % (src.id, src.name))
        for name, (ok, summary) in results.items():
            print("  [%s] %-14s %s" % ("PASS" if ok else "FAIL", name, summary))
        passed = sum(1 for ok, _ in results.values() if ok)
        if passed == 0:
            print("  DROPPED: every endpoint failed")
        print()
    return results


def main():
    parser = argparse.ArgumentParser(description="Live-test anime-api sources")
    parser.add_argument("--source", help="only test this source id")
    args = parser.parse_args()

    if args.source:
        src = get_source(args.source)
        if src is None:
            print("unknown source: %s" % args.source)
            return 1
        sources = [src]
    else:
        sources = list_sources()

    if not sources:
        print("no sources registered")
        return 1

    all_results = {}
    for src in sources:
        all_results[src.id] = test_source(src)

    total_pass = sum(
        1 for res in all_results.values() for ok, _ in res.values() if ok
    )
    total = sum(len(res) for res in all_results.values())
    print("TOTAL: %d/%d endpoints passed" % (total_pass, total))
    return 0 if total_pass > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
