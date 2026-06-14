"""Clip bundle filenames — Finder sort order: video, last frame, json, txt.

Alphabetical order under the same stem:
  {stem}.mp4
  {stem}_last.png
  {stem}_meta.json
  {stem}_meta.txt
"""

from __future__ import annotations

import json
import os
import shutil

from arkitect.shared import GENERATED_RESERVED_DIRS, _GENERATED_DIR

META_JSON_NAME = "_meta.json"
META_TXT_NAME = "_meta.txt"
LAST_FRAME_NAME = "_last.png"
LEGACY_SETTINGS_NAME = "_settings.json"


def clip_stem(path: str) -> str:
    return os.path.splitext(path)[0]


def clip_meta_json_path(media_path: str) -> str:
    return clip_stem(media_path) + META_JSON_NAME


def clip_meta_txt_path(media_path: str) -> str:
    return clip_stem(media_path) + META_TXT_NAME


def clip_last_frame_path(video_path: str) -> str:
    return clip_stem(video_path) + LAST_FRAME_NAME


def resolve_meta_json_path(media_path: str) -> str:
    stem = clip_stem(media_path)
    new_path = stem + META_JSON_NAME
    legacy = stem + LEGACY_SETTINGS_NAME
    if os.path.isfile(new_path):
        return new_path
    if os.path.isfile(legacy):
        return legacy
    return new_path


def resolve_meta_txt_path(media_path: str) -> str:
    stem = clip_stem(media_path)
    new_path = stem + META_TXT_NAME
    legacy = stem + ".txt"
    if os.path.isfile(new_path):
        return new_path
    if os.path.isfile(legacy):
        return legacy
    return new_path


def _rename_if_needed(src: str, dest: str) -> bool:
    if not src or not os.path.isfile(src):
        return False
    if os.path.normpath(src) == os.path.normpath(dest):
        return False
    if os.path.exists(dest):
        try:
            if os.path.getsize(dest) == os.path.getsize(src):
                os.remove(src)
                return True
        except OSError:
            pass
        base, ext = os.path.splitext(dest)
        n = 1
        while os.path.exists(dest):
            dest = f"{base}_renamed{n}{ext}"
            n += 1
    shutil.move(src, dest)
    return True


def migrate_clip_bundle_names(*, dry_run: bool = False) -> dict:
    """Rename legacy .txt and _settings.json to _meta.* for sort order."""
    renamed = 0
    stems_touched: set[str] = set()

    for project in os.listdir(_GENERATED_DIR):
        proj_dir = os.path.join(_GENERATED_DIR, project)
        if not os.path.isdir(proj_dir) or project in GENERATED_RESERVED_DIRS:
            continue
        for date_name in os.listdir(proj_dir):
            if not (len(date_name) == 10 and date_name[4] == "-" and date_name[7] == "-"):
                continue
            date_dir = os.path.join(proj_dir, date_name)
            if not os.path.isdir(date_dir):
                continue
            for fname in os.listdir(date_dir):
                path = os.path.join(date_dir, fname)
                if not os.path.isfile(path) or fname.endswith(".arkitect-rating"):
                    continue
                stem = None
                if fname.endswith(".mp4") or fname.endswith(".mov") or fname.endswith(".webm"):
                    stem = clip_stem(path)
                elif fname.endswith(".png") and not fname.endswith(LAST_FRAME_NAME):
                    stem = clip_stem(path)
                if not stem:
                    continue
                if stem in stems_touched:
                    continue
                stems_touched.add(stem)

                legacy_txt = stem + ".txt"
                new_txt = stem + META_TXT_NAME
                legacy_json = stem + LEGACY_SETTINGS_NAME
                new_json = stem + META_JSON_NAME

                for src, dest in ((legacy_txt, new_txt), (legacy_json, new_json)):
                    if dry_run:
                        if os.path.isfile(src) and os.path.normpath(src) != os.path.normpath(dest):
                            renamed += 1
                    else:
                        if _rename_if_needed(src, dest):
                            renamed += 1

    db_updated = 0
    if not dry_run and renamed:
        db_updated = _rewrite_gallery_sidecar_paths()

    return {"renamed": renamed, "stems": len(stems_touched), "db_updated": db_updated}


def _rewrite_gallery_sidecar_paths() -> int:
    from arkitect.storage import GALLERY_FILE
    import copy

    if not os.path.isfile(GALLERY_FILE):
        return 0
    with open(GALLERY_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    new_data = copy.deepcopy(data)
    changed = False

    def _fix_item(item: dict) -> None:
        nonlocal changed
        if not isinstance(item, dict):
            return
        for field in ("settings_sidecar_path", "info_file_path"):
            old = item.get(field) or ""
            if not old:
                continue
            new = old
            if old.endswith(LEGACY_SETTINGS_NAME):
                new = clip_stem(old) + META_JSON_NAME
            elif old.endswith(".txt") and not old.endswith(META_TXT_NAME):
                new = clip_stem(old) + META_TXT_NAME
            if new != old:
                item[field] = new
                changed = True
        vp = item.get("video_path") or item.get("image_path") or ""
        if vp and not item.get("settings_sidecar_path"):
            meta = clip_meta_json_path(vp)
            if os.path.isfile(meta):
                item["settings_sidecar_path"] = meta
                changed = True

    for bucket in ("videos", "images"):
        for item in new_data.get(bucket) or []:
            _fix_item(item)

    if changed:
        with open(GALLERY_FILE, "w", encoding="utf-8") as f:
            json.dump(new_data, f, ensure_ascii=False, indent=0)
    return 1 if changed else 0


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Rename clip sidecars for Finder sort order.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(migrate_clip_bundle_names(dry_run=args.dry_run), indent=2))


if __name__ == "__main__":
    main()
