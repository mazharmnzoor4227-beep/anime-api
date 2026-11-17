"""MegaPlay extractor (shared by NineAnime, AniKoto, AniSuge, ...).

Ports MegaPlayResolver / NineAnimeMegaPlay / MegaPlayHelper from the
Raghav CloudStream extensions.

``resolve_megaplay(embed_url, referer) -> (streams, subtitles)``
where streams/subtitles use the same dict shapes as
``anime_api.sources.base.Source.streams``.

Flow: GET embed page -> stream id -> GET
``https://<host>/stream/getSourcesNew?id=<id>&type=<sub|dub>``
(fallback ``getSources``) -> ``sources.file`` (object or ``[0].file``),
else ``enc`` -> AES/CBC decrypt with seeds scraped from
``{host}/lib/newclient.min.js`` -> HMAC-sign the master URL -> parse the
master playlist into per-quality variant links (one master link when
audio-only variants are present).
"""

import base64
import hashlib
import hmac
import re
import time
from urllib.parse import urljoin, urlparse

import requests

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

_FALLBACK_KEY = "i?LMTAx0Q6,:}50U"
_FALLBACK_IV = "W0;27ToaUpl_P%'c"
_HMAC_KEY = b"MpCdnT0k3n!9f2K#xQ7vL5mR8wN1pY4s"
_SIGN_RE = re.compile(r"/([a-f0-9]{32})/([a-f0-9]{32})/")
_SEED_RE = re.compile(r'[A-Za-z]\w*="([^"]{16})",[A-Za-z]\w*="([^"]{16})"')

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": UA})


def _get(url, headers=None, timeout=30):
    r = _SESSION.get(url, headers=headers or {}, timeout=timeout)
    r.raise_for_status()
    return r


def _b64url_decode(data):
    data = data.strip().replace("-", "+").replace("_", "/")
    data += "=" * (-len(data) % 4)
    return base64.b64decode(data)


def _pad_seed(seed, length):
    b = seed.encode("utf-8", "ignore")
    if len(b) >= length:
        return b[:length]
    return b + b"\x00" * (length - len(b))


def _get_seeds(host):
    """Scrape AES key/IV seeds from {host}/lib/newclient.min.js."""
    try:
        js = _get("https://%s/lib/newclient.min.js" % host, timeout=10).text
        m = _SEED_RE.search(js)
        if m:
            return m.group(1), m.group(2)
    except Exception:
        pass
    return _FALLBACK_KEY, _FALLBACK_IV


def _decrypt_enc(enc, host):
    key_seed, iv_seed = _get_seeds(host)
    key = _pad_seed(key_seed, 32)
    iv = _pad_seed(iv_seed, 16)
    raw = _b64url_decode(enc)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded = decryptor.update(raw) + decryptor.finalize()
    unpadder = PKCS7(128).unpadder()
    plain = unpadder.update(padded) + unpadder.finalize()
    m = re.search(r'"file"\s*:\s*"([^"]+)"', plain.decode("utf-8", "ignore"))
    if not m:
        raise ValueError("decrypted MegaPlay payload has no file field")
    return m.group(1)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def sign_url(url):
    """HMAC-sign a CDN URL (only if it matches /<md5>/<md5>/).

    expires = now + 7 days; payload = "<expires>|<id1>/<id2>" (lowercased);
    token = b64url(payload) + "." + b64url(HmacSHA256(payload)).
    Returns the URL unchanged when it does not match.
    """
    m = _SIGN_RE.search(url)
    if not m:
        return url
    expires = int(time.time()) + 7 * 24 * 3600
    payload = "%d|%s/%s" % (expires, m.group(1), m.group(2))
    payload = payload.lower()
    sig = hmac.new(_HMAC_KEY, payload.encode("utf-8"), hashlib.sha256).digest()
    token = "%s.%s" % (_b64url(payload.encode("utf-8")), _b64url(sig))
    sep = "&" if "?" in url else "?"
    return "%s%stoken=%s" % (url, sep, token)


def _parse_master(master_text, master_url, audio_type, host):
    """Parse an HLS master playlist into stream dicts.

    If audio-only variants are present (#EXT-X-MEDIA:TYPE=AUDIO) emit one
    master link with ?t=sub|dub; else one signed link per variant.
    """
    headers = {"User-Agent": UA, "Referer": "https://%s/" % host}
    signed_master = sign_url(master_url)
    lines = master_text.splitlines()
    variants = []  # (quality:int|None, uri:str)
    has_audio = False
    for i, line in enumerate(lines):
        line = line.strip()
        if line.startswith("#EXT-X-MEDIA") and "TYPE=AUDIO" in line:
            has_audio = True
        if line.startswith("#EXT-X-STREAM-INF:"):
            quality = None
            m = re.search(r"RESOLUTION=\d+x(\d+)", line)
            if m:
                quality = int(m.group(1))
            uri = None
            for j in range(i + 1, len(lines)):
                cand = lines[j].strip()
                if cand and not cand.startswith("#"):
                    uri = cand
                    break
            if uri:
                variants.append((quality, urljoin(master_url, uri)))
    if has_audio:
        quality = max((q for q, _ in variants if q), default=None)
        url = signed_master
        sep = "&" if "?" in url else "?"
        url = "%s%st=%s" % (url, sep, audio_type)
        return [{"name": "MegaPlay", "url": url, "quality": quality,
                 "type": "m3u8", "headers": headers, "proxy": False}]
    if not variants:
        return [{"name": "MegaPlay", "url": signed_master, "quality": None,
                 "type": "m3u8", "headers": headers, "proxy": False}]
    streams = []
    for quality, uri in variants:
        name = "MegaPlay %dp" % quality if quality else "MegaPlay"
        streams.append({"name": name, "url": sign_url(uri), "quality": quality,
                        "type": "m3u8", "headers": headers, "proxy": False})
    streams.sort(key=lambda s: -(s["quality"] or 0))
    return streams


def resolve_megaplay(embed_url, referer):
    """Resolve a MegaPlay-family embed URL.

    Returns ``(streams, subtitles)`` using the Source.streams() dict shapes.
    Raises on failure (callers should catch per-server).
    """
    parsed = urlparse(embed_url)
    host = parsed.netloc
    page_referer = referer or ("https://%s/" % host)
    page = _get(embed_url, headers={"User-Agent": UA, "Referer": page_referer})
    html = page.text

    stream_id = None
    m = re.search(r'data-id=["\'](\d+)', html)
    if not m:
        m = re.search(r'data-realid=["\'](\d+)', html)
    if not m:
        m = re.search(r"/stream/s-\d+/(\d+)/", embed_url)
    if m:
        stream_id = m.group(1)
    if not stream_id:
        raise ValueError("MegaPlay: no stream id found in %s" % embed_url)

    if re.search(r"/(dub|sub)(?:[/?#]|$)", embed_url):
        audio_type = re.search(r"/(dub|sub)(?:[/?#]|$)", embed_url).group(1)
    else:
        m = re.search(r'type\s*:\s*["\'](dub|sub)["\']', html)
        audio_type = m.group(1) if m else "sub"

    # Try the page host, then an alternate host from data-domain.
    hosts = [host]
    m = re.search(r'data-domain=["\']([^"\']+)["\']', html)
    if m and m.group(1) not in hosts:
        hosts.append(m.group(1))

    last_error = None
    for try_host in hosts:
        for endpoint in ("getSourcesNew", "getSources"):
            url = ("https://%s/stream/%s?id=%s&type=%s"
                   % (try_host, endpoint, stream_id, audio_type))
            try:
                resp = _get(url, headers={
                    "User-Agent": UA, "Accept": "*/*",
                    "X-Requested-With": "XMLHttpRequest",
                    "Origin": "https://%s" % try_host,
                    "Referer": embed_url,
                }, timeout=15)
                data = resp.json()
            except Exception as e:
                last_error = e
                continue
            file_url = None
            sources = data.get("sources")
            if isinstance(sources, dict):
                file_url = sources.get("file")
            elif isinstance(sources, list) and sources:
                first = sources[0]
                if isinstance(first, dict):
                    file_url = first.get("file")
                elif isinstance(first, str):
                    file_url = first
            if not file_url and data.get("enc"):
                file_url = _decrypt_enc(data["enc"], try_host)
            if not file_url:
                last_error = ValueError("MegaPlay: no sources.file or enc in %s" % url)
                continue
            # Legacy CDN rewrite: serve from this stream's own origin.
            if file_url.startswith("https://cdn.imgnex.top/anime"):
                file_url = "https://%s%s" % (try_host, file_url[len("https://cdn.imgnex.top/anime"):])
            subtitles = []
            for track in data.get("tracks") or []:
                if isinstance(track, dict) and track.get("kind") in ("captions", "subtitles"):
                    if track.get("file"):
                        subtitles.append({"label": track.get("label") or "English",
                                          "url": track["file"]})
            headers = {"User-Agent": UA, "Referer": "https://%s/" % try_host}
            signed = sign_url(file_url)
            try:
                # The CDN rejects the master fetch unless Referer is the
                # MegaPlay host itself (any other Referer -> 403).
                master = _get(signed, headers={
                    "User-Agent": UA, "Referer": "https://%s/" % try_host},
                    timeout=15).text
                if "#EXT-X-STREAM-INF" in master or "#EXTM3U" in master:
                    return _parse_master(master, file_url, audio_type, try_host), subtitles
            except Exception:
                pass
            return [{"name": "MegaPlay", "url": signed, "quality": None,
                     "type": "m3u8" if ".m3u8" in file_url else "video",
                     "headers": headers, "proxy": False}], subtitles
    raise ValueError("MegaPlay: all getSources attempts failed for %s (%s)"
                     % (embed_url, last_error))
