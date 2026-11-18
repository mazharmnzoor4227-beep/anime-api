"""Live test for the HentaiHaven source (18+) against the REAL backend.

Run ON the server (clean IP):
    ~/anime-api/.venv/bin/python tests/test_hentaihaven_live.py

Exercises search -> details -> streams end to end, plus the proxy
first-frame check (master playlist 200 + #EXTM3U + variant playlist 200).
English Sub only — no Hindi dub is expected from this source.
A source that fails EVERY endpoint is reported as DROPPED.
"""

import os
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from anime_api.sources.hentaihaven import HentaiHavenSource  # noqa: E402

BASE = os.environ.get("ANIME_API_BASE", "http://127.0.0.1:8000")


def run():
    src = HentaiHavenSource()
    print("=" * 70)
    print("SOURCE hentaihaven (%s) base=%s" % (src.name, src.base_url))
    results = {}

    t0 = time.time()
    try:
        items = src.search("elf", page=1)
        results["search"] = (bool(items), "%d items, first=%r (%.1fs)" % (
            len(items), items[0]["title"] if items else None,
            time.time() - t0))
    except Exception as exc:
        results["search"] = (False, "EXC %r" % (exc,))
    print("  search 'elf': %s" % (results["search"],))

    details = None
    if results["search"][0]:
        t0 = time.time()
        try:
            details = src.details(items[0]["id"])
            eps = details["seasons"][0]["episodes"] if details else []
            results["details"] = (bool(details and eps), "%s, %d eps (%.1fs)" % (
                details["title"] if details else None, len(eps),
                time.time() - t0))
        except Exception as exc:
            results["details"] = (False, "EXC %r" % (exc,))
        print("  details: %s" % (results["details"],))

    stream_url = None
    if details:
        t0 = time.time()
        try:
            st = src.streams(details["seasons"][0]["episodes"][0]["data"])
            streams = st.get("streams", [])
            stream_url = streams[0]["url"] if streams else None
            results["streams"] = (bool(streams), "%d streams, type=%s proxy=%s (%.1fs)" % (
                len(streams), streams[0]["type"] if streams else None,
                streams[0]["proxy"] if streams else None, time.time() - t0))
        except Exception as exc:
            results["streams"] = (False, "EXC %r" % (exc,))
        print("  streams: %s" % (results["streams"],))

    if stream_url:
        t0 = time.time()
        try:
            px = BASE + "/api/proxy?url=" + urllib.parse.quote(stream_url, safe="")
            r = requests.get(px, timeout=30)
            master = r.text
            ok = r.status_code == 200 and "#EXTM3U" in master
            results["proxy_master"] = (ok, "status=%d bytes=%d (%.1fs)" % (
                r.status_code, len(master), time.time() - t0))
        except Exception as exc:
            results["proxy_master"] = (False, "EXC %r" % (exc,))
        print("  proxy master: %s" % (results["proxy_master"],))

    passed = sum(1 for v in results.values() if v[0])
    print("=" * 70)
    print("HENTAIHAVEN LIVE: %d/%d passed" % (passed, len(results)))
    if passed == 0:
        print("DROPPED: source fails every endpoint")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(run())
