import os
import json
import re
import random
from datetime import datetime

import streamlit as st

from arkitect.shared import (
    CachedUploadedFile,
    AssetFile,
    GENERATED_RESERVED_DIRS,
    _ASSETS_DIR,
    _DB_DIR,
    _GENERATED_DIR,
    _UPLOADS_DIR,
)

GALLERY_FILE = os.path.join(_DB_DIR, "gallery.json")
SNAPSHOTS_FILE = os.path.join(_DB_DIR, "snapshots.json")

ASSETS_DIR = _ASSETS_DIR
ASSETS_CATALOG_FILE = os.path.join(_DB_DIR, "assets_catalog.json")

PROJECTS_FILE = os.path.join(_DB_DIR, "projects.json")

DOWNLOADS_DIR = _GENERATED_DIR
UPLOADS_DIR = _UPLOADS_DIR

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}
VIDEO_EXTS = {'.mp4', '.mov', '.webm'}
AUDIO_EXTS = {'.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac'}


def load_gallery_from_disk():
    if not os.path.exists(GALLERY_FILE):
        return [], []
    try:
        with open(GALLERY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("videos", []), data.get("images", [])
    except Exception:
        return [], []

def save_gallery_to_disk(videos, images):
    try:
        with open(GALLERY_FILE, "w", encoding="utf-8") as f:
            json.dump({"videos": videos, "images": images}, f, ensure_ascii=False, indent=0)
    except Exception:
        pass

def load_all_snapshots() -> dict:
    if not os.path.exists(SNAPSHOTS_FILE):
        return {"storyboard": {}, "editing": {}}
    try:
        with open(SNAPSHOTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"storyboard": {}, "editing": {}}

def save_all_snapshots(snapshots: dict):
    try:
        with open(SNAPSHOTS_FILE, "w", encoding="utf-8") as f:
            json.dump(snapshots, f, ensure_ascii=False, indent=0)
    except Exception:
        pass


def snapshot_entry_items(value):
    """Return frame list from a storyboard/editing snapshot (legacy list or dict with items)."""
    if isinstance(value, dict) and "items" in value:
        return value["items"]
    if isinstance(value, list):
        return value
    return []


def snapshot_entry_project_id(value):
    if isinstance(value, dict) and "items" in value:
        return value.get("project_id")
    return None


def filter_snapshot_names(entries_dict, active_proj):
    """Names visible in pick list: new format filtered by project; legacy lists only in All Projects."""
    saved_names = []
    for name, value in (entries_dict or {}).items():
        if isinstance(value, dict) and "items" in value:
            if active_proj is None or value.get("project_id") == active_proj:
                saved_names.append(name)
        else:
            if active_proj is None:
                saved_names.append(name)
    return saved_names


def upsert_snapshot_entry(snap_key, name, items_list):
    """Auto-save from grid: keep existing project_id if entry is dict; else use active project."""
    if not name:
        return
    snaps = load_all_snapshots()
    bucket = snaps.setdefault(snap_key, {})
    prev = bucket.get(name)
    if isinstance(prev, dict) and "items" in prev:
        pid = prev.get("project_id")
    else:
        pid = get_active_project_id()
    bucket[name] = {"project_id": pid, "items": list(items_list)}
    save_all_snapshots(snaps)


def save_snapshot_with_active_project(snap_key, name, items_list):
    """Explicit SAVE button: always tag with current active project."""
    snaps = load_all_snapshots()
    snaps.setdefault(snap_key, {})[name] = {
        "project_id": get_active_project_id(),
        "items": list(items_list),
    }
    save_all_snapshots(snaps)


def load_asset_catalog():
    if not os.path.exists(ASSETS_CATALOG_FILE):
        return []
    try:
        with open(ASSETS_CATALOG_FILE, "r", encoding="utf-8") as f:
            catalog = json.load(f)
        # Remove entries whose files no longer exist on disk
        valid = [a for a in catalog if os.path.exists(a.get("path", ""))]
        if len(valid) != len(catalog):
            save_asset_catalog(valid)
        return valid
    except Exception:
        return []


def save_asset_catalog(catalog):
    os.makedirs(ASSETS_DIR, exist_ok=True)
    try:
        with open(ASSETS_CATALOG_FILE, "w", encoding="utf-8") as f:
            json.dump(catalog, f, ensure_ascii=False, indent=0)
    except Exception:
        pass


def _project_asset_name_prefix(project_name):
    """Sanitize project name for asset filenames (e.g. My_Film_001.jpg)."""
    if not project_name or str(project_name).strip() in ("", "All Projects"):
        return "asset"
    slug = re.sub(r"[^\w\-]", "_", str(project_name).strip())
    return slug or "asset"


def next_project_image_asset_name(project_id=None, project_name=None, ext=".jpg"):
    """
    Next catalog filename for a project image: {ProjectSlug}_001.ext, _002, etc.
    Counts existing image assets in the same project with matching prefix.
    """
    catalog = load_asset_catalog()
    prefix = _project_asset_name_prefix(project_name)
    max_n = 0
    for a in catalog:
        if a.get("type") != "image":
            continue
        if project_id is not None:
            if a.get("project_id") != project_id:
                continue
        stem = os.path.splitext(a.get("name", ""))[0]
        m = re.match(rf"^{re.escape(prefix)}_(\d+)$", stem, re.I)
        if m:
            max_n = max(max_n, int(m.group(1)))
    ext = ext if ext.startswith(".") else f".{ext}"
    return f"{prefix}_{max_n + 1:03d}{ext}"


def add_to_assets(source_path=None, uploaded_file=None, original_name=None, provenance=None,
                  asset_name=None):
    """
    Add a file to the asset library.
    source_path: path on disk (for copies from Gallery/Storyboard/Editing)
    uploaded_file: Streamlit UploadedFile (for desktop uploads)
    provenance: optional dict (e.g. ReferencesRoom: vendor, high_res_url, original_width/height)
    Returns the new asset dict or None on failure.
    """
    catalog = load_asset_catalog()

    if uploaded_file:
        upload_original = uploaded_file.name
        name = asset_name or upload_original
        data = uploaded_file.getvalue()
        mime = getattr(uploaded_file, 'type', None) or 'application/octet-stream'
    elif source_path and os.path.exists(source_path):
        upload_original = original_name or os.path.basename(source_path)
        name = asset_name or upload_original
        with open(source_path, 'rb') as f:
            data = f.read()
        ext = os.path.splitext(name)[1].lower()
        mime_map = {
            '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
            '.webp': 'image/webp', '.gif': 'image/gif',
            '.mp4': 'video/mp4', '.mov': 'video/quicktime', '.webm': 'video/webm',
            '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.ogg': 'audio/ogg',
            '.m4a': 'audio/mp4', '.flac': 'audio/flac', '.aac': 'audio/aac',
        }
        mime = mime_map.get(ext, 'application/octet-stream')
    else:
        return None

    # Determine type and subdir
    if mime.startswith('image'):
        ftype, subdir = 'image', 'images'
    elif mime.startswith('video'):
        ftype, subdir = 'video', 'videos'
    elif mime.startswith('audio'):
        ftype, subdir = 'audio', 'audio'
    else:
        return None

    _src_abs = ""
    if source_path and os.path.exists(source_path):
        _src_abs = os.path.normpath(os.path.abspath(source_path))

    # Check for duplicates by original filename + size
    for existing in catalog:
        if existing.get("original_name") == upload_original and existing.get("size") == len(data):
            if _src_abs:
                prov = dict(existing.get("provenance") or {})
                prov["gallery_source_path"] = _src_abs
                existing["provenance"] = prov
                save_asset_catalog(catalog)
            return existing

    # Save file to assets/{subdir}/
    dest_dir = os.path.join(ASSETS_DIR, subdir)
    os.makedirs(dest_dir, exist_ok=True)
    safe_name = re.sub(r'[^\w.\-]', '_', name)
    dest = os.path.join(dest_dir, safe_name)
    if os.path.exists(dest):
        base, ext_s = os.path.splitext(safe_name)
        idx = 1
        while os.path.exists(os.path.join(dest_dir, f"{base}_{idx}{ext_s}")):
            idx += 1
        safe_name = f"{base}_{idx}{ext_s}"
        dest = os.path.join(dest_dir, safe_name)

    with open(dest, 'wb') as f:
        f.write(data)

    asset_id = f"{ftype[0]}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(100, 999)}"
    entry = {
        "id": asset_id,
        "name": safe_name,
        "original_name": upload_original,
        "type": ftype,
        "path": dest,
        "mime": mime,
        "size": len(data),
        "size_str": f"{len(data) / (1024*1024):.1f} MB" if len(data) >= 1024*1024 else f"{len(data) / 1024:.0f} KB",
        "notes": "",
        "uploaded_at": datetime.now().isoformat(),
        "project_id": st.session_state.get("active_project_id"),
    }
    prov: dict = dict(provenance) if isinstance(provenance, dict) else {}
    if _src_abs:
        prov["gallery_source_path"] = _src_abs
    if prov:
        entry["provenance"] = prov
    catalog.append(entry)
    save_asset_catalog(catalog)
    return entry


def load_projects():
    if not os.path.exists(PROJECTS_FILE):
        return {"projects": [], "active_project_id": None}
    try:
        with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "projects" not in data:
            data["projects"] = []
        if "active_project_id" not in data:
            data["active_project_id"] = None
        return data
    except Exception:
        return {"projects": [], "active_project_id": None}


def save_projects(data):
    try:
        with open(PROJECTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_active_project_id():
    return st.session_state.get("active_project_id")


def get_active_project_name():
    return st.session_state.get("active_project_name", "All Projects")


def scan_assets(filter_type="All"):
    """
    Scan downloads/ directory for all media files.
    filter_type: "All", "Images", "Videos", "Audio"
    Returns list of dicts sorted by modification time (newest first).
    """
    assets = []
    if not os.path.exists(DOWNLOADS_DIR):
        return assets

    for root, dirs, files in os.walk(DOWNLOADS_DIR):
        dirs[:] = [d for d in dirs if d not in GENERATED_RESERVED_DIRS]
        for fname in files:
            fpath = os.path.join(root, fname)
            ext = os.path.splitext(fname)[1].lower()

            # Skip metadata text files
            if ext == '.txt':
                continue

            # Determine type
            if ext in IMAGE_EXTS:
                ftype = "image"
            elif ext in VIDEO_EXTS:
                ftype = "video"
            elif ext in AUDIO_EXTS:
                ftype = "audio"
            else:
                continue

            # Apply filter
            if filter_type == "Images" and ftype != "image":
                continue
            if filter_type == "Videos" and ftype != "video":
                continue
            if filter_type == "Audio" and ftype != "audio":
                continue

            # Relative path under generated/ (e.g. My_Project/2026-06-04 or uploads)
            rel = os.path.relpath(root, DOWNLOADS_DIR)
            folder = rel if rel != "." else ""

            try:
                stat = os.stat(fpath)
                mtime = stat.st_mtime
                size_bytes = stat.st_size
            except Exception:
                mtime = 0
                size_bytes = 0

            # Human-readable size
            if size_bytes < 1024:
                size_str = f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                size_str = f"{size_bytes / 1024:.1f} KB"
            else:
                size_str = f"{size_bytes / (1024 * 1024):.1f} MB"

            assets.append({
                "path": fpath,
                "name": fname,
                "type": ftype,
                "ext": ext,
                "size": size_bytes,
                "size_str": size_str,
                "date": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"),
                "date_short": datetime.fromtimestamp(mtime).strftime("%m/%d"),
                "folder": folder,
                "mtime": mtime,
            })

    assets.sort(key=lambda x: x["mtime"], reverse=True)
    return assets
