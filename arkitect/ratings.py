"""Persistent global ratings for generated images and videos (single source of truth)."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone

from arkitect.clip_naming import clip_last_frame_path
from arkitect.shared import _DB_DIR

RATINGS_FILE = os.path.join(_DB_DIR, "ratings.json")

VALID_RATINGS = frozenset({"red", "orange", "green"})
RATING_COLORS = {
    "red": "#E53935",
    "orange": "#FF9800",
    "green": "#43A047",
}
UNRATED = "unrated"

# Gallery sort: green first, then orange, red, unrated last
RATING_SORT_RANK = {"green": 0, "orange": 1, "red": 2}
UNRATED_SORT_RANK = 3

_lock = threading.Lock()
_cache: dict | None = None
_cache_mtime: float | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_path(path: str) -> str:
    if not path:
        return ""
    return os.path.normpath(os.path.abspath(path))


def _media_kind(item: dict, path: str = "") -> str:
    if item.get("type") == "video" or item.get("video_path"):
        return "video"
    if path:
        ext = os.path.splitext(path)[1].lower()
        if ext in {".mp4", ".mov", ".webm"}:
            return "video"
    return "image"


def _path_rating_key(kind: str, path: str) -> str:
    norm = _normalize_path(path)
    if not norm:
        return ""
    return f"path:{kind}:{norm}"


def _path_keys_for_asset(asset: dict) -> list[str]:
    keys: list[str] = []
    prov = asset.get("provenance") or {}
    for src in (prov.get("gallery_source_path"), prov.get("source_path")):
        if src:
            k = _path_rating_key(_media_kind(asset, src), src)
            if k and k not in keys:
                keys.append(k)
    apath = asset.get("path") or ""
    if apath:
        k = _path_rating_key(_media_kind(asset, apath), apath)
        if k and k not in keys:
            keys.append(k)
    return keys


def _asset_ids_for_source_path(norm_path: str) -> list[str]:
    norm_path = _normalize_path(norm_path)
    if not norm_path:
        return []
    from arkitect.storage import load_asset_catalog

    out: list[str] = []
    for asset in load_asset_catalog():
        aid = asset.get("id")
        if not aid:
            continue
        prov = asset.get("provenance") or {}
        linked = (
            _normalize_path(prov.get("gallery_source_path") or ""),
            _normalize_path(prov.get("source_path") or ""),
            _normalize_path(asset.get("path") or ""),
        )
        if norm_path in linked and aid not in out:
            out.append(aid)
    return out


def item_key_for_rating(item: dict, *, ref_key: str | None = None) -> str:
    """Stable global key — gallery path first so Gallery and Assets stay in sync."""
    if ref_key:
        return ref_key if ref_key.startswith("ref:") else f"ref:{ref_key}"

    if not isinstance(item, dict):
        return ""

    prov = item.get("provenance") or {}
    for src in (prov.get("gallery_source_path"), prov.get("source_path")):
        if src:
            key = _path_rating_key(_media_kind(item, src), src)
            if key:
                return key

    video_path = _normalize_path(item.get("video_path") or "")
    image_path = _normalize_path(item.get("image_path") or "")
    if video_path:
        return f"path:video:{video_path}"
    if image_path:
        return f"path:image:{image_path}"

    generic_path = _normalize_path(item.get("path") or "")
    if generic_path:
        return _path_rating_key(_media_kind(item, generic_path), generic_path)

    asset_id = item.get("id")
    if asset_id:
        return f"asset:{asset_id}"

    url = (item.get("url") or item.get("src") or "").strip()
    if url:
        import hashlib
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        return f"url:{digest}"

    return ""


def rating_keys_for_item(item: dict) -> list[str]:
    """All keys that should share one rating for this item."""
    keys: list[str] = []
    seen: set[str] = set()

    def _add(key: str) -> None:
        if key and key not in seen:
            seen.add(key)
            keys.append(key)

    if not isinstance(item, dict):
        return keys

    _add(item_key_for_rating(item))
    if item.get("id"):
        _add(f"asset:{item['id']}")
        for pk in _path_keys_for_asset(item):
            _add(pk)
    for field in ("image_path", "video_path", "last_frame_path"):
        norm = _normalize_path(item.get(field) or "")
        if norm:
            _add(_path_rating_key(_media_kind(item, norm), norm))
            for aid in _asset_ids_for_source_path(norm):
                _add(f"asset:{aid}")
    _link_video_image_rating_keys(item, _add)
    return keys


def _link_video_image_rating_keys(item: dict, add_fn) -> None:
    """Keep video + last-frame PNG on the same rating."""
    video_path = _normalize_path(item.get("video_path") or "")
    image_path = _normalize_path(item.get("image_path") or "")
    last_frame = _normalize_path(item.get("last_frame_path") or "")

    if video_path:
        add_fn(_path_rating_key("video", video_path))
        if not last_frame:
            last_frame = _normalize_path(clip_last_frame_path(video_path))
        if last_frame:
            add_fn(_path_rating_key("image", last_frame))

    if image_path:
        add_fn(_path_rating_key("image", image_path))
        if image_path.endswith("_last.png"):
            base = image_path[: -len("_last.png")]
            for ext in (".mp4", ".mov", ".webm", ".m4v"):
                candidate = base + ext
                if os.path.isfile(candidate):
                    add_fn(_path_rating_key("video", candidate))
                    break


def _collect_related_rating_keys(item_key: str) -> list[str]:
    """Expand a bridge key to all linked gallery/asset aliases."""
    keys: list[str] = []
    seen: set[str] = set()

    def _add(key: str) -> None:
        if key and key not in seen:
            seen.add(key)
            keys.append(key)

    _add(item_key)
    if item_key.startswith("path:"):
        parts = item_key.split(":", 2)
        if len(parts) == 3:
            norm_path = _normalize_path(parts[2])
            for aid in _asset_ids_for_source_path(norm_path):
                _add(f"asset:{aid}")
            try:
                from arkitect.rating_fs import paired_video_image_paths

                for linked in paired_video_image_paths(norm_path):
                    kind = _media_kind({}, linked)
                    _add(_path_rating_key(kind, linked))
            except Exception:
                pass
    elif item_key.startswith("asset:"):
        from arkitect.storage import load_asset_catalog

        aid = item_key[6:]
        for asset in load_asset_catalog():
            if asset.get("id") == aid:
                for pk in _path_keys_for_asset(asset):
                    _add(pk)
                break
    return keys


def get_rating_for_item(item: dict) -> str | None:
    for key in rating_keys_for_item(item):
        rating = get_rating(key)
        if rating:
            return rating
    return None


def _load_all_unlocked() -> dict:
    global _cache, _cache_mtime
    if not os.path.isfile(RATINGS_FILE):
        _cache = {}
        _cache_mtime = None
        return _cache
    mtime = os.path.getmtime(RATINGS_FILE)
    if _cache is not None and _cache_mtime == mtime:
        return _cache
    with open(RATINGS_FILE, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    if not isinstance(raw, dict):
        raise ValueError(f"{RATINGS_FILE}: expected JSON object at root")
    cleaned: dict = {}
    for key, entry in raw.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            continue
        rating = entry.get("rating")
        if rating in VALID_RATINGS:
            cleaned[key] = {
                "rating": rating,
                "updated_at": entry.get("updated_at") or _now_iso(),
            }
    _cache = cleaned
    _cache_mtime = mtime
    return _cache


def _save_all_unlocked(data: dict) -> None:
    global _cache, _cache_mtime
    os.makedirs(_DB_DIR, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=_DB_DIR, suffix=".tmp", prefix="ratings_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, RATINGS_FILE)
        _cache = dict(data)
        _cache_mtime = os.path.getmtime(RATINGS_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def invalidate_cache() -> None:
    global _cache, _cache_mtime
    with _lock:
        _cache = None
        _cache_mtime = None


def get_rating(item_key: str) -> str | None:
    if not item_key:
        return None
    with _lock:
        store = _load_all_unlocked()
    entry = store.get(item_key)
    if not entry:
        return None
    rating = entry.get("rating")
    return rating if rating in VALID_RATINGS else None


def set_rating(item_key: str, rating: str) -> None:
    if not item_key:
        raise ValueError("item_key is required")
    if rating not in VALID_RATINGS:
        raise ValueError(f"invalid rating: {rating!r}")
    related = _collect_related_rating_keys(item_key)
    with _lock:
        store = dict(_load_all_unlocked())
        entry = {"rating": rating, "updated_at": _now_iso()}
        for key in related:
            store[key] = dict(entry)
        _save_all_unlocked(store)
    _sync_rating_files(related, rating)


def set_rating_for_item(item: dict, rating: str) -> bool:
    """Apply a rating to a gallery/asset dict (all linked keys). Returns False if no key."""
    if rating not in VALID_RATINGS:
        raise ValueError(f"invalid rating: {rating!r}")
    key = item_key_for_rating(item)
    if not key:
        return False
    set_rating(key, rating)
    return True


def clear_rating(item_key: str) -> None:
    if not item_key:
        return
    related = _collect_related_rating_keys(item_key)
    changed = False
    with _lock:
        store = dict(_load_all_unlocked())
        for key in related:
            if key in store:
                del store[key]
                changed = True
        if changed:
            _save_all_unlocked(store)
    if changed:
        _sync_rating_files(related, None)


def _sync_rating_files(related_keys: list[str], rating: str | None) -> None:
    try:
        from arkitect.rating_fs import sync_paths_for_rating_keys

        sync_paths_for_rating_keys(related_keys, rating)
    except Exception:
        pass


def toggle_rating(item_key: str, rating: str) -> str | None:
    """Set rating, or clear if the same rating is already active. Returns new rating or None."""
    current = None
    for key in _collect_related_rating_keys(item_key):
        current = get_rating(key)
        if current:
            break
    if current == rating:
        clear_rating(item_key)
        return None
    set_rating(item_key, rating)
    return rating


def filter_items_by_rating(
    items: list,
    allowed: set[str] | list[str] | None,
    *,
    key_fn=None,
) -> list:
    """Keep items whose rating is in ``allowed``. Use ``unrated`` for items without a rating."""
    if not items:
        return []
    if not allowed:
        return list(items)
    allowed_set = set(allowed)
    if allowed_set >= {*VALID_RATINGS, UNRATED}:
        return list(items)

    out = []
    for item in items:
        rating = get_rating_for_item(item) if key_fn is None else get_rating(key_fn(item))
        bucket = rating if rating else UNRATED
        if bucket in allowed_set:
            out.append(item)
    return out


def _rating_sort_rank(item: dict) -> int:
    rating = get_rating_for_item(item)
    return RATING_SORT_RANK.get(rating, UNRATED_SORT_RANK)


def sort_items_by_color(items: list, *, date_field: str = "created_at") -> list:
    """Green → orange → red → unrated; within each group newest first."""
    chronological = sorted(items, key=lambda x: x.get(date_field, ""), reverse=True)
    buckets: dict[int, list] = {0: [], 1: [], 2: [], 3: []}
    for item in chronological:
        buckets[_rating_sort_rank(item)].append(item)
    return buckets[0] + buckets[1] + buckets[2] + buckets[3]


def sort_items_chronological(items: list, *, date_field: str = "created_at") -> list:
    return sorted(items, key=lambda x: x.get(date_field, ""), reverse=True)


def apply_gallery_sort(items: list, mode: str, *, date_field: str = "created_at") -> list:
    m = (mode or "").strip().lower()
    if m in ("chronological", "cronologica", "cronologico"):
        return sort_items_chronological(items, date_field=date_field)
    return sort_items_by_color(items, date_field=date_field)


def get_rating_counts(items: list) -> dict[str, int]:
    counts = {r: 0 for r in VALID_RATINGS}
    counts[UNRATED] = 0
    for item in items:
        rating = get_rating_for_item(item)
        if rating in VALID_RATINGS:
            counts[rating] += 1
        else:
            counts[UNRATED] += 1
    return counts
