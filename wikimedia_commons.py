"""
Wikimedia Commons API client for public-domain artwork and photography search.

Uses the MediaWiki Action API on commons.wikimedia.org with optional on-disk caching.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

API_URL = "https://commons.wikimedia.org/w/api.php"
# Wikimedia requires a descriptive User-Agent (see meta.wikimedia.org/wiki/User-Agent_policy)
DEFAULT_HEADERS = {
    "User-Agent": "ArkitectAgent-WikimediaCommons/1.0 (Python; Wikimedia Commons API client)",
}

# Project root: same directory as this module
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_CACHE_DIR = os.path.join(_PROJECT_ROOT, "data", "cache")
_CACHE_FILE = os.path.join(_CACHE_DIR, "wikimedia_commons_cache.json")
_CACHE_TTL = timedelta(days=7)

_MIN_REQUEST_INTERVAL_SEC = 1.0
_last_request_monotonic: float = 0.0


def _rate_limit_before_request() -> None:
    """Sleep if needed so consecutive API calls are at least ~1s apart."""
    global _last_request_monotonic
    now = time.monotonic()
    if _last_request_monotonic > 0:
        wait = _MIN_REQUEST_INTERVAL_SEC - (now - _last_request_monotonic)
        if wait > 0:
            time.sleep(wait)
    _last_request_monotonic = time.monotonic()


def _cache_key(query: str, max_results: int) -> str:
    """Return a stable SHA-256 hex digest for (query, max_results)."""
    raw = f"{query.strip().lower()}|{max_results}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _ensure_cache_dir() -> None:
    """Create the cache directory if it does not exist."""
    os.makedirs(_CACHE_DIR, mode=0o755, exist_ok=True)


def _load_cache_file() -> Dict[str, Any]:
    """Load the entire cache JSON object, or return an empty shell."""
    if not os.path.isfile(_CACHE_FILE):
        return {"entries": {}}
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"entries": {}}
        if "entries" not in data or not isinstance(data["entries"], dict):
            data["entries"] = {}
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Could not read Wikimedia cache file: %s", e)
        return {"entries": {}}


def _save_cache_file(data: Dict[str, Any]) -> None:
    """Persist the cache JSON to disk."""
    _ensure_cache_dir()
    try:
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.warning("Could not write Wikimedia cache file: %s", e)


def _prune_expired_entries(entries: Dict[str, Any], now_ts: float) -> None:
    """Remove cache entries older than CACHE_TTL (mutates entries in place)."""
    cutoff = now_ts - _CACHE_TTL.total_seconds()
    stale = [k for k, v in entries.items() if not isinstance(v, dict) or v.get("saved_at", 0) < cutoff]
    for k in stale:
        del entries[k]


def _get_cached_results(query: str, max_results: int) -> Optional[List[Dict[str, Any]]]:
    """
    Return cached results if present and not expired; otherwise None.

    Args:
        query: Search query string.
        max_results: Maximum number of results used for the cache key.

    Returns:
        Cached list of result dicts, or None if missing or stale.
    """
    key = _cache_key(query, max_results)
    data = _load_cache_file()
    entries = data.get("entries", {})
    now_ts = datetime.now(timezone.utc).timestamp()
    _prune_expired_entries(entries, now_ts)
    blob = entries.get(key)
    if not isinstance(blob, dict):
        return None
    saved = blob.get("saved_at")
    results = blob.get("results")
    if saved is None or not isinstance(results, list):
        return None
    if now_ts - float(saved) > _CACHE_TTL.total_seconds():
        return None
    return results


def _set_cached_results(query: str, max_results: int, results: List[Dict[str, Any]]) -> None:
    """Store results under a hashed key with the current UTC timestamp."""
    key = _cache_key(query, max_results)
    data = _load_cache_file()
    entries = data.setdefault("entries", {})
    now_ts = datetime.now(timezone.utc).timestamp()
    _prune_expired_entries(entries, now_ts)
    entries[key] = {
        "query": query.strip(),
        "max_results": max_results,
        "saved_at": now_ts,
        "results": results,
    }
    _save_cache_file(data)


def _extmetadata_value(extmetadata: Optional[Dict[str, Any]], key: str) -> Optional[str]:
    """
    Read a human-readable value from imageinfo extmetadata.

    Values are often dicts with a 'value' key.

    Args:
        extmetadata: The extmetadata object from the API.
        key: Metadata key (e.g. 'Artist', 'LicenseShortName').

    Returns:
        The string value, or None.
    """
    if not extmetadata or key not in extmetadata:
        return None
    v = extmetadata[key]
    if isinstance(v, dict):
        val = v.get("value")
        return val if isinstance(val, str) else (str(val) if val is not None else None)
    if isinstance(v, str):
        return v
    return None


def _guess_medium(extmetadata: Optional[Dict[str, Any]]) -> Optional[str]:
    """
    Try to extract a medium / object description from extmetadata.

    Args:
        extmetadata: The extmetadata object from the API.

    Returns:
        A short medium string if found, else None.
    """
    if not extmetadata:
        return None
    for key in ("Medium", "ObjectName", "ImageDescription", "Credit"):
        s = _extmetadata_value(extmetadata, key)
        if s and len(s.strip()) > 0:
            # Keep first line only if very long
            line = s.strip().split("\n", 1)[0].strip()
            if len(line) > 200:
                line = line[:197] + "..."
            return line
    return None


def _filename_from_title(title: str) -> str:
    """Strip the 'File:' prefix from a Commons page title."""
    if title.startswith("File:"):
        return title[5:]
    return title


def _commons_file_url(title: str) -> str:
    """Build the canonical Commons file page URL for a given title."""
    # Title may include spaces; path uses underscores in MediaWiki convention
    safe = title.replace(" ", "_")
    from urllib.parse import quote

    return "https://commons.wikimedia.org/wiki/" + quote(safe, safe="/():%")


def _parse_page_record(page: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Convert one API 'page' object into the public result dict format.

    Args:
        page: A page dict from query.pages.

    Returns:
        A normalized result dict, or None if the record cannot be parsed.
    """
    try:
        title = page.get("title")
        if not title or not isinstance(title, str):
            return None
        iilist = page.get("imageinfo")
        if not iilist or not isinstance(iilist, list):
            return None
        ii = iilist[0]
        if not isinstance(ii, dict):
            return None

        image_url = ii.get("url") or ""
        thumb_url = ii.get("thumburl") or image_url
        width = ii.get("width")
        height = ii.get("height")
        if width is not None:
            width = int(width)
        if height is not None:
            height = int(height)

        ext = ii.get("extmetadata")
        if ext is not None and not isinstance(ext, dict):
            ext = None

        artist = _extmetadata_value(ext, "Artist")
        date = _extmetadata_value(ext, "DateTime") or _extmetadata_value(ext, "DateTimeOriginal")
        license_short = _extmetadata_value(ext, "LicenseShortName") or _extmetadata_value(ext, "UsageTerms")
        license_url = _extmetadata_value(ext, "LicenseUrl") or _extmetadata_value(ext, "License")
        medium = _guess_medium(ext)

        filename = _filename_from_title(title)
        source_link = _commons_file_url(title)

        return {
            "title": title,
            "filename": filename,
            "image_url": image_url,
            "thumb_url": thumb_url,
            "width": width,
            "height": height,
            "artist": artist or "",
            "date": date or "",
            "license": license_short or "",
            "license_url": license_url or "",
            "source_link": source_link,
            "medium": medium or "",
        }
    except (TypeError, ValueError, KeyError) as e:
        logger.debug("Skip malformed page record: %s", e)
        return None


def _fetch_from_api(query: str, max_results: int) -> List[Dict[str, Any]]:
    """
    Perform a single HTTP GET to the Commons API and parse pages.

    Args:
        query: Raw search string (trimmed).
        max_results: gsrlimit.

    Returns:
        List of result dicts (may be empty on error).
    """
    _rate_limit_before_request()
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": f"intitle:{query}",
        "gsrnamespace": 6,
        "gsrlimit": min(max(1, max_results), 500),
        "prop": "pageimages|imageinfo",
        "iiprop": "url|extmetadata|dimensions",
        "iiurlwidth": 400,
        "format": "json",
    }
    try:
        resp = requests.get(API_URL, params=params, headers=DEFAULT_HEADERS, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as e:
        logger.warning("Wikimedia Commons API request failed: %s", e)
        return []
    except ValueError as e:
        logger.warning("Wikimedia Commons API returned invalid JSON: %s", e)
        return []

    if not isinstance(payload, dict):
        return []
    q = payload.get("query")
    if not isinstance(q, dict):
        return []
    pages = q.get("pages")
    if not isinstance(pages, dict):
        return []

    out: List[Dict[str, Any]] = []
    # Preserve JSON object iteration order (search relevance from the API)
    for page in pages.values():
        if not isinstance(page, dict):
            continue
        rec = _parse_page_record(page)
        if rec:
            out.append(rec)
        if len(out) >= max_results:
            break
    return out


def search_wikimedia_commons(query: str, max_results: int = 20) -> List[Dict[str, Any]]:
    """
    Search Wikimedia Commons file namespace for titles matching the query.

    Uses ``generator=search`` with ``intitle:`` scoped to namespace 6 (File).
    Results are optionally read from ``data/cache/wikimedia_commons_cache.json``
    when a non-expired entry exists (TTL 7 days).

    Args:
        query: Human-readable search string (e.g. artist name).
        max_results: Maximum number of file pages to return (capped by the API at 500).

    Returns:
        A list of dicts with keys: title, filename, image_url, thumb_url, width, height,
        artist, date, license, license_url, source_link, medium.
        Returns an empty list on empty query, network failure, or unparseable responses.
    """
    q = (query or "").strip()
    if not q:
        return []

    cached = _get_cached_results(q, max_results)
    if cached is not None:
        return list(cached)

    results = _fetch_from_api(q, max_results)
    if results:
        try:
            _set_cached_results(q, max_results, results)
        except Exception as e:
            logger.debug("Could not cache Wikimedia results: %s", e)
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = search_wikimedia_commons("Caravaggio")
    print(f"Found {len(results)} results")
    if results:
        print(f"First result: {results[0]['title']}")
