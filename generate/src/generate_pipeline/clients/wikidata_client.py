"""Small client for the Wikidata public API."""

import gzip
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections import deque


API_URL = "https://www.wikidata.org/w/api.php"
DEFAULT_USER_AGENT = (
    "kg-construction-llm-evaluation/1.0 "
    "(https://github.com/local/kg-construction-llm-evaluation; contact: set WIKIDATA_USER_AGENT)"
)
USER_AGENT = os.getenv("WIKIDATA_USER_AGENT", DEFAULT_USER_AGENT)
MAX_RETRIES = 5
MAXLAG_SECONDS = 5
REQUEST_TIMEOUT_SECONDS = 10
MIN_REQUEST_INTERVAL_SECONDS = 1.0
ERROR_WINDOW_SECONDS = 60
MAX_ERRORS_PER_WINDOW = 25
RETRY_STATUSES = {429, 500, 502, 503, 504}

_CACHE: dict[tuple[tuple[str, str], ...], dict] = {}
_ERROR_TIMESTAMPS: deque[float] = deque()
_LAST_REQUEST_AT = 0.0


def _cache_key(params: dict) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(key), str(value)) for key, value in params.items()))


def _trim_error_window(now: float) -> None:
    while _ERROR_TIMESTAMPS and now - _ERROR_TIMESTAMPS[0] >= ERROR_WINDOW_SECONDS:
        _ERROR_TIMESTAMPS.popleft()


def _record_error() -> None:
    now = time.monotonic()
    _trim_error_window(now)
    _ERROR_TIMESTAMPS.append(now)


def _throttle_request() -> None:
    global _LAST_REQUEST_AT

    now = time.monotonic()
    _trim_error_window(now)
    if len(_ERROR_TIMESTAMPS) >= MAX_ERRORS_PER_WINDOW:
        time.sleep(ERROR_WINDOW_SECONDS - (now - _ERROR_TIMESTAMPS[0]))
        now = time.monotonic()
        _trim_error_window(now)

    elapsed = now - _LAST_REQUEST_AT
    if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
        time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)
    _LAST_REQUEST_AT = time.monotonic()


def _retry_delay(exc: urllib.error.HTTPError, attempt: int) -> float:
    """Return a respectful retry delay for transient Wikidata errors."""
    retry_after = exc.headers.get("Retry-After")
    if retry_after:
        try:
            return max(float(retry_after), 1.0)
        except ValueError:
            pass
    return min(2 ** attempt, 30)


def _decode_response(response) -> str:
    """Decode a compressed or plain HTTP response body."""
    body = response.read()
    encoding = response.headers.get("Content-Encoding", "").casefold()
    if encoding == "gzip":
        body = gzip.decompress(body)
    elif encoding == "deflate":
        body = zlib.decompress(body)
    return body.decode("utf-8")


def _fetch_json(params: dict) -> dict:
    """Request JSON from the Wikidata API."""
    params = {"maxlag": MAXLAG_SECONDS, **params}
    cache_key = _cache_key(params)
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    request = urllib.request.Request(
        f"{API_URL}?{urllib.parse.urlencode(params)}",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
        },
    )
    for attempt in range(MAX_RETRIES + 1):
        try:
            _throttle_request()
            with urllib.request.urlopen(
                request, timeout=REQUEST_TIMEOUT_SECONDS
            ) as response:
                data = json.loads(_decode_response(response))
                error = data.get("error", {})
                if error.get("code") == "maxlag":
                    _record_error()
                    if attempt < MAX_RETRIES:
                        time.sleep(min(2 ** attempt, 30))
                        continue
                    raise RuntimeError(
                        f"Wikidata API error: maxlag {error.get('info', '')}".strip()
                    )
                if error:
                    _record_error()
                    code = error.get("code", "unknown")
                    info = error.get("info", "no details")
                    raise RuntimeError(f"Wikidata API error: {code} {info}")
                _CACHE[cache_key] = data
                return data
        except urllib.error.HTTPError as exc:
            _record_error()
            if exc.code in RETRY_STATUSES and attempt < MAX_RETRIES:
                time.sleep(_retry_delay(exc, attempt))
                continue
            raise RuntimeError(f"HTTP error: {exc.code} {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Network error: {exc.reason}") from exc

    raise RuntimeError("HTTP error: retry limit exceeded")


def find_entity_ids_by_name(name: str, lang: str, limit: int = 2) -> list[str]:
    """Return up to ``limit`` Wikidata item IDs matching ``name`` in API order."""
    data = _fetch_json(
        {
            "action": "wbsearchentities",
            "format": "json",
            "language": lang,
            "uselang": lang,
            "type": "item",
            "limit": limit,
            "search": name,
        }
    )
    results = data.get("search", [])
    return [result["id"] for result in results if result.get("id")]


def find_entity_id_by_name(name: str, lang: str) -> str | None:
    """Return the best match, for callers that resolve one description token."""
    entity_ids = find_entity_ids_by_name(name, lang, limit=1)
    return entity_ids[0] if entity_ids else None


def fetch_entity(entity_id: str, lang: str) -> dict:
    """Fetch the label and Wikipedia sitelink needed by the generator."""
    data = _fetch_json(
        {
            "action": "wbgetentities",
            "format": "json",
            "ids": entity_id,
            "languages": lang,
            "props": "labels|sitelinks",
            "sitefilter": f"{lang}wiki",
        }
    )
    entity = data.get("entities", {}).get(entity_id)
    if not entity or "missing" in entity:
        raise RuntimeError(f"entity '{entity_id}' was not found")
    return entity

def fetch_labels(entity_ids: set[str], lang: str) -> dict[str, str]:
    """Fetch labels for a set of Wikidata item IDs."""
    if not entity_ids:
        return {}

    data = _fetch_json(
        {
            "action": "wbgetentities",
            "format": "json",
            "ids": "|".join(sorted(entity_ids)),
            "languages": lang,
            "props": "labels",
        }
    )
    return {
        item_id: item["labels"][lang]["value"]
        for item_id, item in data.get("entities", {}).items()
        if lang in item.get("labels", {})
    }
