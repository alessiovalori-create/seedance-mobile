"""Mirror gallery ratings onto files under generated/ (sidecar + macOS Finder label)."""

from __future__ import annotations

import json
import os
import platform
import plistlib
import subprocess
from datetime import datetime, timezone

from arkitect.clip_naming import clip_last_frame_path
from arkitect.shared import _GENERATED_DIR

FINDER_INFO_XATTR = "com.apple.FinderInfo"
FINDER_TAGS_XATTR = "com.apple.metadata:_kMDItemUserTags"
SIDECAR_SUFFIX = ".arkitect-rating"

# com.apple.FinderInfo kColor byte (offset 9) — NOT the same as tag color index 0-7
_FINDER_INFO_COLOR_BYTE = {
    "green": 0x04,
    "orange": 0x0E,
    "red": 0x0C,
}

# com.apple.metadata:_kMDItemUserTags — "Name\\nColorIndex"
_FINDER_TAG_STRING = {
    "green": "Green\n2",
    "orange": "Orange\n7",
    "red": "Red\n6",
}

_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _norm(path: str) -> str:
    return os.path.normpath(os.path.abspath(path)) if path else ""


def _under_generated(path: str) -> bool:
    path = _norm(path)
    root = _norm(_GENERATED_DIR)
    return bool(path and root and (path == root or path.startswith(root + os.sep)))


def _path_from_rating_key(key: str) -> str | None:
    if not key.startswith("path:") or key.count(":") < 2:
        return None
    return _norm(key.split(":", 2)[2])


def paired_video_image_paths(path: str) -> list[str]:
    """Return [video, last_frame] when path is one half of a generated clip pair."""
    path = _norm(path)
    if not path:
        return []
    base, ext = os.path.splitext(path)
    out: list[str] = []
    if ext.lower() in _VIDEO_EXTS:
        out.append(path)
        last_frame = clip_last_frame_path(path)
        if os.path.isfile(last_frame):
            out.append(_norm(last_frame))
    elif path.endswith("_last.png"):
        out.append(path)
        video_guess = base[:-5] if base.endswith("_last") else ""
        if video_guess:
            for vext in _VIDEO_EXTS:
                candidate = video_guess + vext
                if os.path.isfile(candidate):
                    out.append(_norm(candidate))
                    break
    else:
        out.append(path)
    return out


def _companion_paths(path: str) -> list[str]:
    path = _norm(path)
    if not path or not os.path.isfile(path):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for p in paired_video_image_paths(path):
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def paths_for_rating_keys(keys: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for key in keys:
        raw = _path_from_rating_key(key)
        if not raw or not _under_generated(raw):
            continue
        for p in _companion_paths(raw):
            if p not in seen:
                seen.add(p)
                out.append(p)
    return out


def _sidecar_path(media_path: str) -> str:
    return media_path + SIDECAR_SUFFIX


def _write_sidecar(media_path: str, rating: str) -> None:
    payload = {"rating": rating, "updated_at": _now_iso()}
    sc = _sidecar_path(media_path)
    with open(sc, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _remove_sidecar(media_path: str) -> None:
    sc = _sidecar_path(media_path)
    try:
        os.remove(sc)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _read_finder_info(media_path: str) -> bytearray:
    if hasattr(os, "getxattr"):
        try:
            data = bytearray(os.getxattr(media_path, FINDER_INFO_XATTR))
            if len(data) < 32:
                data.extend(b"\x00" * (32 - len(data)))
            return data
        except OSError:
            return bytearray(32)
    try:
        proc = subprocess.run(
            ["xattr", "-px", FINDER_INFO_XATTR, media_path],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode != 0:
            return bytearray(32)
        hexbytes = proc.stdout.split()
        data = bytearray(int(h, 16) for h in hexbytes)
        if len(data) < 32:
            data.extend(b"\x00" * (32 - len(data)))
        return data
    except (OSError, ValueError, subprocess.SubprocessError):
        return bytearray(32)


def _write_xattr_bytes(media_path: str, attr: str, payload: bytes) -> None:
    if hasattr(os, "setxattr"):
        try:
            os.setxattr(media_path, attr, payload)
            return
        except OSError:
            pass
    try:
        hexstr = " ".join(f"{b:02x}" for b in payload)
        subprocess.run(
            ["xattr", "-wx", attr, hexstr, media_path],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _remove_xattr(media_path: str, attr: str) -> None:
    if hasattr(os, "removexattr"):
        try:
            os.removexattr(media_path, attr)
            return
        except OSError:
            pass
    try:
        subprocess.run(
            ["xattr", "-d", attr, media_path],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _set_finder_label(media_path: str, rating: str | None) -> None:
    if platform.system() != "Darwin":
        return
    if rating and rating in _FINDER_TAG_STRING:
        tag_plist = plistlib.dumps([_FINDER_TAG_STRING[rating]])
        _write_xattr_bytes(media_path, FINDER_TAGS_XATTR, tag_plist)
        data = _read_finder_info(media_path)
        data[9] = _FINDER_INFO_COLOR_BYTE[rating] & 0xFF
        _write_xattr_bytes(media_path, FINDER_INFO_XATTR, bytes(data[:32]))
    else:
        _remove_xattr(media_path, FINDER_TAGS_XATTR)
        data = _read_finder_info(media_path)
        data[9] = 0
        _write_xattr_bytes(media_path, FINDER_INFO_XATTR, bytes(data[:32]))


def apply_rating_to_path(media_path: str, rating: str) -> None:
    media_path = _norm(media_path)
    if not media_path or not os.path.isfile(media_path) or not _under_generated(media_path):
        return
    _write_sidecar(media_path, rating)
    _set_finder_label(media_path, rating)


def clear_rating_from_path(media_path: str) -> None:
    media_path = _norm(media_path)
    if not _under_generated(media_path):
        return
    _remove_sidecar(media_path)
    if os.path.isfile(media_path):
        _set_finder_label(media_path, None)


def sync_paths_for_rating_keys(keys: list[str], rating: str | None) -> None:
    for path in paths_for_rating_keys(keys):
        if rating:
            apply_rating_to_path(path, rating)
        else:
            clear_rating_from_path(path)


def sync_all_ratings_from_db() -> dict:
    """Backfill: apply every stored rating to files under generated/."""
    from arkitect.ratings import RATINGS_FILE, VALID_RATINGS

    if not os.path.isfile(RATINGS_FILE):
        return {"synced": 0, "paths": 0}
    with open(RATINGS_FILE, "r", encoding="utf-8") as f:
        store = json.load(f)
    synced = 0
    paths = 0
    for key, entry in (store or {}).items():
        if not isinstance(entry, dict):
            continue
        rating = entry.get("rating")
        if rating not in VALID_RATINGS:
            continue
        batch = paths_for_rating_keys([key])
        if not batch:
            continue
        sync_paths_for_rating_keys([key], rating)
        synced += 1
        paths += len(batch)
    return {"synced": synced, "paths": paths}


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Sync gallery ratings to generated/ files.")
    parser.add_argument("--backfill", action="store_true", help="Apply all ratings.json entries to disk.")
    args = parser.parse_args()
    if args.backfill:
        print(json.dumps(sync_all_ratings_from_db(), indent=2))


if __name__ == "__main__":
    main()
