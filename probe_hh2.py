"""Live probe 2: search, video page, episode list, full stream flow."""
import base64
import json
import re

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"}
S = requests.Session()
S.headers.update(UA)

# --- search
r = S.get("https://hentaihaven.com/", params={"s": "maid"}, timeout=30)
print("search maid:", r.status_code, len(r.text))
slugs = sorted(set(re.findall(r"https://hentaihaven\.com/video/([a-z0-9\-]+)/?", r.text)))
print("search slugs:", len(slugs), slugs[:5])
open("/tmp/hh_search.html", "w").write(r.text)

# --- video page (first search result)
slug = slugs[0]
url = "https://hentaihaven.com/video/%s/" % slug
r = S.get(url, timeout=30)
print("video page:", slug, r.status_code, len(r.text))
open("/tmp/hh_video.html", "w").write(r.text)
m = re.search(r'chapter-heading" class="h3">([^<]+)', r.text)
print("title:", m.group(1).strip() if m else None)
# episode links
eps = sorted(set(re.findall(r"https://hentaihaven\.com/video/%s/episode-(\d+)/?" % re.escape(slug), r.text)))
print("episodes:", eps[:10])
m = re.search(r'([^"]+/wp-content/plugins/player-logic/player\.php[^"]+)', r.text)
print("player.php on series page:", m.group(1)[:160] if m else None)

# --- episode page
ep_url = "https://hentaihaven.com/video/%s/episode-1" % slug
r = S.get(ep_url, timeout=30)
print("episode page:", r.status_code, len(r.text))
open("/tmp/hh_ep.html", "w").write(r.text)
m = re.search(r'([^"]+/wp-content/plugins/player-logic/player\.php[^"]+)', r.text)
embed = m.group(1) if m else None
print("player.php:", embed[:200] if embed else None)
if not embed:
    raise SystemExit("no embed found")

# --- embed page -> token
r = S.get(embed, timeout=30)
print("embed page:", r.status_code, len(r.text))
open("/tmp/hh_embed.html", "w").write(r.text)
m = re.search(r'<meta[^>]*name=["\']x-secure-token["\'][^>]*content=["\']([^"\']+)["\']', r.text) or \
    re.search(r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']x-secure-token["\']', r.text)
print("token meta found:", bool(m))
if m:
    token = m.group(1)
    print("token head:", token[:40])
    cipher = token[len("sha512-"):] if token.startswith("sha512-") else token
    CIPHER_MAP = bytes.maketrans(
        b"NOPQRSTUVWXYZABCDEFGHIJKLMnopqrstuvwxyzabcdefghijklm",
        b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")

    def decipher(s):
        b = s.encode("ascii")
        for _ in range(3):
            b = b.translate(CIPHER_MAP)
            b = base64.b64decode(b)
        return b.decode("ascii")

    interim = json.loads(decipher(cipher))
    print("interim keys:", list(interim.keys()))
    print("uri:", interim.get("uri"))
    print("en head:", str(interim.get("en"))[:40], "iv:", interim.get("iv"))

    # --- api.php POST (multipart like the plugin)
    r = S.post("https:" + interim["uri"].rstrip("/") + "/api.php",
               files={"action": (None, "zarat_get_data_player_ajax"),
                      "a": (None, interim["en"]),
                      "b": (None, interim["iv"])},
               timeout=30)
    print("api.php:", r.status_code, len(r.text))
    data = r.json()
    print("api status:", data.get("status"))
    src = data["data"]["sources"][0]["src"]
    print("m3u8 src:", src[:160])
    print("isOctopus:", data["data"].get("isOctopus"))
    r2 = S.get(src, timeout=30)
    print("m3u8 fetch:", r2.status_code, len(r2.text))
    print(r2.text[:400])
