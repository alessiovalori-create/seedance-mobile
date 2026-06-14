"""One-time migration: generated/{date}/ -> generated/{project}/{date}/.

Also normalizes legacy downloads/{date}/ paths into data/generated/{project}/{date}/.
Updates gallery, snapshots, ratings, and assets catalog paths.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
from datetime import datetime

from arkitect.shared import (
    _DB_DIR,
    _GENERATED_DIR,
    _PERSIST_DIR,
    sanitize_project_dir_name,
)

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LEGACY_DOWNLOADS_DIR = os.path.join(_APP_DIR, "downloads")

_DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PATH_FIELDS = (
    "video_path",
    "image_path",
    "last_frame_path",
    "info_file_path",
    "path",
    "src",
)
_PROVENANCE_FIELDS = ("gallery_source_path", "source_path")

_DB_FILES = (
    ("gallery.json", None),
    ("snapshots.json", None),
    ("assets_catalog.json", None),
    ("ratings.json", None),
)


def _norm(path: str) -> str:
    if not path:
        return ""
    return os.path.normpath(os.path.abspath(path))


def _is_date_dir(name: str) -> bool:
    return bool(_DATE_DIR_RE.match(name or ""))


def _load_project_slug_map() -> dict[str, str]:
    projects_file = os.path.join(_DB_DIR, "projects.json")
    out: dict[str, str] = {}
    if not os.path.exists(projects_file):
        return out
    try:
        with open(projects_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        for proj in data.get("projects") or []:
            pid = proj.get("id")
            if pid:
                out[str(pid)] = sanitize_project_dir_name(proj.get("name"))
    except Exception:
        pass
    return out


def _project_slug_for_item(item: dict, project_map: dict[str, str]) -> str:
    if not isinstance(item, dict):
        return "general"
    pid = item.get("project_id")
    if pid and pid in project_map:
        return project_map[pid]
    return "general"


def _register_path(mapping: dict[str, str], old_path: str, project_slug: str) -> None:
    old_path = (old_path or "").strip()
    if not old_path or old_path.startswith("http"):
        return
    abs_path = _norm(old_path)
    if not abs_path:
        return
    mapping.setdefault(abs_path, project_slug)


def _build_path_project_map(project_map: dict[str, str]) -> dict[str, str]:
    """Map absolute legacy file paths -> project folder slug."""
    out: dict[str, str] = {}

    gallery_file = os.path.join(_DB_DIR, "gallery.json")
    if os.path.exists(gallery_file):
        with open(gallery_file, "r", encoding="utf-8") as f:
            gallery = json.load(f)
        for bucket_key in ("videos", "images"):
            for item in gallery.get(bucket_key) or []:
                slug = _project_slug_for_item(item, project_map)
                for field in _PATH_FIELDS:
                    _register_path(out, item.get(field) or "", slug)
                prov = item.get("provenance") or {}
                for field in _PROVENANCE_FIELDS:
                    _register_path(out, prov.get(field) or "", slug)

    snapshots_file = os.path.join(_DB_DIR, "snapshots.json")
    if os.path.exists(snapshots_file):
        with open(snapshots_file, "r", encoding="utf-8") as f:
            snaps = json.load(f)
        for bucket in (snaps or {}).values():
            if not isinstance(bucket, dict):
                continue
            for entry in bucket.values():
                entry_slug = "general"
                if isinstance(entry, dict):
                    entry_slug = _project_slug_for_item(entry, project_map)
                    items = entry.get("items") or []
                elif isinstance(entry, list):
                    items = entry
                else:
                    items = []
                for item in items:
                    slug = _project_slug_for_item(item, project_map)
                    if slug == "general":
                        slug = entry_slug
                    for field in _PATH_FIELDS:
                        _register_path(out, item.get(field) or "", slug)

    assets_file = os.path.join(_DB_DIR, "assets_catalog.json")
    if os.path.exists(assets_file):
        with open(assets_file, "r", encoding="utf-8") as f:
            catalog = json.load(f)
        for asset in catalog or []:
            slug = _project_slug_for_item(asset, project_map)
            _register_path(out, asset.get("path") or "", slug)
            prov = asset.get("provenance") or {}
            for field in _PROVENANCE_FIELDS:
                _register_path(out, prov.get(field) or "", slug)

    return out


def _legacy_roots() -> list[str]:
    roots = [_GENERATED_DIR]
    if os.path.isdir(_LEGACY_DOWNLOADS_DIR):
        roots.append(_LEGACY_DOWNLOADS_DIR)
    return roots


def _relocate_key(old_abs: str, new_abs: str, path_rewrites: dict[str, str]) -> None:
    path_rewrites[_norm(old_abs)] = _norm(new_abs)


def _backup_db_files() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(_DB_DIR, f"migration_backup_{stamp}")
    os.makedirs(backup_dir, exist_ok=True)
    for fname, _ in _DB_FILES:
        src = os.path.join(_DB_DIR, fname)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(backup_dir, fname))
    return backup_dir


def _default_project_slug(project_map: dict[str, str]) -> str:
    projects_file = os.path.join(_DB_DIR, "projects.json")
    if os.path.exists(projects_file):
        try:
            with open(projects_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            active_id = data.get("active_project_id")
            if active_id and active_id in project_map:
                return project_map[active_id]
            projects = data.get("projects") or []
            if len(projects) == 1 and projects[0].get("id") in project_map:
                return project_map[projects[0]["id"]]
        except Exception:
            pass
    if project_map:
        return next(iter(project_map.values()))
    return "general"


def _project_slug_for_date_folder(
    date_name: str,
    file_paths: list[str],
    path_project_map: dict[str, str],
    project_map: dict[str, str],
) -> str:
    """Pick one project folder for an entire date directory (no per-file split)."""
    counts: dict[str, int] = {}
    for src in file_paths:
        slug = path_project_map.get(_norm(src))
        if slug:
            counts[slug] = counts.get(slug, 0) + 1
    if counts:
        non_general = {k: v for k, v in counts.items() if k != "general"}
        pool = non_general or counts
        return max(pool.items(), key=lambda kv: kv[1])[0]
    return _default_project_slug(project_map)


def _move_file_to_dest(
    canonical_src: str,
    sources: list[str],
    dest_path: str,
    path_rewrites: dict[str, str],
    *,
    dry_run: bool,
) -> str:
    """Move one file; return 'moved', 'skipped', or 'error:...'."""
    dest_norm = _norm(dest_path)
    if _norm(canonical_src) == dest_norm:
        for s in sources:
            _relocate_key(s, dest_path, path_rewrites)
        return "skipped"

    if os.path.exists(dest_path):
        try:
            if os.path.getsize(dest_path) == os.path.getsize(canonical_src):
                for s in sources:
                    _relocate_key(s, dest_path, path_rewrites)
                return "skipped"
        except OSError:
            pass

    if dry_run:
        for s in sources:
            _relocate_key(s, dest_path, path_rewrites)
        return "moved"

    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        if os.path.exists(dest_path):
            base, ext = os.path.splitext(os.path.basename(dest_path))
            n = 1
            while os.path.exists(dest_path):
                dest_path = os.path.join(os.path.dirname(dest_path), f"{base}_mig{n}{ext}")
                n += 1
        shutil.move(canonical_src, dest_path)
        for s in sources:
            _relocate_key(s, dest_path, path_rewrites)
        return "moved"
    except Exception as exc:
        return f"error:{canonical_src} -> {dest_path}: {exc}"


def migrate_generated_layout(*, dry_run: bool = False) -> dict:
    project_map = _load_project_slug_map()
    path_project_map = _build_path_project_map(project_map)
    path_rewrites: dict[str, str] = {}
    moved = 0
    skipped = 0
    errors: list[str] = []

    # Group by date folder — entire date dir goes under ONE project slug.
    date_buckets: dict[str, list[tuple[str, list[str]]]] = {}
    for root in _legacy_roots():
        if not os.path.isdir(root):
            continue
        for name in os.listdir(root):
            if not _is_date_dir(name):
                continue
            date_dir = os.path.join(root, name)
            for fname in os.listdir(date_dir):
                src = os.path.join(date_dir, fname)
                if not os.path.isfile(src):
                    continue
                date_buckets.setdefault(name, []).append((fname, [src]))

    # Merge duplicate (date, fname) from downloads + generated roots
    pending: dict[tuple[str, str], list[str]] = {}
    all_paths_by_date: dict[str, list[str]] = {}
    for date_name, entries in date_buckets.items():
        for fname, sources in entries:
            key = (date_name, fname)
            pending.setdefault(key, [])
            for s in sources:
                if _norm(s) not in {_norm(x) for x in pending[key]}:
                    pending[key].append(s)
            all_paths_by_date.setdefault(date_name, []).extend(sources)

    date_project: dict[str, str] = {}
    for date_name, paths in all_paths_by_date.items():
        date_project[date_name] = _project_slug_for_date_folder(
            date_name, paths, path_project_map, project_map
        )

    for (date_name, fname), sources in sorted(pending.items()):
        sources = sorted(set(_norm(s) for s in sources))
        canonical_src = None
        for s in sources:
            if s.startswith(_norm(_GENERATED_DIR) + os.sep):
                canonical_src = s
                break
        if canonical_src is None:
            canonical_src = sources[0]

        project_slug = date_project.get(date_name) or _default_project_slug(project_map)
        dest_dir = os.path.join(_GENERATED_DIR, project_slug, date_name)
        dest_path = os.path.join(dest_dir, fname)

        result = _move_file_to_dest(
            canonical_src, sources, dest_path, path_rewrites, dry_run=dry_run
        )
        if result == "moved":
            moved += 1
        elif result == "skipped":
            skipped += 1
        elif result.startswith("error:"):
            errors.append(result[6:])

    db_updated = 0
    backup_dir = None
    if path_rewrites and not dry_run:
        backup_dir = _backup_db_files()
        db_updated = _rewrite_database_paths(path_rewrites)

    if not dry_run:
        _remove_empty_legacy_date_dirs()

    return {
        "moved": moved,
        "skipped": skipped,
        "path_rewrites": len(path_rewrites),
        "db_updated": db_updated,
        "backup_dir": backup_dir,
        "errors": errors,
    }


def _remove_empty_legacy_date_dirs() -> None:
    for root in _legacy_roots():
        if not os.path.isdir(root):
            continue
        for name in os.listdir(root):
            if not _is_date_dir(name):
                continue
            date_dir = os.path.join(root, name)
            try:
                if os.path.isdir(date_dir) and not os.listdir(date_dir):
                    os.rmdir(date_dir)
            except OSError:
                pass


def _rewrite_string(value: str, path_rewrites: dict[str, str]) -> str:
    if not value or value.startswith("http"):
        return value
    norm = _norm(value)
    if norm in path_rewrites:
        return path_rewrites[norm]
    return value


def _rewrite_obj(obj, path_rewrites: dict[str, str]):
    if isinstance(obj, dict):
        for key, value in list(obj.items()):
            if isinstance(value, str):
                if key in _PATH_FIELDS or key in _PROVENANCE_FIELDS:
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
    if not isinstance(data, dict):
        return data
    out = {}
    for key, value in data.items():
        if key.startswith("path:") and ":" in key:
            parts = key.split(":", 2)
            if len(parts) == 3:
                new_path = path_rewrites.get(_norm(parts[2]))
                if new_path:
                    key = f"{parts[0]}:{parts[1]}:{new_path}"
        out[key] = value
    return out


def _rewrite_database_paths(path_rewrites: dict[str, str]) -> int:
    updated = 0
    for fname, _ in _DB_FILES:
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
                json.dump(new_data, f, ensure_ascii=False, indent=0 if fname != "projects.json" else 2)
            updated += 1
    return updated


def rewrite_database_paths_from_disk() -> dict[str, str]:
    """Rebuild path rewrites from current layout (after files were already moved)."""
    project_map = _load_project_slug_map()
    path_project_map = _build_path_project_map(project_map)
    path_rewrites: dict[str, str] = {}

    for root in _legacy_roots():
        if not os.path.isdir(root):
            continue
        for name in os.listdir(root):
            if not _is_date_dir(name):
                continue
            date_dir = os.path.join(root, name)
            for fname in os.listdir(date_dir):
                src = os.path.join(date_dir, fname)
                if not os.path.isfile(src):
                    continue
                slug = path_project_map.get(_norm(src), "general")
                dest = os.path.join(_GENERATED_DIR, slug, name, fname)
                _relocate_key(src, dest, path_rewrites)

    for project in os.listdir(_GENERATED_DIR):
        proj_dir = os.path.join(_GENERATED_DIR, project)
        if not os.path.isdir(proj_dir) or _is_date_dir(project):
            continue
        if project in ("assets", "references", "exports", "uploads", "_assets"):
            continue
        for date_name in os.listdir(proj_dir):
            if not _is_date_dir(date_name):
                continue
            date_dir = os.path.join(proj_dir, date_name)
            for fname in os.listdir(date_dir):
                dest = os.path.join(date_dir, fname)
                if not os.path.isfile(dest):
                    continue
                legacy_gen = os.path.join(_GENERATED_DIR, date_name, fname)
                legacy_dl = os.path.join(_LEGACY_DOWNLOADS_DIR, date_name, fname)
                _relocate_key(legacy_gen, dest, path_rewrites)
                _relocate_key(legacy_dl, dest, path_rewrites)
    return path_rewrites


def rewrite_paths_only() -> dict:
    path_rewrites = rewrite_database_paths_from_disk()
    backup_dir = _backup_db_files()
    db_updated = _rewrite_database_paths(path_rewrites)
    return {
        "path_rewrites": len(path_rewrites),
        "db_updated": db_updated,
        "backup_dir": backup_dir,
    }


def merge_project_folders(source_slug: str, target_slug: str, *, dry_run: bool = False) -> dict:
    """Move all date folders from source_slug into target_slug (keeps dates intact)."""
    src_root = os.path.join(_GENERATED_DIR, source_slug)
    dst_root = os.path.join(_GENERATED_DIR, target_slug)
    path_rewrites: dict[str, str] = {}
    moved = 0
    skipped = 0
    errors: list[str] = []

    if not os.path.isdir(src_root):
        return {"moved": 0, "skipped": 0, "errors": [f"Source not found: {src_root}"]}

    for date_name in sorted(os.listdir(src_root)):
        if not _is_date_dir(date_name):
            continue
        src_date = os.path.join(src_root, date_name)
        if not os.path.isdir(src_date):
            continue
        for fname in os.listdir(src_date):
            src = os.path.join(src_date, fname)
            if not os.path.isfile(src):
                continue
            dest = os.path.join(dst_root, date_name, fname)
            legacy_gen = os.path.join(_GENERATED_DIR, date_name, fname)
            legacy_dl = os.path.join(_LEGACY_DOWNLOADS_DIR, date_name, fname)
            sources = sorted({_norm(src), _norm(legacy_gen), _norm(legacy_dl)})
            result = _move_file_to_dest(
                _norm(src), sources, dest, path_rewrites, dry_run=dry_run
            )
            if result == "moved":
                moved += 1
            elif result == "skipped":
                skipped += 1
            elif result.startswith("error:"):
                errors.append(result[6:])

    db_updated = 0
    backup_dir = None
    if path_rewrites and not dry_run:
        backup_dir = _backup_db_files()
        db_updated = _rewrite_database_paths(path_rewrites)
        try:
            if os.path.isdir(src_root) and not os.listdir(src_root):
                os.rmdir(src_root)
            else:
                for date_name in os.listdir(src_root):
                    date_dir = os.path.join(src_root, date_name)
                    if os.path.isdir(date_dir) and not os.listdir(date_dir):
                        os.rmdir(date_dir)
                if os.path.isdir(src_root) and not os.listdir(src_root):
                    os.rmdir(src_root)
        except OSError:
            pass

    return {
        "source": source_slug,
        "target": target_slug,
        "moved": moved,
        "skipped": skipped,
        "path_rewrites": len(path_rewrites),
        "db_updated": db_updated,
        "backup_dir": backup_dir,
        "errors": errors,
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Migrate generated/ date folders into project subfolders.")
    parser.add_argument("--dry-run", action="store_true", help="Report actions without moving files.")
    parser.add_argument(
        "--rewrite-db-only",
        action="store_true",
        help="Only rewrite JSON database paths (files already migrated).",
    )
    parser.add_argument(
        "--merge-into",
        nargs=2,
        metavar=("SOURCE", "TARGET"),
        help="Merge project folder SOURCE into TARGET (e.g. general PROCIDA).",
    )
    args = parser.parse_args()
    if args.merge_into:
        result = merge_project_folders(args.merge_into[0], args.merge_into[1], dry_run=args.dry_run)
    elif args.rewrite_db_only:
        result = rewrite_paths_only()
    else:
        result = migrate_generated_layout(dry_run=args.dry_run)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
