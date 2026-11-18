"""Live probe of hentaihaven.com from the server (read-only)."""
import base64
import json
import re

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"}
S = requests.Session()
S.headers.update(UA)

r = S.get("https://hentaihaven.com/", timeout=30)
print("home:", r.status_code, len(r.text))
open("/tmp/hh_home.html", "w").write(r.text)
# search form?
m = re.search(r"<form[^>]*action=\"([^\"]+)\"[^>]*>", r.text)
print("search form action:", m.group(1) if m else None)
print("search input name:",
      re.search(r"<input[^>]*name=\"([^\"]+)\"[^>]*>", r.text).group(1)
      if re.search(r"<input[^>]*name=\"([^\"]+)\"[^>]*>", r.text) else None)
# video links
links = sorted(set(re.findall(r"https://hentaihaven\.com/video/([a-z0-9\-]+)/?", r.text)))
print("video slugs on home:", len(links), links[:5])
# card structure sample
m = re.search(r"(<a[^>]*href=\"https://hentaihaven\.com/video/[^\"]+\"[^>]*>.*?</a>)",
              r.text, re.S)
print("sample card:", (m.group(1)[:300] if m else None))
