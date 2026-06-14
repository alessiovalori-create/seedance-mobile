"""Repair gallery file paths after storage migrations."""

from __future__ import annotations

import os

from arkitect.clip_naming import clip_last_frame_path, resolve_meta_json_path, resolve_meta_txt_path
from arkitect.shared import _ASSETS_DIR, _GENERATED_DIR

_PATH_FIELDS_VIDEO = ("video_path", "last_frame_path")
_PATH_FIELDS_IMAGE = ("image_path",)


def _norm(path: str) -> str:
    return os.path.normpath(os.path.abspath(path)) if path else ""


def _find_media_basename(basename: str) -> str:
    if not basename:
        return ""
    for root, dirs, files in os.walk(_GENERATED_DIR):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        if basename in files:
            return os.path.join(root, basename)
    assets_videos = os.path.join(_ASSETS_DIR, "videos")
    if os.path.isdir(assets_videos):
        candidate = os.path.join(assets_videos, basename)
        if os.path.isfile(candidate):
            return candidate
    return ""


def resolve_media_path(path: str) -> str:
    """Return an existing absolute path, resolving stale/migrated locations by basename."""
    raw = (path or "").replace("\n", "").replace("\r", "").strip()
    if not raw or raw.startswith("http"):
        return path or ""
    norm = _norm(raw)
    if norm and os.path.exists(norm):
        return norm
    basename = os.path.basename(norm)
    found = _find_media_basename(basename)
    return found or norm


def playable_video_source(item: dict | None = None, path: str | None = None) -> str:
    """Local file path or remote URL suitable for st.video, or empty string."""
    item = item or {}
    raw_path = (path or item.get("video_path") or "").strip()
    url = (item.get("url") or "").strip()
    if raw_path and not raw_path.startswith("http"):
        resolved = resolve_media_path(raw_path)
        if resolved and os.path.isfile(resolved):
            return resolved
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return ""


def _repair_video_item(item: dict) -> bool:
    changed = False
    for field in _PATH_FIELDS_VIDEO:
        old = item.get(field) or ""
        if not old:
            continue
        new = resolve_media_path(old)
        if new and new != old:
            item[field] = new
            changed = True
    vp = item.get("video_path") or ""
    if vp and os.path.exists(vp):
        expected = clip_last_frame_path(vp)
        if os.path.exists(expected) and item.get("last_frame_path") != expected:
            item["last_frame_path"] = expected
            changed = True
    if vp:
        meta_json = resolve_meta_json_path(vp)
        if os.path.exists(meta_json) and item.get("settings_sidecar_path") != meta_json:
            item["settings_sidecar_path"] = meta_json
            changed = True
        meta_txt = resolve_meta_txt_path(vp)
        if os.path.exists(meta_txt) and item.get("info_file_path") != meta_txt:
            item["info_file_path"] = meta_txt
            changed = True
    return changed


def _repair_image_item(item: dict) -> bool:
    old = item.get("image_path") or ""
    if not old:
        return False
    new = resolve_media_path(old)
    if new and new != old:
        item["image_path"] = new
        return True
    return False


def repair_gallery_media_paths(videos: list, images: list) -> bool:
    """Fix broken paths and re-link videos to their last-frame PNG when present."""
    changed = False
    for item in videos or []:
        if _repair_video_item(item):
            changed = True
    for item in images or []:
        if _repair_image_item(item):
            changed = True
    return changed
