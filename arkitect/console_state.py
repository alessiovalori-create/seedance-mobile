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
        "gen_mode_selector", "s2_gen_mode",
        "sd_resolution", "sd_ar_select",
        "common_temperature", "common_num_variations", "last_num_variations",
        "sd_optimize", "enforce_stability",
        "enable_audio", "s2_audio_output",
        "v_lang", "v_emo", "v_timbre", "v_pace",
        "s2_dialogue", "s2_sfx",
    ])
    for i in range(5):
        keys.update([f"seed_input_{i}"])

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
        "common_temperature": 0.5,
        "common_num_variations": 1,
        "enable_audio": False,
        "en_s2": False,
        "en_s3": False,
        # Matches LIST_LANGUAGES[0] / LIST_EMOTIONS[0] in the main block
        "v_lang": "English",
        "v_emo": "Neutral",
        "v_timbre": "Normal",
        "v_pace": "Normal",
        "s2_gen_mode": "Standard (Online)",
        "s2_entry_point": "All-in-One Reference",
        "s2_workflow": "Standard Generation",
        "s2_workflow_fl": "Standard Generation",
        "s2_workflow_ff": "Standard Generation",
        "sd_resolution": "3K",
        "sd_ar_select": "Smart",
        "sd_style_select": "None (Raw Prompt)",
        "sd_optimize": "None",
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


def apply_assets_selection_to_console(entry_point, catalog_assets, image_usage=None):
    """
    Load ordered Assets images into the Seedance 2.0 Console workflow.
    entry_point: First Frame | First and Last Frames | All-in-One Reference
    catalog_assets: list of catalog dicts (image type), in @Image tag order.
    """
    assets = [a for a in (catalog_assets or []) if a.get("type") == "image"]
    files = []
    tag_map = {}
    labels = []
    for i, asset in enumerate(assets):
        cached = _cached_from_asset_catalog_entry(asset)
        if not cached:
            continue
        files.append(cached)
        tag = f"@Image {len(files)}"
        tag_map[asset["name"]] = tag
        orig = asset.get("original_name")
        if orig:
            tag_map[orig] = tag
        labels.append(_asset_picker_label(asset))

    # Clear previous reference caches so workflow switch is clean
    for k in (
        "_cached_s2_images", "_cached_s2_first_frame", "_cached_s2_last_frame", "_cached_s2_first_only",
        "_persist_s2_assets_images", "_persist_s2_assets_first_frame", "_persist_s2_assets_last_frame",
        "_persist_s2_assets_first_only",
        "_persisted_img_1", "_persisted_img_2", "_persisted_img_3", "_persisted_img_4",
        "_seedream_to_seedance_ref",
    ):
        st.session_state.pop(k, None)

    # Cannot assign model_selector after its widget exists — use flag read before st.radio
    st.session_state["_switch_to_seedance"] = True
    st.session_state["s2_entry_point"] = entry_point
    st.session_state["_console_ref_tag_map"] = tag_map

    if entry_point == "First Frame":
        if files:
            st.session_state["_cached_s2_first_only"] = files[0]
            st.session_state["_persist_s2_assets_first_only"] = labels[0]
    elif entry_point == "First and Last Frames":
        if len(files) >= 1:
            st.session_state["_cached_s2_first_frame"] = files[0]
            st.session_state["_persist_s2_assets_first_frame"] = labels[0]
        if len(files) >= 2:
            st.session_state["_cached_s2_last_frame"] = files[1]
            st.session_state["_persist_s2_assets_last_frame"] = labels[1]
    else:
        st.session_state["_cached_s2_images"] = files[:9]
        st.session_state["_persist_s2_assets_images"] = labels[:9]
        if image_usage:
            st.session_state["s2_image_usage"] = image_usage


def consume_assets_to_console_pending():
    """
    Apply a pending Assets → Console transfer (set from Assets page).
    Returns (ok, message) for UI toast.
    """
    pending = st.session_state.pop("_assets_to_console_pending", None)
    if not pending:
        return False, ""
    entry_point = pending.get("entry_point") or "All-in-One Reference"
    asset_ids = pending.get("asset_ids") or []
    image_usage = pending.get("image_usage")
    catalog = pending.get("catalog") or []
    by_id = {a["id"]: a for a in catalog if a.get("id")}
    ordered = [by_id[aid] for aid in asset_ids if aid in by_id]
    if not ordered:
        return False, "No valid images found in Assets."
    apply_assets_selection_to_console(entry_point, ordered, image_usage=image_usage)
    tags = ", ".join(f"@Image {i + 1}" for i in range(len(ordered)))
    return True, f"Loaded {len(ordered)} image(s) as {tags} → {entry_point}"
