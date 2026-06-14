import json
import os
from datetime import datetime

import streamlit as st

from arkitect.shared import _DB_DIR, AssetFile, CachedUploadedFile
from arkitect.storage import load_projects

_CONSOLE_FILE_AND_ASSET_PICKER_KEYS = frozenset({
    "s2_first_frame", "s2_assets_first_frame", "s2_last_frame", "s2_assets_last_frame",
    "s2_first_only", "s2_assets_first_only", "s2_images", "s2_assets_images",
    "s2_videos", "s2_assets_videos", "s2_audio", "s2_assets_audio",
    "sd_refs_upload", "sd_assets_refs",
})


def _console_session_state_assign_forbidden(k: str) -> bool:
    """Streamlit forbids assigning session_state for st.button / file_uploader / camera_input keys."""
    if not k:
        return True
    if k in _CONSOLE_FILE_AND_ASSET_PICKER_KEYS:
        return True
    lk = k.lower()
    if "btn" in lk:
        return True
    if "add_c_" in k:
        return True
    if "add_motions_" in k:
        return True
    if "_production_opt" in k:
        return True
    if "preview_prompt_btn" in k or "preview_btn" in lk:
        return True
    if "_analyze_" in k:
        return True
    if "uploader" in lk or "upload" in lk:
        return True
    return False


def _clear_console_prompts_for_project_change():
    """When switching projects, clear prompts/results only (not technical parameters)."""
    for k in (
        "s2_opt_prompt", "s2_raw_prompt",
        "sd_opt_prompt", "sd_raw_prompt", "json_preview", "_json_dict",
        "s2_last_result", "sd_last_result", "show_generate_button",
        "_cached_s2_first_frame", "_cached_s2_last_frame", "_cached_s2_first_only",
        "_cached_s2_images", "_cached_s2_videos", "_cached_s2_audio",
        "_cached_sd_refs",
        "_s2_img_saved_names", "_s2_vid_saved_names", "_s2_aud_saved_names",
        "_sd_ref_saved_names",
        "_console_ref_tag_map",
    ):
        st.session_state.pop(k, None)


def _console_snapshot_key_list():
    """Keys to snapshot/restore across page navigation (Streamlit drops undisplayed widget state)."""
    keys = set()

    keys.update([
        "model_selector",
        "action_desc_s2", "sd_prompt_input",
        "s2_entry_point", "s2_workflow", "s2_workflow_fl", "s2_workflow_ff",
        "s2_image_usage",
        "sd_style_select",
    ])

    # File upload / asset-picker keys: do not del or assign via session_state (Streamlit restriction).

    keys.update([
        "s2_raw_prompt", "s2_opt_prompt", "s2_last_result",
        "sd_raw_prompt", "sd_opt_prompt", "sd_last_result",
        "json_preview", "_json_dict",
        "show_generate_button",
        "_do_preview_s2", "_do_preview_sd",
        "_do_generate_s2", "_do_generate_sd",
        "_preview_feedback",
        "canvas_prompt_editor", "canvas_json_viewer",
        "vision_context",
    ])

    keys.update([
        "video_resolution", "video_aspect_ratio", "common_duration",
        "s2_speed_mode", "s2_seed_mode", "s2_last_seed", "s2_seed_manual",
        "sd_resolution", "sd_ar_select",
        "sd_optimize", "sd_num_variations", "sd_variation_mode", "enforce_stability",
        "enable_audio", "s2_audio_output",
        "v_lang", "v_emo", "v_timbre", "v_pace",
        "s2_dialogue", "s2_sfx",
    ])
    for i in range(15):
        keys.update([f"sd_seed_input_{i}"])

    keys.update([
        "sd_shot_type", "sd_mood", "sd_period",
        "sd_camera", "sd_lenses", "sd_film_stock", "sd_sensor",
        "sd_light_src", "sd_light_dir", "sd_light_type",
    ])

    keys.update([
        "_persist_s2_assets_images",
        "_persist_s2_assets_videos",
        "_persist_s2_assets_audio",
        "_persist_s2_assets_first_frame",
        "_persist_s2_assets_last_frame",
        "_persist_s2_assets_first_only",
        "_persist_sd_assets_refs",
    ])

    keys.update(["en_s2", "en_s3"])

    for prefix in ["s"]:
        for shot_n in range(1, 4):
            k = f"{prefix}{shot_n}"
            keys.update([
                f"{k}_assets",
                f"{k}_shot_type", f"{k}_style", f"{k}_mood", f"{k}_period",
                f"{k}_camera", f"{k}_lenses", f"{k}_film_stock", f"{k}_sensor",
                f"{k}_light_src", f"{k}_light_dir", f"{k}_light",
                f"{k}_pill_grain", f"{k}_pill_vignette", f"{k}_pill_focus", f"{k}_pill_dof",
                f"{k}_pill_brightness", f"{k}_pill_contrast", f"{k}_pill_saturation",
                f"{k}_pill_temperature", f"{k}_pill_chromatic", f"{k}_pill_motion",
                f"{k}_vfx_a", f"{k}_vfx_e",
                f"{k}_m1_type", f"{k}_m1_pace", f"{k}_m1_s", f"{k}_m1_e",
                f"{k}_m1_ca", f"{k}_m1_so",
                f"{k}_m2_type", f"{k}_m2_pace", f"{k}_m2_s", f"{k}_m2_e",
                f"{k}_m2_ca", f"{k}_m2_so",
                f"show_secondary_{k}",
                f"color_count_{k}",
            ])
            for ci in range(3):
                keys.update([f"{k}_c_hex_{ci}", f"{k}_c_tar_{ci}"])

    return list(keys)


_CONSOLE_SNAPSHOT_SKIP = frozenset({
    "s2_first_frame", "s2_assets_first_frame",
    "s2_last_frame", "s2_assets_last_frame",
    "s2_first_only", "s2_assets_first_only",
    "s2_images", "s2_assets_images",
    "s2_videos", "s2_assets_videos",
    "s2_audio", "s2_assets_audio",
    "sd_refs_upload", "sd_assets_refs",
    "show_generate_button",
    "_do_preview_s2", "_do_preview_sd",
    "_do_generate_s2", "_do_generate_sd",
    "_preview_feedback",
    "canvas_prompt_editor", "canvas_json_viewer",
    "s2_last_result", "sd_last_result",
    "_console_reset_pending",
    "_console_param_snapshot",
})


def _project_settings_path(project_id):
    """Return path to per-project Console settings JSON file."""
    if not project_id:
        return None
    _dir = os.path.join(_DB_DIR, "project_settings")
    os.makedirs(_dir, exist_ok=True)
    # project_id is a slug/uuid; safe for filename
    safe_id = str(project_id).replace("/", "_").replace("\\", "_")
    return os.path.join(_dir, f"{safe_id}.json")


def _default_console_params():
    """Return the default Console parameter set used for new projects
    and for migrating legacy projects without a settings file.
    Keep this in sync with the if-not-in-session-state defaults at
    the top of the main render loop."""
    defaults = {
        "video_resolution": "1080p",
        "video_aspect_ratio": "adaptive",
        "common_duration": 15,
        "s2_smart_duration": False,
        "s2_watermark": False,
        "s2_speed_mode": "Standard",
        "s2_seed_mode": "🎲 New variation",
        "enable_audio": False,
        "en_s2": False,
        "en_s3": False,
        # Matches LIST_LANGUAGES[0] / LIST_EMOTIONS[0] in the main block
        "v_lang": "English",
        "v_emo": "Neutral",
        "v_timbre": "Normal",
        "v_pace": "Normal",
        "s2_entry_point": "All-in-One Reference",
        "s2_workflow": "Standard Generation",
        "s2_workflow_fl": "Standard Generation",
        "s2_workflow_ff": "Standard Generation",
        "sd_resolution": "3K",
        "sd_ar_select": "Smart",
        "sd_style_select": "None (Raw Prompt)",
        "sd_optimize": "None",
        "sd_num_variations": 1,
        "sd_variation_mode": "Independent (per seed)",
        "action_desc_s2": "",
        "sd_prompt_input": "",
    }
    return defaults


def _migrate_legacy_projects_to_per_project_settings():
    """One-shot migration: for any project in projects.json that does
    not yet have a per-project settings JSON file, create one populated
    with default values. Marker file prevents re-running."""
    marker = os.path.join(_DB_DIR, ".migration_per_project_v1_done")
    if os.path.isfile(marker):
        return
    try:
        proj_data = load_projects()
        projects = proj_data.get("projects", []) if isinstance(proj_data, dict) else []
    except Exception:
        projects = []
    for p in projects:
        if not isinstance(p, dict):
            continue
        pid = p.get("id")
        if not pid:
            continue
        path = _project_settings_path(pid)
        if not path or os.path.isfile(path):
            continue  # already has a settings file — leave it alone
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(_default_console_params(), f, indent=2, ensure_ascii=False)
        except OSError:
            continue
    try:
        with open(marker, "w", encoding="utf-8") as f:
            f.write(datetime.now().isoformat())
    except OSError:
        pass


def _save_project_console_settings(project_id=None):
    """Persist current Console params to the active project's JSON file.
    model_selector is excluded — it stays global."""
    pid = project_id or st.session_state.get("active_project_id")
    if not pid:
        return
    path = _project_settings_path(pid)
    if not path:
        return
    snap = {}
    for k in _console_snapshot_key_list():
        if k == "model_selector":
            continue  # Model is global, not per-project
        if k in _CONSOLE_SNAPSHOT_SKIP:
            continue
        if _console_session_state_assign_forbidden(k):
            continue
        if k not in st.session_state:
            continue
        val = st.session_state[k]
        # Only serialize JSON-safe primitives + lists/dicts of them
        try:
            json.dumps(val)
            snap[k] = val
        except (TypeError, ValueError):
            continue
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snap, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


def _load_project_console_settings(project_id):
    """Inject the given project's saved params into session_state.
    Existing live keys are OVERWRITTEN — switching projects means
    loading that project's exact state. model_selector is never
    touched (stays global)."""
    if not project_id:
        return
    path = _project_settings_path(project_id)
    if not path or not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(snap, dict):
        return
    for sk, sv in snap.items():
        if sk == "model_selector":
            continue
        if _console_session_state_assign_forbidden(sk):
            continue
        st.session_state[sk] = sv


def _delete_project_console_settings(project_id):
    """Delete the saved settings file for a project. Used by RESET."""
    if not project_id:
        return
    path = _project_settings_path(project_id)
    if not path:
        return
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def _save_console_param_snapshot():
    """Persist console params when leaving Console — Streamlit drops undisplayed widget keys."""
    snap = {}
    for k in _console_snapshot_key_list():
        if k in _CONSOLE_SNAPSHOT_SKIP:
            continue
        if _console_session_state_assign_forbidden(k):
            continue
        if k not in st.session_state:
            continue
        snap[k] = st.session_state[k]
    st.session_state["_console_param_snapshot"] = snap


def _restore_console_param_snapshot():
    """Re-inject snapshotted params when returning to Console.

    After navigating away, Streamlit may keep stale widget keys or drop them.
    When ``_console_was_away`` is set, overwrite session_state from the snapshot
    so cinematography params are not replaced by defaults.
    """
    if st.session_state.get("active_page") != "console":
        return
    was_away = st.session_state.pop("_console_was_away", False)
    snap = st.session_state.get("_console_param_snapshot")
    if not isinstance(snap, dict) or not snap:
        # Fall back to per-project JSON if in-memory snapshot is empty/corrupt
        pid = st.session_state.get("active_project_id")
        if pid and was_away:
            _load_project_console_settings(pid)
        return
    if was_away:
        st.session_state["_console_just_restored"] = True
    for sk, sv in snap.items():
        if _console_session_state_assign_forbidden(sk):
            continue
        if was_away or sk not in st.session_state:
            st.session_state[sk] = sv


def _clear_console_param_keys():
    """Remove all snapshotted console/cinematography keys (RESET)."""
    for k in _console_snapshot_key_list():
        if k in _CONSOLE_SNAPSHOT_SKIP:
            continue
        if _console_session_state_assign_forbidden(k):
            continue
        st.session_state.pop(k, None)


def _asset_picker_label(asset):
    return f"{asset['name']} ({asset.get('size_str', '')})"


def _cached_from_asset_catalog_entry(asset):
    """Build CachedUploadedFile from an assets catalog row."""
    path = asset.get("path") or ""
    if not path or not os.path.isfile(path):
        return None
    mime = asset.get("mime") or "image/jpeg"
    with open(path, "rb") as f:
        data = f.read()
    return CachedUploadedFile(asset["name"], data, mime)


def _console_file_from_asset(asset):
    """Console-ready file handle from a catalog row (images, videos, audio)."""
    path = asset.get("path") or ""
    if not path or not os.path.isfile(path):
        return None
    mime = asset.get("mime") or "application/octet-stream"
    atype = asset.get("type")
    if atype in ("video", "audio"):
        return AssetFile(path, asset["name"], mime)
    return _cached_from_asset_catalog_entry(asset)


def _tag_asset_names(tag_map: dict, asset: dict, tag: str) -> None:
    tag_map[asset["name"]] = tag
    orig = asset.get("original_name")
    if orig:
        tag_map[orig] = tag


def _ref_file_path(f) -> str:
    p = getattr(f, "_path", None) or ""
    if p and os.path.isfile(p):
        return os.path.abspath(p)
    return ""


def active_console_reference_lists():
    """File-like objects currently loaded as Console references (ordered)."""
    model = st.session_state.get("model_selector", "SEEDANCE 2.0")
    if model == "SEEDREAM 5.0":
        return list(st.session_state.get("_cached_sd_refs") or []), [], []

    entry = st.session_state.get("s2_entry_point", "All-in-One Reference")
    if entry == "First Frame":
        fo = st.session_state.get("_cached_s2_first_only")
        return ([fo] if fo else []), [], []
    if entry == "First and Last Frames":
        ff = st.session_state.get("_cached_s2_first_frame")
        lf = st.session_state.get("_cached_s2_last_frame")
        return [x for x in (ff, lf) if x], [], []

    if st.session_state.get("s2_workflow") == "Text to Video":
        return [], [], []

    return (
        list(st.session_state.get("_cached_s2_images") or []),
        list(st.session_state.get("_cached_s2_videos") or []),
        list(st.session_state.get("_cached_s2_audio") or []),
    )


def build_console_reference_tag_map(catalog: list | None = None) -> dict[str, str]:
    """Map catalog asset names → @Image/@Video/@Audio N for active console refs."""
    imgs, vids, auds = active_console_reference_lists()
    by_path: dict[str, dict] = {}
    if catalog:
        for asset in catalog:
            path = asset.get("path") or ""
            if path and os.path.isfile(path):
                by_path[os.path.abspath(path)] = asset

    tag_map: dict[str, str] = {}

    def _tag_files(files, prefix: str) -> None:
        for i, f in enumerate(files):
            tag = f"@{prefix} {i + 1}"
            name = getattr(f, "name", "") or ""
            if name:
                tag_map[name] = tag
            path = _ref_file_path(f)
            if path and path in by_path:
                _tag_asset_names(tag_map, by_path[path], tag)

    _tag_files(imgs, "Image")
    _tag_files(vids, "Video")
    _tag_files(auds, "Audio")
    return tag_map


def apply_assets_selection_to_console(
    entry_point,
    catalog_assets,
    image_usage=None,
    *,
    preserve_workflow: bool = True,
):
    """
    Load ordered Assets into the Seedance 2.0 Console workflow.
    Images → @Image N; videos → @Video N (All-in-One Reference).
    """
    ordered = list(catalog_assets or [])
    images = [a for a in ordered if a.get("type") == "image"]
    videos = [a for a in ordered if a.get("type") == "video"]
    audios = [a for a in ordered if a.get("type") == "audio"]
    has_videos = bool(videos)
    has_audios = bool(audios)

    if has_videos or has_audios:
        entry_point = "All-in-One Reference"

    # Clear previous reference caches so workflow switch is clean
    for k in (
        "_cached_s2_images", "_cached_s2_videos", "_cached_s2_audio",
        "_cached_s2_first_frame", "_cached_s2_last_frame", "_cached_s2_first_only",
        "_persist_s2_assets_images", "_persist_s2_assets_videos", "_persist_s2_assets_audio",
        "_persist_s2_assets_first_frame", "_persist_s2_assets_last_frame",
        "_persist_s2_assets_first_only",
        "_persisted_img_1", "_persisted_img_2", "_persisted_img_3", "_persisted_img_4",
        "_persisted_vid_1", "_persisted_aud_1",
        "_seedream_to_seedance_ref",
        "s2_assets_images", "s2_assets_videos", "s2_assets_audio",
        "s2_assets_first_frame", "s2_assets_last_frame", "s2_assets_first_only",
    ):
        st.session_state.pop(k, None)

    st.session_state["_switch_to_seedance"] = True
    st.session_state["s2_entry_point"] = entry_point

    tag_map: dict[str, str] = {}
    img_files = []
    img_labels = []
    vid_files = []
    vid_labels = []
    aud_files = []
    aud_labels = []

    if entry_point == "First Frame":
        for asset in images[:1]:
            f = _console_file_from_asset(asset)
            if not f:
                continue
            img_files.append(f)
            img_labels.append(_asset_picker_label(asset))
            _tag_asset_names(tag_map, asset, "@Image 1")
        if img_files:
            st.session_state["_cached_s2_first_only"] = img_files[0]
            st.session_state["_persist_s2_assets_first_only"] = img_labels[0]
    elif entry_point == "First and Last Frames":
        for i, asset in enumerate(images[:2]):
            f = _console_file_from_asset(asset)
            if not f:
                continue
            img_files.append(f)
            img_labels.append(_asset_picker_label(asset))
            _tag_asset_names(tag_map, asset, f"@Image {len(img_files)}")
        if len(img_files) >= 1:
            st.session_state["_cached_s2_first_frame"] = img_files[0]
            st.session_state["_persist_s2_assets_first_frame"] = img_labels[0]
        if len(img_files) >= 2:
            st.session_state["_cached_s2_last_frame"] = img_files[1]
            st.session_state["_persist_s2_assets_last_frame"] = img_labels[1]
    else:
        for asset in images[:9]:
            f = _console_file_from_asset(asset)
            if not f:
                continue
            img_files.append(f)
            img_labels.append(_asset_picker_label(asset))
            _tag_asset_names(tag_map, asset, f"@Image {len(img_files)}")
        for asset in videos[:3]:
            f = _console_file_from_asset(asset)
            if not f:
                continue
            vid_files.append(f)
            vid_labels.append(_asset_picker_label(asset))
            _tag_asset_names(tag_map, asset, f"@Video {len(vid_files)}")
        for asset in audios[:3]:
            f = _console_file_from_asset(asset)
            if not f:
                continue
            aud_files.append(f)
            aud_labels.append(_asset_picker_label(asset))
            _tag_asset_names(tag_map, asset, f"@Audio {len(aud_files)}")

        st.session_state["_cached_s2_images"] = img_files
        st.session_state["_persist_s2_assets_images"] = img_labels
        st.session_state["_cached_s2_videos"] = vid_files
        st.session_state["_persist_s2_assets_videos"] = vid_labels
        st.session_state["_cached_s2_audio"] = aud_files
        st.session_state["_persist_s2_assets_audio"] = aud_labels

        if image_usage:
            st.session_state["s2_image_usage"] = image_usage
        elif has_videos or has_audios:
            workflow = st.session_state.get("s2_workflow", "Standard Generation")
            if not img_files or workflow in ("Video Extension", "Video Editing"):
                st.session_state["s2_image_usage"] = "reference_only"
            elif not preserve_workflow:
                pass
        elif not preserve_workflow and image_usage is None:
            pass

    st.session_state["_console_ref_tag_map"] = tag_map


def consume_assets_to_console_pending():
    """
    Apply a pending Assets → Console transfer (set from Assets page).
    Returns (ok, message) for UI toast.
    """
    pending = st.session_state.pop("_assets_to_console_pending", None)
    if not pending:
        return False, ""
    asset_ids = pending.get("asset_ids") or []
    image_usage = pending.get("image_usage")
    catalog = pending.get("catalog") or []
    preserve_workflow = pending.get("preserve_workflow", True)
    by_id = {a["id"]: a for a in catalog if a.get("id")}
    ordered = [by_id[aid] for aid in asset_ids if aid in by_id]
    if not ordered:
        return False, "No valid assets found in Assets."

    has_video = any(a.get("type") == "video" for a in ordered)
    has_audio = any(a.get("type") == "audio" for a in ordered)
    if has_video or has_audio:
        entry_point = "All-in-One Reference"
    else:
        entry_point = pending.get("entry_point") or st.session_state.get(
            "s2_entry_point", "All-in-One Reference"
        )

    apply_assets_selection_to_console(
        entry_point,
        ordered,
        image_usage=image_usage,
        preserve_workflow=preserve_workflow,
    )

    img_n = sum(1 for a in ordered if a.get("type") == "image")
    vid_n = sum(1 for a in ordered if a.get("type") == "video")
    aud_n = sum(1 for a in ordered if a.get("type") == "audio")
    parts = []
    if img_n:
        parts.append(f"{img_n} image(s)")
    if vid_n:
        parts.append(f"{vid_n} video(s) as @Video")
    if aud_n:
        parts.append(f"{aud_n} audio(s) as @Audio")
    summary = ", ".join(parts) if parts else f"{len(ordered)} asset(s)"
    return True, f"Loaded {summary} → {entry_point}"


def consume_assets_to_console_pending_seedream():
    """Pop the Seedream pending payload and apply it. Returns (applied: bool, message: str)."""
    payload = st.session_state.pop("_assets_to_console_pending_seedream", None)
    if not payload:
        return (False, "")
    asset_ids = payload.get("asset_ids") or []
    catalog = payload.get("catalog") or []
    if not asset_ids:
        return (False, "No assets to send.")

    # Resolve IDs to ordered catalog dicts, preserving order
    _by_id = {a["id"]: a for a in catalog}
    ordered = [_by_id[aid] for aid in asset_ids if aid in _by_id]
    if not ordered:
        return (False, "No matching assets found in catalog.")

    return apply_assets_selection_to_seedream(ordered)


def apply_assets_selection_to_seedream(catalog_assets):
    """Pre-seed Seedream's in-Console 'From Assets' picker. Returns (True, message)."""
    # Build the labels using the SAME format as console.py:841 — f"{a['name']} ({a['size_str']})"
    labels = [f"{a['name']} ({a['size_str']})" for a in catalog_assets]

    # Clear the widget key so the default= takes effect on next render
    st.session_state.pop("sd_assets_refs", None)

    # Pre-seed the persistence key that Seedream's picker reads as default
    st.session_state["_persist_sd_assets_refs"] = labels

    # Force model switch to Seedream
    st.session_state["_switch_to_seedream"] = True

    return (True, f"Pre-seeded {len(labels)} Seedream reference(s).")
