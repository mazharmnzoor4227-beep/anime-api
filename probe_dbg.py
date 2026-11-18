import re
from urllib.parse import urlsplit
from anime_api.http import get
from bs4 import BeautifulSoup
from anime_api.sources.dramacool import (
    DramaCool, _extract_file_url, _REDIRECT_HOSTS, _MAIN_HOSTS)

dc = DramaCool()
for slug in ("the-confession-truth", "pieces-of-guilt"):
    url = "https://dramaacool.best/drama/%s/episode-1" % slug
    print("=" * 10, slug)
    try:
        resp = get(url, timeout=60)
        print("episode page:", resp.status_code, len(resp.text))
    except Exception as e:
        print("episode page FAILED:", str(e)[:120])
        continue
    soup = BeautifulSoup(resp.text, "lxml")
    urls, seen = [], set()
    for iframe in soup.select("iframe[src]"):
        src = iframe.get("src") or ""
        if src.startswith("http") and src not in seen:
            seen.add(src)
            urls.append(src)
    from anime_api.sources.dramacool import _EMBED_RE
    for href in _EMBED_RE.findall(resp.text):
        if href not in seen:
            seen.add(href)
            urls.append(href)
    print("candidate urls (%d):" % len(urls))
    for u in urls:
        print("  ", u)
    for u in urls[:5]:
        print("--- trying", u)
        cands = [u]
        parts = urlsplit(u)
        if parts.hostname in _REDIRECT_HOSTS:
            for host in _MAIN_HOSTS:
                cands.append("https://%s%s" % (host, parts.path or "/"))
        for c in cands:
            try:
                r = get(c, headers={"Referer": url}, timeout=15)
                print("   ", c[:60], "->", r.status_code, len(r.text),
                      "file:", _extract_file_url(r.text))
            except Exception as e:
                print("   ", c[:60], "-> FAILED:", str(e)[:100])
