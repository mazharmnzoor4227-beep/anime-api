"""Flask app for anime-api (scaffold-owned).

Routes (all JSON, CORS enabled) — see INTERFACE.md and README.md:
  GET /health
  GET /api/sources
  GET /api/search?q=&lang=&source=&page=1
  GET /api/trending|popular|latest?lang=&source=&page=1
  GET /api/anime?source=&id=
  GET /api/streams?source=&data=
  GET /api/proxy?url=&ua=&referer=   (Range-capable passthrough)
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from flask import Flask, Response, jsonify, request, stream_with_context

from anime_api.config import FANOUT_TIMEOUT_SECONDS, HOST, PORT
from anime_api.sources import get_source, list_sources

app = Flask(__name__)

_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
}
_FORWARD_HEADERS = {
    "content-type", "content-length", "content-range", "accept-ranges",
    "content-disposition", "cache-control", "expires", "last-modified",
    "etag",
}


@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    return resp


def _error(message, status, source=None):
    body = {"error": str(message)}
    if source:
        body["source"] = source
    return jsonify(body), status


def _lang_sources(lang):
    """Sources matching a lang filter (hindi|english|japanese|all)."""
    lang = (lang or "all").lower()
    sources = list_sources()
    if lang == "hindi":
        return [s for s in sources if s.language == "hindi"]
    if lang == "english":
        return [s for s in sources if s.language == "english"]
    if lang == "japanese":
        # Japanese audio + subtitles == english sources that offer "sub".
        # Audio is per-item, so keep all english sources and filter items
        # after the fan-out (see _fan_out).
        return [s for s in sources if s.language == "english"]
    return sources  # "all" or anything else


def _fan_out(sources, lang, fn):
    """Run fn(source) in parallel; return (items, errors).

    A source that raises, or is still running when the fan-out timeout
    expires, is recorded in ``errors`` — it never fails the whole request.
    """
    items, errors = [], []
    if not sources:
        return items, errors
    pool = ThreadPoolExecutor(max_workers=max(1, len(sources)))
    futures = {pool.submit(fn, s): s for s in sources}
    try:
        for fut in as_completed(futures, timeout=FANOUT_TIMEOUT_SECONDS):
            src = futures[fut]
            try:
                result = fut.result()
                if isinstance(result, list):
                    items.extend(result)
            except Exception as exc:  # noqa: BLE001 - one source must not kill the rest
                errors.append({"source": src.id, "error": str(exc)})
    except TimeoutError:
        # as_completed raises once the timeout elapses with futures unfinished.
        pass
    for fut, src in futures.items():
        if not fut.done():
            errors.append({
                "source": src.id,
                "error": "timeout after %ss" % FANOUT_TIMEOUT_SECONDS,
            })
    # Do not block the response on still-running source threads; pending
    # (not yet started) futures are cancelled, running ones finish alone.
    pool.shutdown(wait=False, cancel_futures=True)
    # Sites repeat cards (same title twice in one row); dedupe by
    # (source, id) keeping first occurrence so clients never see the
    # same item twice in one list.
    seen = set()
    unique = []
    for it in items:
        key = (it.get("source"), it.get("id"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(it)
    items = unique
    if (lang or "all").lower() == "japanese":
        items = [it for it in items if "sub" in (it.get("audio") or [])]
    return items, errors


def _page_param():
    try:
        return max(1, int(request.args.get("page", "1")))
    except ValueError:
        return 1


@app.route("/health")
def health():
    return jsonify({"ok": True, "sources": [s.id for s in list_sources()]})


@app.route("/api/sources")
def api_sources():
    return jsonify([
        {"id": s.id, "name": s.name, "language": s.language}
        for s in list_sources()
    ])


@app.route("/api/search")
def api_search():
    query = (request.args.get("q") or "").strip()
    if not query:
        return _error("missing ?q=", 400)
    lang = request.args.get("lang", "all")
    source_param = request.args.get("source", "all")
    page = _page_param()
    sources = _lang_sources(lang)
    if source_param != "all":
        src = get_source(source_param)
        if src is None:
            return _error("unknown source: %s" % source_param, 404,
                          source=source_param)
        sources = [s for s in sources if s.id == src.id]
        if lang == "all":
            sources = [src]
    items, errors = _fan_out(
        sources, lang, lambda s: s.search(query, page=page)
    )
    return jsonify({"results": items, "errors": errors})


def _home_route(section):
    lang = request.args.get("lang", "all")
    source_param = request.args.get("source", "all")
    page = _page_param()
    sources = _lang_sources(lang)
    if source_param != "all":
        src = get_source(source_param)
        if src is None:
            return _error("unknown source: %s" % source_param, 404,
                          source=source_param)
        sources = [s for s in sources if s.id == src.id]
        if lang == "all":
            sources = [src]
    items, errors = _fan_out(
        sources, lang, lambda s: s.home(section, page=page)
    )
    return jsonify({"results": items, "errors": errors})


@app.route("/api/trending")
def api_trending():
    return _home_route("trending")


@app.route("/api/popular")
def api_popular():
    return _home_route("popular")


@app.route("/api/latest")
def api_latest():
    return _home_route("latest")


@app.route("/api/anime")
def api_anime():
    source_param = request.args.get("source") or ""
    item_id = request.args.get("id") or ""
    if not source_param or not item_id:
        return _error("missing ?source= or ?id=", 400)
    src = get_source(source_param)
    if src is None:
        return _error("unknown source: %s" % source_param, 404,
                      source=source_param)
    try:
        result = src.details(item_id)
    except Exception as exc:  # noqa: BLE001
        return _error(str(exc), 502, source=source_param)
    if isinstance(result, dict) and result.get("error"):
        return _error(result["error"], 502, source=source_param)
    return jsonify(result)


@app.route("/api/streams")
def api_streams():
    source_param = request.args.get("source") or ""
    data = request.args.get("data") or ""
    if not source_param or not data:
        return _error("missing ?source= or ?data=", 400)
    src = get_source(source_param)
    if src is None:
        return _error("unknown source: %s" % source_param, 404,
                      source=source_param)
    try:
        result = src.streams(data)
    except Exception as exc:  # noqa: BLE001
        return _error(str(exc), 502, source=source_param)
    if isinstance(result, dict) and result.get("error"):
        return _error(result["error"], 502, source=source_param)
    return jsonify(result)


@app.route("/api/proxy")
def api_proxy():
    url = request.args.get("url") or ""
    if not url.startswith(("http://", "https://")):
        return _error("url must start with http(s)", 400)
    headers = {}
    ua = request.args.get("ua")
    if ua:
        headers["User-Agent"] = ua
    referer = request.args.get("referer")
    if referer:
        headers["Referer"] = referer
    if request.headers.get("Range"):
        headers["Range"] = request.headers["Range"]
    try:
        upstream = requests.get(url, headers=headers, stream=True, timeout=30)
    except Exception as exc:  # noqa: BLE001
        return _error(str(exc), 502)
    if upstream.status_code >= 400:
        return _error("upstream HTTP %s" % upstream.status_code, 502)
    resp_headers = {
        k: v for k, v in upstream.headers.items()
        if k.lower() in _FORWARD_HEADERS
    }
    return Response(
        stream_with_context(upstream.iter_content(chunk_size=64 * 1024)),
        status=upstream.status_code,
        headers=resp_headers,
        direct_passthrough=True,
    )


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
