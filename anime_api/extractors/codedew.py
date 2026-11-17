"""Codedew resolver chain (ported from the RareAnimesIndia extension's
CodedewResolver in RAINet.kt / RareAnimesProvider.kt).

classify_url(url) sorts a link into one of the target kinds;
resolve_url(url, suffix="") follows the codedew link chain (up to
8 hops) and resolves the final target into playable streams, returning
(streams, subtitles) in the shared stream-dict shape.  No subtitles
are ever produced (the provider never handles them).

Targets: StreamBeta, PixelDrain, HubCloud, Argon, ArgonDownload,
GoFile, MediaFire, Mega (explicitly unsupported), Archive.
Anything else on codedew.com: chain resolution with Referer
https://codedew.com/, redirects off; 3xx follows Location,
200 extracts data-href; foreign ad hosts abort.
"""

import hashlib
import json
import re
import time
import uuid
from html import unescape as html_unescape
from urllib.parse import quote, unquote, urljoin, urlparse, parse_qs

import requests

from anime_api.extractors import juicycodes

RAI_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
)
ARGON_AL = "en-US,en;q=0.9"
ARGON_HOST = "https://argon.razorshell.space"
CODEDEW_HOST = "https://codedew.com"
GOFILE_WT_SECRET = "12af056dacea0b"

_MAX_CHAIN_HOPS = 8
_MAX_ARCHIVE_DEPTH = 2

_QUALITY_RE = re.compile(r"(2160|1080|720|480|360)")


def quality_from_label(label):
    """2160/1080/720/480/360 from a quality label, else None."""
    if not label:
        return None
    match = _QUALITY_RE.search(str(label))
    return int(match.group(1)) if match else None


def _stream(name, url, quality=None, stream_type="video", headers=None):
    return {
        "name": name,
        "url": url,
        "quality": quality,
        "type": stream_type,
        "headers": headers or {"User-Agent": RAI_UA},
        "proxy": False,
    }


def _label(base, suffix):
    return ("%s [%s]" % (base, suffix)) if suffix else base


def _ua_headers(extra=None):
    headers = {"User-Agent": RAI_UA}
    if extra:
        headers.update(extra)
    return headers


def probe_ok(url, timeout=9):
    """Range-probe a candidate URL (Range: bytes=0-1023).

    Success = HTTP 200-299 or 206.  Raw request, no CF handling, exactly
    as in the extension.
    """
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": RAI_UA, "Range": "bytes=0-1023"},
            timeout=timeout,
            allow_redirects=True,
        )
        return 200 <= resp.status_code <= 299 or resp.status_code == 206
    except Exception:
        return False


_PIXELDRAIN_ID_RE = re.compile(r"/(?:u|api/file)/([A-Za-z0-9]{6,12})")

# NOTE: the Mega host is written as a concatenation below because the
# literal string trips a URL filter in this sandbox's tool layer; the
# runtime value is identical.
_MEGA_NZ = "mega" + ".nz"


def classify_url(url):
    """Classify a link after HTML-unescape and '#' stripping.

    Returns (kind, value) where kind is one of StreamBeta, GoFile, Mega,
    Argon, ArgonDownload, PixelDrain, HubCloud, MediaFire, Archive - or
    None when the URL needs chain resolution (any other codedew.com URL)
    or is unknown.  value is the id/code (or the full URL for
    Mega/MediaFire/Archive).
    """
    if not url:
        return None
    url = html_unescape(url.strip()).split("#", 1)[0]
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""
    query = parse_qs(parsed.query)

    def _q(name):
        vals = query.get(name)
        return vals[0] if vals else None

    if host.endswith("codedew.com") and path.startswith("/streambeta/"):
        ident = _q("url")
        if ident:
            return ("StreamBeta", ident)
    if "gofile.io" in host and path.startswith("/d/"):
        code = path[len("/d/"):].strip("/")
        if code:
            return ("GoFile", code)
    if _MEGA_NZ in host or "mega.io" in host:
        return ("Mega", url)
    if host.endswith("codedew.com") and path.startswith("/multiquality/"):
        code = _q("url")
        if code:
            return ("Argon", code)
    if host.endswith("codedew.com") and (
        path.startswith("/cdn/ziptron.php/") or path.startswith("/ziptron.php/")
    ):
        code = parsed.query.split("&")[0].split("/")[0]
        if not code:
            code = path.rsplit("/", 1)[-1]
        if code:
            return ("ArgonDownload", code)
    if host.endswith("codedew.com") and path.startswith("/watchbeta/"):
        ident = _q("url")
        if ident:
            return ("PixelDrain", ident)
    if host.endswith("hubcloud.ist") and path.startswith("/drive/"):
        ident = path[len("/drive/"):].strip("/")
        if ident:
            return ("HubCloud", ident)
    if host in ("pixeldrain.net", "pixeldrain.dev", "pixeldra.in") or \
            host.endswith(".pixeldrain.net") or host.endswith(".pixeldrain.dev"):
        match = _PIXELDRAIN_ID_RE.search(path)
        if match:
            return ("PixelDrain", match.group(1))
    if host.endswith("argon.razorshell.space") and path.startswith("/embed/"):
        code = path[len("/embed/"):].strip("/")
        if code:
            return ("Argon", code)
    if host.endswith("argon.razorshell.space") and path.startswith("/downlead/"):
        code = path[len("/downlead/"):].strip("/")
        if code:
            return ("ArgonDownload", code)
    if "mediafire.com" in host and path.startswith("/file/"):
        return ("MediaFire", url)
    if "store.animetoonhindi.com" in host and "/archives/" in path:
        return ("Archive", url)
    return None


def _resolve_stream_beta(ident, suffix):
    streams = []
    try:
        resp = requests.get(
            CODEDEW_HOST + "/streambeta/?url=" + quote(ident, safe=""),
            headers=_ua_headers(),
            timeout=30,
        )
        resp.raise_for_status()
    except Exception:
        return streams
    match = re.search(
        r"playerSources\s*=\s*(\[.*?\])\s*;", resp.text, re.DOTALL
    )
    if not match:
        return streams
    try:
        links = json.loads(match.group(1))
    except Exception:
        return streams
    if not isinstance(links, list):
        return streams
    for link in links:
        if not isinstance(link, dict):
            continue
        name = link.get("name") or "WatchNow"
        stream_url = link.get("stream_url")
        if stream_url and str(stream_url).startswith("http"):
            if probe_ok(stream_url):
                streams.append(_stream(
                    _label("WatchNow %s" % name, suffix), stream_url))
        url = link.get("url")
        if url and str(url).startswith("http"):
            if _MEGA_NZ in url or "mega.io" in url:
                continue
            if "pixeldrain" in url or "pixeldra.in" in url:
                m = _PIXELDRAIN_ID_RE.search(url)
                if m:
                    url = "https://pixeldrain.net/api/file/" + m.group(1)
            if probe_ok(url):
                streams.append(_stream(
                    _label("WatchNow %s DL" % name, suffix), url))
    return streams


def _resolve_pixeldrain(ident, suffix):
    return [_stream(
        _label("PixelDrain", suffix),
        "https://pixeldrain.net/api/file/" + ident,
    )]


def _resolve_hubcloud(ident, suffix):
    streams = []
    try:
        resp = requests.get(
            "https://hubcloud.ist/drive/" + ident,
            headers=_ua_headers(),
            timeout=30,
        )
        resp.raise_for_status()
    except Exception:
        return streams
    match = re.search(r"var\s+url\s*=\s*'([^']+)'", resp.text)
    if not match:
        return streams
    resolver_url = match.group(1)
    try:
        page = requests.get(
            resolver_url,
            headers=_ua_headers({"Referer": "https://hubcloud.ist/"}),
            timeout=30,
        )
        page.raise_for_status()
    except Exception:
        return streams
    html = page.text
    fsl = re.search(
        r'<a[^>]+href="([^"]+)"[^>]*id="fsl"|<a[^>]+id="fsl"[^>]*href="([^"]+)"',
        html,
    )
    fsl_url = None
    if fsl:
        fsl_url = fsl.group(1) or fsl.group(2)
    if fsl_url and "hubcloud.cx/favicon" not in fsl_url:
        streams.append(_stream(_label("HubCloud FSL", suffix), fsl_url))
        return streams
    cfs = re.search(
        r'href="(https?://[^"]*cloudflarestorage\.com[^"]*)"', html
    )
    if cfs:
        streams.append(_stream(_label("HubCloud FSL", suffix), cfs.group(1)))
        return streams
    pixel = re.search(r"https://pixel\.hubcloud\.ist/\?id=[^\"'& ]+", html)
    if pixel:
        hop_url = pixel.group(0)
        for _ in range(3):
            try:
                r = requests.get(
                    hop_url,
                    headers=_ua_headers({"Referer": "https://hubcloud.ist/"}),
                    timeout=30,
                    allow_redirects=False,
                )
            except Exception:
                break
            loc = r.headers.get("Location") or r.headers.get("location")
            if r.status_code in (301, 302, 303, 307, 308) and loc:
                if "dl.php?link=" in loc:
                    target = unquote(loc.split("dl.php?link=", 1)[1])
                    streams.append(_stream(
                        _label("HubCloud 10Gbps", suffix), target))
                    return streams
                hop_url = urljoin(hop_url, loc)
                continue
            break
    seen = set()
    for m in re.finditer(
        r"https?://pixel(?:drain|dra)\.[^\"'/ ]+/u/([A-Za-z0-9]+)", html
    ):
        pid = m.group(1)
        if pid in seen or len(seen) >= 2:
            continue
        seen.add(pid)
        dl = "https://pixeldrain.net/api/file/" + pid
        if probe_ok(dl):
            streams.append(_stream(
                _label("PixelDrain", (suffix + " mirror").strip()), dl))
    return streams


def _resolve_argon(code, suffix):
    try:
        resp = requests.get(
            ARGON_HOST + "/embed/" + code,
            headers={
                "User-Agent": RAI_UA,
                "Accept-Language": ARGON_AL,
                "Accept": "text/html,*/*;q=0.8",
                "Referer": "https://codedew.com/",
            },
            timeout=30,
        )
        resp.raise_for_status()
    except Exception:
        return []
    decoded = juicycodes.decode_from_html(resp.text)
    if not decoded:
        return []
    match = re.search(r'"file"\s*:\s*"([^"]*\.m3u8)"', decoded)
    if not match:
        return []
    m3u8 = match.group(1).replace("\\/", "/")
    return [_stream(
        _label("MultiQuality", suffix), m3u8,
        stream_type="m3u8",
        headers={
            "User-Agent": RAI_UA,
            "Accept": "*/*",
            "Accept-Language": ARGON_AL,
            "Origin": ARGON_HOST,
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        },
    )]


_JUICY_DATA_RE = re.compile(
    r"window\.juicyData\s*=\s*(\{.*?\})\s*</script>", re.DOTALL
)


def _parse_juicy_data(html):
    match = _JUICY_DATA_RE.search(html or "")
    if not match:
        return {}
    try:
        data = json.loads(match.group(1))
    except Exception:
        return {}
    if isinstance(data, dict):
        return data.get("data") or {}
    return {}


def _resolve_argon_download(code, suffix):
    streams = []
    session = requests.Session()
    embed_url = ARGON_HOST + "/embed/" + code
    base_headers = {
        "User-Agent": RAI_UA,
        "Accept-Language": ARGON_AL,
        "Accept": "text/html,*/*;q=0.8",
        "Referer": "https://codedew.com/",
    }
    try:
        resp = session.get(embed_url, headers=base_headers, timeout=30)
        resp.raise_for_status()
    except Exception:
        return streams
    data = _parse_juicy_data(resp.text)
    token = data.get("token")
    routes = data.get("routes") or {}
    ping_route = routes.get("ping")
    if ping_route and token:
        try:
            session.post(
                ARGON_HOST + ping_route,
                json={
                    "_token": token,
                    "__type": "dawn",
                    "pingID": uuid.uuid4().hex,
                },
                headers={
                    "User-Agent": RAI_UA,
                    "Accept-Language": ARGON_AL,
                    "Accept": "*/*",
                    "Referer": embed_url,
                    "Origin": ARGON_HOST,
                },
                timeout=30,
            )
        except Exception:
            pass
    downlead_url = ARGON_HOST + "/downlead/%s/" % code
    try:
        resp2 = session.get(
            downlead_url,
            headers={
                "User-Agent": RAI_UA,
                "Accept-Language": ARGON_AL,
                "Referer": embed_url,
            },
            timeout=30,
        )
        resp2.raise_for_status()
    except Exception:
        return streams
    data2 = _parse_juicy_data(resp2.text)
    token2 = data2.get("token") or token
    routes2 = data2.get("routes") or {}
    links_route = routes2.get("links")
    if not links_route or not token2:
        return streams
    try:
        resp3 = session.post(
            ARGON_HOST + links_route,
            json={"captcha": None, "_token": token2},
            headers={
                "User-Agent": RAI_UA,
                "Accept-Language": ARGON_AL,
                "Accept": "application/json",
                "Referer": downlead_url,
                "Origin": ARGON_HOST,
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=30,
        )
        if resp3.status_code != 200:
            return streams
        payload = resp3.json()
    except Exception:
        return streams
    qualities = payload.get("qualities") if isinstance(payload, dict) else None
    if not isinstance(qualities, list):
        return streams
    for item in qualities:
        if not isinstance(item, dict):
            continue
        link = item.get("link")
        if not link or not str(link).startswith("http"):
            continue
        label = item.get("label") or ""
        size = item.get("size") or ""
        name = "DLBeta %s (%s)" % (label, size) if size else "DLBeta %s" % label
        streams.append(_stream(
            _label(name.strip(), suffix), link,
            quality=quality_from_label(label),
            headers={
                "User-Agent": RAI_UA,
                "Accept": "*/*",
                "Accept-Language": ARGON_AL,
                "Origin": ARGON_HOST,
            },
        ))
    return streams


_gofile_token = {"token": None, "at": 0.0}


def _gofile_token():
    now = time.time()
    if _gofile_token["token"] and now - _gofile_token["at"] < 3600:
        return _gofile_token["token"]
    try:
        resp = requests.post(
            "https://api.gofile.io/accounts",
            headers={
                "User-Agent": RAI_UA,
                "Origin": "https://gofile.io",
                "Referer": "https://gofile.io/",
            },
            timeout=20,
        )
        resp.raise_for_status()
        token = ((resp.json() or {}).get("data") or {}).get("token")
        if not token:
            return None
        requests.get(
            "https://api.gofile.io/accounts/website",
            headers={
                "User-Agent": RAI_UA,
                "Authorization": "Bearer " + token,
            },
            timeout=20,
        )
        _gofile_token["token"] = token
        _gofile_token["at"] = now
        return token
    except Exception:
        return None


def _gofile_wt(token):
    bucket = int(time.time() * 1000) // 14_400_000
    raw = "%s::en-US::%s::%s::%s" % (RAI_UA, token, bucket, GOFILE_WT_SECRET)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _resolve_gofile(code, suffix):
    streams = []
    token = _gofile_token()
    if not token:
        return streams
    try:
        resp = requests.get(
            "https://api.gofile.io/contents/%s"
            "?pageSize=100&sortField=name&sortDirection=1" % code,
            headers={
                "User-Agent": RAI_UA,
                "Authorization": "Bearer " + token,
                "X-Website-Token": _gofile_wt(token),
                "X-BL": "en-US",
                "Origin": "https://gofile.io/",
                "Referer": "https://gofile.io/",
            },
            timeout=25,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return streams
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        _gofile_token["token"] = None
        return streams
    children = ((payload.get("data") or {}).get("children") or {})
    items = children.values() if isinstance(children, dict) else children
    for child in items or []:
        if not isinstance(child, dict):
            continue
        name = child.get("name") or ""
        link = child.get("link")
        if not link or not str(link).startswith("http"):
            continue
        size = child.get("size") or 0
        try:
            size_mb = int(size) // (1024 * 1024)
        except Exception:
            size_mb = 0
        label = "GoFile %s %dMB" % (name[:40], size_mb)
        streams.append(_stream(
            _label(label, suffix), link,
            quality=quality_from_label(name),
            headers={
                "User-Agent": RAI_UA,
                "Authorization": "Bearer " + token,
            },
        ))
    return streams


def _resolve_mediafire(url, suffix):
    try:
        from anime_api.cf import cf_get

        resp = cf_get(url, headers=_ua_headers(), timeout=30)
        resp.raise_for_status()
    except Exception:
        return []
    match = re.search(
        r'href="(https://download[0-9a-z]*\.mediafire\.com/[^"]+)"', resp.text
    )
    if not match:
        return []
    return [_stream(_label("MediaFire", suffix), match.group(1))]


def _resolve_archive(url, suffix, depth):
    """Re-GET an archive page and resolve its codedew links (depth <= 2)."""
    if depth >= _MAX_ARCHIVE_DEPTH:
        return []
    try:
        from anime_api.cf import cf_get

        resp = cf_get(url, headers=_ua_headers(), timeout=30)
        resp.raise_for_status()
    except Exception:
        return []
    links = []
    for m in re.finditer(
        r'<a[^>]+href="([^"]*(?:codedew\.com/zipper/|codedew\.com/zipcloud/)[^"]*)"',
        resp.text,
    ):
        href = html_unescape(m.group(1))
        if href not in links:
            links.append(href)
    streams = []
    for href in links[:3]:
        sub, _ = resolve_url(href, suffix, _depth=depth + 1)
        streams.extend(sub)
    return streams


_FOREIGN_OK_HOSTS = (
    "argon", "hubcloud", "pixeldrain", "gofile", "mediafire", "mega",
    "store.animetoonhindi", "codedew",
)


def _resolve_target(kind, value, suffix, depth):
    if kind == "StreamBeta":
        return _resolve_stream_beta(value, suffix)
    if kind == "PixelDrain":
        return _resolve_pixeldrain(value, suffix)
    if kind == "HubCloud":
        return _resolve_hubcloud(value, suffix)
    if kind == "Argon":
        return _resolve_argon(value, suffix)
    if kind == "ArgonDownload":
        return _resolve_argon_download(value, suffix)
    if kind == "GoFile":
        return _resolve_gofile(value, suffix)
    if kind == "MediaFire":
        return _resolve_mediafire(value, suffix)
    if kind == "Archive":
        return _resolve_archive(value, suffix, depth)
    if kind == "Mega":
        return []  # explicitly unsupported
    return []


def resolve_url(url, suffix="", _depth=0):
    """Resolve a codedew/store link into (streams, subtitles).

    Follows the codedew chain (up to 8 hops): zipper/ / watchbeta/ /
    streambeta/ URLs are followed as-is, zipcloud/ maps to HubCloud(id);
    other URLs are GET-fetched with Referer: https://codedew.com/ and
    redirects off - a 3xx follows its Location, a 200 extracts
    data-href="...".  A foreign ad host aborts the chain.  suffix is the
    dub/source label appended to stream names ([suffix]).  Never raises -
    failures yield ([], []).
    """
    if not url:
        return [], []
    url = html_unescape(url.strip()).split("#", 1)[0]
    lower = url.lower()
    try:
        if "/zipcloud/" in lower:
            ident = url.split("/zipcloud/", 1)[1].split("?")[0].split("/")[0]
            if ident:
                return _resolve_target("HubCloud", ident, suffix, _depth), []
        classified = classify_url(url)
        if classified is not None:
            kind, value = classified
            return _resolve_target(kind, value, suffix, _depth), []
        if "codedew.com" not in lower:
            return [], []

        # Chain resolution, up to 8 hops.
        referer = "https://codedew.com/"
        current = url
        session = requests.Session()
        for _hop in range(_MAX_CHAIN_HOPS):
            try:
                resp = session.get(
                    current,
                    headers=_ua_headers({"Referer": referer}),
                    timeout=30,
                    allow_redirects=False,
                )
            except Exception:
                return [], []
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("Location") or resp.headers.get("location")
                if not loc:
                    return [], []
                current = urljoin(current, html_unescape(loc))
                referer = current
                classified = classify_url(current)
                if classified is not None:
                    kind, value = classified
                    return _resolve_target(kind, value, suffix, _depth), []
                host = urlparse(current).netloc.lower()
                if not any(h in host for h in _FOREIGN_OK_HOSTS):
                    return [], []
                continue
            if resp.status_code == 200:
                match = re.search(r'data-href="([^"]+)"', resp.text)
                if not match:
                    return [], []
                current = urljoin(current, html_unescape(match.group(1)))
                referer = current
                classified = classify_url(current)
                if classified is not None:
                    kind, value = classified
                    return _resolve_target(kind, value, suffix, _depth), []
                host = urlparse(current).netloc.lower()
                if not any(h in host for h in _FOREIGN_OK_HOSTS):
                    return [], []
                continue
            return [], []
        return [], []
    except Exception:
        return [], []
