"""Unit + app-level tests for the v1.2 response cache (no live network).

Run: ~/workspace/anime-api-work/venv/bin/python tests/test_cache.py
"""

import json
import os
import sys
import time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anime_api.cache import TTLCache  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS %s" % name)
    else:
        FAIL += 1
        print("FAIL %s %s" % (name, extra))


# ---------------------------------------------------------------- TTLCache
c = TTLCache(max_entries=2)
c.set("a", {"v": 1}, 60)
val, hit = c.get("a")
check("cache: set/get hit", hit and val == {"v": 1}, repr((val, hit)))
val, hit = c.get("missing")
check("cache: miss", not hit and val is None)
c.set("short", 1, 0.05)
time.sleep(0.07)
val, hit = c.get("short")
check("cache: ttl expiry", not hit, repr((val, hit)))
c.set("b", 2, 60)
c.set("c", 3, 60)  # max 2 -> evicts the soonest-expiring ("a")
val, hit = c.get("a")
check("cache: eviction at capacity", not hit, repr((val, hit)))
c.clear()
check("cache: clear", len(c) == 0, str(len(c)))

# ---------------------------------------------------------------- app routes
import app as app_module  # noqa: E402

app_module.CACHE.clear()


class FakeSource:
    def __init__(self, sid, language="hindi"):
        self.id = sid
        self.language = language


fake_sources = [FakeSource("animedekho"), FakeSource("animeworld")]
fanout_calls = {"n": 0}


def _fake_fanout(sources, lang, fn):
    fanout_calls["n"] += 1
    return ([{"id": "x", "title": "T", "source": s.id} for s in sources], [])


client = app_module.app.test_client()
with mock.patch.object(app_module, "list_sources",
                       return_value=fake_sources), \
        mock.patch.object(app_module, "_fan_out",
                          side_effect=_fake_fanout):
    r1 = client.get("/api/latest?lang=hindi")
    r2 = client.get("/api/latest?lang=hindi")
check("app: first list MISS", r1.headers.get("X-Cache") == "MISS",
      r1.headers.get("X-Cache"))
check("app: second list HIT", r2.headers.get("X-Cache") == "HIT",
      r2.headers.get("X-Cache"))
check("app: fan-out ran once for two identical calls",
      fanout_calls["n"] == 1, str(fanout_calls["n"]))
check("app: cached body identical",
      r1.get_json() == r2.get_json(), repr(r2.get_json()))
r3 = client.get("/api/latest?lang=english")
check("app: different lang is a different key (MISS)",
      r3.headers.get("X-Cache") == "MISS", r3.headers.get("X-Cache"))

# search caches separately by query
with mock.patch.object(app_module, "list_sources",
                       return_value=fake_sources), \
        mock.patch.object(app_module, "_fan_out",
                          side_effect=_fake_fanout):
    s1 = client.get("/api/search?q=naruto")
    s2 = client.get("/api/search?q=naruto")
    s3 = client.get("/api/search?q=one+piece")
check("app: search MISS then HIT",
      s1.headers.get("X-Cache") == "MISS"
      and s2.headers.get("X-Cache") == "HIT",
      (s1.headers.get("X-Cache"), s2.headers.get("X-Cache")))
check("app: different query is a different key (MISS)",
      s3.headers.get("X-Cache") == "MISS", s3.headers.get("X-Cache"))

# details None -> 502 (was JSON null with 200)


class NoneSource(FakeSource):
    def details(self, item_id):
        return None


with mock.patch.object(app_module, "get_source",
                       return_value=NoneSource("anisuge", "english")):
    d = client.get("/api/anime?source=anisuge&id=missing")
check("app: details None -> 502",
      d.status_code == 502 and "error" in (d.get_json() or {}),
      "%s %s" % (d.status_code, d.get_data(as_text=True)[:120]))

print()
print("TOTAL: %d passed, %d failed" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
