"""Consolidate assets, references, exports and loose files under data/generated/."""

from __future__ import annotations

import copy
import json
import os
import shutil
from datetime import datetime

from arkitect.shared import (
    GENERATED_RESERVED_DIRS,
    _APP_DIR,
    _ASSETS_DIR,
    _DB_DIR,
    _GENERATED_DIR,
    _PERSIST_DIR,
    _REFERENCES_DIR,
)

_LEGACY_ASSETS = os.path.join(_PERSIST_DIR, "assets")
_LEGACY_REFERENCES = os.path.join(_PERSIST_DIR, "references")
_LEGACY_GENERATED_ASSETS = os.path.join(_GENERATED_DIR, "_assets")
_REPO_ASSETS = os.path.join(_APP_DIR, "assets")

_MEDIA_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".mov", ".webm", ".mp3", ".wav"}

_DB_FILES = (
    "gallery.json",
    "snapshots.json",
    "assets_catalog.json",
    "ratings.json",
)


def _norm(path: str) -> str:
    return os.path.normpath(os.path.abspath(path)) if path else ""


def _backup_db() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(_DB_DIR, f"storage_migration_backup_{stamp}")
    os.makedirs(backup_dir, exist_ok=True)
    for fname in _DB_FILES:
        src = os.path.join(_DB_DIR, fname)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(backup_dir, fname))
    return backup_dir


def _merge_tree(src_root: str, dst_root: str, path_rewrites: dict[str, str], *, dry_run: bool) -> int:
    """Merge src_root into dst_root, recording absolute path rewrites."""
    moved = 0
    if not os.path.isdir(src_root):
        return 0
    for root, _dirs, files in os.walk(src_root):
        for fname in files:
            if fname.startswith("."):
                continue
            src = os.path.join(root, fname)
            if not os.path.isfile(src):
                continue
            rel = os.path.relpath(src, src_root)
            dest = os.path.join(dst_root, rel)
            path_rewrites[_norm(src)] = _norm(dest)
            if _norm(src) == _norm(dest):
                continue
            if dry_run:
                moved += 1
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if os.path.exists(dest):
                try:
                    if os.path.getsize(dest) == os.path.getsize(src):
                        continue
                except OSError:
                    pass
                base, ext = os.path.splitext(dest)
                n = 1
                while os.path.exists(dest):
                    dest = f"{base}_mig{n}{ext}"
                    n += 1
                path_rewrites[_norm(src)] = _norm(dest)
            shutil.move(src, dest)
            moved += 1
    return moved


def _rewrite_string(value: str, path_rewrites: dict[str, str]) -> str:
    if not value or value.startswith("http"):
        return value
    norm = _norm(value)
    if norm in path_rewrites:
        return path_rewrites[norm]
    for old, new in path_rewrites.items():
        if old in norm:
            return norm.replace(old, new)
    return value


def _rewrite_obj(obj, path_rewrites: dict[str, str]) -> None:
    path_fields = {
        "video_path", "image_path", "last_frame_path", "info_file_path",
        "path", "src", "gallery_source_path", "source_path",
    }
    if isinstance(obj, dict):
        for key, value in list(obj.items()):
            if isinstance(value, str) and key in path_fields:
                obj[key] = _rewrite_string(value, path_rewrites)
            else:
                _rewrite_obj(value, path_rewrites)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            if isinstance(value, str):
                obj[i] = _rewrite_string(value, path_rewrites)
            else:
                _rewrite_obj(value, path_rewrites)


def _rewrite_ratings(data: dict, path_rewrites: dict[str, str]) -> dict:
    out = {}
    for key, value in data.items():
        if key.startswith("path:") and key.count(":") >= 2:
            prefix, kind, raw = key.split(":", 2)
            new_path = path_rewrites.get(_norm(raw), _rewrite_string(raw, path_rewrites))
            key = f"{prefix}:{kind}:{new_path}"
        out[key] = value
    return out


def _rewrite_databases(path_rewrites: dict[str, str]) -> int:
    updated = 0
    for fname in _DB_FILES:
        fpath = os.path.join(_DB_DIR, fname)
        if not os.path.exists(fpath):
            continue
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if fname == "ratings.json":
            new_data = _rewrite_ratings(copy.deepcopy(data), path_rewrites)
        else:
            new_data = copy.deepcopy(data)
            _rewrite_obj(new_data, path_rewrites)
        if new_data != data:
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(new_data, f, ensure_ascii=False, indent=0)
            updated += 1
    return updated


def _relocate_loose_generated_files(path_rewrites: dict[str, str], *, dry_run: bool) -> int:
    """Move stray media files sitting directly in generated/ into references/."""
    moved = 0
    for fname in os.listdir(_GENERATED_DIR):
        src = os.path.join(_GENERATED_DIR, fname)
        if not os.path.isfile(src):
            continue
        ext = os.path.splitext(fname)[1].lower()
        if ext not in _MEDIA_EXTS:
            continue
        dest = os.path.join(_REFERENCES_DIR, fname)
        path_rewrites[_norm(src)] = _norm(dest)
        if dry_run:
            moved += 1
            continue
        if os.path.exists(dest):
            base, ext_s = os.path.splitext(fname)
            n = 1
            while os.path.exists(dest):
                dest = os.path.join(_REFERENCES_DIR, f"{base}_mig{n}{ext_s}")
                n += 1
            path_rewrites[_norm(src)] = _norm(dest)
        shutil.move(src, dest)
        moved += 1
    return moved


def _remove_empty_dirs(root: str) -> None:
    if not os.path.isdir(root):
        return
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if os.path.isdir(path):
            _remove_empty_dirs(path)
    try:
        if not os.listdir(root):
            os.rmdir(root)
    except OSError:
        pass


def _ensure_compat_symlink(link_path: str, target_path: str) -> None:
    """Optional symlink at legacy location pointing to new path."""
    if os.path.islink(link_path):
        if _norm(os.path.realpath(link_path)) == _norm(target_path):
            return
        os.remove(link_path)
    elif os.path.isdir(link_path):
        _remove_empty_dirs(link_path)
        if os.path.isdir(link_path):
            return
    try:
        os.symlink(target_path, link_path, target_is_directory=True)
    except OSError:
        pass


def migrate_storage_layout(*, dry_run: bool = False) -> dict:
    path_rewrites: dict[str, str] = {}
    moved = 0

    sources = [
        (_LEGACY_ASSETS, _ASSETS_DIR),
        (_LEGACY_REFERENCES, _REFERENCES_DIR),
        (_LEGACY_GENERATED_ASSETS, _ASSETS_DIR),
        (_REPO_ASSETS, _ASSETS_DIR),
    ]
    for src, dst in sources:
        moved += _merge_tree(src, dst, path_rewrites, dry_run=dry_run)

    moved += _relocate_loose_generated_files(path_rewrites, dry_run=dry_run)

    backup_dir = None
    db_updated = 0
    if path_rewrites and not dry_run:
        backup_dir = _backup_db()
        db_updated = _rewrite_databases(path_rewrites)
        _ensure_compat_symlink(_LEGACY_ASSETS, _ASSETS_DIR)
        _ensure_compat_symlink(_LEGACY_REFERENCES, _REFERENCES_DIR)
        for src, _dst in sources:
            if os.path.isdir(src):
                try:
                    if not os.listdir(src):
                        os.rmdir(src)
                except OSError:
                    pass
        if os.path.isdir(_LEGACY_GENERATED_ASSETS):
            try:
                shutil.rmtree(_LEGACY_GENERATED_ASSETS)
            except OSError:
                pass

    return {
        "moved": moved,
        "path_rewrites": len(path_rewrites),
        "db_updated": db_updated,
        "backup_dir": backup_dir,
        "targets": {
            "assets": _ASSETS_DIR,
            "references": _REFERENCES_DIR,
            "exports": os.path.join(_GENERATED_DIR, "exports"),
            "uploads": os.path.join(_GENERATED_DIR, "uploads"),
            "reserved": sorted(GENERATED_RESERVED_DIRS),
        },
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Consolidate assets/references under generated/.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(migrate_storage_layout(dry_run=args.dry_run), indent=2))


if __name__ == "__main__":
    main()
