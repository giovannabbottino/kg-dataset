"""Small client for fetching short Wikipedia article phrases."""

import gzip
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib


DEFAULT_USER_AGENT = (
    "kg-construction-llm-evaluation/1.0 "
    "(https://github.com/local/kg-construction-llm-evaluation; contact: set WIKIDATA_USER_AGENT)"
)
USER_AGENT = os.getenv("WIKIDATA_USER_AGENT", DEFAULT_USER_AGENT)
REQUEST_TIMEOUT_SECONDS = 10
MIN_REQUEST_INTERVAL_SECONDS = 1.0
MAX_RETRIES = 3
RETRY_STATUSES = {429, 500, 502, 503, 504}

_CACHE: dict[tuple[str, tuple[tuple[str, str], ...]], dict] = {}
_LAST_REQUEST_AT = 0.0


def _cache_key(url: str, params: dict) -> tuple[str, tuple[tuple[str, str], ...]]:
    return url, tuple(sorted((str(key), str(value)) for key, value in params.items()))


def _throttle_request() -> None:
    global _LAST_REQUEST_AT

    elapsed = time.monotonic() - _LAST_REQUEST_AT
    if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
        time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)
    _LAST_REQUEST_AT = time.monotonic()


def _decode_response(response) -> str:
    body = response.read()
    encoding = response.headers.get("Content-Encoding", "").casefold()
    if encoding == "gzip":
        body = gzip.decompress(body)
    elif encoding == "deflate":
        body = zlib.decompress(body)
    return body.decode("utf-8")


def _fetch_json(url: str, params: dict) -> dict:
    cache_key = _cache_key(url, params)
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    request = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}",
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
                _CACHE[cache_key] = data
                return data
        except urllib.error.HTTPError as exc:
            if exc.code in RETRY_STATUSES and attempt < MAX_RETRIES:
                time.sleep(min(2 ** attempt, 10))
                continue
            raise RuntimeError(f"Wikipedia HTTP error: {exc.code} {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Wikipedia network error: {exc.reason}") from exc

    raise RuntimeError("Wikipedia HTTP error: retry limit exceeded")


def _api_url(lang: str) -> str:
    return f"https://{lang}.wikipedia.org/w/api.php"


def _split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []

    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", normalized)
        if sentence.strip()
    ]


def fetch_wikipedia_phrases(title: str, lang: str, limit: int = 2) -> list[str]:
    """Return up to ``limit`` introductory Wikipedia sentences for a page title."""
    if not title.strip():
        return []

    data = _fetch_json(
        _api_url(lang),
        {
            "action": "query",
            "format": "json",
            "prop": "extracts",
            "exintro": 1,
            "explaintext": 1,
            "redirects": 1,
            "titles": title,
        },
    )
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        if "missing" in page:
            continue
        return _split_sentences(page.get("extract", ""))[:limit]
    return []
