# REQUIREMENTS: Streamlit >= 1.31.0 for static file serving (video timeline)
# Upgrade: pip install --upgrade streamlit

import os
import hashlib
from urllib.parse import quote
from dotenv import load_dotenv

# QUESTA È LA RIGA CHE APRE IL CAVEAU .ENV
load_dotenv()

import streamlit as st
import re
import json
import html as _html_stdlib
import random
import copy
import requests
from datetime import datetime
import streamlit.components.v1 as components
import base64 as _b64

from arkitect.shared import (
    CachedUploadedFile,
    AssetFile,
    _materialize_multi_file_upload,
    _APP_DIR,
    _PERSIST_DIR,
    _DB_DIR,
    _GENERATED_DIR,
    _REFERENCES_DIR,
    _DOWNLOADS_DIR,
    _STATIC_DIR,
)
from arkitect.media_server import (
    _setup_static_serving,
    _ensure_media_server,
    _to_media_url,
    _to_static_url,
    _STATIC_SERVING_OK,
    _STATIC_SERVING_SUPPORTED,
)
from arkitect.storage import (
    load_gallery_from_disk,
    save_gallery_to_disk,
    load_all_snapshots,
    save_all_snapshots,
    snapshot_entry_items,
    snapshot_entry_project_id,
    filter_snapshot_names,
    upsert_snapshot_entry,
    save_snapshot_with_active_project,
    load_asset_catalog,
    save_asset_catalog,
    add_to_assets,
    load_projects,
    save_projects,
    get_active_project_id,
    get_active_project_name,
    scan_assets,
)
from arkitect.pages.references import render_references_page
from arkitect.pages.gallery import render_gallery_page
from arkitect.pages.assets import render_assets_page

from builder import build_prompt as build_video_prompt, analyze_cinematography, build_image_prompt
from generator import generate_video, generate_seedream_image, SEEDANCE_2_0_MODEL_ID, SEEDREAM_5_0_LITE_MODEL_ID, SEEDREAM_4_5_MODEL_ID, PEXELS_API_KEY, UNSPLASH_API_KEY, estimate_cost, format_cost_str, _estimate_seedance2_usage
GENERATION_ENABLED = True  # ← Set to False to disable generation
try:
    from streamlit_sortables import sort_items
    SORTABLES_AVAILABLE = True
except ImportError:
    SORTABLES_AVAILABLE = False

import subprocess
import shutil
import tempfile

# References (Pexels/Unsplash) iframe — Gallery .gal-card tokens + CSS columns masonry (natural aspect ratio)




def _normalize_editing_video_item(item):
    """trim_start >= 0; trim_end defaults to -1 (full duration)."""
    out = dict(item)
    ts_raw = out.get("trim_start", 0)
    try:
        ts = float(ts_raw)
    except (TypeError, ValueError):
        ts = 0.0
    if ts < 0 or ts_raw is None:
        ts = 0.0
    out["trim_start"] = round(ts, 2)
    te_raw = out.get("trim_end", -1)
    if te_raw is None:
        te = -1.0
    else:
        try:
            te = float(te_raw)
        except (TypeError, ValueError):
            te = -1.0
    out["trim_end"] = round(te, 2)
    return out


def _get_thumbnail_src(item):
    # Prioritize image thumbnails for videos (last_frame_path), then standard paths
    src = item.get("last_frame_path") or item.get("image_path") or item.get("video_path") or item.get("url") or item.get("src") or ""
    if not src:
        return ""
    if src.startswith("http://") or src.startswith("https://"):
        return src

    if os.path.exists(src):
        ext = os.path.splitext(src)[1].lower()
        # DANGER: Do not base64 encode massive video files. Return a flag.
        if ext in [".mp4", ".mov", ".webm"]:
            return "VIDEO_PLACEHOLDER"

        try:
            mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
            mime = mime_map.get(ext, "image/jpeg")
            with open(src, "rb") as f:
                data = _b64.b64encode(f.read()).decode("utf-8")
            return f"data:{mime};base64,{data}"
        except Exception:
            return ""

    return src

def _get_thumbnail_src_resized(item, max_px=320):
    """
    Like _get_thumbnail_src but resizes local images to max_px on the
    longest side before base64-encoding. Keeps URLs and VIDEO_PLACEHOLDER
    unchanged. Falls back to _get_thumbnail_src on any error.
    """
    src = (item.get("image_path") or item.get("url") or
           item.get("src") or item.get("last_frame_path") or "")
    if not src:
        return ""
    # URLs and remote srcs: return as-is
    if src.startswith("http://") or src.startswith("https://"):
        return src
    if not os.path.exists(src):
        return src
    ext = os.path.splitext(src)[1].lower()
    if ext in (".mp4", ".mov", ".webm"):
        return "VIDEO_PLACEHOLDER"
    try:
        from PIL import Image as _PILImage
        import io as _io
        mime_map = {".png": "image/png", ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg", ".webp": "image/webp",
                    ".gif": "image/gif"}
        mime = mime_map.get(ext, "image/jpeg")
        with _PILImage.open(src) as im:
            im.thumbnail((max_px, max_px), _PILImage.LANCZOS)
            buf = _io.BytesIO()
            save_fmt = "JPEG" if mime == "image/jpeg" else "PNG"
            im.convert("RGB").save(buf, format=save_fmt, quality=82, optimize=True)
            data = _b64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:{mime};base64,{data}"
    except Exception:
        # PIL not available or error: fall back to original
        return _get_thumbnail_src(item)

def _section_title(text):
    st.markdown(
        f'<p style="color: #00E5CC; font-size: 2rem; font-weight: 600; margin-bottom: 0.25rem; text-align: center;">{text}</p>',
        unsafe_allow_html=True
    )

def _inject_pulse_css():
    st.markdown("""
    <style>
    @keyframes pulse-yellow {
        0%, 100% { opacity: 1; filter: brightness(1); }
        50% { opacity: 0.85; filter: brightness(1.15); }
    }
    @keyframes pulse-green {
        0%, 100% { opacity: 1; filter: brightness(1); }
        50% { opacity: 0.85; filter: brightness(1.15); }
    }
    .pulse-msg-yellow {
        color: #FFEB3B;
        font-weight: 600;
        text-align: center;
        padding: 0.5rem 1rem;
        border-radius: 0.5rem;
        background: rgba(255, 235, 59, 0.12);
        animation: pulse-yellow 1.8s ease-in-out infinite;
    }
    .pulse-msg-green {
        color: #00E676;
        font-weight: 600;
        text-align: center;
        padding: 0.5rem 1rem;
        border-radius: 0.5rem;
        background: rgba(0, 230, 118, 0.12);
        animation: pulse-green 1.8s ease-in-out infinite;
    }
    </style>
    """, unsafe_allow_html=True)

def _sync_storyboard_name_from_widgets():
    """Preferisce sb_active_name; altrimenti il primo campo sb_name_field* compilato."""
    v = (st.session_state.get("sb_active_name") or "").strip()
    if v:
        return v
    for key in list(st.session_state.keys()):
        if key.startswith("sb_name_field"):
            v = (st.session_state.get(key) or "").strip()
            if v:
                st.session_state.sb_active_name = v
                return v
    return ""


def _autosave_storyboard_snapshot():
    """Salvataggio immediato su disco se c'è un nome (usato da grid / gallery)."""
    nm = _sync_storyboard_name_from_widgets()
    if not nm:
        return
    upsert_snapshot_entry("storyboard", nm, st.session_state.get("sb_active_images", []))


def _on_storyboard_grid_pick_change():
    raw = (st.session_state.get("sb_pick_act") or "").strip()
    if not raw:
        return
    st.session_state["sb_pick_act"] = ""
    sname = raw.split("|")[0].strip()
    sd = load_all_snapshots()
    sd_map = sd.get("storyboard", {})
    if sname not in sd_map:
        return
    raw_e = sd_map.get(sname, [])
    items = snapshot_entry_items(raw_e)
    st.session_state.sb_active_images = items
    st.session_state.sb_active_name = sname
    st.session_state.sb_mode = "loaded"


def _thumbnail_for_editing_items(raw_ed_items):
    """Primo frame utile (last_frame o cv2) e numero clip — per griglia Editing."""
    if not raw_ed_items:
        return "", 0
    ed_thumb = ""
    for _ei in raw_ed_items:
        _eip = _ei.get("last_frame_path") or ""
        if _eip and os.path.exists(_eip):
            try:
                from PIL import Image as _PILImage
                import io as _io
                with _PILImage.open(_eip) as _eim:
                    _eim.thumbnail((400, 240), _PILImage.LANCZOS)
                    _ebuf = _io.BytesIO()
                    _eim.convert("RGB").save(_ebuf, format="JPEG", quality=75)
                    ed_thumb = f"data:image/jpeg;base64,{_b64.b64encode(_ebuf.getvalue()).decode('ascii')}"
            except Exception:
                pass
        if not ed_thumb:
            _evp = _ei.get("video_path") or ""
            if _evp and os.path.exists(_evp):
                try:
                    import cv2
                    cap = cv2.VideoCapture(_evp)
                    if cap.isOpened():
                        ret, frame = cap.read()
                        if ret:
                            h, w = frame.shape[:2]
                            scale = min(400 / max(w, 1), 240 / max(h, 1), 1.0)
                            if scale < 1:
                                frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
                            _, _ebuf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 72])
                            ed_thumb = f"data:image/jpeg;base64,{_b64.b64encode(_ebuf.tobytes()).decode('ascii')}"
                    cap.release()
                except Exception:
                    pass
        if ed_thumb:
            break
    return ed_thumb, len(raw_ed_items)


def _on_editing_grid_pick_change():
    raw = (st.session_state.get("ed_pick_act") or "").strip()
    if not raw:
        return
    st.session_state["ed_pick_act"] = ""
    ename = raw.split("|")[0].strip()
    sd = load_all_snapshots()
    ed_map = sd.get("editing", {})
    if ename not in ed_map:
        return
    raw_e = ed_map.get(ename, [])
    items = snapshot_entry_items(raw_e)
    st.session_state.ed_active_videos = [_normalize_editing_video_item(dict(x)) for x in items]
    st.session_state.ed_active_name = ename
    st.session_state.ed_mode = "loaded"


def _render_storyboard_projects_sidebar():
    """Sidebar STORYBOARD dedicata: stessa struttura della pagina PROJECTS."""
    st.markdown(
        '<p style="color:#9E9E8A;font-size:0.75rem;font-weight:600;letter-spacing:0.08em;'
        'margin:0 0 8px;">NEW STORYBOARD</p>',
        unsafe_allow_html=True,
    )
    new_sb_name = st.text_input(
        "Storyboard name",
        key="sb_page_new_name_input",
        label_visibility="collapsed",
        placeholder="Storyboard name...",
    )
    if st.button("NEW STORYBOARD", key="sbi_sidebar_new_btn", use_container_width=True):
        name = (new_sb_name or "").strip()
        if name:
            snaps = load_all_snapshots()
            all_sb = snaps.get("storyboard", {})
            sb_list = filter_snapshot_names(all_sb, get_active_project_id())
            if any(x.lower() == name.lower() for x in sb_list):
                st.warning(f"Storyboard '{name}' already exists.")
            else:
                st.session_state.sb_mode = "new"
                st.session_state.sb_active_name = name
                st.session_state.sb_active_images = []
                st.toast(f"New storyboard: {name}")
                st.rerun()
        else:
            st.session_state.sb_mode = "new"
            st.session_state.sb_active_name = ""
            st.session_state.sb_active_images = []
            st.rerun()

    st.markdown(
        '<hr style="border:none;border-top:1px solid #2a2a28;margin:16px 0;">',
        unsafe_allow_html=True,
    )
    if st.button("DELETE", key="sbi_sidebar_delete_btn", use_container_width=True):
        name = st.session_state.get("sb_active_name")
        mode = st.session_state.get("sb_mode")
        if not name or mode not in ("new", "loaded"):
            st.toast("Select a storyboard in the grid or create one first.")
        else:
            snaps = load_all_snapshots()
            bucket = snaps.setdefault("storyboard", {})
            if name in bucket:
                bucket.pop(name, None)
                save_all_snapshots(snaps)
                st.toast(f"Deleted: {name}")
            else:
                st.toast("Workspace cleared.")
            st.session_state.sb_mode = None
            st.session_state.sb_active_name = ""
            st.session_state.sb_active_images = []
            st.rerun()

    st.markdown(
        '<hr style="border:none;border-top:1px solid #2a2a28;margin:16px 0;">',
        unsafe_allow_html=True,
    )
    _is_browse = st.session_state.get("sb_mode") is None
    _all_lbl = "ALL STORYBOARDS" + (" ✓" if _is_browse else "")
    if st.button(_all_lbl, key="sbi_sidebar_all_btn", use_container_width=True):
        st.session_state.sb_mode = None
        st.session_state.sb_active_name = ""
        st.session_state.sb_active_images = []
        st.toast("Storyboard workspace reset.")
        st.rerun()

    st.markdown(
        '<hr style="border:none;border-top:1px solid #2a2a28;margin:16px 0;">',
        unsafe_allow_html=True,
    )
    if st.button("CLEAR", key="sbi_sidebar_clear_btn", use_container_width=True):
        st.session_state.sb_active_images = []
        st.session_state.gallery_selected_imgs = set()
        st.session_state.sb_mode = None
        st.session_state.sb_active_name = ""
        st.rerun()




def _render_editing_projects_sidebar():
    """Sidebar EDITING dedicata: stessa struttura di Projects / Storyboard."""
    st.markdown(
        '<p style="color:#9E9E8A;font-size:0.75rem;font-weight:600;letter-spacing:0.08em;'
        'margin:0 0 8px;">NEW EDITING</p>',
        unsafe_allow_html=True,
    )
    new_ed_name = st.text_input(
        "Editing session name",
        key="ed_page_new_name_input",
        label_visibility="collapsed",
        placeholder="Editing name...",
    )
    if st.button("NEW EDITING", key="ed_sidebar_new_btn", use_container_width=True):
        name = (new_ed_name or "").strip()
        if name:
            snaps = load_all_snapshots()
            all_ed = snaps.get("editing", {})
            ed_list = filter_snapshot_names(all_ed, get_active_project_id())
            if any(x.lower() == name.lower() for x in ed_list):
                st.warning(f"Editing '{name}' already exists.")
            else:
                st.session_state.ed_mode = "new"
                st.session_state.ed_active_name = name
                st.session_state.ed_active_videos = []
                st.toast(f"New editing: {name}")
                st.rerun()
        else:
            st.session_state.ed_mode = "new"
            st.session_state.ed_active_name = ""
            st.session_state.ed_active_videos = []
            st.rerun()

    st.markdown(
        '<hr style="border:none;border-top:1px solid #2a2a28;margin:16px 0;">',
        unsafe_allow_html=True,
    )
    if st.button("DELETE", key="ed_sidebar_delete_btn", use_container_width=True):
        name = st.session_state.get("ed_active_name")
        mode = st.session_state.get("ed_mode")
        if not name or mode not in ("new", "loaded"):
            st.toast("Select an editing in the grid or create one first.")
        else:
            snaps = load_all_snapshots()
            bucket = snaps.setdefault("editing", {})
            if name in bucket:
                bucket.pop(name, None)
                save_all_snapshots(snaps)
                st.toast(f"Deleted: {name}")
            else:
                st.toast("Workspace cleared.")
            st.session_state.ed_mode = None
            st.session_state.ed_active_name = ""
            st.session_state.ed_active_videos = []
            st.rerun()

    st.markdown(
        '<hr style="border:none;border-top:1px solid #2a2a28;margin:16px 0;">',
        unsafe_allow_html=True,
    )
    _is_browse_ed = st.session_state.get("ed_mode") is None
    _all_ed_lbl = "ALL EDITINGS" + (" ✓" if _is_browse_ed else "")
    if st.button(_all_ed_lbl, key="ed_sidebar_all_btn", use_container_width=True):
        st.session_state.ed_mode = None
        st.session_state.ed_active_name = ""
        st.session_state.ed_active_videos = []
        st.toast("Editing workspace reset.")
        st.rerun()

    st.markdown(
        '<hr style="border:none;border-top:1px solid #2a2a28;margin:16px 0;">',
        unsafe_allow_html=True,
    )
    if st.button("CLEAR", key="ed_sidebar_clear_btn", use_container_width=True):
        st.session_state.ed_active_videos = []
        st.session_state.gallery_selected_vids = set()
        st.session_state.ed_mode = None
        st.session_state.ed_active_name = ""
        st.rerun()


def _render_project_indicator():
    """Shows a small non-interactive label with the active project name."""
    name = get_active_project_name()
    if name and name != "All Projects":
        st.markdown(
            f'<p style="color:#BB86FC; font-size:0.7rem; font-weight:600; '
            f'font-family:Open Sans,sans-serif; letter-spacing:0.06em; '
            f'margin:0 0 8px 0; padding:0;">Projects : {name}</p>',
            unsafe_allow_html=True,
        )
    elif name == "All Projects":
        st.markdown(
            f'<p style="color:#555; font-size:0.65rem; font-weight:500; '
            f'font-family:Open Sans,sans-serif; letter-spacing:0.04em; '
            f'margin:0 0 8px 0; padding:0;">Projects : All Projects</p>',
            unsafe_allow_html=True,
        )


def _render_project_name_inline_right():
    """Right-aligned 'Project : name' in the top nav row (same style as Gallery)."""
    _pname = get_active_project_name()
    _pcol = "#FFEB3B" if _pname != "All Projects" else "#555"
    st.markdown(
        f'<p style="text-align:right; color:{_pcol}; font-size:0.75rem; font-weight:600; '
        f'font-family:Open Sans,sans-serif; letter-spacing:0.05em; '
        f'margin:10px 0 0; -webkit-text-fill-color:{_pcol};">'
        f'Project : {_pname}</p>',
        unsafe_allow_html=True,
    )




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
                f"{k}_tb", f"{k}_tc", f"{k}_ts", f"{k}_tt", f"{k}_tbo", f"{k}_tsh",
                f"{k}_tv", f"{k}_tca", f"{k}_tg", f"{k}_tso", f"{k}_tmb",
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
    """Re-inject snapshotted params on every Console rerun. Re-mounts widget keys
    that Streamlit dropped between renders (e.g. after a model_selector flip).
    Existing live values in session_state take precedence — we only fill gaps."""
    if st.session_state.get("active_page") != "console":
        return
    # Clear the was-away flag if it's set, but do not gate on it.
    if st.session_state.get("_console_was_away"):
        st.session_state["_console_was_away"] = False
    snap = st.session_state.get("_console_param_snapshot")
    if not isinstance(snap, dict) or not snap:
        return
    for sk, sv in snap.items():
        if _console_session_state_assign_forbidden(sk):
            continue
        # Fill gap only — never overwrite a live value the user just set.
        if sk in st.session_state:
            continue
        st.session_state[sk] = sv


def check_password():
    def password_entered():
        entered = st.session_state.get("password", "")
        expected = os.getenv("APP_PASSWORD", "")
        if entered.strip() == expected.strip():
            st.session_state["password_correct"] = True
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.markdown("<h1 style='text-align: center; color: #e8e4df; margin-top: 50px; font-family: Open Sans, sans-serif; font-weight: 700; letter-spacing: 0.2em; text-transform: uppercase;'>DIRECTOR ACCESS</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #7a7a75;'>Secure Console for AI Cinematography</p>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("Enter Password", type="password", on_change=password_entered, key="password")
        if "password_correct" in st.session_state and not st.session_state["password_correct"]:
            st.error("😕 Access Denied: Incorrect Password")
    return False

if check_password():
    st.set_page_config(page_title="AI DOP Console", layout="wide")

    if not os.getenv("ARK_API_KEY"):
        st.error("ARK_API_KEY not set. Add it to Railway Variables and redeploy.")
        st.stop()

    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:ital,wght@0,400;0,500;0,700&family=Open+Sans:wght@700;800&display=swap');
        :root { 
            --brand-color: #e8e4df;
            --bg-primary: #000;
            --bg-secondary: #0a0a0a;
            --bg-card: #141414;
            --text-primary: #f5f5f0;
            --text-secondary: #c4c4be;
            --text-muted: #7a7a75;
            --border-color: #2a2a28;
            --refs-cream: #F5F5DC;
        }
        .stApp { font-family: 'Inter', sans-serif; background: var(--bg-primary); color: var(--text-primary); line-height: 1.6; }
        .stApp > div:first-child { border: 1px solid var(--border-color); min-height: 100vh; }
        .main .block-container { padding: 1rem 2rem; max-width: 100%; }
        .main-console-title { color: #FFEB3B !important; text-shadow: 0 0 10px rgba(255,253,240,0.6); }
        h1 { font-family: 'Open Sans', sans-serif !important; text-align: center; color: var(--brand-color) !important; text-transform: uppercase; font-weight: 700; font-size: clamp(1.5rem, 2.5vw, 2.2rem); letter-spacing: 0.2em; margin-bottom: 0.5rem; }
        .built-by { font-family: 'Inter', sans-serif; text-align: center; color: var(--text-muted); margin-top: -6px; margin-bottom: 1rem; font-size: 0.85rem; }
        .stButton > button { background: var(--brand-color); color: #0a0a0a !important; border: none; border-radius: 0; font-family: 'Inter', sans-serif; font-weight: 500; font-size: 0.9rem; padding: 0.7rem 1.75rem; letter-spacing: 0.12em; text-transform: uppercase; transition: background 0.2s ease; }
        .stButton > button:not([kind="primary"]):hover { background: #FFFF00 !important; color: #000 !important; box-shadow: 0 0 12px rgba(255,255,0,0.5); }
        .stButton > button[kind="primary"]:hover { background: #00FF00 !important; color: #000 !important; box-shadow: 0 0 12px rgba(0,255,0,0.5); }
        .stTextInput > div > div, .stTextArea > div > div, .stNumberInput > div > div { border: 1px solid rgba(255,255,255,0.5) !important; border-radius: 8px !important; background-color: var(--bg-card) !important; }
        .stTextInput > div > div:focus-within, .stTextArea > div > div:focus-within, .stNumberInput > div > div:focus-within { border-color: #FFEB3B !important; }
        .stTextInput > div > div > input, .stTextArea > div > div > textarea, .stNumberInput > div > div > input { background-color: transparent !important; color: var(--text-primary) !important; border: none !important; outline: none !important; box-shadow: none !important; padding: 0.875rem 1rem !important; font-size: 0.95rem !important; }
        .stTextArea > div > div > textarea { min-height: 80px !important; height: auto !important; resize: vertical; }
        .stSelectbox [data-baseweb="select"] { border: 1px solid rgba(255,255,255,0.5) !important; border-radius: 8px !important; background-color: var(--bg-card) !important; }
        .stSelectbox [data-baseweb="select"]:focus-within { border-color: #FFEB3B !important; }
        .stSelectbox [data-baseweb="select"] * { color: #ffffff !important; }
        .streamlit-expanderHeader { background-color: var(--bg-secondary) !important; border-radius: 6px !important; padding: 0.75rem 1rem !important; border: 1px solid var(--border-color) !important; }
        .streamlit-expanderContent { background-color: var(--bg-card) !important; border-radius: 0 0 6px 6px !important; padding: 1rem !important; }
        .stRadio > div { background-color: var(--bg-card); border-radius: 8px; padding: 1rem; border: 1px solid rgba(255,255,255,0.4) !important; }
        .stRadio label, .stRadio p, .stRadio div { color: #f5f5f0 !important; }
        label { font-weight: 500; color: var(--text-secondary) !important; font-size: 0.9rem; }
        .stTextInput input, .stTextArea textarea, .stNumberInput input { color: #ffffff !important; -webkit-text-fill-color: #ffffff !important; }
        .stTextInput input::placeholder, .stTextArea textarea::placeholder { color: #9a9a95 !important; }
        .stNumberInput input { color: #ffffff !important; background-color: #141414 !important; -webkit-text-fill-color: #ffffff !important; }
        [data-baseweb="menu"] li, [data-baseweb="menu"] div { color: #ffffff !important; background-color: #0a0a0a !important; }
        [data-baseweb="menu"] li:hover { background-color: #2a2a28 !important; }
        select, option { color: #ffffff !important; background-color: #141414 !important; }
        .stFileUploader { border: 2px dashed var(--border-color); border-radius: 8px; padding: 1rem; }
        /* Clean upload widgets */
        div[data-testid="stFileUploader"] {
            margin-bottom: 0.5rem !important;
        }
        div[data-testid="stFileUploader"] label {
            font-size: 0.8rem !important;
            color: #9E9E8A !important;
            font-weight: 500 !important;
        }
        div[data-testid="stFileUploader"] section {
            padding: 0.5rem !important;
        }
        div[data-testid="stFileUploader"] section > div {
            font-size: 0.75rem !important;
        }
        .stSlider { margin-bottom: 1rem !important; }
        .stImage { border-radius: 8px; overflow: hidden; box-shadow: 0px 8px 30px rgba(0,0,0,0.5); }
        .stVideo { border-radius: 8px; overflow: hidden; box-shadow: 0px 8px 30px rgba(0,0,0,0.5); }
        .preview-btn-wrap, .generate-btn-wrap { margin-top: 0 !important; padding-top: 0 !important; }
        .preview-btn-wrap { margin-top: 18px !important; }
        .preview-btn-wrap .stButton, .generate-btn-wrap .stButton { margin: 0 !important; }
        .preview-btn-wrap .stButton > button { background: #FFEB3B !important; color: #000000 !important; border: none !important; width: 100% !important; min-height: 46px !important; height: 46px !important; margin: 0 !important; }
        .preview-btn-wrap .stButton > button:hover { background: #FFFF00 !important; box-shadow: 0 0 16px rgba(255,255,0,0.7) !important; }
        .generate-btn-wrap .stButton > button { background: #F7F7F7 !important; color: #000000 !important; -webkit-text-fill-color: #000000 !important; border: 1px solid #d9d9d9 !important; width: 100% !important; min-height: 46px !important; height: 46px !important; margin: 0 !important; opacity: 1 !important; visibility: visible !important; }
        .generate-btn-wrap .stButton > button[kind="primary"] { background: #00E676 !important; color: #000000 !important; border: none !important; }
        .generate-btn-wrap .stButton > button[kind="primary"] { -webkit-text-fill-color: #000000 !important; }
        .generate-btn-wrap .stButton > button:hover { background: #FFFFFF !important; box-shadow: 0 0 12px rgba(255,255,255,0.3) !important; }
        .generate-btn-wrap .stButton > button[kind="primary"]:hover { background: #00FF00 !important; box-shadow: 0 0 16px rgba(0,255,0,0.7) !important; }
        .generate-btn-wrap .stButton > button:disabled { opacity: 1 !important; visibility: visible !important; background: #F7F7F7 !important; color: #000000 !important; -webkit-text-fill-color: #000000 !important; border: 1px solid #d9d9d9 !important; cursor: not-allowed !important; }
        /* Hard override for generate buttons by key */
        div[data-testid="stButton"][data-key*="s2_production_opt"] > button,
        div[data-testid="stButton"][data-key*="sd_production_opt"] > button {
            background: #F7F7F7 !important;
            color: #000000 !important;
            -webkit-text-fill-color: #000000 !important;
            border: 1px solid #d9d9d9 !important;
            opacity: 1 !important;
            visibility: visible !important;
            display: block !important;
            filter: none !important;
            mix-blend-mode: normal !important;
            min-height: 46px !important;
            height: 46px !important;
        }
        div[data-testid="stButton"][data-key*="s2_production_opt"],
        div[data-testid="stButton"][data-key*="sd_production_opt"] {
            opacity: 1 !important;
            visibility: visible !important;
            filter: none !important;
        }
        div[data-testid="stButton"][data-key*="s2_production_opt"] > button[kind="primary"],
        div[data-testid="stButton"][data-key*="sd_production_opt"] > button[kind="primary"] {
            background: #00E676 !important;
            color: #000000 !important;
            -webkit-text-fill-color: #000000 !important;
            border: none !important;
        }
        div[data-testid="stButton"][data-key*="s2_production_opt"] > button:disabled,
        div[data-testid="stButton"][data-key*="sd_production_opt"] > button:disabled {
            background: #F7F7F7 !important;
            color: #000000 !important;
            -webkit-text-fill-color: #000000 !important;
            border: 1px solid #d9d9d9 !important;
            opacity: 1 !important;
            visibility: visible !important;
            display: block !important;
        }
        @keyframes pulse-generate {
            0% { transform: scale(1); box-shadow: 0 0 0 rgba(0, 255, 0, 0.0); }
            50% { transform: scale(1.02); box-shadow: 0 0 14px rgba(0, 255, 0, 0.65); }
            100% { transform: scale(1); box-shadow: 0 0 0 rgba(0, 255, 0, 0.0); }
        }
        /* PREVIEW button inside canvas */
        div[data-testid="stButton"][data-key*="preview_prompt_btn"] > button,
        div[data-testid="stButton"][data-key*="sd_preview_btn"] > button {
            background: #FFEB3B !important;
            color: #000000 !important;
            border: none !important;
            font-weight: 700 !important;
            padding: 12px 40px !important;
            font-size: 0.9rem !important;
            letter-spacing: 0.1em !important;
            box-shadow: 0 4px 20px rgba(255, 235, 59, 0.3) !important;
            margin-top: 22px !important;
        }
        div[data-testid="stButton"][data-key*="preview_prompt_btn"] > button:hover,
        div[data-testid="stButton"][data-key*="sd_preview_btn"] > button:hover {
            background: #FFFF00 !important;
            box-shadow: 0 4px 24px rgba(255, 255, 0, 0.5) !important;
        }
        /* RESET button — subtle, not distracting */
        div[data-testid="stButton"][data-key*="console_reset_btn"] button {
            background: transparent !important;
            color: #9E9E8A !important;
            -webkit-text-fill-color: #9E9E8A !important;
            border: 1px solid rgba(158,158,138,0.3) !important;
            font-size: 0.72rem !important;
            font-weight: 600 !important;
            letter-spacing: 0.06em !important;
            padding: 4px 12px !important;
            min-height: 0 !important;
            height: auto !important;
        }
        div[data-testid="stButton"][data-key*="console_reset_btn"] button:hover {
            color: #f0ece4 !important;
            -webkit-text-fill-color: #f0ece4 !important;
            border-color: rgba(240,236,228,0.4) !important;
        }
        /* ── STATE 1: Empty canvas with centered PREVIEW button ── */
        .empty-canvas-wrap {
            background: #F0EEE9;
            border-radius: 8px;
            border: 1px solid #e8e4df;
            aspect-ratio: 16 / 9;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 4px 16px rgba(0,0,0,0.15);
        }

        /* ── STATE 2: Text area IS the 16:9 canvas ── */
        textarea[aria-label="CANVAS_PROMPT"],
        .stTextArea textarea[aria-label="CANVAS_PROMPT"],
        div[data-testid="stTextArea"] textarea[aria-label="CANVAS_PROMPT"] {
            background-color: #F0EEE9 !important;
            color: #000000 !important;
            -webkit-text-fill-color: #000000 !important;
            border: 1px solid #e8e4df !important;
            border-radius: 8px !important;
            font-family: 'JetBrains Mono', 'Fira Code', monospace !important;
            font-size: 0.85rem !important;
            line-height: 1.7 !important;
            padding: 20px !important;
            resize: none !important;
            caret-color: #FF1493 !important;
            box-shadow: 0 4px 16px rgba(0,0,0,0.15) !important;
            aspect-ratio: 16 / 9 !important;
            height: auto !important;
            min-height: 0 !important;
            max-height: none !important;
            overflow-y: auto !important;
        }
        textarea[aria-label="CANVAS_PROMPT"]:focus {
            outline: none !important;
            border: 1px solid #e8e4df !important;
            box-shadow: 0 4px 16px rgba(0,0,0,0.15) !important;
            color: #000000 !important;
            -webkit-text-fill-color: #000000 !important;
        }
        div[data-testid="stTextArea"]:has(textarea[aria-label="CANVAS_PROMPT"]) > div {
            border: none !important;
            background: transparent !important;
        }
        div[data-testid="stTextArea"]:has(textarea[aria-label="CANVAS_PROMPT"]) > div > div {
            background-color: transparent !important;
            border: none !important;
        }
        .gallery-card { background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 8px; padding: 0.75rem; margin-bottom: 1rem; }
        /* ══════════════════════════════════════════════
           GLOBAL PAGE CONSISTENCY — all pages match console style
           ══════════════════════════════════════════════ */
        div[data-testid="stButton"][data-key*="back_to_console"] button,
        div[data-testid="stButton"][data-key*="sb_back"] button,
        div[data-testid="stButton"][data-key*="sbi_back"] button,
        div[data-testid="stButton"][data-key*="sbv_back"] button,
        div[data-testid="stButton"][data-key*="goto_sb"] button,
        div[data-testid="stButton"][data-key*="sbi_goto"] button,
        div[data-testid="stButton"][data-key*="sbv_goto"] button,
        div[data-testid="stButton"][data-key*="clear_gallery"] button,
        div[data-testid="stButton"][data-key*="sbi_clear"] button,
        div[data-testid="stButton"][data-key*="sbv_clear"] button,
        div[data-testid="stButton"][data-key*="sb_clear"] button,
        div[data-testid="stButton"][data-key*="gal_img"] button,
        div[data-testid="stButton"][data-key*="gal_vid"] button,
        div[data-testid="stButton"][data-key*="sb_export"] button,
        div[data-testid="stButton"][data-key*="sb_save"] button,
        div[data-testid="stButton"][data-key*="sb_load"] button,
        div[data-testid="stButton"][data-key*="sb_delete"] button,
        div[data-testid="stButton"][data-key*="sb_rm_"] button,
        div[data-testid="stButton"][data-key*="sel_img_"] button,
        div[data-testid="stButton"][data-key*="sel_vid_"] button {
            background: #0d0d0b !important;
            color: #f0ece4 !important;
            -webkit-text-fill-color: #f0ece4 !important;
            border: 1px solid rgba(255,255,255,0.15) !important;
            border-radius: 6px !important;
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.8rem !important;
            font-weight: 600 !important;
            letter-spacing: 0.06em !important;
            padding: 6px 16px !important;
            box-shadow: none !important;
        }
        div[data-testid="stButton"][data-key*="sel_vid_"].st-emotion-cache-1 button[kind="secondary"]:not(:disabled) {
            min-height: 24px !important;
            height: 24px !important;
            padding: 0 6px !important;
            font-size: 0.6rem !important;
            letter-spacing: 0.04em !important;
        }
        div[data-testid="stButton"][data-key*="back_to_console"] button:hover,
        div[data-testid="stButton"][data-key*="sb_back"] button:hover,
        div[data-testid="stButton"][data-key*="sbi_back"] button:hover,
        div[data-testid="stButton"][data-key*="sbv_back"] button:hover,
        div[data-testid="stButton"][data-key*="goto_sb"] button:hover,
        div[data-testid="stButton"][data-key*="sbi_goto"] button:hover,
        div[data-testid="stButton"][data-key*="sbv_goto"] button:hover,
        div[data-testid="stButton"][data-key*="clear_gallery"] button:hover,
        div[data-testid="stButton"][data-key*="sbi_clear"] button:hover,
        div[data-testid="stButton"][data-key*="sbv_clear"] button:hover,
        div[data-testid="stButton"][data-key*="sb_clear"] button:hover {
            background: #1a1a18 !important;
            border-color: rgba(255,255,255,0.3) !important;
            color: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
        }
        div[data-testid="stButton"][data-key*="_delete_btn"] button {
            background: transparent !important;
            color: #ff4444 !important;
            -webkit-text-fill-color: #ff4444 !important;
            border: 1px solid rgba(255,68,68,0.3) !important;
            font-size: 0.72rem !important;
            font-weight: 600 !important;
        }
        div[data-testid="stButton"][data-key*="_delete_btn"] button:hover {
            background: rgba(255,68,68,0.1) !important;
            border-color: #ff4444 !important;
        }
        div[data-testid="stButton"][data-key*="_dup_btn"] button {
            background: transparent !important;
            color: #9E9E8A !important;
            -webkit-text-fill-color: #9E9E8A !important;
            border: 1px solid rgba(255,255,255,0.12) !important;
            font-size: 0.72rem !important;
            font-weight: 600 !important;
        }
        div[data-testid="stButton"][data-key*="_dup_btn"] button:hover {
            color: #f0ece4 !important;
            -webkit-text-fill-color: #f0ece4 !important;
            border-color: rgba(255,255,255,0.3) !important;
        }
        .stTabs [data-baseweb="tab-list"] {
            background: #0d0d0b !important;
            border-bottom: 1px solid rgba(255,255,255,0.1) !important;
            gap: 0 !important;
        }
        .stTabs [data-baseweb="tab"] {
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.85rem !important;
            font-weight: 600 !important;
            letter-spacing: 0.08em !important;
            text-transform: uppercase !important;
            color: #9E9E8A !important;
            -webkit-text-fill-color: #9E9E8A !important;
            padding: 10px 24px !important;
            background: transparent !important;
            border: none !important;
        }
        .stTabs [data-baseweb="tab"][aria-selected="true"] {
            color: #f0ece4 !important;
            -webkit-text-fill-color: #f0ece4 !important;
            border-bottom: 2px solid #f0ece4 !important;
        }
        .stTabs [data-baseweb="tab"]:hover {
            color: #f0ece4 !important;
            -webkit-text-fill-color: #f0ece4 !important;
        }
        .stImage + div[data-testid="stCaption"],
        .stVideo + div[data-testid="stCaption"] {
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.72rem !important;
            color: #9E9E8A !important;
            -webkit-text-fill-color: #9E9E8A !important;
        }
        .stCheckbox label span {
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.78rem !important;
            color: #f0ece4 !important;
            -webkit-text-fill-color: #f0ece4 !important;
        }
        div[data-testid="stButton"][data-key*="gal_img_prev"] button,
        div[data-testid="stButton"][data-key*="gal_img_next"] button,
        div[data-testid="stButton"][data-key*="gal_vid_prev"] button,
        div[data-testid="stButton"][data-key*="gal_vid_next"] button {
            background: #0d0d0b !important;
            color: #f0ece4 !important;
            -webkit-text-fill-color: #f0ece4 !important;
            border: 1px solid rgba(255,255,255,0.15) !important;
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.8rem !important;
            font-weight: 600 !important;
        }
        div[data-testid="stExpander"] details summary {
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.85rem !important;
            font-weight: 600 !important;
            letter-spacing: 0.08em !important;
            color: #f0ece4 !important;
            -webkit-text-fill-color: #f0ece4 !important;
        }
        div[data-testid="stTextInput"][data-key*="sb_name"] input {
            background-color: #0d0d0b !important;
            color: #f0ece4 !important;
            -webkit-text-fill-color: #f0ece4 !important;
            border: 1px solid rgba(255,255,255,0.15) !important;
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.8rem !important;
        }
        div[data-testid="stAlert"] {
            background: #1a1a18 !important;
            border: 1px solid rgba(255,255,255,0.1) !important;
            color: #9E9E8A !important;
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.82rem !important;
        }
        /* ══════════════════════════════════════════════
           CINEMATIC GALLERY — modern card grid
           ══════════════════════════════════════════════ */
        div[data-testid="stImage"] {
            border-radius: 6px !important;
            overflow: hidden !important;
            transition: all 0.3s ease !important;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3) !important;
            border: 2px solid transparent !important;
        }
        div[data-testid="stImage"]:hover {
            box-shadow: 0 8px 24px rgba(0,0,0,0.5) !important;
            transform: translateY(-2px) !important;
            border-color: rgba(255,235,59,0.4) !important;
        }
        div[data-testid="stVideo"] {
            border-radius: 6px !important;
            overflow: hidden !important;
            transition: all 0.3s ease !important;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3) !important;
            border: 2px solid transparent !important;
        }
        div[data-testid="stVideo"]:hover {
            box-shadow: 0 8px 24px rgba(0,0,0,0.5) !important;
            transform: translateY(-2px) !important;
            border-color: rgba(255,20,147,0.4) !important;
        }
        div[data-testid="stCaption"] {
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.68rem !important;
            color: #7a7a6e !important;
            -webkit-text-fill-color: #7a7a6e !important;
            padding: 4px 2px 0 2px !important;
            line-height: 1.3 !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
        }
        div[data-testid="stCheckbox"][data-key^="sel_img_"],
        div[data-testid="stCheckbox"][data-key^="sel_vid_"] {
            margin-top: -2px !important;
            margin-bottom: 4px !important;
        }
        div[data-testid="stCheckbox"][data-key^="sel_img_"] label,
        div[data-testid="stCheckbox"][data-key^="sel_vid_"] label {
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.68rem !important;
            font-weight: 600 !important;
            color: #9E9E8A !important;
            -webkit-text-fill-color: #9E9E8A !important;
            gap: 4px !important;
        }
        div[data-testid="stCheckbox"][data-key^="sel_img_"]:has(input:checked) + div div[data-testid="stImage"],
        div[data-testid="stCheckbox"][data-key^="sel_vid_"]:has(input:checked) + div div[data-testid="stVideo"] {
            border-color: #FFEB3B !important;
            box-shadow: 0 0 12px rgba(255,235,59,0.3) !important;
        }
        div[data-testid="stCheckbox"][data-key^="sel_img_"]:has(input:checked) label,
        div[data-testid="stCheckbox"][data-key^="sel_vid_"]:has(input:checked) label {
            color: #FFEB3B !important;
            -webkit-text-fill-color: #FFEB3B !important;
        }
        div[data-testid="stButton"][data-key^="gal_img_"] button,
        div[data-testid="stButton"][data-key^="gal_vid_"] button {
            all: unset !important;
            cursor: pointer !important;
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.78rem !important;
            font-weight: 600 !important;
            color: #9E9E8A !important;
            -webkit-text-fill-color: #9E9E8A !important;
            padding: 6px 14px !important;
            border: 1px solid rgba(255,255,255,0.1) !important;
            border-radius: 4px !important;
            display: inline-block !important;
            text-align: center !important;
        }
        div[data-testid="stButton"][data-key^="gal_img_"] button:hover,
        div[data-testid="stButton"][data-key^="gal_vid_"] button:hover {
            color: #f0ece4 !important;
            -webkit-text-fill-color: #f0ece4 !important;
            border-color: rgba(255,255,255,0.3) !important;
        }
        div[data-testid="stButton"][data-key^="gal_img_"] button:disabled,
        div[data-testid="stButton"][data-key^="gal_vid_"] button:disabled {
            opacity: 0.3 !important;
            cursor: default !important;
        }
        div[data-testid="stHorizontalBlock"]:has(div[data-testid="stImage"]) {
            gap: 8px !important;
        }
        div[data-testid="stHorizontalBlock"]:has(div[data-testid="stVideo"]) {
            gap: 8px !important;
        }
        /* Hide storyboard action input — nuclear */
        div[data-testid="stTextInput"][data-key$="_action"],
        div[data-testid="stTextInput"][data-key$="_action"] * {
            height: 0 !important;
            max-height: 0 !important;
            overflow: hidden !important;
            margin: 0 !important;
            padding: 0 !important;
            opacity: 0 !important;
            position: absolute !important;
            pointer-events: none !important;
            border: none !important;
        }
        /* Gallery iframe bridges — never show as a visible box */
        div[data-testid="stTextInput"]:has(input[aria-label="gal_sel_bridge_inp"]),
        div[data-testid="stTextInput"]:has(input[aria-label="refs_pexels_sel_bridge"]),
        div[data-testid="stTextInput"]:has(input[aria-label="refs_unsplash_sel_bridge"]),
        div[data-testid="stTextInput"]:has(input[aria-label="gallery_action_input_img"]),
        div[data-testid="stTextInput"]:has(input[aria-label="proj_pick_bridge"]),
        div[data-testid="stTextInput"]:has(input[aria-label="sb_pick_bridge"]),
        div[data-testid="stTextInput"]:has(input[aria-label="ed_pick_bridge"]) {
            height: 0 !important;
            max-height: 0 !important;
            overflow: hidden !important;
            margin: 0 !important;
            padding: 0 !important;
            opacity: 0 !important;
            position: absolute !important;
            pointer-events: none !important;
            border: none !important;
        }
        /* ══ Editing clip selector buttons ══ */
        div[data-testid="stButton"][data-key*="_clip_"] button {
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.75rem !important;
            font-weight: 700 !important;
            min-height: 30px !important;
            height: 30px !important;
            padding: 2px 6px !important;
        }
        div[data-testid="stButton"][data-key*="_clip_"] button[kind="primary"] {
            background: #FF9800 !important;
            color: #000 !important;
            -webkit-text-fill-color: #000 !important;
            border: none !important;
        }
        div[data-testid="stButton"][data-key*="_clip_"] button:not([kind="primary"]) {
            background: #1a1a18 !important;
            color: #9E9E8A !important;
            -webkit-text-fill-color: #9E9E8A !important;
            border: 1px solid rgba(255,255,255,0.1) !important;
        }
        div[data-testid="stButton"][data-key*="_clip_"] button:not([kind="primary"]):hover {
            color: #FF9800 !important;
            -webkit-text-fill-color: #FF9800 !important;
            border-color: rgba(255,152,0,0.3) !important;
        }
        /* ══ Editing transport buttons ══ */
        div[data-testid="stButton"][data-key*="_prev"] button,
        div[data-testid="stButton"][data-key*="_next"] button,
        div[data-testid="stButton"][data-key*="_rm_clip"] button {
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.7rem !important;
            font-weight: 600 !important;
            min-height: 30px !important;
            height: 30px !important;
            background: #0d0d0b !important;
            color: #9E9E8A !important;
            -webkit-text-fill-color: #9E9E8A !important;
            border: 1px solid rgba(255,255,255,0.1) !important;
        }
        /* ══ Filmstrip select buttons ══ */
        div[data-testid="stButton"][data-key*="_sel_prev"] button,
        div[data-testid="stButton"][data-key*="_sel_next"] button {
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.65rem !important;
            font-weight: 600 !important;
            min-height: 26px !important;
            height: 26px !important;
            padding: 2px 8px !important;
            background: #0d0d0b !important;
            color: #555 !important;
            -webkit-text-fill-color: #555 !important;
            border: 1px solid rgba(255,255,255,0.08) !important;
        }
        div[data-testid="stButton"][data-key*="_sel_prev"] button:hover,
        div[data-testid="stButton"][data-key*="_sel_next"] button:hover {
            color: #FF9800 !important;
            -webkit-text-fill-color: #FF9800 !important;
            border-color: rgba(255,152,0,0.3) !important;
        }
        /* Jump-to buttons */
        div[data-testid="stButton"][data-key*="_jmp_"] button {
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.7rem !important;
            font-weight: 700 !important;
            min-height: 28px !important;
            height: 28px !important;
            padding: 2px 4px !important;
        }
        div[data-testid="stButton"][data-key*="_jmp_"] button[kind="primary"] {
            background: #FF9800 !important;
            color: #000 !important;
            -webkit-text-fill-color: #000 !important;
            border: none !important;
        }
        div[data-testid="stButton"][data-key*="_jmp_"] button:not([kind="primary"]) {
            background: #1a1a18 !important;
            color: #777 !important;
            -webkit-text-fill-color: #777 !important;
            border: 1px solid rgba(255,255,255,0.08) !important;
        }
        /* ══ Storyboard management buttons — clean compact ══ */
        div[data-testid="stButton"][data-key$="_new_btn"] button,
        div[data-testid="stButton"][data-key$="_recall_btn"] button,
        div[data-testid="stButton"][data-key$="_del_btn"] button {
            background: #0d0d0b !important;
            color: #9E9E8A !important;
            -webkit-text-fill-color: #9E9E8A !important;
            border: 1px solid rgba(255,255,255,0.12) !important;
            border-radius: 4px !important;
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.72rem !important;
            font-weight: 600 !important;
            padding: 4px 8px !important;
            min-height: 0 !important;
            height: 30px !important;
            letter-spacing: 0.04em !important;
        }
        div[data-testid="stButton"][data-key$="_new_btn"] button:hover {
            color: #f0ece4 !important;
            -webkit-text-fill-color: #f0ece4 !important;
            border-color: rgba(255,255,255,0.3) !important;
        }
        div[data-testid="stButton"][data-key$="_recall_btn"] button:hover {
            color: #f0ece4 !important;
            -webkit-text-fill-color: #f0ece4 !important;
            border-color: rgba(255,255,255,0.3) !important;
        }
        div[data-testid="stButton"][data-key$="_del_btn"] button:hover {
            color: #ff4444 !important;
            -webkit-text-fill-color: #ff4444 !important;
            border-color: #ff4444 !important;
        }
        /* New storyboard name input — compact, match height */
        div[data-testid="stTextInput"][data-key$="_new_name"] input {
            background: #1a1a18 !important;
            color: #f0ece4 !important;
            -webkit-text-fill-color: #f0ece4 !important;
            border: 1px solid rgba(255,255,255,0.12) !important;
            border-radius: 4px !important;
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.75rem !important;
            padding: 4px 10px !important;
            height: 30px !important;
        }
        div[data-testid="stTextInput"][data-key$="_new_name"] input:focus {
            border-color: rgba(255,255,255,0.25) !important;
            outline: none !important;
            box-shadow: none !important;
        }
        div[data-testid="stTextInput"][data-key$="_new_name"] input::placeholder {
            color: #555 !important;
            -webkit-text-fill-color: #555 !important;
        }
        /* Saved storyboard selectbox — compact */
        div[data-testid="stSelectbox"][data-key$="_saved_select"] [data-baseweb="select"] {
            background: #1a1a18 !important;
            border: 1px solid rgba(255,255,255,0.12) !important;
            border-radius: 4px !important;
            min-height: 30px !important;
            height: 30px !important;
        }
        div[data-testid="stSelectbox"][data-key$="_saved_select"] [data-baseweb="select"] * {
            color: #f0ece4 !important;
            -webkit-text-fill-color: #f0ece4 !important;
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.75rem !important;
        }
        /* Horizontal radio nav — all pages consistent */
        div[data-testid="stRadio"][data-key*="_nav"] > div {
            background: transparent !important;
            border: none !important;
            padding: 0 !important;
            gap: 0 !important;
        }
        div[data-testid="stRadio"][data-key*="_nav"] label {
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.82rem !important;
            font-weight: 600 !important;
            letter-spacing: 0.06em !important;
            color: #9E9E8A !important;
            -webkit-text-fill-color: #9E9E8A !important;
            padding: 8px 16px !important;
            cursor: pointer !important;
            border-bottom: 2px solid transparent !important;
            transition: all 0.2s !important;
        }
        div[data-testid="stRadio"][data-key*="_nav"] label:hover {
            color: #f0ece4 !important;
            -webkit-text-fill-color: #f0ece4 !important;
        }
        div[data-testid="stRadio"][data-key*="_nav"] label[data-checked="true"],
        div[data-testid="stRadio"][data-key*="_nav"] label:has(input:checked) {
            color: #f0ece4 !important;
            -webkit-text-fill-color: #f0ece4 !important;
            border-bottom: 2px solid #f0ece4 !important;
        }
        /* Hide radio circle dots */
        div[data-testid="stRadio"][data-key*="_nav"] input[type="radio"] {
            display: none !important;
        }
        div[data-testid="stRadio"][data-key*="_nav"] label > div:first-child {
            display: none !important;
        }
        /* STORYBOARD button — teal */
        div[data-testid="stButton"][data-key*="top_sb_images_btn"] > button,
        div[data-testid="stButton"][data-key*="top_sb_images_btn"] button {
            background: #00E5CC !important;
            color: #000000 !important;
            border: none !important;
            width: 100% !important;
            font-weight: 700 !important;
        }
        div[data-testid="stButton"][data-key*="top_sb_images_btn"] > button:hover,
        div[data-testid="stButton"][data-key*="top_sb_images_btn"] button:hover {
            background: #33FFE0 !important;
            box-shadow: 0 0 14px rgba(0, 229, 204, 0.55) !important;
        }
        /* EDITING button — orange */
        div[data-testid="stButton"][data-key*="top_sb_video_btn"] > button,
        div[data-testid="stButton"][data-key*="top_sb_video_btn"] button {
            background: #FF9800 !important;
            color: #000000 !important;
            border: none !important;
            width: 100% !important;
            font-weight: 700 !important;
        }
        div[data-testid="stButton"][data-key*="top_sb_video_btn"] > button:hover,
        div[data-testid="stButton"][data-key*="top_sb_video_btn"] button:hover {
            background: #FFB74D !important;
            box-shadow: 0 0 14px rgba(255, 152, 0, 0.55) !important;
        }
        /* Sortable drag items styling */
        .sortable-item {
            background: #1a1a18 !important;
            border: 1px solid rgba(255,255,255,0.12) !important;
            border-radius: 6px !important;
            color: #f0ece4 !important;
            padding: 6px 10px !important;
            margin: 3px !important;
            cursor: grab !important;
            font-size: 0.8rem !important;
        }
        .sortable-item:active {
            cursor: grabbing !important;
            border-color: #00E5CC !important;
            box-shadow: 0 0 10px rgba(0, 229, 204, 0.3) !important;
        }
        /* ══ Video grid play button — centered overlay ══════ */
        div[data-testid="stColumn"]:has(
            div[data-testid="stButton"][data-key^="play_vid_"]
        ) {
            position: relative !important;
        }
        div[data-testid="stButton"][data-key^="play_vid_"] {
            position: absolute !important;
            top: 50% !important;
            left: 50% !important;
            transform: translate(-50%, -92%) !important;
            margin: 0 !important;
            padding: 0 !important;
            width: 28px !important;
            height: 28px !important;
            z-index: 12 !important;
            pointer-events: auto !important;
        }

        div[data-testid="stButton"][data-key^="play_vid_"] button {
            all: unset !important;
            cursor: pointer !important;
            width: 28px !important;
            height: 28px !important;
            min-height: 0 !important;
            padding: 0 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            background: transparent !important;
            border-radius: 0 !important;
            color: #ffffff !important;
            font-size: 22px !important;
            border: none !important;
            box-shadow: none !important;
            line-height: 1 !important;
            letter-spacing: 0 !important;
            text-transform: none !important;
            text-shadow: 0 2px 6px rgba(0,0,0,.9) !important;
        }

        div[data-testid="stButton"][data-key^="play_vid_"] button:hover {
            background: transparent !important;
            color: #ffffff !important;
            transform: scale(1.08) !important;
        }
        /* ══ Selection bar — multiselect + ADD button ══ */
        div[data-testid="stMultiSelect"][data-key^="img_select_multi"] [data-baseweb="select"],
        div[data-testid="stMultiSelect"][data-key^="vid_select_multi"] [data-baseweb="select"] {
            background: #1a1a18 !important;
            border: 1px solid rgba(255,255,255,0.15) !important;
            border-radius: 6px !important;
            min-height: 36px !important;
        }
        div[data-testid="stMultiSelect"][data-key^="img_select_multi"] [data-baseweb="select"] *,
        div[data-testid="stMultiSelect"][data-key^="vid_select_multi"] [data-baseweb="select"] * {
            color: #f0ece4 !important;
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.75rem !important;
        }
        div[data-testid="stButton"][data-key="add_imgs_to_sb"] button {
            background: #00E5CC !important;
            color: #000 !important;
            -webkit-text-fill-color: #000 !important;
            border: none !important;
            font-weight: 700 !important;
            font-size: 0.78rem !important;
            letter-spacing: 0.06em !important;
        }
        div[data-testid="stButton"][data-key="add_imgs_to_sb"] button:hover {
            background: #33FFE0 !important;
            box-shadow: 0 0 14px rgba(0, 229, 204, 0.5) !important;
        }
        div[data-testid="stButton"][data-key="add_imgs_to_sb"] button:disabled {
            background: #1a1a18 !important;
            color: #555 !important;
            -webkit-text-fill-color: #555 !important;
            border: 1px solid rgba(255,255,255,0.1) !important;
        }
        div[data-testid="stButton"][data-key="add_vids_to_ed"] button {
            background: #FF9800 !important;
            color: #000 !important;
            -webkit-text-fill-color: #000 !important;
            border: none !important;
            font-weight: 700 !important;
            font-size: 0.78rem !important;
            letter-spacing: 0.06em !important;
        }
        div[data-testid="stButton"][data-key="add_vids_to_ed"] button:hover {
            background: #FFB74D !important;
            box-shadow: 0 0 14px rgba(255, 152, 0, 0.5) !important;
        }
        div[data-testid="stButton"][data-key="add_vids_to_ed"] button:disabled {
            background: #1a1a18 !important;
            color: #555 !important;
            -webkit-text-fill-color: #555 !important;
            border: 1px solid rgba(255,255,255,0.1) !important;
        }
        /* ══ PROJECTS button — console ══ */
        div[data-testid="stButton"][data-key="top_projects_btn"] button {
            background: #BB86FC !important;
            color: #000000 !important;
            -webkit-text-fill-color: #000000 !important;
            border: none !important;
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.85rem !important;
            font-weight: 700 !important;
            letter-spacing: 0.1em !important;
            text-transform: uppercase !important;
        }
        div[data-testid="stButton"][data-key="top_projects_btn"] button:hover {
            background: #CE93D8 !important;
            box-shadow: 0 0 14px rgba(187,134,252,0.5) !important;
        }
        /* ══ Projects page — buttons ══ */
        div[data-testid="stButton"][data-key="create_project_btn"] button {
            background: #BB86FC !important;
            color: #000 !important;
            -webkit-text-fill-color: #000 !important;
            border: none !important;
            font-weight: 700 !important;
        }
        div[data-testid="stButton"][data-key="create_project_btn"] button:hover {
            background: #CE93D8 !important;
        }
        div[data-testid="stButton"][data-key^="proj_select_"] button {
            background: #1a1a18 !important;
            color: #BB86FC !important;
            -webkit-text-fill-color: #BB86FC !important;
            border: 1px solid rgba(187,134,252,0.3) !important;
            font-size: 0.72rem !important;
            font-weight: 600 !important;
        }
        div[data-testid="stButton"][data-key^="proj_select_"] button:hover {
            border-color: #BB86FC !important;
            box-shadow: 0 0 8px rgba(187,134,252,0.3) !important;
        }
        div[data-testid="stButton"][data-key^="proj_rename_"] button {
            background: #1a1a18 !important;
            color: #9E9E8A !important;
            -webkit-text-fill-color: #9E9E8A !important;
            border: 1px solid rgba(255,255,255,0.12) !important;
            font-size: 0.72rem !important;
        }
        div[data-testid="stButton"][data-key^="proj_delete_"] button {
            background: #1a1a18 !important;
            color: #ff4444 !important;
            -webkit-text-fill-color: #ff4444 !important;
            border: 1px solid rgba(255,68,68,0.2) !important;
            font-size: 0.72rem !important;
        }
        div[data-testid="stButton"][data-key^="proj_delete_"] button:hover {
            border-color: #ff4444 !important;
            background: rgba(255,68,68,0.08) !important;
        }
        div[data-testid="stButton"][data-key="select_all_projects"] button {
            background: #1a1a18 !important;
            color: #9E9E8A !important;
            -webkit-text-fill-color: #9E9E8A !important;
            border: 1px solid rgba(255,255,255,0.12) !important;
            font-size: 0.78rem !important;
            font-weight: 600 !important;
        }
        div[data-testid="stButton"][data-key^="proj_sel_"] button:disabled {
            background: rgba(187,134,252,0.08) !important;
            color: #BB86FC !important;
            -webkit-text-fill-color: #BB86FC !important;
            border: 1px solid rgba(187,134,252,0.3) !important;
            opacity: 1 !important;
        }
        /* Projects page — new project input */
        div[data-testid="stTextInput"][data-key="new_project_name_input"] input {
            background: #1a1a18 !important;
            color: #f0ece4 !important;
            -webkit-text-fill-color: #f0ece4 !important;
            border: 1px solid rgba(187,134,252,0.2) !important;
            border-radius: 6px !important;
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.8rem !important;
        }
        div[data-testid="stTextInput"][data-key="new_project_name_input"] input:focus {
            border-color: #BB86FC !important;
        }
        /* ══ ASSETS button — console ══ */
        div[data-testid="stButton"][data-key="top_assets_btn"] button {
            background: #FFFFFF !important;
            color: #000000 !important;
            -webkit-text-fill-color: #000000 !important;
            border: none !important;
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.85rem !important;
            font-weight: 700 !important;
            letter-spacing: 0.1em !important;
            text-transform: uppercase !important;
        }
        div[data-testid="stButton"][data-key="top_assets_btn"] button:hover {
            background: #F0F0F0 !important;
            box-shadow: 0 0 14px rgba(255,255,255,0.4) !important;
        }
        /* ══ REFERENCES button — console ══ */
        div[data-testid="stButton"][data-key="top_references_btn"] button {
            background: #FFFFFF !important;
            color: #000000 !important;
            -webkit-text-fill-color: #000000 !important;
            border: none !important;
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.85rem !important;
            font-weight: 700 !important;
            letter-spacing: 0.1em !important;
            text-transform: uppercase !important;
        }
        div[data-testid="stButton"][data-key="top_references_btn"] button:hover {
            background: #F0F0F0 !important;
            box-shadow: 0 0 14px rgba(255,255,255,0.4) !important;
        }
        /* ══ JSON button — console left column ══ */
        div[data-testid="stButton"][data-key="json_settings_btn"] button {
            background: #0d0d0b !important;
            color: #00E5CC !important;
            -webkit-text-fill-color: #00E5CC !important;
            border: 1px solid rgba(0,229,204,0.3) !important;
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.8rem !important;
            font-weight: 700 !important;
            letter-spacing: 0.1em !important;
            text-transform: uppercase !important;
        }
        div[data-testid="stButton"][data-key="json_settings_btn"] button:hover {
            border-color: #00E5CC !important;
            box-shadow: 0 0 12px rgba(0,229,204,0.4) !important;
            background: rgba(0,229,204,0.06) !important;
        }
        /* JSON canvas — same cream style but monospace for readability */
        textarea[aria-label="CANVAS_PROMPT"]:disabled,
        div[data-testid="stTextArea"] textarea[aria-label="CANVAS_PROMPT"]:disabled {
            background-color: #F0EEE9 !important;
            color: #333333 !important;
            -webkit-text-fill-color: #333333 !important;
            font-family: 'JetBrains Mono', 'Fira Code', monospace !important;
            font-size: 0.75rem !important;
            opacity: 1 !important;
        }
        /* ══ TO ASSETS buttons — gallery/storyboard/editing ══ */
        /* ══ References room — bottom bar (cream) ══ */
        div[data-testid="stButton"][data-key^="refs_bar_storyboard_btn"] button,
        div[data-testid="stButton"][data-key^="refs_bar_asset_btn"] button {
            background: var(--refs-cream, #F5F5DC) !important;
            color: #1a1a12 !important;
            -webkit-text-fill-color: #1a1a12 !important;
            border: 1px solid rgba(26, 26, 18, 0.18) !important;
            border-radius: 6px !important;
            font-family: 'Open Sans', sans-serif !important;
            font-weight: 700 !important;
            font-size: 0.82rem !important;
            letter-spacing: 0.14em !important;
            text-transform: uppercase !important;
            min-height: 44px !important;
        }
        div[data-testid="stButton"][data-key^="refs_bar_storyboard_btn"] button:hover,
        div[data-testid="stButton"][data-key^="refs_bar_asset_btn"] button:hover {
            background: #faf8ec !important;
            box-shadow: 0 2px 14px rgba(245, 245, 220, 0.28) !important;
        }
        div[data-testid="stButton"][data-key^="refs_bar_storyboard_btn"] button:disabled,
        div[data-testid="stButton"][data-key^="refs_bar_asset_btn"] button:disabled {
            opacity: 0.42 !important;
            cursor: not-allowed !important;
            box-shadow: none !important;
        }
        /* ReferencesRoom — STORYBOARD/ASSET dock: fixed above scroll so long masonry does not push it away */
        div[data-testid="stVerticalBlockBorderWrapper"]:has(
            div[data-testid="stButton"][data-key^="refs_bar_storyboard_btn"]
        ) {
            position: fixed !important;
            bottom: 0 !important;
            left: 0 !important;
            right: 0 !important;
            z-index: 10001 !important;
            margin: 0 !important;
            max-width: none !important;
            width: 100% !important;
            box-sizing: border-box !important;
            padding: 0.55rem 1.25rem calc(0.7rem + env(safe-area-inset-bottom, 0px)) !important;
            background: rgba(12, 12, 10, 0.94) !important;
            backdrop-filter: blur(14px) !important;
            -webkit-backdrop-filter: blur(14px) !important;
            border: none !important;
            border-top: 1px solid rgba(245, 245, 220, 0.28) !important;
            border-radius: 0 !important;
            box-shadow: 0 -10px 36px rgba(0, 0, 0, 0.5) !important;
        }
        section[data-testid="stMain"] .block-container:has(
            div[data-testid="stButton"][data-key^="refs_bar_storyboard_btn"]
        ) {
            padding-bottom: 9.5rem !important;
        }
        /* References — CLEAR + row SAVE (cream, same family as bottom bar) */
        div[data-testid="stButton"][data-key="refs_pexels_clear_sel"] button,
        div[data-testid="stButton"][data-key="refs_unsplash_clear_sel"] button,
        div[data-testid="stButton"][data-key="refs_art_clear_sel"] button,
        div[data-testid="stButton"][data-key="refs_pexels_video_clear_sel"] button,
        div[data-testid="stButton"][data-key^="unsplash_save_"] button {
            background: var(--refs-cream, #F5F5DC) !important;
            color: #1a1a12 !important;
            -webkit-text-fill-color: #1a1a12 !important;
            border: 1px solid rgba(26, 26, 18, 0.18) !important;
            border-radius: 6px !important;
            font-family: 'Open Sans', sans-serif !important;
            font-weight: 700 !important;
            font-size: 0.72rem !important;
            letter-spacing: 0.1em !important;
            text-transform: uppercase !important;
            min-height: 38px !important;
        }
        div[data-testid="stButton"][data-key="refs_pexels_clear_sel"] button:hover,
        div[data-testid="stButton"][data-key="refs_unsplash_clear_sel"] button:hover,
        div[data-testid="stButton"][data-key="refs_art_clear_sel"] button:hover,
        div[data-testid="stButton"][data-key="refs_pexels_video_clear_sel"] button:hover,
        div[data-testid="stButton"][data-key^="unsplash_save_"] button:hover {
            background: #faf8ec !important;
            box-shadow: 0 2px 12px rgba(245, 245, 220, 0.25) !important;
        }
        div[data-testid="stButton"][data-key="save_imgs_to_assets"] button,
        div[data-testid="stButton"][data-key="save_vids_to_assets"] button,
        div[data-testid="stButton"][data-key*="_to_assets"] button {
            background: #0d0d0b !important;
            color: #BB86FC !important;
            -webkit-text-fill-color: #BB86FC !important;
            border: 1px solid rgba(187,134,252,0.3) !important;
            font-size: 0.72rem !important;
            font-weight: 600 !important;
        }
        div[data-testid="stButton"][data-key="save_imgs_to_assets"] button:hover,
        div[data-testid="stButton"][data-key="save_vids_to_assets"] button:hover,
        div[data-testid="stButton"][data-key*="_to_assets"] button:hover {
            border-color: #BB86FC !important;
            box-shadow: 0 0 10px rgba(187,134,252,0.3) !important;
        }
        div[data-testid="stButton"][data-key="save_imgs_to_assets"] button:disabled,
        div[data-testid="stButton"][data-key="save_vids_to_assets"] button:disabled,
        div[data-testid="stButton"][data-key*="_to_assets"] button:disabled {
            color: #555 !important;
            -webkit-text-fill-color: #555 !important;
            border-color: rgba(255,255,255,0.1) !important;
        }
        /* ══ ASSETS page — filter radio ══ */
        div[data-testid="stRadio"][data-key="assets_filter_radio"] > div {
            background: transparent !important;
            border: none !important;
            padding: 0 !important;
        }
        div[data-testid="stRadio"][data-key="assets_filter_radio"] label {
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.75rem !important;
            font-weight: 600 !important;
            color: #9E9E8A !important;
            -webkit-text-fill-color: #9E9E8A !important;
            padding: 6px 14px !important;
            border: 1px solid rgba(255,255,255,0.1) !important;
            border-radius: 4px !important;
            margin-right: 4px !important;
        }
        div[data-testid="stRadio"][data-key="assets_filter_radio"] label:has(input:checked) {
            color: #f0ece4 !important;
            -webkit-text-fill-color: #f0ece4 !important;
            border-color: #f0ece4 !important;
            background: rgba(255,255,255,0.06) !important;
        }
        div[data-testid="stRadio"][data-key="assets_filter_radio"] input[type="radio"] {
            display: none !important;
        }
        div[data-testid="stRadio"][data-key="assets_filter_radio"] label > div:first-child {
            display: none !important;
        }
        /* ASSETS delete — icona compatta senza scale (evita tagli da overflow) */
        div[data-testid="stButton"][data-key^="asset_del_"] {
            overflow: visible !important;
        }
        div[data-testid="stButton"][data-key^="asset_del_"] button {
            all: unset !important;
            cursor: pointer !important;
            font-size: 0.75rem !important;
            color: #666 !important;
            padding: 4px 6px !important;
            line-height: 1.2 !important;
            min-height: 1.5em !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            overflow: visible !important;
            box-sizing: content-box !important;
        }
        div[data-testid="stButton"][data-key^="asset_del_"] button:hover {
            color: #ff4444 !important;
        }
        /* Cestino sotto il preview (stessa riga del nome), colonna destra — niente overlay sul titolo */
        div[data-testid="stButton"][data-key^="asset_del_image_"],
        div[data-testid="stButton"][data-key^="asset_del_video_"] {
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            margin: 0 !important;
            padding: 2px 0 2px 2px !important;
            min-height: 28px !important;
            overflow: visible !important;
        }
        div[data-testid="stButton"][data-key^="asset_del_audio_"] {
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            min-height: 0 !important;
            margin-top: -2px !important;
        }
        /* ASSETS multiselects in WORKFLOW */
        div[data-testid="stMultiSelect"][data-key^="s2_assets_"] [data-baseweb="select"],
        div[data-testid="stMultiSelect"][data-key^="sd_assets_"] [data-baseweb="select"] {
            background: #1a1a18 !important;
            border: 1px dashed rgba(187,134,252,0.25) !important;
            border-radius: 6px !important;
            min-height: 32px !important;
        }
        div[data-testid="stMultiSelect"][data-key^="s2_assets_"] [data-baseweb="select"] *,
        div[data-testid="stMultiSelect"][data-key^="sd_assets_"] [data-baseweb="select"] * {
            color: #BB86FC !important;
            font-size: 0.7rem !important;
        }
        /* Assets upload area */
        div[data-testid="stFileUploader"][data-key="assets_desktop_upload"] {
            border: 1px dashed rgba(255,255,255,0.15) !important;
            border-radius: 6px !important;
            padding: 0.5rem !important;
            margin-bottom: 1rem !important;
        }
        div[data-testid="stFileUploader"][data-key="assets_desktop_upload"] label {
            color: #7a7a6e !important;
            font-size: 0.72rem !important;
        }
        /* Assets pagination buttons */
        div[data-testid="stButton"][data-key="assets_prev"] button,
        div[data-testid="stButton"][data-key="assets_next"] button {
            background: #0d0d0b !important;
            color: #f0ece4 !important;
            -webkit-text-fill-color: #f0ece4 !important;
            border: 1px solid rgba(255,255,255,0.15) !important;
            font-family: 'Open Sans', sans-serif !important;
            font-size: 0.78rem !important;
            font-weight: 600 !important;
        }
        /* ══ Compact cinematography tabs ══ */
        div[data-testid="stExpander"]:has(div[data-baseweb="tab-list"]) .stTabs [data-baseweb="tab"] {
            padding: 8px 12px !important;
            font-size: 0.72rem !important;
            letter-spacing: 0.04em !important;
        }
        </style>
    """, unsafe_allow_html=True)

    # Titolo e riga progetto solo sulla Console: evita il "flash" di UI console
    # su Gallery/Projects/Assets/Storyboard/Editing durante il rerun.
    _ap_top = st.session_state.get("active_page", "console")
    if _ap_top == "console":
        st.markdown(
            '<div style="text-align: center; margin-bottom: 0.25rem;">'
            '<span style="font-family: \'Open Sans\', sans-serif; font-size: 1.64rem; font-weight: 600; '
            'letter-spacing: 0.06em; color: #2196F3; -webkit-text-fill-color: #2196F3;">'
            'SEEDANCE DOP CONSOLE</span>'
            '</div>'
            '<div style="text-align: center; margin-top: -6px; '
            'font-family: \'Open Sans\', sans-serif; font-size: 0.75rem; font-weight: 600; '
            'color: #f0ece4; -webkit-text-fill-color: #f0ece4;">'
            'Built by Alessio Valori DOP'
            '</div>',
            unsafe_allow_html=True,
        )
        _cons_nav_row_l, _cons_nav_row_r = st.columns([4, 1])
        with _cons_nav_row_r:
            _render_project_name_inline_right()

    if 'trigger_seed_update' not in st.session_state: st.session_state.trigger_seed_update = False
    if st.session_state.trigger_seed_update:
        max_vars = st.session_state.get('common_num_variations', 1)
        for i in range(max_vars): st.session_state[f'seed_input_{i}'] = str(random.randint(1, 1000000))
        st.session_state.trigger_seed_update = False

    LIST_CAMERA_ANGLES = ["Not specified", "Eye-level", "High Angle", "Low Angle", "Bird View (Overhead)", "Ant Perspective (Worm's Eye)", "Over-the-shoulder", "Subjective View (POV)", "Surveillance View (Fisheye)", "Telescope View", "Peeping Perspective"]
    LIST_SUBJECT_ANGLES = ["Not specified", "Front View", "Profile", "Half-profile", "Back View", "Top View", "Bottom View"]
    LIST_MOVEMENTS = ["Not specified", "Static", "Dolly-in", "Dolly-out", "Pan", "Track", "Follow (Behind)", "Lead (Ahead)", "Rise (Crane Up)", "Fall (Crane Down)", "Whirl", "Rotate", "Surround (Orbit)", "Zoom", "Hitchcock Zoom", "Bullet Time"]
    LIST_PACES = ["Not specified", "Extremely Slow", "Slow", "Normal", "Fast", "Dynamic", "Time-lapse"]
    LIST_STYLES = ["Not specified", "Realistic / Photorealistic", "Japanese Anime (Manga)", "Disney-style Animation", "Pixar-style Animation", "Studio Ghibli Style", "Cyberpunk", "Solarpunk", "Dark Fantasy", "Cthulhu / Body Horror", "Oil Painting", "Japanese Drama (Little Forest Style)"]
    LIST_MOODS = ["Not specified", "Optimistic", "Melancholic", "Tense", "Romantic", "Mysterious", "Heroic", "Noir", "Dreamy", "Documentary / Neutral", "Epic", "Intimate", "Surreal", "Nostalgic", "Urgent", "Peaceful"]
    LIST_PERIODS = ["Not specified", "Contemporary", "1920s / Art Deco", "1930s–40s", "1950s", "1960s–70s", "Medieval", "Victorian", "Renaissance", "Ancient", "Futuristic", "Retro-futurism", "Timeless / Unspecified"]
    LIST_CAMERAS = ["Not specified", "ARRI Alexa", "ARRI Alexa Mini", "RED Komodo", "RED Ranger", "Sony Venice", "Sony FX", "Blackmagic", "Canon C70", "Panasonic Varicam", "Film (35mm)", "Film (16mm)", "Other / Custom"]
    LIST_LENSES = ["Not specified", "Cooke S4/i", "Cooke S7/i", "Cooke Anamorphic/i", "Cooke Speed Panchro", "ARRI Signature Prime", "ARRI Master Anamorphic", "ARRI Ultra Prime", "ARRI Alura", "Zeiss Supreme Prime", "Zeiss Compact Prime", "Zeiss Master Anamorphic", "Zeiss Super Speed", "Canon K35", "Canon Sumire Prime", "Canon Cine-Servo", "Panavision Primo 70", "Panavision T Series Anamorphic", "Leica Summilux-C", "Leica Thalia", "Angenieux EZ", "Angenieux Optimo Style", "Other / Custom"]
    LIST_SHOT_TYPES = ["Not specified", "Wide Shot", "Full Shot", "Medium Wide", "Medium Shot", "Medium Close-up", "Close-up", "Big Close-up", "Extreme Close-up", "Insert", "Two Shot", "Bust", "Half-length Portrait", "Full-length Portrait"]
    LIST_FILM_STOCKS = ["Not specified", "Digital (no stock)", "Kodak 5219 (500T)", "Kodak 5207 (250D)", "Kodak 5213 (200T)", "Fuji Eterna", "Fuji Eterna Vivid", "Kodak Vision3", "Film emulation (custom)", "Other"]
    LIST_SENSORS = ["Not specified", "Full Frame", "Super 35", "Super 16", "Micro Four Thirds", "Large format", "Vista Vision", "Other"]
    LIST_LIGHTING_SOURCE = ["Not specified", "Natural only", "Artificial only", "Practical (in-frame)", "Mixed natural + artificial", "Studio", "Available light", "Single source", "Multiple sources"]
    LIST_LIGHTING = ["Not specified", "Natural daylight", "Golden hour", "Hard directional", "Soft diffused", "Low-key (Chiaroscuro)", "Neon / Cyberpunk", "Candlelight", "Tyndall Effect (God Rays)"]
    LIST_LIGHTING_DIRECTION = ["Not specified", "Front Lighting", "Side Lighting (Cross Lighting)", "Backlighting", "Top Lighting", "Underlighting (Bottom Light)", "Three-Point Lighting", "Rembrandt Lighting", "Butterfly (Paramount) Lighting", "High-Key Lighting", "Low-Key Lighting"]
    LIST_LANGUAGES = ["English", "Mandarin", "Cantonese", "Sichuan Dialect", "Shaanxi Dialect", "Taiwanese Accent", "Japanese", "Korean", "Spanish", "Indonesian"]
    LIST_EMOTIONS = ["Neutral", "Calm", "Gentle", "Restrained", "Forceful", "Confident", "Happy", "Sad", "Whispering", "Flustered", "Alert"]

    if 'show_generate_button' not in st.session_state: st.session_state.show_generate_button = False
    if 'last_num_variations' not in st.session_state: st.session_state.last_num_variations = 1
    if 'show_image_generate_button' not in st.session_state: st.session_state.show_image_generate_button = False
    if 's2_last_result' not in st.session_state: st.session_state.s2_last_result = None
    if 's2_raw_prompt' not in st.session_state: st.session_state.s2_raw_prompt = ""
    if 's2_opt_prompt' not in st.session_state: st.session_state.s2_opt_prompt = ""
    if 'sd_last_result' not in st.session_state: st.session_state.sd_last_result = None
    if 'sd_raw_prompt' not in st.session_state: st.session_state.sd_raw_prompt = ""
    if 'sd_opt_prompt' not in st.session_state: st.session_state.sd_opt_prompt = ""
    if 'gallery_selected_imgs' not in st.session_state:
        st.session_state.gallery_selected_imgs = set()
    if 'gallery_selected_vids' not in st.session_state:
        st.session_state.gallery_selected_vids = set()
    if "refs_selected_pexels" not in st.session_state:
        st.session_state.refs_selected_pexels = set()
    if "refs_selected_unsplash" not in st.session_state:
        st.session_state.refs_selected_unsplash = set()
    if "refs_selected_art_chicago" not in st.session_state:
        st.session_state.refs_selected_art_chicago = set()
    if "refs_selected_met" not in st.session_state:
        st.session_state.refs_selected_met = set()
    if "refs_selected_wiki" not in st.session_state:
        st.session_state.refs_selected_wiki = set()
    if "_refs_wiki_by_id" not in st.session_state:
        st.session_state._refs_wiki_by_id = {}
    if "_refs_met_by_id" not in st.session_state:
        st.session_state._refs_met_by_id = {}
    if "refs_selected_google_arts" not in st.session_state:
        st.session_state.refs_selected_google_arts = set()
    if "_refs_google_arts_by_id" not in st.session_state:
        st.session_state._refs_google_arts_by_id = {}
    if "refs_selected_pexels_videos" not in st.session_state:
        st.session_state.refs_selected_pexels_videos = set()
    if "_refs_pexels_video_by_id" not in st.session_state:
        st.session_state._refs_pexels_video_by_id = {}
    if "_refs_pexels_video_ids_current" not in st.session_state:
        st.session_state._refs_pexels_video_ids_current = []
    if "refs_selected_pixabay_videos" not in st.session_state:
        st.session_state.refs_selected_pixabay_videos = set()
    if "_refs_pixabay_video_by_id" not in st.session_state:
        st.session_state._refs_pixabay_video_by_id = {}
    if "_refs_pixabay_video_ids_current" not in st.session_state:
        st.session_state._refs_pixabay_video_ids_current = []
    if "refs_selected_coverr_videos" not in st.session_state:
        st.session_state.refs_selected_coverr_videos = set()
    if "_refs_coverr_video_by_id" not in st.session_state:
        st.session_state._refs_coverr_video_by_id = {}
    if "_refs_coverr_video_ids_current" not in st.session_state:
        st.session_state._refs_coverr_video_ids_current = []
    if "selected_images" not in st.session_state:
        # Map: "<source>:<id>" -> {source,id,url,caption,provenance,...}
        st.session_state.selected_images = {}
    if 'sb_mode' not in st.session_state:
        st.session_state.sb_mode = None          # None | "new" | "loaded"
    if 'sb_active_name' not in st.session_state:
        st.session_state.sb_active_name = ""
    if 'sb_active_images' not in st.session_state:
        st.session_state.sb_active_images = []

    if 'ed_mode' not in st.session_state:
        st.session_state.ed_mode = None
    if 'ed_active_name' not in st.session_state:
        st.session_state.ed_active_name = ""
    if 'ed_active_videos' not in st.session_state:
        st.session_state.ed_active_videos = []
    if 'gallery_img_page' not in st.session_state: st.session_state.gallery_img_page = 0
    if 'gallery_vid_page' not in st.session_state: st.session_state.gallery_vid_page = 0
    if 'assets_filter' not in st.session_state:
        st.session_state.assets_filter = "All"
    if 'assets_page' not in st.session_state:
        st.session_state.assets_page = 0
    if 'gallery_vid_preview_idx' not in st.session_state:
        st.session_state.gallery_vid_preview_idx = -1
    if 'gallery_images' not in st.session_state or 'gallery_videos' not in st.session_state:
        loaded_videos, loaded_images = load_gallery_from_disk()
        if 'gallery_videos' not in st.session_state: st.session_state.gallery_videos = loaded_videos
        if 'gallery_images' not in st.session_state: st.session_state.gallery_images = loaded_images
    if 'active_page' not in st.session_state: st.session_state.active_page = 'console'
    _restore_console_param_snapshot()
    if 'model_selector' not in st.session_state: st.session_state.model_selector = 'SEEDANCE 2.0'
    if 'video_resolution' not in st.session_state: st.session_state.video_resolution = "1080p"
    if 'video_aspect_ratio' not in st.session_state: st.session_state.video_aspect_ratio = "adaptive"
    if 'common_duration' not in st.session_state: st.session_state.common_duration = 15
    if 's2_smart_duration' not in st.session_state: st.session_state.s2_smart_duration = False
    if 's2_watermark' not in st.session_state: st.session_state.s2_watermark = False
    if 'common_temperature' not in st.session_state: st.session_state.common_temperature = 0.5
    if 'common_num_variations' not in st.session_state: st.session_state.common_num_variations = 1
    if 'enable_audio' not in st.session_state: st.session_state.enable_audio = False
    if 'en_s2' not in st.session_state: st.session_state.en_s2 = False
    if 'en_s3' not in st.session_state: st.session_state.en_s3 = False
    if 'v_lang' not in st.session_state: st.session_state.v_lang = LIST_LANGUAGES[0]
    if 'v_emo' not in st.session_state: st.session_state.v_emo = LIST_EMOTIONS[0]
    if 'v_timbre' not in st.session_state: st.session_state.v_timbre = "Normal"
    if 'v_pace' not in st.session_state: st.session_state.v_pace = "Normal"
    for _prefix in ["s"]:
        for _shot_n in range(1, 4):
            _k = f"{_prefix}{_shot_n}"
            if f"{_k}_shot_type" not in st.session_state: st.session_state[f"{_k}_shot_type"] = LIST_SHOT_TYPES[0]
            if f"{_k}_style" not in st.session_state: st.session_state[f"{_k}_style"] = LIST_STYLES[0]
            if f"{_k}_mood" not in st.session_state: st.session_state[f"{_k}_mood"] = LIST_MOODS[0]
            if f"{_k}_period" not in st.session_state: st.session_state[f"{_k}_period"] = LIST_PERIODS[0]
            if f"{_k}_camera" not in st.session_state: st.session_state[f"{_k}_camera"] = LIST_CAMERAS[0]
            if f"{_k}_lenses" not in st.session_state: st.session_state[f"{_k}_lenses"] = LIST_LENSES[0]
            if f"{_k}_film_stock" not in st.session_state: st.session_state[f"{_k}_film_stock"] = LIST_FILM_STOCKS[0]
            if f"{_k}_sensor" not in st.session_state: st.session_state[f"{_k}_sensor"] = LIST_SENSORS[0]
            if f"{_k}_light_src" not in st.session_state: st.session_state[f"{_k}_light_src"] = LIST_LIGHTING_SOURCE[0]
            if f"{_k}_light_dir" not in st.session_state: st.session_state[f"{_k}_light_dir"] = LIST_LIGHTING_DIRECTION[0]
            if f"{_k}_light" not in st.session_state: st.session_state[f"{_k}_light"] = LIST_LIGHTING[0]
            if f"{_k}_tb" not in st.session_state: st.session_state[f"{_k}_tb"] = 5
            if f"{_k}_tc" not in st.session_state: st.session_state[f"{_k}_tc"] = 5
            if f"{_k}_ts" not in st.session_state: st.session_state[f"{_k}_ts"] = 5
            if f"{_k}_tt" not in st.session_state: st.session_state[f"{_k}_tt"] = 5
            if f"{_k}_tbo" not in st.session_state: st.session_state[f"{_k}_tbo"] = 3
            if f"{_k}_tsh" not in st.session_state: st.session_state[f"{_k}_tsh"] = 5
            if f"{_k}_tv" not in st.session_state: st.session_state[f"{_k}_tv"] = 0
            if f"{_k}_tca" not in st.session_state: st.session_state[f"{_k}_tca"] = 0
            if f"{_k}_tg" not in st.session_state: st.session_state[f"{_k}_tg"] = 0
            if f"{_k}_tso" not in st.session_state: st.session_state[f"{_k}_tso"] = 0
            if f"{_k}_tmb" not in st.session_state: st.session_state[f"{_k}_tmb"] = 5
            if f"{_k}_m1_type" not in st.session_state: st.session_state[f"{_k}_m1_type"] = LIST_MOVEMENTS[0]
            if f"{_k}_m1_pace" not in st.session_state: st.session_state[f"{_k}_m1_pace"] = LIST_PACES[0]
            if f"{_k}_m1_s" not in st.session_state: st.session_state[f"{_k}_m1_s"] = (0 if _shot_n == 1 else 5)
            if f"{_k}_m1_e" not in st.session_state: st.session_state[f"{_k}_m1_e"] = (4 if _shot_n == 1 else 10)
            if f"{_k}_m1_ca" not in st.session_state: st.session_state[f"{_k}_m1_ca"] = LIST_CAMERA_ANGLES[0]
            if f"{_k}_m1_so" not in st.session_state: st.session_state[f"{_k}_m1_so"] = LIST_SUBJECT_ANGLES[0]
            if f"{_k}_m2_type" not in st.session_state: st.session_state[f"{_k}_m2_type"] = LIST_MOVEMENTS[0]
            if f"{_k}_m2_pace" not in st.session_state: st.session_state[f"{_k}_m2_pace"] = LIST_PACES[0]
            if f"{_k}_m2_s" not in st.session_state: st.session_state[f"{_k}_m2_s"] = (4 if _shot_n == 1 else 10)
            if f"{_k}_m2_e" not in st.session_state: st.session_state[f"{_k}_m2_e"] = (8 if _shot_n == 1 else 15)
            if f"{_k}_m2_ca" not in st.session_state: st.session_state[f"{_k}_m2_ca"] = LIST_CAMERA_ANGLES[0]
            if f"{_k}_m2_so" not in st.session_state: st.session_state[f"{_k}_m2_so"] = LIST_SUBJECT_ANGLES[0]
    if 'json_preview' not in st.session_state:
        st.session_state.json_preview = None  # None or JSON string

    # One-shot migration of legacy projects (no per-project settings file yet).
    # Runs once; marker file at data/db/.migration_per_project_v1_done blocks repeats.
    _migrate_legacy_projects_to_per_project_settings()

    # ── Projects ──
    if 'active_project_id' not in st.session_state:
        proj_data = load_projects()
        st.session_state.active_project_id = proj_data.get("active_project_id")
    if 'active_project_name' not in st.session_state:
        proj_data = load_projects()
        active_id = st.session_state.active_project_id
        if active_id:
            proj = next((p for p in proj_data.get("projects", []) if p["id"] == active_id), None)
            st.session_state.active_project_name = proj["name"] if proj else "All Projects"
        else:
            st.session_state.active_project_name = "All Projects"

    # First-time load of active project's saved Console settings
    if not st.session_state.get("_project_settings_loaded_for"):
        _aid = st.session_state.get("active_project_id")
        if _aid:
            _load_project_console_settings(_aid)
        st.session_state["_project_settings_loaded_for"] = _aid or "_none_"

    max_seeds = st.session_state.get('common_num_variations', 1)
    for i in range(max_seeds):
        if f'seed_input_{i}' not in st.session_state: st.session_state[f'seed_input_{i}'] = str(random.randint(1, 1000000))

    def render_shot_panel(shot_num, key_prefix="s"):
        k = f"{key_prefix}{shot_num}"
        data = {}
        data['assets'] = st.text_input(f"Target Assets for Shot {shot_num}", placeholder="e.g., @Image 1, @Video 2", key=f"{k}_assets")
        tab_shot_type, tab_style, tab_gear, tab_lighting, tab_tones, tab_atmos = st.tabs(
            ["Shots", "Style", "Gear", "Lights", "Tones", "Atmos VFX"]
        )
        with tab_shot_type:
            data['shot_type'] = st.selectbox("Shot Type", LIST_SHOT_TYPES, key=f"{k}_shot_type")
        with tab_style:
            data['style'] = st.selectbox("Visual Style", LIST_STYLES, key=f"{k}_style")
            data['mood'] = st.selectbox("Mood", LIST_MOODS, key=f"{k}_mood")
            data['period'] = st.selectbox("Period / Era", LIST_PERIODS, key=f"{k}_period")
        with tab_gear:
            data['camera'] = st.selectbox("Camera", LIST_CAMERAS, key=f"{k}_camera")
            data['lenses'] = st.selectbox("Lenses", LIST_LENSES, key=f"{k}_lenses")
            data['film_stock'] = st.selectbox("Film Stock", LIST_FILM_STOCKS, key=f"{k}_film_stock")
            data['sensor'] = st.selectbox("Sensor", LIST_SENSORS, key=f"{k}_sensor")
        with tab_lighting:
            data['lighting_source'] = st.selectbox("Lighting Source", LIST_LIGHTING_SOURCE, key=f"{k}_light_src")
            data['lighting_direction'] = st.selectbox("Lighting Direction", LIST_LIGHTING_DIRECTION, key=f"{k}_light_dir")
            data['lighting'] = st.selectbox("Lighting Type", LIST_LIGHTING, key=f"{k}_light")
        with tab_tones:
            data['tone_brightness'] = st.slider("Brightness", 0, 10, key=f"{k}_tb")
            data['tone_contrast'] = st.slider("Contrast", 0, 10, key=f"{k}_tc")
            data['tone_saturation'] = st.slider("Saturation", 0, 10, key=f"{k}_ts")
            data['tone_temperature'] = st.slider("Color Temp.", 0, 10, key=f"{k}_tt")
            data['tone_bokeh'] = st.slider("Background Bokeh", 0, 10, key=f"{k}_tbo")
            data['tone_sharpness'] = st.slider("Sharpness", 0, 10, key=f"{k}_tsh")
            data['tone_vignette'] = st.slider("Vignette", 0, 10, key=f"{k}_tv")
            data['tone_chromatic'] = st.slider("Chromatic Aberr.", 0, 10, key=f"{k}_tca")
            data['tone_grain'] = st.slider("Film Grain", 0, 10, key=f"{k}_tg")
            data['tone_softness'] = st.slider("Softness (Bloom)", 0, 10, key=f"{k}_tso")
            data['tone_motionblur'] = st.slider("Motion Blur", 0, 10, key=f"{k}_tmb")
            st.markdown("**Color Grading**")
            default_colors = ["#1E90FF", "#FF4500", "#32CD32"]
            color_maps = []
            if f'color_count_{k}' not in st.session_state: st.session_state[f'color_count_{k}'] = 1
            for i in range(st.session_state[f'color_count_{k}']):
                c_hex, c_tar = st.columns([1, 4])
                with c_hex: hex_val = st.color_picker(f"C{i+1}", value=default_colors[i%3], key=f"{k}_c_hex_{i}", label_visibility="collapsed")
                with c_tar: target_val = st.text_input(f"Target", placeholder="e.g., Sky...", key=f"{k}_c_tar_{i}", label_visibility="collapsed")
                if target_val.strip(): color_maps.append((hex_val, target_val.strip()))
            if st.session_state[f'color_count_{k}'] < 3:
                if st.button("Add Color", key=f"add_c_btn_{k}"):
                    st.session_state[f'color_count_{k}'] += 1
                    st.rerun()
            data['color_palette'] = color_maps
        with tab_atmos:
            data['vfx_atmos'] = st.text_input(
                "Atmosphere Notes",
                placeholder="e.g., Fog, dust particles, rain, haze...",
                key=f"{k}_vfx_a",
            )
            data['vfx_effects'] = st.text_input(
                "VFX",
                placeholder="e.g., Lens flare, motion trails, sparks...",
                key=f"{k}_vfx_e",
            )
        c1, c2, c3, c4 = st.columns([2, 1.5, 1, 1], gap="medium")
        with c1: data['m1_type'] = st.selectbox("Movement Type", LIST_MOVEMENTS, key=f"{k}_m1_type")
        with c2: data['m1_pace'] = st.selectbox("Pace", LIST_PACES, key=f"{k}_m1_pace")
        with c3: data['m1_start'] = st.number_input("Start (s)", min_value=0, max_value=15, key=f"{k}_m1_s")
        with c4: data['m1_end'] = st.number_input("End (s)", min_value=0, max_value=15, key=f"{k}_m1_e")
        c8, c9 = st.columns([1, 1], gap="medium")
        with c8: data['m1_angle'] = st.selectbox("Camera Angle", LIST_CAMERA_ANGLES, key=f"{k}_m1_ca")
        with c9: data['m1_subj'] = st.selectbox("Subject Orientation", LIST_SUBJECT_ANGLES, key=f"{k}_m1_so")
        if f"show_secondary_{k}" not in st.session_state: st.session_state[f"show_secondary_{k}"] = False
        if st.session_state[f"show_secondary_{k}"]:
            c1b, c2b, c3b, c4b = st.columns([2, 1.5, 1, 1], gap="medium")
            with c1b: data['m2_type'] = st.selectbox("Movement Type", LIST_MOVEMENTS, key=f"{k}_m2_type")
            with c2b: data['m2_pace'] = st.selectbox("Pace", LIST_PACES, key=f"{k}_m2_pace")
            with c3b: data['m2_start'] = st.number_input("Start (s)", min_value=0, max_value=15, key=f"{k}_m2_s")
            with c4b: data['m2_end'] = st.number_input("End (s)", min_value=0, max_value=15, key=f"{k}_m2_e")
            c8b, c9b = st.columns([1, 1], gap="medium")
            with c8b: data['m2_angle'] = st.selectbox("Camera Angle (End)", LIST_CAMERA_ANGLES, key=f"{k}_m2_ca")
            with c9b: data['m2_subj'] = st.selectbox("Subject Orientation (End)", LIST_SUBJECT_ANGLES, key=f"{k}_m2_so")
        else:
            if st.button("Add motions", key=f"add_motions_{k}"):
                st.session_state[f"show_secondary_{k}"] = True
                st.rerun()
            data['m2_type'] = data['m2_pace'] = data['m2_start'] = data['m2_end'] = None
            data['m2_angle'] = data['m2_subj'] = None
        return data

    def _build_settings_json(model_sel, **kwargs):
        """Collect all UI parameters into a structured dict for JSON export."""
        settings = {
            "meta": {
                "app": "AI DOP Console",
                "exported_at": datetime.now().isoformat(),
                "project": get_active_project_name(),
            },
            "model": model_sel,
        }

        if model_sel == "SEEDANCE 2.0":
            settings["scene_description"] = kwargs.get("action_desc", "")
            settings["workflow"] = {
                "entry_point": kwargs.get("entry_point", ""),
                "workflow_type": kwargs.get("workflow", "Standard Generation"),
                "image_usage": kwargs.get("image_usage", "auto"),
            }
            settings["technical"] = {
                "resolution": kwargs.get("resolution", "1080p"),
                "aspect_ratio": kwargs.get("aspect_ratio", "16:9"),
                "duration_sec": kwargs.get("duration", 15),
                "processing_mode": kwargs.get("gen_mode", "Standard (Online)"),
            }
            settings["creativity"] = {
                "temperature": kwargs.get("temperature", 0.5),
                "seeds": kwargs.get("seeds", []),
            }
            settings["files"] = {
                "images": kwargs.get("num_imgs", 0),
                "videos": kwargs.get("num_vids", 0),
                "audio": kwargs.get("num_auds", 0),
                "total": kwargs.get("total_files", 0),
            }
            settings["audio_generation"] = {
                "enabled": kwargs.get("gen_audio", False),
                "details": kwargs.get("audio_details", {}),
            }

        elif model_sel == "SEEDREAM 5.0":
            settings["prompt"] = kwargs.get("prompt", "")
            settings["style"] = {
                "preset": kwargs.get("style", "None"),
                "shot_type": kwargs.get("shot_type"),
                "mood": kwargs.get("mood"),
                "period": kwargs.get("period"),
            }
            settings["gear"] = {
                "camera": kwargs.get("camera"),
                "lenses": kwargs.get("lenses"),
                "film_stock": kwargs.get("film_stock"),
                "sensor": kwargs.get("sensor"),
            }
            settings["lighting"] = {
                "source": kwargs.get("lighting_source"),
                "direction": kwargs.get("lighting_direction"),
                "type": kwargs.get("lighting_type"),
            }
            settings["technical"] = {
                "resolution": kwargs.get("resolution", "2K"),
                "aspect_ratio": kwargs.get("aspect_ratio", "Smart"),
                "optimize_prompt": kwargs.get("optimize", "None"),
            }
            settings["files"] = {
                "reference_images": kwargs.get("num_refs", 0),
            }

        # Cinematography / shots data (Seedance 2.0)
        shots = kwargs.get("shots_data", [])
        if shots:
            settings["cinematography"] = []
            for i, shot in enumerate(shots):
                shot_entry = {"shot_number": i + 1}
                for key, val in shot.items():
                    if val is not None and val != "Not specified" and val != "":
                        # Convert color_palette tuples to dicts
                        if key == "color_palette" and isinstance(val, list):
                            shot_entry[key] = [{"hex": h, "target": t} for h, t in val]
                        else:
                            shot_entry[key] = val
                settings["cinematography"].append(shot_entry)

        # Remove None values for cleaner output
        def _clean(obj):
            if isinstance(obj, dict):
                return {k: _clean(v) for k, v in obj.items() if v is not None and v != "" and v != "Not specified"}
            elif isinstance(obj, list):
                return [_clean(item) for item in obj]
            return obj

        return _clean(settings)

    def _render_storyboard_grid(items_key, selection_key, media_type, page_prefix):
        items = st.session_state.get(items_key, [])
        if not items:
            st.info(f"No {media_type}s selected. Go to Gallery → ☆ to add.")
            return
        total = len(items)
        action_key = f"{page_prefix}_action"
        action_val = st.session_state.get(action_key, "")
        if action_val:
            st.session_state[action_key] = ""
            if action_val.startswith("reorder:"):
                try:
                    new_indices = [int(x) for x in action_val.replace("reorder:", "").split(",") if x.strip().isdigit()]
                    if len(new_indices) == total and sorted(new_indices) == list(range(total)):
                        st.session_state[items_key] = [items[i] for i in new_indices]
                        if page_prefix.startswith("sbi"):
                            _autosave_storyboard_snapshot()
                        elif page_prefix.startswith("sbv") and st.session_state.get("ed_active_name"):
                            upsert_snapshot_entry("editing", st.session_state.ed_active_name, st.session_state[items_key])
                        st.rerun()
                except (ValueError, IndexError):
                    pass
            elif action_val.startswith("remove:"):
                try:
                    rm_idx = int(action_val.replace("remove:", ""))
                    if 0 <= rm_idx < len(items):
                        items.pop(rm_idx)
                        st.session_state[items_key] = items
                        if page_prefix.startswith("sbi"):
                            _autosave_storyboard_snapshot()
                        elif page_prefix.startswith("sbv") and st.session_state.get("ed_active_name"):
                            upsert_snapshot_entry("editing", st.session_state.ed_active_name, st.session_state[items_key])
                        st.rerun()
                except (ValueError, IndexError):
                    pass
            elif action_val.startswith("note:"):
                try:
                    parts = action_val.split(":", 2)  # "note:INDEX:TEXT"
                    note_idx = int(parts[1])
                    note_text = parts[2] if len(parts) > 2 else ""
                    if 0 <= note_idx < len(items):
                        items[note_idx]["notes"] = note_text.strip()[:200]
                        st.session_state[items_key] = items
                        if page_prefix.startswith("sbi"):
                            _autosave_storyboard_snapshot()
                        elif page_prefix.startswith("sbv") and st.session_state.get("ed_active_name"):
                            upsert_snapshot_entry("editing", st.session_state.ed_active_name, items)
                        st.rerun()
                except (ValueError, IndexError):
                    pass
        thumb_size = 120 if media_type == "image" else 150
        cards_html = ""
        for i, item in enumerate(items):
            src = _get_thumbnail_src(item)
            caption = item.get("caption", "")[:20]
            notes = (item.get("notes", "") or "").replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
            if media_type == "image":
                media_el = f'<img src="{src}" style="width:100%;height:{thumb_size}px;object-fit:cover;border-radius:4px;display:block;" draggable="false"/>'
            else:
                if src == "VIDEO_PLACEHOLDER":
                    media_el = f'<div style="width:100%;height:{thumb_size}px;background:#2a2a28;border:1px solid #444;border-radius:4px;display:flex;align-items:center;justify-content:center;"><span style="color:#FFEB3B;font-size:32px;">▶</span></div>'
                elif src.startswith("data:image"):
                    media_el = f'<div style="position:relative;"><img src="{src}" style="width:100%;height:{thumb_size}px;object-fit:cover;border-radius:4px;display:block;" draggable="false"/><div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:#FFEB3B;font-size:32px;text-shadow:0 2px 8px rgba(0,0,0,0.8);">▶</div></div>'
                else:
                    media_el = f'<video src="{src}" style="width:100%;height:{thumb_size}px;object-fit:cover;border-radius:4px;display:block;" muted preload="metadata"></video>'
            cards_html += f'''
            <div class="gal-card" data-idx="{i}">
                <div class="gal-badge">{i + 1}</div>
                <div class="gal-remove" onclick="removeItem({i})">×</div>
                {media_el}
                <div class="gal-caption">{caption}</div>
                <div class="gal-notes" contenteditable="true"
                     data-idx="{i}"
                     onblur="saveNote({i}, this.textContent)"
                     placeholder="note...">{notes}</div>
            </div>'''
        cols_count = 6 if media_type == "image" else 4
        html_code = f'''
        <script src="https://cdnjs.cloudflare.com/ajax/libs/Sortable/1.15.3/Sortable.min.js"></script>
        <style>
            * {{ margin:0; padding:0; box-sizing:border-box; }}
            body {{ background: transparent; font-family: 'Open Sans', sans-serif; }}
            .gal-grid {{ display:grid; grid-template-columns:repeat({cols_count},1fr); gap:8px; padding:4px; }}
            .gal-card {{ position:relative; background:#1a1a18; border-radius:6px; overflow:hidden; cursor:grab; border:2px solid transparent; transition:border-color .2s,box-shadow .2s; }}
            .gal-card:hover {{ border-color:rgba(255,235,59,.35); box-shadow:0 4px 16px rgba(0,0,0,.35); }}
            .gal-card.sortable-ghost {{ opacity:.35; border-color:#FFEB3B; }}
            .gal-badge {{ position:absolute; top:4px; left:4px; background:rgba(0,0,0,.75); color:#fff; font-size:9px; font-weight:700; padding:1px 6px; border-radius:3px; z-index:2; pointer-events:none; }}
            .gal-remove {{ position:absolute; top:4px; right:4px; color:#666; font-size:12px; cursor:pointer; z-index:2; width:16px; height:16px; text-align:center; line-height:16px; border-radius:50%; }}
            .gal-remove:hover {{ color:#ff4444; background:rgba(255,68,68,.15); }}
            .gal-caption {{ color:#999; font-size:9px; padding:3px 6px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
            .gal-notes {{
                color: #FFEB3B;
                font-size: 8px;
                padding: 2px 6px 4px;
                min-height: 14px;
                outline: none;
                border-top: 1px solid rgba(255,255,255,0.06);
                cursor: text;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }}
            .gal-notes:empty::before {{
                content: attr(placeholder);
                color: #444;
            }}
            .gal-notes:focus {{
                color: #fff;
                background: rgba(255,235,59,0.08);
                white-space: normal;
            }}
            div[data-testid="stTextInput"][data-key$="_action"] {{ height:0!important; overflow:hidden!important; margin:0!important; padding:0!important; opacity:0!important; position:absolute!important; }}
        </style>
        <div class="gal-grid" id="sortableGrid">{cards_html}</div>
        <script>
            if (!window.parent.__sbBridgeInstalled) {{
                window.parent.__sbBridgeInstalled = true;
                window.parent.addEventListener('message', function(event) {{
                    const data = event.data || {{}};
                    if (data.type !== 'sb_action' || !data.prefix) return;
                    const input = window.parent.document.querySelector(
                        'input[aria-label="sb_action_input_' + data.prefix + '"]'
                    );
                    if (!input) return;
                    const nativeSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    ).set;
                    nativeSetter.call(input, data.payload || '');
                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }});
            }}

            function sendAction(payload) {{
                window.parent.postMessage({{
                    type: 'sb_action',
                    prefix: '{page_prefix}',
                    payload: payload
                }}, '*');
            }}

            const grid = document.getElementById('sortableGrid');
            Sortable.create(grid, {{
                animation: 200, ghostClass:'sortable-ghost', chosenClass:'sortable-chosen',
                onEnd: function(evt) {{
                    const cards = grid.querySelectorAll('.gal-card');
                    const newOrder = Array.from(cards).map(c => c.dataset.idx);
                    cards.forEach((c,i) => {{ c.querySelector('.gal-badge').textContent = i+1; }});
                    sendAction('reorder:' + newOrder.join(','));
                }}
            }});
            function removeItem(idx) {{
                sendAction('remove:' + idx);
            }}
            function saveNote(idx, text) {{
                sendAction('note:' + idx + ':' + text.substring(0, 200));
            }}
        </script>'''
        st.text_input(f"sb_action_input_{page_prefix}", value="", key=f"{page_prefix}_action", label_visibility="collapsed")
        grid_height = ((total // cols_count) + (1 if total % cols_count else 0)) * (thumb_size + 62) + 20
        components.html(html_code, height=grid_height, scrolling=False)
        st.markdown(f'<p style="color:#f0ece4;font-size:0.78rem;font-weight:600;font-family:Open Sans,sans-serif;margin-top:8px;">{total} {media_type}s</p>', unsafe_allow_html=True)

    def _process_editing_actions(items_key, page_prefix):
        """Process any pending editing actions (trim/reorder/remove) from the JS component.
        Must be called BEFORE any SAVE logic to ensure state is current."""
        _action_key = f"{page_prefix}_action"
        _av = st.session_state.get(_action_key, "")
        if not _av:
            return
        st.session_state[_action_key] = ""
        items = list(st.session_state.get(items_key, []))
        try:
            if _av.startswith("trim:"):
                p = _av.split(":")
                tidx, ts, te, dur = int(p[1]), float(p[2]), float(p[3]), float(p[4])
                if 0 <= tidx < len(items):
                    items[tidx]["trim_start"] = round(max(0, ts), 2)
                    items[tidx]["trim_end"] = round(te, 2)
                    items[tidx]["duration"] = round(dur, 2)
                    st.session_state[items_key] = items
                    if st.session_state.get("ed_active_name"):
                        upsert_snapshot_entry("editing", st.session_state.ed_active_name, items)
            elif _av.startswith("remove:"):
                ridx = int(_av.split(":", 1)[1])
                if 0 <= ridx < len(items):
                    items.pop(ridx)
                    st.session_state[items_key] = items
                    if st.session_state.get("ed_active_name"):
                        upsert_snapshot_entry("editing", st.session_state.ed_active_name, items)
            elif _av.startswith("reorder:"):
                rest = _av.split(":", 1)[1]
                ni = [int(x) for x in rest.split(",") if x.strip().isdigit()]
                if len(ni) == len(items) and sorted(ni) == list(range(len(items))):
                    items = [items[i] for i in ni]
                    st.session_state[items_key] = items
                    if st.session_state.get("ed_active_name"):
                        upsert_snapshot_entry("editing", st.session_state.ed_active_name, items)
        except (ValueError, IndexError):
            pass

    def _export_editing_video(items, project_name="untitled"):
        """Export the editing timeline as a single video using ffmpeg.
        Respects trim_start/trim_end for each clip. Returns the output file path or None."""
        if not items:
            return None
        try:
            ffmpeg_path = shutil.which("ffmpeg")
            if not ffmpeg_path:
                # Try common macOS Homebrew paths
                for p in ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"]:
                    if os.path.exists(p):
                        ffmpeg_path = p
                        break
            if not ffmpeg_path:
                return None

            export_dir = os.path.join(_DOWNLOADS_DIR, "exports")
            os.makedirs(export_dir, exist_ok=True)

            safe_name = re.sub(r'[^\w\-]', '_', project_name.lower().strip()) or "untitled"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(export_dir, f"{safe_name}_{timestamp}.mp4")

            # Build clip list with trim points
            valid_clips = []
            for item in items:
                vpath = item.get("video_path") or ""
                if not vpath or not os.path.exists(vpath):
                    continue
                dur = float(item.get("duration") or 0)
                ts = float(item.get("trim_start") or 0)
                te = float(item.get("trim_end") or dur)
                if te <= 0:
                    te = dur
                if te <= ts:
                    te = ts + 1  # minimum 1s
                valid_clips.append({"path": vpath, "ts": ts, "te": te})

            if not valid_clips:
                return None

            if len(valid_clips) == 1:
                # Single clip: simple trim
                c = valid_clips[0]
                cmd = [
                    ffmpeg_path, "-y",
                    "-ss", str(c["ts"]),
                    "-to", str(c["te"]),
                    "-i", c["path"],
                    "-c:v", "libx264", "-preset", "fast",
                    "-crf", "18",
                    "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart",
                    "-pix_fmt", "yuv420p",
                    output_path,
                ]
                result = subprocess.run(cmd, capture_output=True, timeout=300)
                if result.returncode != 0:
                    return None
                return output_path

            # Multiple clips: create trimmed segments, then concatenate
            import tempfile
            temp_dir = tempfile.mkdtemp(prefix="arkitect_export_")
            segment_paths = []
            concat_file = None

            try:
                for idx, c in enumerate(valid_clips):
                    seg_path = os.path.join(temp_dir, f"seg_{idx:04d}.mp4")
                    cmd = [
                        ffmpeg_path, "-y",
                        "-ss", str(c["ts"]),
                        "-to", str(c["te"]),
                        "-i", c["path"],
                        "-c:v", "libx264", "-preset", "fast",
                        "-crf", "18",
                        "-c:a", "aac", "-b:a", "192k",
                        "-r", "30",
                        "-pix_fmt", "yuv420p",
                        "-s", "1920x1080",
                        seg_path,
                    ]
                    result = subprocess.run(cmd, capture_output=True, timeout=300)
                    if result.returncode != 0:
                        continue
                    if os.path.exists(seg_path) and os.path.getsize(seg_path) > 0:
                        segment_paths.append(seg_path)

                if not segment_paths:
                    return None

                # Write concat list
                concat_file = os.path.join(temp_dir, "concat.txt")
                with open(concat_file, "w") as f:
                    for sp in segment_paths:
                        f.write(f"file '{sp}'\n")

                # Concatenate
                cmd = [
                    ffmpeg_path, "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", concat_file,
                    "-c", "copy",
                    "-movflags", "+faststart",
                    output_path,
                ]
                result = subprocess.run(cmd, capture_output=True, timeout=600)
                if result.returncode != 0:
                    return None

                return output_path if os.path.exists(output_path) else None

            finally:
                # Cleanup temp segments
                for sp in segment_paths:
                    try:
                        os.remove(sp)
                    except Exception:
                        pass
                try:
                    if concat_file and os.path.exists(concat_file):
                        os.remove(concat_file)
                    os.rmdir(temp_dir)
                except Exception:
                    pass

        except Exception:
            return None

    def _render_editing_room(items_key, page_prefix):
        """Editing room — unified player + timeline in a single HTML/JS component.
        All playback, selection, and scrubbing is handled client-side in JS.
        Only trim, reorder, and remove actions communicate back to Streamlit."""
        _action_key = f"{page_prefix}_action"

        items = st.session_state.get(items_key, [])
        if not items:
            st.info("No clips remaining.")
            return

        clips_js = []
        for i, item in enumerate(items):
            dur = float(item.get("duration") or 10)
            if dur <= 0:
                dur = 10
            ts = float(item.get("trim_start") or 0)
            te = float(item.get("trim_end") or dur)
            if te <= 0:
                te = dur

            # ── THUMBNAIL: base64 image from last_frame_path or cv2 frame extraction ──
            thumb = ""
            # 1) Try last_frame_path (PNG saved during generation)
            _lfp = item.get("last_frame_path") or ""
            if _lfp and os.path.exists(_lfp):
                try:
                    ext_lf = os.path.splitext(_lfp)[1].lower()
                    mime_map = {
                        ".png": "image/png",
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".webp": "image/webp",
                    }
                    mime_lf = mime_map.get(ext_lf, "image/jpeg")
                    try:
                        from PIL import Image as _PILImage
                        import io as _io

                        with _PILImage.open(_lfp) as im:
                            im.thumbnail((200, 120), _PILImage.LANCZOS)
                            buf_lf = _io.BytesIO()
                            im.convert("RGB").save(buf_lf, format="JPEG", quality=72)
                            thumb = (
                                f"data:image/jpeg;base64,"
                                f"{_b64.b64encode(buf_lf.getvalue()).decode('ascii')}"
                            )
                    except Exception:
                        with open(_lfp, "rb") as f_lf:
                            thumb = (
                                f"data:{mime_lf};base64,"
                                f"{_b64.b64encode(f_lf.read()).decode('ascii')}"
                            )
                except Exception:
                    thumb = ""

            # 2) Fallback: extract first frame from video file with cv2
            if not thumb:
                _vid_file = item.get("video_path") or ""
                if _vid_file and not os.path.isabs(_vid_file):
                    _vid_abs = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)), _vid_file
                    )
                    if os.path.exists(_vid_abs):
                        _vid_file = _vid_abs
                if _vid_file and os.path.exists(_vid_file):
                    try:
                        import cv2

                        cap = cv2.VideoCapture(_vid_file)
                        if cap.isOpened():
                            ret, frame = cap.read()
                            if ret:
                                h, w = frame.shape[:2]
                                scale = min(200 / max(w, 1), 120 / max(h, 1))
                                if scale < 1:
                                    frame = cv2.resize(
                                        frame, (int(w * scale), int(h * scale))
                                    )
                                _, buf_cv = cv2.imencode(
                                    ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70]
                                )
                                thumb = (
                                    f"data:image/jpeg;base64,"
                                    f"{_b64.b64encode(buf_cv.tobytes()).decode('ascii')}"
                                )
                        cap.release()
                    except Exception:
                        thumb = ""

            # ── VIDEO URL: local path via static serving (persistent, no expiry) ──
            _local_path = item.get("video_path") or ""
            if _local_path and not os.path.isabs(_local_path):
                _lp_abs = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), _local_path
                )
                if os.path.exists(_lp_abs):
                    _local_path = _lp_abs
            vurl = _to_media_url(_local_path) if _local_path else ""

            clips_js.append(
                {
                    "i": i,
                    "ts": float(round(ts, 2)),
                    "te": float(round(te, 2)),
                    "d": float(round(dur, 2)),
                    "thumb": thumb,
                    "vurl": vurl,
                    "cap": (item.get("caption", "") or "")[:20],
                }
            )

        clips_b64 = _b64.b64encode(
            json.dumps(clips_js, ensure_ascii=False).encode("utf-8")
        ).decode("ascii")
        prefix_js = json.dumps(page_prefix)

        st.text_input(
            f"sb_action_input_{page_prefix}",
            value="",
            key=_action_key,
            label_visibility="collapsed",
        )

        _ed_room_html = r"""<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Open+Sans:wght@400;600&display=swap" rel="stylesheet"/>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Sortable/1.15.3/Sortable.min.js"></script>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  .ed-room {
    width:100%; max-width:100%;
    background:transparent; color:#f0ece4; font-family:'Open Sans',sans-serif;
  }
  .ed-player-wrap { margin-bottom:12px; }
  .ed-player-stack {
    position:relative; width:100%; border-radius:8px; overflow:hidden;
    background:#000; aspect-ratio:16/9; max-height:380px;
  }
  .ed-player-stack video {
    position:absolute; top:0; left:0; width:100%; height:100%;
    background:#000; outline:none; object-fit:contain;
    transition:opacity 0.08s ease;
  }
  .ed-player-stack video.standby {
    opacity:0; pointer-events:none; z-index:1;
  }
  .ed-player-stack video.active {
    opacity:1; pointer-events:auto; z-index:2;
  }
  .ed-transport {
    display:inline-flex; align-items:center; gap:12px; margin-top:10px;
    flex-wrap:wrap;
  }
  .ed-tbtn {
    background:#1a1a18; color:#f0ece4; border:none; border-radius:8px;
    padding:8px 14px; font-family:'Open Sans',sans-serif; font-size:12px; font-weight:600;
    cursor:pointer; transition:background 0.15s ease, color 0.15s ease, opacity 0.15s ease;
  }
  .ed-tbtn:hover { opacity:0.92; }
  .ed-tbtn:disabled { opacity:0.35; cursor:not-allowed; }
  .ed-time-readout {
    font-family:'JetBrains Mono',monospace; font-size:12px; color:#9E9E8A;
    min-width:140px;
  }
  .ed-timeline-outer {
    background:#111; border-radius:8px; padding:8px 12px 28px;
    position:relative; margin-top:4px;
  }
  .ed-ruler-tick {
    position:absolute; bottom:0; width:1px; background:#333; height:6px;
  }
  .ed-ruler-tick.major { height:10px; background:#444; }
  .ed-ruler-label {
    position:absolute; bottom:12px; transform:translateX(-50%);
    font-family:'JetBrains Mono',monospace; font-size:10px; color:#555;
    white-space:nowrap;
  }
  .ed-track-scroll {
    overflow-x:auto; position:relative; min-height:136px;
  }
  .ed-track-inner {
    position:relative; display:flex; align-items:stretch;
    gap:2px; min-height:128px;
  }
  .ed-playhead {
    position:absolute; top:-8px; bottom:-8px; width:2px; background:#FFEB3B;
    z-index:10; pointer-events:none;
    box-shadow:0 0 8px rgba(255,235,59,0.5);
  }
  .ed-playhead::before {
    content:''; position:absolute; top:0; left:50%; transform:translateX(-50%);
    width:0; height:0;
    border-left:6px solid transparent; border-right:6px solid transparent;
    border-top:8px solid #FFEB3B;
  }
  .ed-playhead-grab {
    position:absolute; top:-8px; bottom:-8px; width:24px; margin-left:-11px;
    z-index:11; cursor:col-resize; pointer-events:auto;
  }
  .ed-playhead-grab:hover ~ .ed-playhead,
  .ed-playhead-grab.dragging ~ .ed-playhead {
    width:3px; box-shadow:0 0 10px rgba(255,235,59,0.7);
  }
  .ed-ruler {
    position:relative; height:22px; margin-bottom:6px;
    border-bottom:1px solid #222;
    cursor:col-resize;
  }
  .ed-clip {
    flex-shrink:0; height:128px; position:relative; cursor:pointer;
    overflow:hidden; border:2px solid transparent; border-radius:4px;
    background:#1a1a18; transition:border-color 0.15s ease, box-shadow 0.15s ease, opacity 0.15s ease;
    opacity:0.88; z-index:2;
  }
  .ed-clip:hover { border-color:rgba(255,255,255,0.2); opacity:1; }
  .ed-clip.active {
    border-color:#fff; opacity:1;
    box-shadow:0 0 0 1px rgba(255,255,255,0.25), 0 0 12px rgba(255,235,59,0.15);
  }
  .ed-clip.sortable-ghost { opacity:0.25; }
  .ed-clip img, .ed-clip video {
    width:100%; height:100%; object-fit:cover; display:block; pointer-events:none;
  }
  .ed-clip-fallback {
    width:100%; height:100%; background:linear-gradient(135deg,#2a2a28,#1a1a18);
    display:flex; align-items:center; justify-content:center;
    color:#555; font-size:11px; font-family:'JetBrains Mono',monospace;
  }
  .ed-badge {
    position:absolute; top:3px; left:3px; font-size:9px; font-weight:600;
    background:rgba(0,0,0,0.55); color:#f0ece4; padding:2px 5px; border-radius:3px;
    pointer-events:none; z-index:3; font-family:'Open Sans',sans-serif;
  }
  .ed-rm {
    position:absolute; top:2px; right:2px; z-index:6; width:18px; height:18px;
    line-height:16px; text-align:center; font-size:14px; color:transparent;
    cursor:pointer; transition:color 0.15s ease; border-radius:3px;
  }
  .ed-clip:hover .ed-rm { color:rgba(255,255,255,0.45); }
  .ed-rm:hover { color:#ff5252 !important; background:rgba(0,0,0,0.35); }
  .ed-trim-l, .ed-trim-r {
    position:absolute; top:0; width:5px; height:100%; background:#fff;
    cursor:col-resize; z-index:5; transition:background 0.15s ease;
  }
  .ed-trim-l { left:0; border-radius:2px 0 0 2px; }
  .ed-trim-r { right:0; border-radius:0 2px 2px 0; }
  .ed-trim-l:hover, .ed-trim-r:hover { background:#00E5CC; }
  .ed-total {
    position:absolute; bottom:8px; right:12px;
    font-family:'JetBrains Mono',monospace; font-size:11px; color:#9E9E8A;
  }
  .ed-zoom-bar {
    display:flex; align-items:center; gap:8px;
    padding:6px 0 0;
  }
  .ed-zoom-btn {
    background:#1a1a18; color:#f0ece4; border:none; border-radius:4px;
    width:26px; height:26px; font-size:16px; font-weight:600;
    cursor:pointer; display:flex; align-items:center; justify-content:center;
    transition:background 0.15s;
    font-family:'JetBrains Mono',monospace;
  }
  .ed-zoom-btn:hover { background:#2a2a28; }
  .ed-zoom-slider {
    -webkit-appearance:none; appearance:none;
    width:100px; height:4px; background:#333; border-radius:2px;
    outline:none; cursor:pointer;
  }
  .ed-zoom-slider::-webkit-slider-thumb {
    -webkit-appearance:none; width:12px; height:12px;
    background:#FFEB3B; border-radius:50%; cursor:pointer;
  }
  .ed-zoom-label {
    font-family:'JetBrains Mono',monospace; font-size:10px;
    color:#9E9E8A; min-width:32px; text-align:center;
  }
</style>
<div class="ed-room">
  <div class="ed-player-wrap">
    <div class="ed-player-stack" id="edPlayerStack">
      <video id="edVidA" controls playsinline></video>
      <video id="edVidB" controls playsinline></video>
    </div>
    <div class="ed-transport">
      <button type="button" class="ed-tbtn" id="edPrev">PREV</button>
      <button type="button" class="ed-tbtn" id="edPlayPause">PLAY</button>
      <button type="button" class="ed-tbtn" id="edNext">NEXT</button>
      <span class="ed-time-readout" id="edTimeReadout">00:00 / 00:00</span>
    </div>
  </div>
  <div class="ed-timeline-outer">
    <div class="ed-ruler" id="edRuler"></div>
    <div class="ed-track-scroll" id="edTrackScroll">
      <div class="ed-track-inner" id="edTrackInner">
        <div class="ed-playhead-grab" id="edPlayheadGrab"></div>
        <div class="ed-playhead" id="edPlayhead"></div>
      </div>
    </div>
    <div class="ed-zoom-bar">
      <button type="button" class="ed-zoom-btn" id="edZoomOut">-</button>
      <input type="range" class="ed-zoom-slider" id="edZoomSlider" min="1" max="10" step="0.5" value="1"/>
      <button type="button" class="ed-zoom-btn" id="edZoomIn">+</button>
      <span class="ed-zoom-label" id="edZoomLabel">1x</span>
    </div>
    <div class="ed-total" id="edTotalLab"></div>
  </div>
</div>
<script>
(function(){
var CLIPS = JSON.parse(atob('__CLIPS_B64__'));
var PREFIX = __PREFIX_JSON__;
var activeIdx = 0;
var _sortable = null;
var trimState = null;

function sendAction(str) {
  if (!window.parent.__sbBridgeInstalled) {
    window.parent.__sbBridgeInstalled = true;
    window.parent.addEventListener('message', function(ev) {
      var d = ev.data || {};
      if (d.type !== 'sb_action' || !d.prefix) return;
      var inp = window.parent.document.querySelector(
        'input[aria-label="sb_action_input_' + d.prefix + '"]'
      );
      if (!inp) return;
      var ns = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value'
      ).set;
      ns.call(inp, d.payload || '');
      inp.dispatchEvent(new Event('input', {bubbles:true}));
      inp.dispatchEvent(new Event('change', {bubbles:true}));
    });
  }
  window.parent.postMessage({type:'sb_action', prefix:PREFIX, payload:str}, '*');
}

function ensureClip(c) {
  if (!c.d || c.d <= 0) c.d = 10;
  if (c.te <= 0) c.te = c.d;
  if (c.ts < 0) c.ts = 0;
  if (c.te < c.ts + 0.1) c.te = c.ts + 0.1;
}
CLIPS.forEach(ensureClip);

function trimDur(c) { return Math.max(0.01, c.te - c.ts); }
function totalDur() {
  var t = 0;
  CLIPS.forEach(function(c) { t += trimDur(c); });
  return t;
}

function fmtTime(s) {
  if (isNaN(s) || s < 0) s = 0;
  var m = Math.floor(s / 60);
  var sec = Math.floor(s % 60);
  return (m < 10 ? '0' : '') + m + ':' + (sec < 10 ? '0' : '') + sec;
}

function updatePlayhead() {
  var inner = document.getElementById('edTrackInner');
  var ph = document.getElementById('edPlayhead');
  var phg = document.getElementById('edPlayheadGrab');
  if (!inner || !ph) return;
  var td = totalDur();
  var el = getElapsed();
  var w = inner.offsetWidth;
  if (w <= 0 || td <= 0) { ph.style.left = '0px'; if (phg) phg.style.left = '0px'; return; }
  var px = (el / td) * w;
  ph.style.left = px + 'px';
  if (phg) phg.style.left = px + 'px';
}

function updateRuler() {
  var ruler = document.getElementById('edRuler');
  if (!ruler) return;
  ruler.innerHTML = '';
  var td = totalDur();
  if (td <= 0) return;
  var t;
  for (t = 0; t <= td + 0.001; t += 5) {
    var pct = (t / td) * 100;
    var tick = document.createElement('div');
    tick.className = 'ed-ruler-tick' + (Math.round(t) % 10 === 0 ? ' major' : '');
    tick.style.left = pct + '%';
    ruler.appendChild(tick);
  }
  for (t = 0; t <= td + 0.001; t += 10) {
    var lpct = (t / td) * 100;
    var lab = document.createElement('div');
    lab.className = 'ed-ruler-label';
    lab.style.left = lpct + '%';
    lab.textContent = String(Math.round(t)) + 's';
    ruler.appendChild(lab);
  }
}

function buildTrack() {
  var track = document.getElementById('edTrackInner');
  var scroll = document.getElementById('edTrackScroll');
  if (!track || !scroll) return;
  if (_sortable && typeof _sortable.destroy === 'function') {
    _sortable.destroy();
    _sortable = null;
  }
  track.querySelectorAll('.ed-clip').forEach(function(n) { n.remove(); });
  var td = totalDur();
  var cw = scroll.clientWidth || 800;
  var widths = [];
  CLIPS.forEach(function(c) {
    var w = Math.max(60, Math.round((trimDur(c) / Math.max(td, 0.01)) * cw * zoomLevel));
    widths.push(w);
  });
  var sumW = widths.reduce(function(a,b){return a+b;}, 0) + Math.max(0, CLIPS.length - 1) * 2;
  track.style.width = Math.max(sumW, cw) + 'px';
  var ph = document.getElementById('edPlayhead');
  var h = (track.offsetHeight || 64) + 'px';
  if (ph) { ph.style.height = h; }
  var phg = document.getElementById('edPlayheadGrab');
  if (phg) { phg.style.height = h; }

  CLIPS.forEach(function(clip, i) {
    var div = document.createElement('div');
    div.className = 'ed-clip' + (i === activeIdx ? ' active' : '');
    div.dataset.idx = String(i);
    div.style.width = widths[i] + 'px';
    div.style.minWidth = '60px';

    if (clip.thumb) {
      div.innerHTML = '<img src="' + clip.thumb + '" draggable="false" alt=""/>';
    } else if (clip.vurl) {
      div.innerHTML = '<video src="' + clip.vurl + '" preload="metadata" muted playsinline></video>';
    } else {
      div.innerHTML = '<div class="ed-clip-fallback">' + (i + 1) + '</div>';
    }
    div.innerHTML += '<div class="ed-badge">' + (i + 1) + '</div>';
    div.innerHTML += '<div class="ed-rm" data-rm="' + i + '">&times;</div>';
    if (i === activeIdx) {
      div.innerHTML += '<div class="ed-trim-l" data-idx="' + i + '" data-side="left"></div>';
      div.innerHTML += '<div class="ed-trim-r" data-idx="' + i + '" data-side="right"></div>';
    }
    div.addEventListener('click', function(e) {
      if (e.target.closest('.ed-trim-l') || e.target.closest('.ed-trim-r') ||
          e.target.closest('.ed-rm')) return;
      selectClip(i, false);
      var vid = activeVid;
      if (vid && CLIPS[i].vurl) {
        vid.pause();
        syncPlayBtn();
      }
    });
    track.appendChild(div);
  });

  track.querySelectorAll('.ed-rm').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      removeClip(parseInt(btn.getAttribute('data-rm'), 10));
    });
  });

  if (typeof Sortable !== 'undefined') {
    _sortable = Sortable.create(track, {
      animation: 180,
      ghostClass: 'sortable-ghost',
      draggable: '.ed-clip',
      filter: '.ed-trim-l,.ed-trim-r,.ed-rm',
      preventOnFilter: false,
      onEnd: function() {
        var cards = track.querySelectorAll('.ed-clip');
        var order = Array.from(cards).map(function(c) { return parseInt(c.dataset.idx, 10); });
        if (order.length !== CLIPS.length) return;
        var timePos = getElapsed();
        var newClips = order.map(function(oi) { return CLIPS[oi]; });
        CLIPS = newClips;
        for (var k = 0; k < CLIPS.length; k++) CLIPS[k].i = k;
        var acc = 0;
        var foundIdx = 0;
        var localT = 0;
        for (var j = 0; j < CLIPS.length; j++) {
          var d = trimDur(CLIPS[j]);
          if (timePos <= acc + d + 0.001) {
            foundIdx = j;
            localT = CLIPS[j].ts + (timePos - acc);
            break;
          }
          acc += d;
          if (j === CLIPS.length - 1) {
            foundIdx = j;
            localT = CLIPS[j].te;
          }
        }
        activeIdx = foundIdx;
        var v = activeVid;
        var c = CLIPS[activeIdx];
        if (c && c.vurl && v) {
          var isSame = false;
          try {
            var abs = new URL(c.vurl, window.location.href).href;
            isSame = (v.src === abs);
          } catch(e) { isSame = v.src && v.src.indexOf(c.vurl) >= 0; }
          if (isSame && v.readyState >= 1) {
            v.currentTime = localT;
            buildTrack();
            updatePlayhead();
            updateReadout();
          } else {
            v.src = c.vurl;
            v.addEventListener('loadedmetadata', function once() {
              v.removeEventListener('loadedmetadata', once);
              v.currentTime = localT;
              buildTrack();
              updatePlayhead();
              updateReadout();
            });
            v.load();
          }
        } else {
          buildTrack();
          updatePlayhead();
          updateReadout();
        }
        preloadInto(standbyVid, activeIdx + 1);
        sendAction('reorder:' + order.join(','));
      }
    });
  }
  updateRuler();
  updatePlayhead();
  updateReadout();
}

/* ═══ Double-buffer video engine ═══ */
var vidA = document.getElementById('edVidA');
var vidB = document.getElementById('edVidB');
vidA.className = 'active';
vidB.className = 'standby';
var activeVid = vidA;
var standbyVid = vidB;
var rafId = null;
var trimEndLatch = false;

function activeVideo() { return activeVid; }

function getElapsed() {
  var v = activeVid;
  var off = 0;
  for (var i = 0; i < activeIdx; i++) off += trimDur(CLIPS[i]);
  if (!v || !CLIPS.length) return off;
  var c = CLIPS[activeIdx];
  if (!c || !c.vurl) return off;
  return off + Math.max(0, Math.min(v.currentTime - c.ts, trimDur(c)));
}

function updateReadout() {
  var v = activeVid;
  var el = document.getElementById('edTimeReadout');
  if (!el) return;
  var td = totalDur();
  var c = CLIPS[activeIdx];
  var inClip = 0;
  if (v && c && c.vurl) inClip = Math.max(0, v.currentTime - c.ts);
  el.textContent = fmtTime(inClip) + ' / ' + fmtTime(td);
  var tl = document.getElementById('edTotalLab');
  if (tl) tl.textContent = 'TOTAL ' + fmtTime(td);
}

function syncPlayBtn() {
  var v = activeVid;
  var b = document.getElementById('edPlayPause');
  if (!v || !b) return;
  b.textContent = v.paused ? 'PLAY' : 'PAUSE';
}

function stopRaf() {
  if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
}
function loop() {
  updatePlayhead();
  updateReadout();
  var v = activeVid;
  if (v && !v.paused) rafId = requestAnimationFrame(loop);
  else rafId = null;
}
function startRaf() {
  if (!rafId) rafId = requestAnimationFrame(loop);
}

function preloadInto(vid, idx) {
  if (idx < 0 || idx >= CLIPS.length) return;
  var c = CLIPS[idx];
  if (!c.vurl) return;
  var already = false;
  try {
    var abs = new URL(c.vurl, window.location.href).href;
    already = (vid.src === abs);
  } catch(e) {
    already = vid.src && vid.src.indexOf(c.vurl) >= 0;
  }
  if (!already) {
    vid.src = c.vurl;
    vid.addEventListener('loadedmetadata', function once() {
      vid.removeEventListener('loadedmetadata', once);
      vid.currentTime = c.ts;
    });
    try { vid.load(); } catch(e) {}
  }
}

function swapToStandby(andPlay) {
  var old = activeVid;
  old.pause();
  old.className = 'standby';
  standbyVid = old;
  var nv = (old === vidA) ? vidB : vidA;
  nv.className = 'active';
  activeVid = nv;
  bindActiveEvents();
  if (andPlay) {
    nv.play().catch(function(){});
  }
  syncPlayBtn();
  buildTrack();
  updatePlayhead();
  updateReadout();
  if (andPlay) startRaf();
}

function loadVideoAt(idx, andPlay, onReady) {
  activeIdx = Math.max(0, Math.min(idx, CLIPS.length - 1));
  var c = CLIPS[activeIdx];
  var v = activeVid;
  var wantPlay = andPlay === true;
  if (!c || !c.vurl) {
    v.removeAttribute('src');
    try { v.load(); } catch(e) {}
    buildTrack(); updatePlayhead(); updateReadout(); syncPlayBtn();
    if (onReady) onReady();
    return;
  }
  var isSame = false;
  try {
    var absUrl = new URL(c.vurl, window.location.href).href;
    isSame = (v.src === absUrl);
  } catch(err) {
    isSame = v.src && v.src.indexOf(c.vurl) >= 0;
  }
  if (isSame && v.readyState >= 1) {
    var realDur = v.duration;
    if (realDur && isFinite(realDur) && realDur > 0) {
      c.d = Math.round(realDur * 100) / 100;
      if (c.te > c.d || c.te <= 0) c.te = c.d;
      if (c.ts >= c.d) c.ts = 0;
    }
    v.currentTime = c.ts;
    if (wantPlay) { v.play().catch(function(){}); startRaf(); }
    buildTrack(); updatePlayhead(); updateReadout(); syncPlayBtn();
    preloadInto(standbyVid, activeIdx + 1);
    if (onReady) onReady();
    return;
  }
  v.src = c.vurl;
  var onMeta = function() {
    v.removeEventListener('loadedmetadata', onMeta);
    var realDur = v.duration;
    if (realDur && isFinite(realDur) && realDur > 0) {
      c.d = Math.round(realDur * 100) / 100;
      if (c.te > c.d || c.te <= 0) c.te = c.d;
      if (c.ts >= c.d) c.ts = 0;
    }
    v.currentTime = c.ts;
    if (wantPlay) { v.play().catch(function(){}); startRaf(); }
    buildTrack(); updatePlayhead(); updateReadout(); syncPlayBtn();
    preloadInto(standbyVid, activeIdx + 1);
    if (onReady) onReady();
  };
  v.addEventListener('loadedmetadata', onMeta);
  try { v.load(); } catch(e2) {}
  syncPlayBtn();
}

function selectClip(idx, playOn) {
  trimEndLatch = false;
  loadVideoAt(idx, playOn);
}

function bindActiveEvents() {
  var v = activeVid;
  v.onplay = function() { syncPlayBtn(); startRaf(); };
  v.onpause = function() { syncPlayBtn(); stopRaf(); updatePlayhead(); updateReadout(); };
  v.onseeked = function() { trimEndLatch = false; updatePlayhead(); updateReadout(); };
  v.ontimeupdate = handleTimeUpdate;
  v.onended = function() {
    if (activeIdx < CLIPS.length - 1) {
      trimEndLatch = true;
      advanceToNext();
    } else {
      syncPlayBtn(); updatePlayhead(); updateReadout();
    }
  };
}

function handleTimeUpdate() {
  if (trimEndLatch) return;
  var v = activeVid;
  var c = CLIPS[activeIdx];
  if (!c || !c.vurl) { updatePlayhead(); updateReadout(); return; }
  if (c.te < c.d && v.currentTime >= c.te - 0.12) {
    if (activeIdx < CLIPS.length - 1) {
      trimEndLatch = true;
      advanceToNext();
    } else {
      v.pause();
      syncPlayBtn();
    }
    return;
  }
  updatePlayhead();
  updateReadout();
}

function advanceToNext() {
  var nextIdx = activeIdx + 1;
  if (nextIdx >= CLIPS.length) { trimEndLatch = false; return; }
  var nc = CLIPS[nextIdx];
  activeIdx = nextIdx;
  if (!nc.vurl) {
    activeVid.pause();
    trimEndLatch = false;
    buildTrack(); syncPlayBtn();
    return;
  }
  var sb = standbyVid;
  var sbReady = false;
  try {
    var abs2 = new URL(nc.vurl, window.location.href).href;
    sbReady = (sb.src === abs2 && sb.readyState >= 2);
  } catch(e) {
    sbReady = (sb.src && sb.src.indexOf(nc.vurl) >= 0 && sb.readyState >= 2);
  }
  if (sbReady) {
    sb.currentTime = nc.ts;
    swapToStandby(true);
    preloadInto(standbyVid, activeIdx + 1);
    trimEndLatch = false;
  } else {
    sb.src = nc.vurl;
    sb.addEventListener('canplay', function once() {
      sb.removeEventListener('canplay', once);
      sb.currentTime = nc.ts;
      swapToStandby(true);
      preloadInto(standbyVid, activeIdx + 1);
      trimEndLatch = false;
    });
    try { sb.load(); } catch(e3) {}
  }
}

/* ═══ Remove clip ═══ */
function removeClip(idx) {
  if (idx < 0 || idx >= CLIPS.length) return;
  var timePos = getElapsed();
  CLIPS.splice(idx, 1);
  if (!CLIPS.length) {
    activeIdx = 0;
    var v = activeVid;
    if (v) { v.pause(); v.removeAttribute('src'); try { v.load(); } catch(e) {} }
    buildTrack(); syncPlayBtn(); updatePlayhead(); updateReadout();
    sendAction('remove:' + idx);
    return;
  }
  for (var k = 0; k < CLIPS.length; k++) CLIPS[k].i = k;
  var acc = 0;
  var foundIdx = 0;
  for (var j = 0; j < CLIPS.length; j++) {
    var d = trimDur(CLIPS[j]);
    if (timePos <= acc + d + 0.001) { foundIdx = j; break; }
    acc += d;
    if (j === CLIPS.length - 1) foundIdx = j;
  }
  var wasPaused = activeVid && activeVid.paused;
  activeIdx = foundIdx;
  var c = CLIPS[activeIdx];
  var v = activeVid;
  if (c && c.vurl && v) {
    var isSame = false;
    try {
      var abs = new URL(c.vurl, window.location.href).href;
      isSame = (v.src === abs);
    } catch(e) { isSame = v.src && v.src.indexOf(c.vurl) >= 0; }
    if (isSame && v.readyState >= 1) {
      buildTrack(); updatePlayhead(); updateReadout();
    } else {
      v.src = c.vurl;
      v.addEventListener('loadedmetadata', function once() {
        v.removeEventListener('loadedmetadata', once);
        v.currentTime = c.ts;
        if (!wasPaused) v.play().catch(function(){});
        buildTrack(); updatePlayhead(); updateReadout(); syncPlayBtn();
      });
      v.load();
    }
  } else {
    buildTrack(); updatePlayhead(); updateReadout();
  }
  preloadInto(standbyVid, activeIdx + 1);
  sendAction('remove:' + idx);
}

/* ═══ Timeline zoom ═══ */
var zoomLevel = 1;

function applyZoom(val) {
  zoomLevel = Math.max(1, Math.min(10, Math.round(val * 2) / 2));
  var sl = document.getElementById('edZoomSlider');
  var lb = document.getElementById('edZoomLabel');
  if (sl) sl.value = zoomLevel;
  if (lb) lb.textContent = zoomLevel + 'x';
  buildTrack();
  updateRuler();
  updatePlayhead();
}

document.getElementById('edZoomIn').addEventListener('click', function() {
  applyZoom(zoomLevel + 0.5);
});
document.getElementById('edZoomOut').addEventListener('click', function() {
  applyZoom(zoomLevel - 0.5);
});
document.getElementById('edZoomSlider').addEventListener('input', function() {
  applyZoom(parseFloat(this.value));
});

document.getElementById('edTrackScroll').addEventListener('wheel', function(e) {
  if (e.ctrlKey || e.metaKey) {
    e.preventDefault();
    applyZoom(zoomLevel + (e.deltaY < 0 ? 0.5 : -0.5));
  }
}, {passive:false});

/* ═══ Transport controls ═══ */
document.getElementById('edPrev').addEventListener('click', function() {
  if (activeIdx <= 0) return;
  var wasP = activeVid && !activeVid.paused;
  selectClip(activeIdx - 1, wasP);
});
document.getElementById('edNext').addEventListener('click', function() {
  if (activeIdx >= CLIPS.length - 1) return;
  var wasP = activeVid && !activeVid.paused;
  selectClip(activeIdx + 1, wasP);
});
document.getElementById('edPlayPause').addEventListener('click', function() {
  var v = activeVid;
  if (!v || !CLIPS[activeIdx] || !CLIPS[activeIdx].vurl) return;
  if (v.paused) { v.play().catch(function(){}); } else { v.pause(); }
  syncPlayBtn();
});

/* ═══ Keyboard shortcuts ═══ */
document.addEventListener('keydown', function(e) {
  var tag = (e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea') return;
  var v = activeVid;
  switch(e.code) {
    case 'Space': case 'KeyK':
      e.preventDefault();
      if (!v || !CLIPS[activeIdx] || !CLIPS[activeIdx].vurl) return;
      if (v.paused) { v.play().catch(function(){}); } else { v.pause(); }
      syncPlayBtn();
      break;
    case 'ArrowLeft':
      e.preventDefault();
      if (activeIdx > 0) selectClip(activeIdx - 1, v && !v.paused);
      break;
    case 'ArrowRight':
      e.preventDefault();
      if (activeIdx < CLIPS.length - 1) selectClip(activeIdx + 1, v && !v.paused);
      break;
    case 'KeyJ':
      e.preventDefault();
      if (v && CLIPS[activeIdx]) {
        v.currentTime = Math.max(CLIPS[activeIdx].ts, v.currentTime - 1);
        updatePlayhead(); updateReadout();
      }
      break;
    case 'KeyL':
      e.preventDefault();
      if (v && CLIPS[activeIdx]) {
        v.currentTime = Math.min(CLIPS[activeIdx].te, v.currentTime + 1);
        updatePlayhead(); updateReadout();
      }
      break;
    case 'Home':
      e.preventDefault(); selectClip(0, false); break;
    case 'End':
      e.preventDefault(); selectClip(CLIPS.length - 1, false); break;
    case 'Delete': case 'Backspace':
      e.preventDefault();
      if (CLIPS.length > 0) removeClip(activeIdx);
      break;
    case 'Equal': case 'NumpadAdd':
      if (e.ctrlKey || e.metaKey) { e.preventDefault(); applyZoom(zoomLevel + 0.5); }
      break;
    case 'Minus': case 'NumpadSubtract':
      if (e.ctrlKey || e.metaKey) { e.preventDefault(); applyZoom(zoomLevel - 0.5); }
      break;
    case 'Digit0': case 'Numpad0':
      if (e.ctrlKey || e.metaKey) { e.preventDefault(); applyZoom(1); }
      break;
  }
});

/* ── Playhead scrub system: click ruler or drag playhead to seek ── */
var scrubState = null;

function scrubToX(clientX) {
  var inner = document.getElementById('edTrackInner');
  var scroll = document.getElementById('edTrackScroll');
  if (!inner || !scroll) return;
  var rect = inner.getBoundingClientRect();
  var x = clientX - rect.left + scroll.scrollLeft;
  var w = inner.offsetWidth;
  var td = totalDur();
  if (w <= 0 || td <= 0) return;
  var gt = Math.max(0, Math.min((x / w) * td, td));
  var acc = 0;
  for (var i = 0; i < CLIPS.length; i++) {
    var d = trimDur(CLIPS[i]);
    if (gt <= acc + d + 0.0001) {
      var localT = CLIPS[i].ts + (gt - acc);
      var v = activeVid;
      var c = CLIPS[i];
      if (i !== activeIdx) {
        trimEndLatch = false;
        activeIdx = i;
        if (c.vurl && v) {
          v.pause();
          v.src = c.vurl;
          v.addEventListener('loadedmetadata', function once() {
            v.removeEventListener('loadedmetadata', once);
            v.currentTime = localT;
            buildTrack();
            updatePlayhead();
            updateReadout();
            syncPlayBtn();
          });
          v.load();
        } else {
          buildTrack();
          updatePlayhead();
          updateReadout();
        }
      } else if (v && c.vurl) {
        v.currentTime = localT;
        updatePlayhead();
        updateReadout();
      }
      return;
    }
    acc += d;
  }
}

document.getElementById('edPlayheadGrab').addEventListener('mousedown', function(e) {
  e.preventDefault();
  e.stopPropagation();
  scrubState = { source: 'playhead' };
  this.classList.add('dragging');
  var v = activeVid;
  if (v && !v.paused) { scrubState.wasPlaying = true; v.pause(); }
  scrubToX(e.clientX);
});

document.getElementById('edRuler').addEventListener('mousedown', function(e) {
  e.preventDefault();
  scrubState = { source: 'ruler' };
  var v = activeVid;
  if (v && !v.paused) { scrubState.wasPlaying = true; v.pause(); }
  scrubToX(e.clientX);
});

document.getElementById('edTrackScroll').addEventListener('mousedown', function(e) {
  if (e.target.closest('.ed-clip') || e.target.closest('.ed-playhead-grab')) return;
  e.preventDefault();
  scrubState = { source: 'track' };
  var v = activeVid;
  if (v && !v.paused) { scrubState.wasPlaying = true; v.pause(); }
  scrubToX(e.clientX);
});

document.addEventListener('mousemove', function(e) {
  if (!scrubState) return;
  e.preventDefault();
  scrubToX(e.clientX);
});

document.addEventListener('mouseup', function(e) {
  if (!scrubState) return;
  var phg = document.getElementById('edPlayheadGrab');
  if (phg) phg.classList.remove('dragging');
  if (scrubState.wasPlaying) {
    var v = activeVid;
    if (v) v.play().catch(function(){});
    syncPlayBtn();
  }
  scrubState = null;
});

document.addEventListener('mousedown', function(e) {
  var h = e.target;
  if (!h.classList || (!h.classList.contains('ed-trim-l') && !h.classList.contains('ed-trim-r'))) return;
  e.preventDefault();
  e.stopPropagation();
  var idx = parseInt(h.getAttribute('data-idx'), 10);
  if (isNaN(idx) || idx < 0 || idx >= CLIPS.length) return;
  var clipEl = h.closest('.ed-clip');
  if (!clipEl) return;
  var rect = clipEl.getBoundingClientRect();
  trimState = {
    idx: idx,
    side: h.getAttribute('data-side'),
    startX: e.clientX,
    rect: rect,
    origStart: CLIPS[idx].ts,
    origEnd: CLIPS[idx].te,
    duration: CLIPS[idx].d
  };
});
document.addEventListener('mousemove', function(e) {
  if (!trimState) return;
  e.preventDefault();
  var dx = e.clientX - trimState.startX;
  var span = Math.max(0.1, trimState.origEnd - trimState.origStart);
  var ds = dx / (trimState.rect.width / span);
  if (trimState.side === 'left') {
    CLIPS[trimState.idx].ts = Math.round(
      Math.max(0, Math.min(trimState.origStart + ds, trimState.origEnd - 0.3)) * 100) / 100;
  } else {
    CLIPS[trimState.idx].te = Math.round(
      Math.max(trimState.origStart + 0.3, Math.min(trimState.origEnd + ds, trimState.duration)) * 100) / 100;
  }
  ensureClip(CLIPS[trimState.idx]);
  buildTrack();
  var v = activeVid;
  if (v && trimState.idx === activeIdx && CLIPS[activeIdx].vurl) {
    if (v.currentTime < CLIPS[activeIdx].ts) v.currentTime = CLIPS[activeIdx].ts;
    if (v.currentTime > CLIPS[activeIdx].te) v.currentTime = CLIPS[activeIdx].te;
  }
  updatePlayhead();
});
document.addEventListener('mouseup', function() {
  if (trimState) {
    var c = CLIPS[trimState.idx];
    sendAction('trim:' + trimState.idx + ':' + c.ts + ':' + c.te + ':' + c.d);
    trimState = null;
  }
});

window.addEventListener('resize', function() {
  buildTrack();
  updateRuler();
});

function init() {
  bindActiveEvents();
  if (CLIPS.length) {
    loadVideoAt(0, false);
  } else {
    buildTrack();
  }
}
if (document.readyState === 'complete' || document.readyState === 'interactive') {
  setTimeout(init, 80);
} else {
  document.addEventListener('DOMContentLoaded', function() { setTimeout(init, 80); });
}
})();
</script>"""

        html_out = (
            _ed_room_html.replace("__CLIPS_B64__", clips_b64).replace(
                "__PREFIX_JSON__", prefix_js
            )
        )
        components.html(html_out, height=700, scrolling=False)


    def _render_storyboard_save_load(page_prefix, key_suffix="", use_projects_layout=False):
        is_storyboard = page_prefix.startswith("sbi")
        snap_key = "storyboard" if is_storyboard else "editing"
        mode_key = "sb_mode" if is_storyboard else "ed_mode"
        name_key = "sb_active_name" if is_storyboard else "ed_active_name"
        items_key = "sb_active_images" if is_storyboard else "ed_active_videos"
        media_type = "image" if is_storyboard else "video"

        # ════════════════════════════════════════════
        #  STORYBOARD MANAGER
        # ════════════════════════════════════════════
        if page_prefix == "sbi":
            snaps = load_all_snapshots()
            all_sb = snaps.get("storyboard", {})
            active_proj = get_active_project_id()
            sb_names = filter_snapshot_names(all_sb, active_proj)

            if use_projects_layout and st.session_state.sb_mode == "pick":
                st.session_state.sb_mode = None
                st.rerun()

            # ── Entry screen: no active storyboard ──────
            if st.session_state.sb_mode is None:

                if use_projects_layout:
                    snaps_data = snaps.get("storyboard", {})
                    st.text_input(
                        "sb_pick_bridge",
                        key="sb_pick_act",
                        on_change=_on_storyboard_grid_pick_change,
                        label_visibility="collapsed",
                    )
                    if not sb_names:
                        st.info("No storyboards yet. Use **NEW STORYBOARD** in the sidebar to create one.")
                    else:
                        sb_cards = []
                        active_nm = st.session_state.get("sb_active_name") or ""
                        cur_mode = st.session_state.get("sb_mode")
                        for sname in sb_names:
                            raw_items = snapshot_entry_items(snaps_data.get(sname, []))
                            sb_thumb = ""
                            for _si in raw_items:
                                _sip = _si.get("image_path") or _si.get("url") or ""
                                if _sip and os.path.exists(_sip):
                                    try:
                                        from PIL import Image as _PILImage
                                        import io as _io
                                        with _PILImage.open(_sip) as _sim:
                                            _sim.thumbnail((400, 240), _PILImage.LANCZOS)
                                            _sbuf = _io.BytesIO()
                                            _sim.convert("RGB").save(_sbuf, format="JPEG", quality=75)
                                            sb_thumb = f"data:image/jpeg;base64,{_b64.b64encode(_sbuf.getvalue()).decode('ascii')}"
                                    except Exception:
                                        pass
                                elif _sip and _sip.startswith("http"):
                                    sb_thumb = _sip
                                if sb_thumb:
                                    break
                            sb_cards.append({
                                "name": sname,
                                "thumb": sb_thumb,
                                "frames": len(raw_items),
                                "is_active": (sname == active_nm and cur_mode in ("new", "loaded")),
                            })

                        COLS = 4
                        cards_html_parts = []
                        for c in sb_cards:
                            _cname = _html_stdlib.escape(c["name"])
                            _thumb = (c["thumb"] or "").replace('"', "&quot;")
                            bcol = "#FFEB3B" if c["is_active"] else "transparent"
                            init = _html_stdlib.escape(c["name"][:2].upper())
                            _nf = str(c["frames"])
                            if c["thumb"]:
                                thumb_block = (
                                    f'<img src="{_thumb}" style="width:100%;height:100%;object-fit:cover;display:block;" '
                                    f'draggable="false" alt=""/>'
                                )
                            else:
                                thumb_block = (
                                    f'<span style="color:#3a3a38;font-size:1.6rem;font-weight:300;'
                                    f'font-family:Open Sans,sans-serif;">{init}</span>'
                                )
                            _safe = c["name"].replace("\\", "\\\\").replace("'", "\\'")
                            cards_html_parts.append(
                                f'''
                                <div class="proj-cell" onclick="sbPick('{_safe}')">
                                    <div class="proj-thumb" style="border-color:{bcol};">{thumb_block}</div>
                                    <div class="proj-title">{_cname}</div>
                                    <div class="proj-meta">Frames: {_nf}</div>
                                </div>'''
                            )
                        cards_html = "".join(cards_html_parts)
                        nrows = (len(sb_cards) + COLS - 1) // COLS
                        grid_h = max(420, nrows * 210)
                        sb_grid_html = f'''
                        <style>
                            * {{ margin:0; padding:0; box-sizing:border-box; }}
                            body {{ background:transparent; font-family: Open Sans, sans-serif; }}
                            .proj-grid {{
                                display:grid;
                                grid-template-columns:repeat({COLS}, minmax(0, 1fr));
                                gap:14px;
                                padding:4px;
                            }}
                            .proj-cell {{ cursor:pointer; }}
                            .proj-thumb {{
                                position:relative;
                                border:2px solid transparent;
                                border-radius:10px;
                                overflow:hidden;
                                aspect-ratio:16/9;
                                background:#111110;
                                margin-bottom:6px;
                                display:flex;
                                align-items:center;
                                justify-content:center;
                                transition:border-color 0.15s ease;
                            }}
                            .proj-cell:hover .proj-thumb {{ border-color:rgba(255,235,59,0.45) !important; }}
                            .proj-title {{
                                color:#f0ece4;
                                font-size:0.78rem;
                                font-weight:600;
                                margin:0 0 4px;
                                line-height:1.25;
                                word-break:break-word;
                            }}
                            .proj-meta {{
                                color:#7a7a6e;
                                font-size:0.62rem;
                                line-height:1.35;
                                margin:0;
                            }}
                        </style>
                        <div class="proj-grid">{cards_html}</div>
                        <script>
                            function sbPick(name) {{
                                if (!name) return;
                                var inp = window.parent.document.querySelector(
                                    'input[aria-label="sb_pick_bridge"]'
                                );
                                if (!inp) return;
                                var ns = Object.getOwnPropertyDescriptor(
                                    window.HTMLInputElement.prototype, 'value'
                                ).set;
                                var payload = name + '|' + Date.now();
                                ns.call(inp, payload);
                                inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                try {{
                                    inp.dispatchEvent(new InputEvent('input', {{
                                        bubbles: true, inputType: 'insertFromPaste', data: payload
                                    }}));
                                }} catch (e) {{}}
                                try {{ inp.focus({{ preventScroll: true }}); }} catch (e2) {{}}
                                try {{ inp.blur(); }} catch (e3) {{}}
                            }}
                        </script>'''
                        components.html(sb_grid_html, height=grid_h, scrolling=False)
                else:
                    col_new, col_upload = st.columns([1, 1], gap="small")

                    with col_new:
                        if st.button("＋ NEW STORYBOARD", key=f"sb_btn_new{key_suffix}", use_container_width=True):
                            st.session_state.sb_mode = "new"
                            st.session_state.sb_active_name = ""
                            st.session_state.sb_active_images = []
                            st.rerun()

                    with col_upload:
                        if sb_names:
                            if st.button("⬆ UPLOAD STORYBOARD", key=f"sb_btn_upload{key_suffix}", use_container_width=True):
                                st.session_state.sb_mode = "pick"
                                st.rerun()
                        else:
                            st.button("⬆ UPLOAD STORYBOARD", key=f"sb_btn_upload_dis{key_suffix}",
                                      disabled=True, use_container_width=True)

            # ── Pick from saved storyboards ─────────────
            elif st.session_state.sb_mode == "pick" and not use_projects_layout:

                if not sb_names:
                    st.info("No saved storyboards.")
                    if st.button("BACK", key=f"sb_cancel_pick_empty{key_suffix}", use_container_width=True):
                        st.session_state.sb_mode = None
                        st.rerun()
                else:
                    snaps_data = snaps.get("storyboard", {})
                    SB_COLS = 4
                    n_sb_rows = (len(sb_names) + SB_COLS - 1) // SB_COLS
                    sb_flat = 0

                    for _sr in range(n_sb_rows):
                        sb_cols = st.columns(SB_COLS, gap="medium")
                        for _sc in range(SB_COLS):
                            if sb_flat >= len(sb_names):
                                break
                            sname = sb_names[sb_flat]
                            sb_flat += 1

                            with sb_cols[_sc]:
                                # Get thumbnail from first image in snapshot
                                raw_items = snapshot_entry_items(snaps_data.get(sname, []))
                                sb_thumb = ""
                                for _si in raw_items:
                                    _sip = _si.get("image_path") or _si.get("url") or ""
                                    if _sip and os.path.exists(_sip):
                                        try:
                                            from PIL import Image as _PILImage
                                            import io as _io
                                            with _PILImage.open(_sip) as _sim:
                                                _sim.thumbnail((300, 180), _PILImage.LANCZOS)
                                                _sbuf = _io.BytesIO()
                                                _sim.convert("RGB").save(_sbuf, format="JPEG", quality=72)
                                                sb_thumb = f"data:image/jpeg;base64,{_b64.b64encode(_sbuf.getvalue()).decode('ascii')}"
                                        except Exception:
                                            pass
                                    elif _sip and _sip.startswith("http"):
                                        sb_thumb = _sip
                                    if sb_thumb:
                                        break

                                sb_hover_id = f"sb_thumb_{sb_flat}"
                                item_count = len(raw_items)

                                if sb_thumb:
                                    st.markdown(
                                        f'<style>#{sb_hover_id}:hover {{ border-color:#FFEB3B !important; cursor:pointer; }}</style>'
                                        f'<div id="{sb_hover_id}" style="border:2px solid transparent; border-radius:10px; '
                                        f'overflow:hidden; aspect-ratio:16/9; background:#111110; '
                                        f'margin-bottom:4px; transition:border-color 0.15s ease;">'
                                        f'<img src="{sb_thumb}" style="width:100%; height:100%; object-fit:cover; display:block;"/>'
                                        f'</div>',
                                        unsafe_allow_html=True,
                                    )
                                else:
                                    st.markdown(
                                        f'<style>#{sb_hover_id}:hover {{ border-color:#FFEB3B !important; cursor:pointer; }}</style>'
                                        f'<div id="{sb_hover_id}" style="border:2px solid transparent; border-radius:10px; '
                                        f'aspect-ratio:16/9; background:linear-gradient(135deg,#1a1a18,#111110); '
                                        f'display:flex; align-items:center; justify-content:center; '
                                        f'margin-bottom:4px; transition:border-color 0.15s ease;">'
                                        f'<span style="color:#3a3a38; font-size:1.2rem; font-weight:300; '
                                        f'font-family:Open Sans,sans-serif;">{sname[:2].upper()}</span>'
                                        f'</div>',
                                        unsafe_allow_html=True,
                                    )

                                # Click to load
                                if st.button(sname, key=f"sb_pick_card_{sb_flat}{key_suffix}", use_container_width=True):
                                    raw = snaps_data.get(sname, [])
                                    items = snapshot_entry_items(raw)
                                    st.session_state.sb_active_images = items
                                    st.session_state.sb_active_name = sname
                                    st.session_state.sb_mode = "loaded"
                                    st.rerun()

                                st.markdown(
                                    f'<p style="color:#7a7a6e; font-size:0.6rem; font-family:Open Sans,sans-serif; '
                                    f'margin:0; -webkit-text-fill-color:#7a7a6e;">{item_count} frames</p>',
                                    unsafe_allow_html=True,
                                )

                    st.markdown("")
                    if st.button("BACK", key=f"sb_cancel_pick{key_suffix}", use_container_width=True):
                        st.session_state.sb_mode = None
                        st.rerun()

            # ── New or loaded storyboard: show images ───
            elif st.session_state.sb_mode in ("new", "loaded"):

                # Nome solo in sessione / sidebar / griglia elenco; niente box sopra le immagini.

                # Show images from this storyboard
                images = st.session_state.sb_active_images
                if not images:
                    st.info("No images yet — go to Gallery › Images and add images to this storyboard.")
                else:
                    _render_storyboard_grid("sb_active_images", "gallery_selected_imgs", media_type, f"sbi{key_suffix}")

                # Export JSON
                items = st.session_state.get(items_key, [])
                if items:
                    export_data = {
                        "name": st.session_state.get(name_key, "Untitled"),
                        "type": "storyboard" if is_storyboard else "editing",
                        "created": datetime.now().isoformat(),
                        "total_frames": len(items),
                        "frames": [
                            {
                                "position": i + 1,
                                "caption": item.get("caption", ""),
                                "notes": item.get("notes", ""),
                                "prompt": item.get("prompt", ""),
                                "image_path": item.get("image_path", "") if is_storyboard else "",
                                "video_path": item.get("video_path", "") if not is_storyboard else "",
                                "style": item.get("style", ""),
                                "resolution": item.get("resolution", ""),
                                "aspect_ratio": item.get("aspect_ratio", ""),
                                "created_at": item.get("created_at", ""),
                            }
                            for i, item in enumerate(items)
                        ]
                    }
                    current_name = st.session_state.get(name_key, "untitled")
                    safe_name = re.sub(r'[^\w\-]', '_', current_name.lower().strip()) or "untitled"
                    st.download_button(
                        "📥 EXPORT JSON",
                        data=json.dumps(export_data, indent=2, ensure_ascii=False),
                        file_name=f"{safe_name}.json",
                        mime="application/json",
                        key=f"{page_prefix}_export{key_suffix}"
                    )

                # ── Save to Assets ──
                items = st.session_state.get(items_key, [])
                if items and is_storyboard:
                    sb_asset_options = []
                    for si, sitem in enumerate(items):
                        slabel = f"#{si + 1} — {(sitem.get('caption', 'Image') or 'Image')[:30]}"
                        sb_asset_options.append((slabel, si))

                    sb_ac1, sb_ac2 = st.columns([3, 1])
                    with sb_ac1:
                        sb_asset_selected = st.multiselect(
                            "Select images to save to Assets",
                            options=[o[0] for o in sb_asset_options],
                            key=f"{page_prefix}_asset_select{key_suffix}",
                            label_visibility="collapsed",
                            placeholder="Select images for Assets..."
                        )
                    with sb_ac2:
                        sb_n_sel = len(sb_asset_selected)
                        sb_alabel = f"💾 ASSETS ({sb_n_sel})" if sb_n_sel > 0 else "💾 TO ASSETS"
                        if st.button(sb_alabel, key=f"{page_prefix}_to_assets{key_suffix}",
                                     disabled=(sb_n_sel == 0), use_container_width=True):
                            label_to_idx = {o[0]: o[1] for o in sb_asset_options}
                            saved = 0
                            for lab in sb_asset_selected:
                                sidx = label_to_idx[lab]
                                if sidx < len(items):
                                    src = items[sidx].get("image_path", "")
                                    if src and os.path.exists(src):
                                        result = add_to_assets(source_path=src)
                                        if result:
                                            saved += 1
                            if saved > 0:
                                st.toast(f"Saved {saved} image(s) to Assets")
                            st.rerun()

        # ════════════════════════════════════════════
        #  EDITING MANAGER
        # ════════════════════════════════════════════
        else:
            snaps = load_all_snapshots()
            all_ed = snaps.get("editing", {})
            active_proj = get_active_project_id()
            ed_names = filter_snapshot_names(all_ed, active_proj)

            if use_projects_layout and st.session_state.ed_mode == "pick":
                st.session_state.ed_mode = None
                st.rerun()

            # ── Entry screen: no active editing ──────
            if st.session_state.ed_mode is None:

                if use_projects_layout:
                    snaps_data = snaps.get("editing", {})
                    st.text_input(
                        "ed_pick_bridge",
                        key="ed_pick_act",
                        on_change=_on_editing_grid_pick_change,
                        label_visibility="collapsed",
                    )
                    if not ed_names:
                        st.info("No editing sessions yet. Use **NEW EDITING** in the sidebar to create one.")
                    else:
                        ed_cards = []
                        active_nm = st.session_state.get("ed_active_name") or ""
                        cur_mode = st.session_state.get("ed_mode")
                        for ename in ed_names:
                            raw_items = snapshot_entry_items(snaps_data.get(ename, []))
                            ed_thumb, nclips = _thumbnail_for_editing_items(raw_items)
                            ed_cards.append({
                                "name": ename,
                                "thumb": ed_thumb,
                                "clips": nclips,
                                "is_active": (ename == active_nm and cur_mode in ("new", "loaded")),
                            })

                        COLS = 4
                        cards_html_parts = []
                        for c in ed_cards:
                            _cname = _html_stdlib.escape(c["name"])
                            _thumb = (c["thumb"] or "").replace('"', "&quot;")
                            bcol = "#FF9800" if c["is_active"] else "transparent"
                            init = _html_stdlib.escape(c["name"][:2].upper())
                            _nc = str(c["clips"])
                            if c["thumb"]:
                                thumb_block = (
                                    f'<img src="{_thumb}" style="width:100%;height:100%;object-fit:cover;display:block;" '
                                    f'draggable="false" alt=""/>'
                                )
                            else:
                                thumb_block = (
                                    f'<span style="color:#3a3a38;font-size:1.6rem;font-weight:300;'
                                    f'font-family:Open Sans,sans-serif;">{init}</span>'
                                )
                            _safe = c["name"].replace("\\", "\\\\").replace("'", "\\'")
                            cards_html_parts.append(
                                f'''
                                <div class="proj-cell" onclick="edPick('{_safe}')">
                                    <div class="proj-thumb ed-proj-thumb" style="border-color:{bcol};">{thumb_block}</div>
                                    <div class="proj-title">{_cname}</div>
                                    <div class="proj-meta">Clips: {_nc}</div>
                                </div>'''
                            )
                        cards_html = "".join(cards_html_parts)
                        nrows = (len(ed_cards) + COLS - 1) // COLS
                        grid_h = max(420, nrows * 210)
                        ed_grid_html = f'''
                        <style>
                            * {{ margin:0; padding:0; box-sizing:border-box; }}
                            body {{ background:transparent; font-family: Open Sans, sans-serif; }}
                            .proj-grid {{
                                display:grid;
                                grid-template-columns:repeat({COLS}, minmax(0, 1fr));
                                gap:14px;
                                padding:4px;
                            }}
                            .proj-cell {{ cursor:pointer; }}
                            .proj-thumb.ed-proj-thumb {{
                                position:relative;
                                border:2px solid transparent;
                                border-radius:10px;
                                overflow:hidden;
                                aspect-ratio:16/9;
                                background:#111110;
                                margin-bottom:6px;
                                display:flex;
                                align-items:center;
                                justify-content:center;
                                transition:border-color 0.15s ease;
                            }}
                            .proj-cell:hover .proj-thumb.ed-proj-thumb {{ border-color:rgba(255,152,0,0.45) !important; }}
                            .proj-title {{
                                color:#f0ece4;
                                font-size:0.78rem;
                                font-weight:600;
                                margin:0 0 4px;
                                line-height:1.25;
                                word-break:break-word;
                            }}
                            .proj-meta {{
                                color:#7a7a6e;
                                font-size:0.62rem;
                                line-height:1.35;
                                margin:0;
                            }}
                        </style>
                        <div class="proj-grid">{cards_html}</div>
                        <script>
                            function edPick(name) {{
                                if (!name) return;
                                var inp = window.parent.document.querySelector(
                                    'input[aria-label="ed_pick_bridge"]'
                                );
                                if (!inp) return;
                                var ns = Object.getOwnPropertyDescriptor(
                                    window.HTMLInputElement.prototype, 'value'
                                ).set;
                                var payload = name + '|' + Date.now();
                                ns.call(inp, payload);
                                inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                try {{
                                    inp.dispatchEvent(new InputEvent('input', {{
                                        bubbles: true, inputType: 'insertFromPaste', data: payload
                                    }}));
                                }} catch (e) {{}}
                                try {{ inp.focus({{ preventScroll: true }}); }} catch (e2) {{}}
                                try {{ inp.blur(); }} catch (e3) {{}}
                            }}
                        </script>'''
                        components.html(ed_grid_html, height=grid_h, scrolling=False)
                else:
                    col_new, col_upload = st.columns([1, 1], gap="small")

                    with col_new:
                        if st.button("＋ NEW EDITING", key=f"ed_btn_new{key_suffix}", use_container_width=True):
                            st.session_state.ed_mode = "new"
                            st.session_state.ed_active_name = ""
                            st.session_state.ed_active_videos = []
                            st.rerun()

                    with col_upload:
                        if ed_names:
                            if st.button("⬆ UPLOAD EDITING", key=f"ed_btn_upload{key_suffix}", use_container_width=True):
                                st.session_state.ed_mode = "pick"
                                st.rerun()
                        else:
                            st.button("⬆ UPLOAD EDITING", key=f"ed_btn_upload_dis{key_suffix}",
                                      disabled=True, use_container_width=True)

            # ── Pick from saved editing snapshots ─────
            elif st.session_state.ed_mode == "pick" and not use_projects_layout:

                if not ed_names:
                    st.info("No saved editing sessions.")
                    if st.button("BACK", key=f"ed_cancel_pick_empty{key_suffix}", use_container_width=True):
                        st.session_state.ed_mode = None
                        st.rerun()
                else:
                    ed_snaps_data = snaps.get("editing", {})
                    ED_COLS = 4
                    n_ed_rows = (len(ed_names) + ED_COLS - 1) // ED_COLS
                    ed_flat = 0

                    for _er in range(n_ed_rows):
                        ed_cols_row = st.columns(ED_COLS, gap="medium")
                        for _ec in range(ED_COLS):
                            if ed_flat >= len(ed_names):
                                break
                            ename = ed_names[ed_flat]
                            ed_flat += 1

                            with ed_cols_row[_ec]:
                                raw_ed_items = snapshot_entry_items(ed_snaps_data.get(ename, []))
                                ed_thumb = ""
                                for _ei in raw_ed_items:
                                    _eip = _ei.get("last_frame_path") or ""
                                    if _eip and os.path.exists(_eip):
                                        try:
                                            from PIL import Image as _PILImage
                                            import io as _io
                                            with _PILImage.open(_eip) as _eim:
                                                _eim.thumbnail((300, 180), _PILImage.LANCZOS)
                                                _ebuf = _io.BytesIO()
                                                _eim.convert("RGB").save(_ebuf, format="JPEG", quality=72)
                                                ed_thumb = f"data:image/jpeg;base64,{_b64.b64encode(_ebuf.getvalue()).decode('ascii')}"
                                        except Exception:
                                            pass
                                    if not ed_thumb:
                                        _evp = _ei.get("video_path") or ""
                                        if _evp and os.path.exists(_evp):
                                            try:
                                                import cv2
                                                cap = cv2.VideoCapture(_evp)
                                                if cap.isOpened():
                                                    ret, frame = cap.read()
                                                    if ret:
                                                        h, w = frame.shape[:2]
                                                        scale = min(300/max(w,1), 180/max(h,1), 1.0)
                                                        if scale < 1:
                                                            frame = cv2.resize(frame, (int(w*scale), int(h*scale)))
                                                        _, _ebuf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                                                        ed_thumb = f"data:image/jpeg;base64,{_b64.b64encode(_ebuf.tobytes()).decode('ascii')}"
                                                cap.release()
                                            except Exception:
                                                pass
                                    if ed_thumb:
                                        break

                                ed_hover_id = f"ed_thumb_{ed_flat}"
                                ed_item_count = len(raw_ed_items)

                                if ed_thumb:
                                    st.markdown(
                                        f'<style>#{ed_hover_id}:hover {{ border-color:#FFEB3B !important; cursor:pointer; }}</style>'
                                        f'<div id="{ed_hover_id}" style="border:2px solid transparent; border-radius:10px; '
                                        f'overflow:hidden; aspect-ratio:16/9; background:#111110; '
                                        f'margin-bottom:4px; transition:border-color 0.15s ease;">'
                                        f'<img src="{ed_thumb}" style="width:100%; height:100%; object-fit:cover; display:block;"/>'
                                        f'</div>',
                                        unsafe_allow_html=True,
                                    )
                                else:
                                    st.markdown(
                                        f'<style>#{ed_hover_id}:hover {{ border-color:#FFEB3B !important; cursor:pointer; }}</style>'
                                        f'<div id="{ed_hover_id}" style="border:2px solid transparent; border-radius:10px; '
                                        f'aspect-ratio:16/9; background:linear-gradient(135deg,#1a1a18,#111110); '
                                        f'display:flex; align-items:center; justify-content:center; '
                                        f'margin-bottom:4px; transition:border-color 0.15s ease;">'
                                        f'<span style="color:#3a3a38; font-size:1.2rem; font-weight:300; '
                                        f'font-family:Open Sans,sans-serif;">{ename[:2].upper()}</span>'
                                        f'</div>',
                                        unsafe_allow_html=True,
                                    )

                                if st.button(ename, key=f"ed_pick_card_{ed_flat}{key_suffix}", use_container_width=True):
                                    raw = ed_snaps_data.get(ename, [])
                                    items = snapshot_entry_items(raw)
                                    st.session_state.ed_active_videos = [
                                        _normalize_editing_video_item(dict(x)) for x in items
                                    ]
                                    st.session_state.ed_active_name = ename
                                    st.session_state.ed_mode = "loaded"
                                    st.rerun()

                                st.markdown(
                                    f'<p style="color:#7a7a6e; font-size:0.6rem; font-family:Open Sans,sans-serif; '
                                    f'margin:0; -webkit-text-fill-color:#7a7a6e;">{ed_item_count} clips</p>',
                                    unsafe_allow_html=True,
                                )

                    st.markdown("")
                    if st.button("BACK", key=f"ed_cancel_pick{key_suffix}", use_container_width=True):
                        st.session_state.ed_mode = None
                        st.rerun()

            # ── New or loaded editing: show videos ────
            elif st.session_state.ed_mode in ("new", "loaded"):

                _process_editing_actions("ed_active_videos", f"sbv{key_suffix}")

                if not is_storyboard:
                    # ── Import videos from Gallery and Assets ──
                    with st.expander("＋ IMPORT CLIPS", expanded=False):
                        import_tab1, import_tab2 = st.tabs(["From Gallery", "From Assets"])

                        with import_tab1:
                            all_gallery_vids = st.session_state.get("gallery_videos", [])
                            active_proj = st.session_state.get("active_project_id")
                            if active_proj:
                                all_gallery_vids = [v for v in all_gallery_vids if v.get("project_id") == active_proj]

                            if not all_gallery_vids:
                                st.info("No videos in Gallery. Generate some from the Console.")
                            else:
                                gv_options = []
                                for gi, gv in enumerate(all_gallery_vids):
                                    label = f"#{gi+1} — {(gv.get('caption', 'Video') or 'Video')[:35]}"
                                    gv_options.append((label, gi))

                                gv_selected = st.multiselect(
                                    "Select videos from Gallery",
                                    options=[o[0] for o in gv_options],
                                    key=f"{page_prefix}_import_gallery{key_suffix}",
                                    label_visibility="collapsed",
                                    placeholder="Select gallery videos...",
                                )

                                if st.button(
                                    f"ADD ({len(gv_selected)})" if gv_selected else "ADD",
                                    key=f"{page_prefix}_import_gal_btn{key_suffix}",
                                    disabled=(len(gv_selected) == 0),
                                    use_container_width=True,
                                ):
                                    label_to_idx = {o[0]: o[1] for o in gv_options}
                                    existing_paths = {item.get("video_path") for item in st.session_state.get(items_key, []) if item.get("video_path")}
                                    added = 0
                                    for lab in gv_selected:
                                        idx = label_to_idx[lab]
                                        if idx < len(all_gallery_vids):
                                            item = all_gallery_vids[idx]
                                            vpath = item.get("video_path", "")
                                            if not vpath or vpath not in existing_paths:
                                                st.session_state[items_key].append(
                                                    _normalize_editing_video_item(dict(item))
                                                )
                                                if vpath:
                                                    existing_paths.add(vpath)
                                                added += 1
                                    if st.session_state.get(name_key) and added > 0:
                                        upsert_snapshot_entry(snap_key, st.session_state[name_key], st.session_state[items_key])
                                    if added > 0:
                                        st.toast(f"Added {added} clip(s)")
                                    st.rerun()

                        with import_tab2:
                            catalog = load_asset_catalog()
                            if active_proj:
                                catalog = [a for a in catalog if a.get("project_id") == active_proj]
                            video_assets = [a for a in catalog if a["type"] == "video"]

                            if not video_assets:
                                st.info("No video assets. Upload some in the Assets page.")
                            else:
                                va_options = []
                                for ai, va in enumerate(video_assets):
                                    label = f"{va['name']} ({va.get('size_str', '')})"
                                    va_options.append((label, va["id"]))

                                va_selected = st.multiselect(
                                    "Select videos from Assets",
                                    options=[o[0] for o in va_options],
                                    key=f"{page_prefix}_import_assets{key_suffix}",
                                    label_visibility="collapsed",
                                    placeholder="Select asset videos...",
                                )

                                if st.button(
                                    f"ADD ({len(va_selected)})" if va_selected else "ADD",
                                    key=f"{page_prefix}_import_asset_btn{key_suffix}",
                                    disabled=(len(va_selected) == 0),
                                    use_container_width=True,
                                ):
                                    label_to_id = {o[0]: o[1] for o in va_options}
                                    existing_paths = {item.get("video_path") for item in st.session_state.get(items_key, []) if item.get("video_path")}
                                    added = 0
                                    for lab in va_selected:
                                        aid = label_to_id[lab]
                                        asset = next((a for a in video_assets if a["id"] == aid), None)
                                        if asset and os.path.exists(asset["path"]):
                                            vpath = os.path.abspath(asset["path"])
                                            if vpath not in existing_paths:
                                                st.session_state[items_key].append({
                                                    "video_path": vpath,
                                                    "caption": asset.get("original_name", asset["name"])[:50],
                                                    "url": "",
                                                    "trim_start": 0,
                                                    "trim_end": -1,
                                                    "duration": 0,
                                                    "created_at": asset.get("uploaded_at", ""),
                                                })
                                                existing_paths.add(vpath)
                                                added += 1
                                    if st.session_state.get(name_key) and added > 0:
                                        upsert_snapshot_entry(snap_key, st.session_state[name_key], st.session_state[items_key])
                                    if added > 0:
                                        st.toast(f"Added {added} clip(s)")
                                    st.rerun()

                # Show videos from this editing
                videos = st.session_state.ed_active_videos
                if not videos:
                    st.info("No videos yet — go to Gallery › Videos and add videos to this editing session.")
                else:
                    _render_editing_room(items_key, f"sbv{key_suffix}")

                # Export JSON
                items = st.session_state.get(items_key, [])
                if items:
                    export_data = {
                        "name": st.session_state.get(name_key, "Untitled"),
                        "type": "storyboard" if is_storyboard else "editing",
                        "created": datetime.now().isoformat(),
                        "total_frames": len(items),
                        "frames": [
                            {
                                "position": i + 1,
                                "caption": item.get("caption", ""),
                                "notes": item.get("notes", ""),
                                "prompt": item.get("prompt", ""),
                                "image_path": item.get("image_path", "") if is_storyboard else "",
                                "video_path": item.get("video_path", "") if not is_storyboard else "",
                                "style": item.get("style", ""),
                                "resolution": item.get("resolution", ""),
                                "aspect_ratio": item.get("aspect_ratio", ""),
                                "created_at": item.get("created_at", ""),
                            }
                            for i, item in enumerate(items)
                        ]
                    }
                    current_name = st.session_state.get(name_key, "untitled")
                    safe_name = re.sub(r'[^\w\-]', '_', current_name.lower().strip()) or "untitled"
                    _exp_c1, _exp_c2 = st.columns(2, gap="small")
                    with _exp_c1:
                        st.download_button(
                            "📥 EXPORT JSON",
                            data=json.dumps(export_data, indent=2, ensure_ascii=False),
                            file_name=f"{safe_name}.json",
                            mime="application/json",
                            key=f"{page_prefix}_export{key_suffix}",
                            use_container_width=True,
                            type="secondary",
                        )
                    with _exp_c2:
                        if not is_storyboard:
                            _export_key = f"{page_prefix}_export_video{key_suffix}"
                            if st.button(
                                "📥 EXPORT VIDEO",
                                key=_export_key,
                                use_container_width=True,
                                type="secondary",
                            ):
                                with st.spinner("Exporting video with ffmpeg..."):
                                    _exp_name = st.session_state.get(name_key, "untitled")
                                    _exp_result = _export_editing_video(items, _exp_name)
                                if _exp_result and os.path.exists(_exp_result):
                                    _exp_size = os.path.getsize(_exp_result)
                                    _exp_mb = round(_exp_size / (1024 * 1024), 1)
                                    st.success(f"Exported: {os.path.basename(_exp_result)} ({_exp_mb} MB)")
                                    with open(_exp_result, "rb") as _ef:
                                        st.download_button(
                                            "DOWNLOAD",
                                            data=_ef.read(),
                                            file_name=os.path.basename(_exp_result),
                                            mime="video/mp4",
                                            key=f"{page_prefix}_download_export{key_suffix}",
                                        )
                                else:
                                    st.error("Export failed. Check that ffmpeg is installed and video files exist.")

                # ── Save to Assets ──
                items = st.session_state.get(items_key, [])
                if items and not is_storyboard:
                    ed_asset_options = []
                    for ei, eitem in enumerate(items):
                        elabel = f"#{ei + 1} — {(eitem.get('caption', 'Video') or 'Video')[:30]}"
                        ed_asset_options.append((elabel, ei))

                    ed_ac1, ed_ac2 = st.columns([3, 1])
                    with ed_ac1:
                        ed_asset_selected = st.multiselect(
                            "Select videos to save to Assets",
                            options=[o[0] for o in ed_asset_options],
                            key=f"{page_prefix}_asset_select{key_suffix}",
                            label_visibility="collapsed",
                            placeholder="Select videos for Assets..."
                        )
                    with ed_ac2:
                        ed_n_sel = len(ed_asset_selected)
                        ed_alabel = f"💾 ASSETS ({ed_n_sel})" if ed_n_sel > 0 else "💾 TO ASSETS"
                        if st.button(ed_alabel, key=f"{page_prefix}_to_assets{key_suffix}",
                                     disabled=(ed_n_sel == 0), use_container_width=True):
                            label_to_idx = {o[0]: o[1] for o in ed_asset_options}
                            saved = 0
                            for lab in ed_asset_selected:
                                eidx = label_to_idx[lab]
                                if eidx < len(items):
                                    src = items[eidx].get("video_path", "")
                                    if src and os.path.exists(src):
                                        result = add_to_assets(source_path=src)
                                        if result:
                                            saved += 1
                            if saved > 0:
                                st.toast(f"Saved {saved} video(s) to Assets")
                            st.rerun()

    if st.session_state.get("active_page") == "gallery":
        render_gallery_page()

    elif st.session_state.get("active_page") == "projects":
        # ── Navigation ──
        if "proj_nav" not in st.session_state:
            st.session_state.proj_nav = "Projects"

        def _on_proj_nav_change():
            val = st.session_state.proj_nav
            if val == "Console":
                st.session_state.proj_nav = "Projects"
                st.session_state["_console_was_away"] = True
                st.session_state.active_page = "console"
            elif val == "Gallery":
                st.session_state.proj_nav = "Projects"
                st.session_state.active_page = "gallery"
            elif val == "Assets":
                st.session_state.proj_nav = "Projects"
                st.session_state.active_page = "assets"
            elif val == "References":
                st.session_state.proj_nav = "Projects"
                st.session_state.active_page = "references"
            elif val == "Storyboard":
                st.session_state.proj_nav = "Projects"
                st.session_state.active_page = "storyboard"
            elif val == "Editing":
                st.session_state.proj_nav = "Projects"
                st.session_state.active_page = "editing"

        _proj_nav_col, _proj_name_col = st.columns([4, 1])
        with _proj_nav_col:
            st.radio(
                "proj_nav_label",
                ["Console", "Projects", "Gallery", "Assets", "References", "Storyboard", "Editing"],
                horizontal=True,
                key="proj_nav",
                on_change=_on_proj_nav_change,
                label_visibility="collapsed",
            )
        with _proj_name_col:
            _render_project_name_inline_right()

        proj_data = load_projects()
        project_list = proj_data.get("projects", [])
        active_id = st.session_state.get("active_project_id")

        # ── Helper: get thumbnail for a project ──
        def _get_project_thumbnail(pid):
            """Return a base64 data URI thumbnail for the given project, or empty string."""
            # Try gallery videos first (last_frame_path), then gallery images
            all_videos = st.session_state.get("gallery_videos", [])
            for v in all_videos:
                if v.get("project_id") == pid:
                    lfp = v.get("last_frame_path") or ""
                    if lfp and os.path.exists(lfp):
                        try:
                            from PIL import Image as _PILImage
                            import io as _io
                            with _PILImage.open(lfp) as im:
                                im.thumbnail((400, 240), _PILImage.LANCZOS)
                                buf = _io.BytesIO()
                                im.convert("RGB").save(buf, format="JPEG", quality=75)
                                return f"data:image/jpeg;base64,{_b64.b64encode(buf.getvalue()).decode('ascii')}"
                        except Exception:
                            pass
                    # Try cv2 frame extraction
                    vpath = v.get("video_path") or ""
                    if vpath and os.path.exists(vpath):
                        try:
                            import cv2
                            cap = cv2.VideoCapture(vpath)
                            if cap.isOpened():
                                ret, frame = cap.read()
                                if ret:
                                    h, w = frame.shape[:2]
                                    scale = min(400 / max(w, 1), 240 / max(h, 1), 1.0)
                                    if scale < 1:
                                        frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
                                    _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 72])
                                    return f"data:image/jpeg;base64,{_b64.b64encode(buf.tobytes()).decode('ascii')}"
                            cap.release()
                        except Exception:
                            pass

            all_images = st.session_state.get("gallery_images", [])
            for img in all_images:
                if img.get("project_id") == pid:
                    ipath = img.get("image_path") or img.get("url") or ""
                    if ipath and os.path.exists(ipath):
                        try:
                            from PIL import Image as _PILImage
                            import io as _io
                            with _PILImage.open(ipath) as im:
                                im.thumbnail((400, 240), _PILImage.LANCZOS)
                                buf = _io.BytesIO()
                                im.convert("RGB").save(buf, format="JPEG", quality=75)
                                return f"data:image/jpeg;base64,{_b64.b64encode(buf.getvalue()).decode('ascii')}"
                        except Exception:
                            pass
                    elif ipath and ipath.startswith("http"):
                        return ipath
            return ""

        # ── Helper: get last modified date ──
        def _get_project_last_modified(pid):
            """Return the most recent created_at from gallery items for this project."""
            latest = ""
            for coll in ["gallery_videos", "gallery_images"]:
                for item in st.session_state.get(coll, []):
                    if item.get("project_id") == pid:
                        ca = item.get("created_at", "")
                        if ca > latest:
                            latest = ca
            return latest

        def _get_project_spent(pid):
            """Sum estimated_cost from all gallery items for this project."""
            total = 0.0
            for coll in ["gallery_videos", "gallery_images"]:
                for item in st.session_state.get(coll, []):
                    if item.get("project_id") == pid:
                        total += item.get("estimated_cost", 0.0)
            return total

        # ── Build project cards list (thumbnail + metadata for HTML grid) ──
        cards = []
        for proj in project_list:
            pid = proj["id"]
            pname = proj["name"]
            is_active = (pid == active_id)
            thumb = _get_project_thumbnail(pid)
            created_raw = proj.get("created_at", "") or ""
            created_disp = created_raw[:16].replace("T", " ") if created_raw else "—"
            last_mod = _get_project_last_modified(pid)
            last_disp = last_mod[:16].replace("T", " ") if last_mod else "—"
            _spent = _get_project_spent(pid)
            _spent_str = f"${_spent:.2f}" if _spent >= 0.01 else "$0.00"
            cards.append({
                "id": pid,
                "name": pname,
                "thumb": thumb,
                "created": created_disp,
                "last_mod": last_disp,
                "is_active": is_active,
                "spent": _spent_str,
            })

        _proj_pick_key = "proj_pick_act"

        def _on_proj_pick_change():
            raw = (st.session_state.get(_proj_pick_key) or "").strip()
            if not raw:
                return
            st.session_state[_proj_pick_key] = ""
            pid = raw.split("|")[0].strip()
            prev_pid = st.session_state.get("active_project_id")
            pd = load_projects()
            for p in pd.get("projects", []):
                if p["id"] == pid:
                    pd["active_project_id"] = pid
                    save_projects(pd)
                    st.session_state.active_project_id = pid
                    st.session_state.active_project_name = p["name"]
                    if pid != prev_pid:
                        if prev_pid:
                            _save_project_console_settings(prev_pid)
                        _clear_console_prompts_for_project_change()
                        _load_project_console_settings(pid)
                    return

        _col_main, _col_side = st.columns([4, 1], gap="large")

        with _col_side:
            st.markdown(
                '<p style="color:#9E9E8A;font-size:0.75rem;font-weight:600;letter-spacing:0.08em;'
                'margin:0 0 8px;">NEW PROJECT</p>',
                unsafe_allow_html=True,
            )
            new_proj_name = st.text_input(
                "Project name",
                key="new_project_name_input",
                label_visibility="collapsed",
                placeholder="Project name...",
            )
            if st.button("NEW PROJECT", key="create_project_btn", use_container_width=True):
                name = (new_proj_name or "").strip()
                proj_data = load_projects()
                plist = proj_data.get("projects", [])
                if not name:
                    st.warning("Enter a project name.")
                elif any(p["name"].lower() == name.lower() for p in plist):
                    st.warning(f"Project '{name}' already exists.")
                else:
                    new_id = f"proj_{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(100, 999)}"
                    new_proj = {
                        "id": new_id,
                        "name": name,
                        "description": "",
                        "created_at": datetime.now().isoformat(),
                    }
                    proj_data["projects"].append(new_proj)
                    proj_data["active_project_id"] = new_id
                    save_projects(proj_data)
                    st.session_state.active_project_id = new_id
                    st.session_state.active_project_name = name
                    _clear_console_prompts_for_project_change()
                    st.toast(f"Created & activated: {name}")
                    st.rerun()

            st.markdown(
                '<hr style="border:none;border-top:1px solid #2a2a28;margin:16px 0;">',
                unsafe_allow_html=True,
            )
            if st.button(
                "DELETE",
                key="proj_delete_active_btn",
                use_container_width=True,
            ):
                pd = load_projects()
                aid = st.session_state.get("active_project_id")
                if not aid:
                    st.toast("Seleziona un progetto nella griglia, poi usa DELETE.")
                else:
                    pd["projects"] = [p for p in pd.get("projects", []) if p["id"] != aid]
                    if pd.get("active_project_id") == aid:
                        pd["active_project_id"] = None
                    save_projects(pd)
                    st.session_state.active_project_id = None
                    st.session_state.active_project_name = "All Projects"
                    _clear_console_prompts_for_project_change()
                    st.toast("Project deleted.")
                    st.rerun()

            st.markdown(
                '<hr style="border:none;border-top:1px solid #2a2a28;margin:16px 0;">',
                unsafe_allow_html=True,
            )
            _is_all = st.session_state.get("active_project_id") is None
            _all_lbl = "ALL PROJECTS" + (" ✓" if _is_all else "")
            if st.button(_all_lbl, key="select_all_projects", use_container_width=True):
                pd = load_projects()
                pd["active_project_id"] = None
                save_projects(pd)
                if st.session_state.get("active_project_id") is not None:
                    _clear_console_prompts_for_project_change()
                st.session_state.active_project_id = None
                st.session_state.active_project_name = "All Projects"
                st.toast("Switched to: All Projects")
                st.rerun()

        with _col_main:
            st.text_input(
                "proj_pick_bridge",
                key=_proj_pick_key,
                on_change=_on_proj_pick_change,
                label_visibility="collapsed",
            )

            if not cards:
                st.info("No projects yet. Use **NEW PROJECT** in the sidebar to create one.")
            else:
                COLS = 4
                cards_html_parts = []
                for c in cards:
                    _cname = _html_stdlib.escape(c["name"])
                    _thumb = (c["thumb"] or "").replace('"', "&quot;")
                    bcol = "#FFEB3B" if c["is_active"] else "transparent"
                    init = _html_stdlib.escape(c["name"][:2].upper())
                    _cr = _html_stdlib.escape(c["created"])
                    _lm = _html_stdlib.escape(c["last_mod"])
                    _safe_id = c["id"].replace("\\", "\\\\").replace("'", "\\'")
                    if c["thumb"]:
                        thumb_block = (
                            f'<img src="{_thumb}" style="width:100%;height:100%;object-fit:cover;display:block;" '
                            f'draggable="false" alt=""/>'
                        )
                    else:
                        thumb_block = (
                            f'<span style="color:#3a3a38;font-size:1.6rem;font-weight:300;'
                            f'font-family:Open Sans,sans-serif;">{init}</span>'
                        )
                    _spent_val = _html_stdlib.escape(c["spent"])
                    cards_html_parts.append(
                        f'''
                        <div class="proj-cell" onclick="projPick('{_safe_id}')">
                            <div class="proj-thumb" style="border-color:{bcol};">{thumb_block}</div>
                            <div class="proj-title">{_cname}</div>
                            <div class="proj-meta">Created: {_cr}</div>
                            <div class="proj-meta">Last modified: {_lm}</div>
                            <div class="proj-spent">Spent: {_spent_val}</div>
                        </div>'''
                    )
                cards_html = "".join(cards_html_parts)
                nrows = (len(cards) + COLS - 1) // COLS
                grid_h = max(420, nrows * 210)

                proj_grid_html = f'''
                <style>
                    * {{ margin:0; padding:0; box-sizing:border-box; }}
                    body {{ background:transparent; font-family:Open Sans,sans-serif; }}
                    .proj-grid {{
                        display:grid;
                        grid-template-columns:repeat({COLS}, minmax(0, 1fr));
                        gap:14px;
                        padding:4px;
                    }}
                    .proj-cell {{ cursor:pointer; }}
                    .proj-thumb {{
                        position:relative;
                        border:2px solid transparent;
                        border-radius:10px;
                        overflow:hidden;
                        aspect-ratio:16/9;
                        background:#111110;
                        margin-bottom:6px;
                        display:flex;
                        align-items:center;
                        justify-content:center;
                        transition:border-color 0.15s ease;
                    }}
                    .proj-cell:hover .proj-thumb {{ border-color:rgba(255,235,59,0.45) !important; }}
                    .proj-title {{
                        color:#f0ece4;
                        font-size:0.78rem;
                        font-weight:600;
                        margin:0 0 4px;
                        line-height:1.25;
                        word-break:break-word;
                    }}
                    .proj-meta {{
                        color:#7a7a6e;
                        font-size:0.62rem;
                        line-height:1.35;
                        margin:0;
                    }}
                    .proj-spent {{
                        color:#FFEB3B;
                        font-size:0.68rem;
                        font-weight:700;
                        line-height:1.35;
                        margin:2px 0 0;
                        font-family:Open Sans,sans-serif;
                    }}
                </style>
                <div class="proj-grid">{cards_html}</div>
                <script>
                    function projPick(pid) {{
                        if (!pid) return;
                        var inp = window.parent.document.querySelector(
                            'input[aria-label="proj_pick_bridge"]'
                        );
                        if (!inp) return;
                        var ns = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value'
                        ).set;
                        var payload = pid + '|' + Date.now();
                        ns.call(inp, payload);
                        inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        try {{
                            inp.dispatchEvent(new InputEvent('input', {{
                                bubbles: true, inputType: 'insertFromPaste', data: payload
                            }}));
                        }} catch (e) {{}}
                        try {{ inp.focus({{ preventScroll: true }}); }} catch (e2) {{}}
                        try {{ inp.blur(); }} catch (e3) {{}}
                    }}
                </script>'''

                components.html(proj_grid_html, height=grid_h, scrolling=False)
    elif st.session_state.get("active_page") == "assets":
        render_assets_page()

    elif st.session_state.get("active_page") == "references":
        render_references_page()

    elif st.session_state.get("active_page") == "storyboard":
        if "sbi_nav" not in st.session_state:
            st.session_state.sbi_nav = "Storyboard"
        elif st.session_state.sbi_nav not in ("Console", "Projects", "Gallery", "Assets", "References", "Storyboard", "Editing"):
            st.session_state.sbi_nav = "Storyboard"

        def _on_sbi_nav_change():
            val = st.session_state.sbi_nav
            if val == "Console":
                st.session_state.sbi_nav = "Storyboard"
                st.session_state["_console_was_away"] = True
                st.session_state.active_page = "console"
            elif val == "Projects":
                st.session_state.sbi_nav = "Storyboard"
                st.session_state.active_page = "projects"
            elif val == "Gallery":
                st.session_state.sbi_nav = "Storyboard"
                st.session_state.active_page = "gallery"
            elif val == "Assets":
                st.session_state.sbi_nav = "Storyboard"
                st.session_state.active_page = "assets"
            elif val == "References":
                st.session_state.sbi_nav = "Storyboard"
                st.session_state.active_page = "references"
            elif val == "Editing":
                st.session_state.sbi_nav = "Storyboard"
                st.session_state.active_page = "editing"

        # "Storyboard" per primo: un reset sporadico del radio non seleziona "Console" → main page
        _SBI_NAV_ORDER = ["Storyboard", "Console", "Projects", "Gallery", "Assets", "References", "Editing"]
        _sbi_nav_col, _sbi_proj_col = st.columns([4, 1])
        with _sbi_nav_col:
            st.radio(
                "sbi_nav_label",
                _SBI_NAV_ORDER,
                horizontal=True,
                key="sbi_nav",
                on_change=_on_sbi_nav_change,
                label_visibility="collapsed",
            )
        with _sbi_proj_col:
            _render_project_name_inline_right()

        _sb_main, _sb_side = st.columns([4, 1], gap="large")
        with _sb_side:
            _render_storyboard_projects_sidebar()
        with _sb_main:
            _render_storyboard_save_load("sbi", use_projects_layout=True)

    elif st.session_state.get("active_page") == "editing":
        if "sbv_nav" not in st.session_state:
            st.session_state.sbv_nav = "Editing"
        elif st.session_state.sbv_nav not in ("Console", "Projects", "Gallery", "Assets", "References", "Storyboard", "Editing"):
            st.session_state.sbv_nav = "Editing"

        def _on_sbv_nav_change():
            val = st.session_state.sbv_nav
            if val == "Console":
                st.session_state.sbv_nav = "Editing"
                st.session_state["_console_was_away"] = True
                st.session_state.active_page = "console"
            elif val == "Projects":
                st.session_state.sbv_nav = "Editing"
                st.session_state.active_page = "projects"
            elif val == "Gallery":
                st.session_state.sbv_nav = "Editing"
                st.session_state.active_page = "gallery"
            elif val == "Assets":
                st.session_state.sbv_nav = "Editing"
                st.session_state.active_page = "assets"
            elif val == "References":
                st.session_state.sbv_nav = "Editing"
                st.session_state.active_page = "references"
            elif val == "Storyboard":
                st.session_state.sbv_nav = "Editing"
                st.session_state.active_page = "storyboard"

        _SBV_NAV_ORDER = ["Editing", "Console", "Projects", "Gallery", "Assets", "References", "Storyboard"]
        _sbv_nav_col, _sbv_proj_col = st.columns([4, 1])
        with _sbv_nav_col:
            st.radio(
                "sbv_nav_label",
                _SBV_NAV_ORDER,
                horizontal=True,
                key="sbv_nav",
                on_change=_on_sbv_nav_change,
                label_visibility="collapsed",
            )
        with _sbv_proj_col:
            _render_project_name_inline_right()

        _ed_main, _ed_side = st.columns([4, 1], gap="large")
        with _ed_side:
            _render_editing_projects_sidebar()
        with _ed_main:
            _render_storyboard_save_load("sbv", use_projects_layout=True)

    else:
        model_sel = st.session_state.get("model_selector", "SEEDANCE 2.0")
        total_files = num_imgs = num_vids = num_auds = 0
        action_desc = ""
        shots_data = []
        s2_workflow = "Standard Generation"
        image_usage = "auto"
        duration = 15
        temperature = 0.5
        resolution = "1080p"
        aspect_ratio = "16:9"
        gen_mode = "Standard (Online)"
        gen_audio = False
        audio_details_dict = {}
        s2_images = s2_videos = s2_audio = []
        sd_refs = []
        sd_prompt = ""
        sd_style = "None (Raw Prompt)"
        sd_ar = "Smart"
        sd_resolution = "2K"
        sd_shot_type = sd_mood = sd_period = sd_camera = sd_lenses = sd_film_stock = sd_sensor = None
        sd_lighting_source = sd_lighting_direction = sd_lighting_type = None
        preview_clicked = False
        json_clicked = False

        # Save a fresh snapshot at the top of every Console render.
        # Catches in-Console state changes (e.g. model flip) so the other
        # model's params survive when the user flips back.
        _save_console_param_snapshot()
        # Also persist to the active project's JSON file (per-project memory).
        _save_project_console_settings()

        if st.session_state.get("_console_reset_pending"):
            del st.session_state["_console_reset_pending"]
            # Wipe active project's persistent settings file
            _delete_project_console_settings(st.session_state.get("active_project_id"))
            _reset_keys = [
                "action_desc_s2", "sd_prompt_input",
                "s2_opt_prompt", "s2_raw_prompt",
                "sd_opt_prompt", "sd_raw_prompt",
                "json_preview", "_json_dict",
                "s2_last_result", "sd_last_result",
                "show_generate_button", "_preview_feedback",
                "_do_preview_s2", "_do_preview_sd",
                "_do_generate_s2", "_do_generate_sd",
                "canvas_prompt_editor",
                "video_resolution", "video_aspect_ratio", "common_duration", "gen_mode_selector", "s2_gen_mode",
                "s2_workflow",
                "common_temperature",
                "common_num_variations",
                "enable_audio",
                "sd_optimize", "sd_resolution", "sd_ar_select",
                "_cached_s2_images", "_cached_s2_videos", "_cached_s2_audio",
                "_cached_sd_refs",
                "_cached_s2_first_frame", "_cached_s2_last_frame", "_cached_s2_first_only",
                "_s2_img_saved_names", "_s2_vid_saved_names", "_s2_aud_saved_names",
                "_sd_ref_saved_names",
                "_console_ref_tag_map",
                "_persist_s2_assets_images",
                "_persist_s2_assets_videos",
                "_persist_s2_assets_audio",
                "_persist_s2_assets_first_frame",
                "_persist_s2_assets_last_frame",
                "_persist_s2_assets_first_only",
                "_persist_sd_assets_refs",
                "_console_was_away",
            ]
            for k in _reset_keys:
                st.session_state.pop(k, None)
            for i in range(10):
                st.session_state.pop(f"seed_input_{i}", None)
            # Clear in-memory snapshot too, so restore doesn't repopulate
            st.session_state["_console_param_snapshot"] = {}
            st.rerun()

        left_col, center_col, right_col = st.columns([1, 2, 1], vertical_alignment="top")

        with left_col:
            with st.expander("MODELS", expanded=False):
                st.radio("Model", ["SEEDANCE 2.0", "SEEDREAM 5.0"], key="model_selector", label_visibility="collapsed", horizontal=False)

            with st.expander("WORKFLOW", expanded=False):
                if model_sel == "SEEDANCE 2.0":
                    s2_entry_point = st.radio("Entry Point", ["First Frame", "First and Last Frames", "All-in-One Reference"], key="s2_entry_point")
                    is_first_last = s2_entry_point == "First and Last Frames"
                    is_first_frame = s2_entry_point == "First Frame"
                    if is_first_last:
                        s2_workflow = st.selectbox("Creation Workflow", ["Standard Generation"], key="s2_workflow_fl", disabled=True)
                    elif is_first_frame:
                        s2_workflow = st.selectbox("Creation Workflow", ["Standard Generation"], key="s2_workflow_ff", disabled=True)
                    else:
                        s2_workflow = st.selectbox("Creation Workflow", ["Standard Generation", "Video Extension", "Video Editing"], key="s2_workflow")

                    if is_first_last:
                        # ── First + Last Frame: two separate uploaders ──
                        st.markdown(
                            '<p style="color:#FFEB3B; font-size:0.75rem; font-weight:600; margin:0.5rem 0 0.25rem; '
                            'letter-spacing:0.08em; text-transform:uppercase;">First Frame</p>',
                            unsafe_allow_html=True,
                        )
                        _s2_ff_raw = st.file_uploader(
                            "Opening frame (1 image)",
                            type=['png', 'jpg', 'jpeg'],
                            accept_multiple_files=False,
                            key="s2_first_frame",
                            help="PNG, JPG, JPEG",
                        )
                        if _s2_ff_raw is not None:
                            _s2_ff_raw = CachedUploadedFile(_s2_ff_raw.name, _s2_ff_raw.getvalue(), _s2_ff_raw.type)
                            st.session_state["_persisted_img_1"] = _s2_ff_raw
                        elif "_persisted_img_1" in st.session_state:
                            _s2_ff_raw = st.session_state["_persisted_img_1"]
                        if _s2_ff_raw:
                            st.session_state["_cached_s2_first_frame"] = CachedUploadedFile(
                                _s2_ff_raw.name, _s2_ff_raw.getvalue(), _s2_ff_raw.type
                            )
                        s2_first_frame = _s2_ff_raw if _s2_ff_raw else st.session_state.get("_cached_s2_first_frame")
                        if not _s2_ff_raw and s2_first_frame:
                            st.caption(f"Loaded from session: {s2_first_frame.name}")
                        _cat = load_asset_catalog()
                        _active_proj = get_active_project_id()
                        if _active_proj:
                            _cat = [a for a in _cat if a.get("project_id") == _active_proj]
                        _img_assets = [a for a in _cat if a["type"] == "image"]
                        if _img_assets and not s2_first_frame:
                            _ff_opts = ["(none)"] + [f"{a['name']} ({a['size_str']})" for a in _img_assets]
                            _ff_default_idx = 0
                            _ff_persist_val = st.session_state.get("_persist_s2_assets_first_frame")
                            if _ff_persist_val and _ff_persist_val in _ff_opts:
                                _ff_default_idx = _ff_opts.index(_ff_persist_val)
                            _ff_sel = st.selectbox("Or pick from Assets", _ff_opts,
                                                   index=_ff_default_idx,
                                                   key="s2_assets_first_frame", label_visibility="collapsed")
                            if _ff_sel != "(none)":
                                st.session_state["_persist_s2_assets_first_frame"] = _ff_sel
                                _a = next((x for x in _img_assets if f"{x['name']} ({x['size_str']})" == _ff_sel), None)
                                if _a and os.path.exists(_a["path"]):
                                    s2_first_frame = AssetFile(_a["path"], _a["name"], _a["mime"])
                            else:
                                st.session_state.pop("_persist_s2_assets_first_frame", None)
                        st.markdown(
                            '<p style="color:#FF9800; font-size:0.75rem; font-weight:600; margin:0.5rem 0 0.25rem; '
                            'letter-spacing:0.08em; text-transform:uppercase;">Last Frame</p>',
                            unsafe_allow_html=True,
                        )
                        _s2_lf_raw = st.file_uploader(
                            "Closing frame (1 image)",
                            type=['png', 'jpg', 'jpeg'],
                            accept_multiple_files=False,
                            key="s2_last_frame",
                            help="PNG, JPG, JPEG",
                        )
                        if _s2_lf_raw is not None:
                            _s2_lf_raw = CachedUploadedFile(_s2_lf_raw.name, _s2_lf_raw.getvalue(), _s2_lf_raw.type)
                            st.session_state["_persisted_img_2"] = _s2_lf_raw
                        elif "_persisted_img_2" in st.session_state:
                            _s2_lf_raw = st.session_state["_persisted_img_2"]
                        if _s2_lf_raw:
                            st.session_state["_cached_s2_last_frame"] = CachedUploadedFile(
                                _s2_lf_raw.name, _s2_lf_raw.getvalue(), _s2_lf_raw.type
                            )
                        s2_last_frame = _s2_lf_raw if _s2_lf_raw else st.session_state.get("_cached_s2_last_frame")
                        if not _s2_lf_raw and s2_last_frame:
                            st.caption(f"Loaded from session: {s2_last_frame.name}")
                        if _img_assets and not s2_last_frame:
                            _lf_opts = ["(none)"] + [f"{a['name']} ({a['size_str']})" for a in _img_assets]
                            _lf_default_idx = 0
                            _lf_persist_val = st.session_state.get("_persist_s2_assets_last_frame")
                            if _lf_persist_val and _lf_persist_val in _lf_opts:
                                _lf_default_idx = _lf_opts.index(_lf_persist_val)
                            _lf_sel = st.selectbox("Or pick from Assets", _lf_opts,
                                                   index=_lf_default_idx,
                                                   key="s2_assets_last_frame", label_visibility="collapsed")
                            if _lf_sel != "(none)":
                                st.session_state["_persist_s2_assets_last_frame"] = _lf_sel
                                _a = next((x for x in _img_assets if f"{x['name']} ({x['size_str']})" == _lf_sel), None)
                                if _a and os.path.exists(_a["path"]):
                                    s2_last_frame = AssetFile(_a["path"], _a["name"], _a["mime"])
                            else:
                                st.session_state.pop("_persist_s2_assets_last_frame", None)
                        # Build images list: first frame FIRST, last frame SECOND (order matters for API)
                        s2_images = []
                        if s2_first_frame:
                            s2_images.append(s2_first_frame)
                        if s2_last_frame:
                            s2_images.append(s2_last_frame)
                        s2_videos = []
                        s2_audio = []
                        num_imgs = len(s2_images)
                        num_vids = 0
                        num_auds = 0
                        total_files = num_imgs

                        # Force image_usage — no selectbox shown
                        image_usage = "first_last_frame"

                        if s2_first_frame and not s2_last_frame:
                            st.warning("Upload a Last Frame to use first + last frame mode.")
                        elif not s2_first_frame and s2_last_frame:
                            st.warning("Upload a First Frame to use first + last frame mode.")

                    elif is_first_frame:
                        st.markdown(
                            '<p style="color:#FFEB3B; font-size:0.75rem; font-weight:600; margin:0.5rem 0 0.25rem; '
                            'letter-spacing:0.08em; text-transform:uppercase;">First Frame</p>',
                            unsafe_allow_html=True,
                        )
                        _s2_fo_raw = st.file_uploader(
                            "Opening frame (1 image)",
                            type=['png', 'jpg', 'jpeg'],
                            accept_multiple_files=False,
                            key="s2_first_only",
                            help="PNG, JPG, JPEG",
                        )
                        if _s2_fo_raw is not None:
                            _s2_fo_raw = CachedUploadedFile(_s2_fo_raw.name, _s2_fo_raw.getvalue(), _s2_fo_raw.type)
                            st.session_state["_persisted_img_3"] = _s2_fo_raw
                        elif "_persisted_img_3" in st.session_state:
                            _s2_fo_raw = st.session_state["_persisted_img_3"]
                        if _s2_fo_raw:
                            st.session_state["_cached_s2_first_only"] = CachedUploadedFile(
                                _s2_fo_raw.name, _s2_fo_raw.getvalue(), _s2_fo_raw.type
                            )
                        s2_first_only = _s2_fo_raw if _s2_fo_raw else st.session_state.get("_cached_s2_first_only")
                        if not _s2_fo_raw and s2_first_only:
                            st.caption(f"Loaded from session: {s2_first_only.name}")
                        _cat = load_asset_catalog()
                        _active_proj = get_active_project_id()
                        if _active_proj:
                            _cat = [a for a in _cat if a.get("project_id") == _active_proj]
                        _img_assets = [a for a in _cat if a["type"] == "image"]
                        if _img_assets and not s2_first_only:
                            _fo_opts = ["(none)"] + [f"{a['name']} ({a['size_str']})" for a in _img_assets]
                            _fo_default_idx = 0
                            _fo_persist_val = st.session_state.get("_persist_s2_assets_first_only")
                            if _fo_persist_val and _fo_persist_val in _fo_opts:
                                _fo_default_idx = _fo_opts.index(_fo_persist_val)
                            _fo_sel = st.selectbox("Or pick from Assets", _fo_opts,
                                                   index=_fo_default_idx,
                                                   key="s2_assets_first_only", label_visibility="collapsed")
                            if _fo_sel != "(none)":
                                st.session_state["_persist_s2_assets_first_only"] = _fo_sel
                                _a = next((x for x in _img_assets if f"{x['name']} ({x['size_str']})" == _fo_sel), None)
                                if _a and os.path.exists(_a["path"]):
                                    s2_first_only = AssetFile(_a["path"], _a["name"], _a["mime"])
                            else:
                                st.session_state.pop("_persist_s2_assets_first_only", None)
                        s2_images = [s2_first_only] if s2_first_only else []
                        s2_videos = []
                        s2_audio = []
                        num_imgs = len(s2_images)
                        num_vids = 0
                        num_auds = 0
                        total_files = num_imgs
                        image_usage = "first_frame"
                    else:
                        # ── All-in-One Reference: original multi-file uploaders ──
                        st.markdown(
                            '<p style="color:#00E5CC; font-size:0.8rem; font-weight:600; letter-spacing:0.1em; '
                            'margin:0.75rem 0 0.25rem; text-transform:uppercase;">References</p>',
                            unsafe_allow_html=True,
                        )
                        _s2_img_raw = st.file_uploader(
                            "Images (Max 9)",
                            type=['png', 'jpg', 'jpeg'],
                            accept_multiple_files=True,
                            key="s2_images",
                            help="PNG, JPG, JPEG",
                        )
                        if _s2_img_raw:
                            _s2_img_list = [
                                CachedUploadedFile(f.name, f.getvalue(), f.type)
                                for f in _materialize_multi_file_upload(_s2_img_raw)
                            ]
                            st.session_state["_persisted_img_4"] = _s2_img_list
                        elif "_persisted_img_4" in st.session_state:
                            _s2_img_list = list(st.session_state["_persisted_img_4"])
                        else:
                            _s2_img_list = []
                        if _s2_img_list:
                            st.session_state["_cached_s2_images"] = [
                                CachedUploadedFile(f.name, f.getvalue(), f.type) for f in _s2_img_list
                            ]
                            if "_s2_img_saved_names" not in st.session_state:
                                st.session_state["_s2_img_saved_names"] = set()
                            for f in _s2_img_list:
                                if f.name not in st.session_state["_s2_img_saved_names"]:
                                    _result = add_to_assets(uploaded_file=f)
                                    if _result:
                                        st.session_state["_s2_img_saved_names"].add(f.name)
                        s2_images = _s2_img_list if _s2_img_list else list(st.session_state.get("_cached_s2_images") or [])
                        if not _s2_img_list and s2_images:
                            st.caption(f"Loaded from session: {', '.join(f.name for f in s2_images)}")
                        # From Assets — images
                        _cat = load_asset_catalog()
                        _active_proj = get_active_project_id()
                        if _active_proj:
                            _cat = [a for a in _cat if a.get("project_id") == _active_proj]
                        _img_assets = [a for a in _cat if a["type"] == "image"]
                        if _img_assets:
                            _img_opts = {f"{a['name']} ({a['size_str']})": a["id"] for a in _img_assets}
                            _img_selected = st.multiselect(
                                "From Assets (images)",
                                options=list(_img_opts.keys()),
                                default=[x for x in st.session_state.get("_persist_s2_assets_images", []) if x in _img_opts],
                                key="s2_assets_images",
                                label_visibility="collapsed",
                                placeholder="＋ Pick images from Assets..."
                            )
                            if _img_selected:
                                st.session_state["_persist_s2_assets_images"] = _img_selected
                            elif not _img_selected and "s2_assets_images" in st.session_state:
                                st.session_state.pop("_persist_s2_assets_images", None)
                            _img_asset_files = []
                            for _lab in _img_selected:
                                _aid = _img_opts[_lab]
                                _a = next((x for x in _img_assets if x["id"] == _aid), None)
                                if _a and os.path.exists(_a["path"]):
                                    _img_asset_files.append(AssetFile(_a["path"], _a["name"], _a["mime"]))
                            s2_images = list(s2_images or []) + _img_asset_files
                        _s2_vid_raw = st.file_uploader(
                            "Videos (Max 3)",
                            type=['mp4', 'mov', 'mpeg4'],
                            accept_multiple_files=True,
                            key="s2_videos",
                            help="MP4, MOV, MPEG4",
                        )
                        if _s2_vid_raw:
                            _s2_vid_list = [
                                CachedUploadedFile(f.name, f.getvalue(), f.type)
                                for f in _materialize_multi_file_upload(_s2_vid_raw)
                            ]
                            st.session_state["_persisted_vid_1"] = _s2_vid_list
                        elif "_persisted_vid_1" in st.session_state:
                            _s2_vid_list = list(st.session_state["_persisted_vid_1"])
                        else:
                            _s2_vid_list = []
                        if _s2_vid_list:
                            st.session_state["_cached_s2_videos"] = [
                                CachedUploadedFile(f.name, f.getvalue(), f.type) for f in _s2_vid_list
                            ]
                            if "_s2_vid_saved_names" not in st.session_state:
                                st.session_state["_s2_vid_saved_names"] = set()
                            for f in _s2_vid_list:
                                if f.name not in st.session_state["_s2_vid_saved_names"]:
                                    _result = add_to_assets(uploaded_file=f)
                                    if _result:
                                        st.session_state["_s2_vid_saved_names"].add(f.name)
                        s2_videos = _s2_vid_list if _s2_vid_list else list(st.session_state.get("_cached_s2_videos") or [])
                        if not _s2_vid_list and s2_videos:
                            st.caption(f"Loaded from session: {', '.join(f.name for f in s2_videos)}")
                        # From Assets — videos
                        _vid_assets = [a for a in _cat if a["type"] == "video"]
                        if _vid_assets:
                            _vid_opts = {f"{a['name']} ({a['size_str']})": a["id"] for a in _vid_assets}
                            _vid_selected = st.multiselect(
                                "From Assets (videos)",
                                options=list(_vid_opts.keys()),
                                default=[x for x in st.session_state.get("_persist_s2_assets_videos", []) if x in _vid_opts],
                                key="s2_assets_videos",
                                label_visibility="collapsed",
                                placeholder="＋ Pick videos from Assets..."
                            )
                            if _vid_selected:
                                st.session_state["_persist_s2_assets_videos"] = _vid_selected
                            elif not _vid_selected and "s2_assets_videos" in st.session_state:
                                st.session_state.pop("_persist_s2_assets_videos", None)
                            _vid_asset_files = []
                            for _lab in _vid_selected:
                                _aid = _vid_opts[_lab]
                                _a = next((x for x in _vid_assets if x["id"] == _aid), None)
                                if _a and os.path.exists(_a["path"]):
                                    _vid_asset_files.append(AssetFile(_a["path"], _a["name"], _a["mime"]))
                            s2_videos = list(s2_videos or []) + _vid_asset_files
                        _s2_aud_raw = st.file_uploader(
                            "Audio (Max 3)",
                            type=['mp3'],
                            accept_multiple_files=True,
                            key="s2_audio",
                            help="MP3",
                        )
                        if _s2_aud_raw:
                            _s2_aud_list = [
                                CachedUploadedFile(f.name, f.getvalue(), f.type)
                                for f in _materialize_multi_file_upload(_s2_aud_raw)
                            ]
                            st.session_state["_persisted_aud_1"] = _s2_aud_list
                        elif "_persisted_aud_1" in st.session_state:
                            _s2_aud_list = list(st.session_state["_persisted_aud_1"])
                        else:
                            _s2_aud_list = []
                        if _s2_aud_list:
                            st.session_state["_cached_s2_audio"] = [
                                CachedUploadedFile(f.name, f.getvalue(), f.type) for f in _s2_aud_list
                            ]
                            if "_s2_aud_saved_names" not in st.session_state:
                                st.session_state["_s2_aud_saved_names"] = set()
                            for f in _s2_aud_list:
                                if f.name not in st.session_state["_s2_aud_saved_names"]:
                                    _result = add_to_assets(uploaded_file=f)
                                    if _result:
                                        st.session_state["_s2_aud_saved_names"].add(f.name)
                        s2_audio = _s2_aud_list if _s2_aud_list else list(st.session_state.get("_cached_s2_audio") or [])
                        if not _s2_aud_list and s2_audio:
                            st.caption(f"Loaded from session: {', '.join(f.name for f in s2_audio)}")
                        # From Assets — audio
                        _aud_assets = [a for a in _cat if a["type"] == "audio"]
                        if _aud_assets:
                            _aud_opts = {f"{a['name']} ({a['size_str']})": a["id"] for a in _aud_assets}
                            _aud_selected = st.multiselect(
                                "From Assets (audio)",
                                options=list(_aud_opts.keys()),
                                default=[x for x in st.session_state.get("_persist_s2_assets_audio", []) if x in _aud_opts],
                                key="s2_assets_audio",
                                label_visibility="collapsed",
                                placeholder="＋ Pick audio from Assets..."
                            )
                            if _aud_selected:
                                st.session_state["_persist_s2_assets_audio"] = _aud_selected
                            elif not _aud_selected and "s2_assets_audio" in st.session_state:
                                st.session_state.pop("_persist_s2_assets_audio", None)
                            _aud_asset_files = []
                            for _lab in _aud_selected:
                                _aid = _aud_opts[_lab]
                                _a = next((x for x in _aud_assets if x["id"] == _aid), None)
                                if _a and os.path.exists(_a["path"]):
                                    _aud_asset_files.append(AssetFile(_a["path"], _a["name"], _a["mime"]))
                            s2_audio = list(s2_audio or []) + _aud_asset_files
                        num_imgs = len(s2_images) if s2_images else 0
                        num_vids = len(s2_videos) if s2_videos else 0
                        num_auds = len(s2_audio) if s2_audio else 0
                        total_files = num_imgs + num_vids + num_auds

                        # Image usage selectbox: only show for All-in-One when images present
                        if num_imgs > 0 and "Video Extension" not in st.session_state.get("s2_workflow", ""):
                            image_usage = st.selectbox(
                                "Image usage",
                                ["auto", "first_frame", "reference_only", "composite"],
                                format_func=lambda x: {"auto": "Auto", "first_frame": "First frame", "reference_only": "Reference only", "composite": "Composite"}[x],
                                key="s2_image_usage",
                            )

                    # Safety net: all-in-one only — if uploads are empty on rerun, restore from session cache
                    if not is_first_last and not is_first_frame:
                        if not s2_videos and st.session_state.get("_cached_s2_videos"):
                            s2_videos = list(st.session_state.get("_cached_s2_videos"))
                        if not s2_images and st.session_state.get("_cached_s2_images"):
                            s2_images = list(st.session_state.get("_cached_s2_images"))
                        if not s2_audio and st.session_state.get("_cached_s2_audio"):
                            s2_audio = list(st.session_state.get("_cached_s2_audio"))
                        num_imgs = len(s2_images) if s2_images else 0
                        num_vids = len(s2_videos) if s2_videos else 0
                        num_auds = len(s2_audio) if s2_audio else 0
                        total_files = num_imgs + num_vids + num_auds

                    # ── Asset tags info (after uploaders + From Assets) ──
                    if total_files > 0:
                        tag_list = [f"@Image {i+1}" for i in range(num_imgs)] + [f"@Video {i+1}" for i in range(num_vids)] + [f"@Audio {i+1}" for i in range(num_auds)]
                        _tag_details = []
                        _all_console_files = list(s2_images or []) + list(s2_videos or []) + list(s2_audio or [])
                        for _ti, _tname in enumerate(tag_list):
                            if _ti < len(_all_console_files):
                                _fn = getattr(_all_console_files[_ti], "name", "?")[:25]
                                _tag_details.append(f"{_tname} = {_fn}")
                            else:
                                _tag_details.append(_tname)
                        st.info(f"**Tags:** {' · '.join(_tag_details)}")
                        if total_files > 12:
                            st.warning(f"Seedance 2.0 limit exceeded: max 12 total files (current: {total_files}).")
                        if num_imgs > 9:
                            st.warning(f"Seedance 2.0 limit exceeded: max 9 images (current: {num_imgs}).")
                        if num_vids > 3:
                            st.warning(f"Seedance 2.0 limit exceeded: max 3 videos (current: {num_vids}).")
                        if num_auds > 3:
                            st.warning(f"Seedance 2.0 limit exceeded: max 3 audio files (current: {num_auds}).")
                    _ref_tag_map = {}
                    if total_files > 0:
                        for _i, _f in enumerate(s2_images or []):
                            _n = getattr(_f, "name", "") or ""
                            if _n:
                                _ref_tag_map[_n] = f"@Image {_i + 1}"
                        for _i, _f in enumerate(s2_videos or []):
                            _n = getattr(_f, "name", "") or ""
                            if _n:
                                _ref_tag_map[_n] = f"@Video {_i + 1}"
                        for _i, _f in enumerate(s2_audio or []):
                            _n = getattr(_f, "name", "") or ""
                            if _n:
                                _ref_tag_map[_n] = f"@Audio {_i + 1}"
                    st.session_state["_console_ref_tag_map"] = _ref_tag_map

                    if num_imgs > 0:
                        btn_cols = st.columns(min(num_imgs, 4))
                        vision_context_list = []
                        for i, img_file in enumerate(s2_images or []):
                            if is_first_last:
                                frame_label = "First Frame" if i == 0 else "Last Frame"
                            else:
                                frame_label = f"@Image {i+1}"
                            with btn_cols[i % 4]:
                                if st.button(f"Analyze {frame_label}", key=f"analyze_btn_{i}"):
                                    with st.spinner(f"Processing {frame_label}..."):
                                        report = analyze_cinematography(img_file, frame_label)
                                        st.session_state[f"vision_report_{i}"] = report
                        for i in range(num_imgs):
                            if f"vision_report_{i}" in st.session_state:
                                with st.expander(f"Report @Image {i+1}", expanded=False):
                                    st.markdown(st.session_state[f"vision_report_{i}"])
                                    vision_context_list.append(st.session_state[f"vision_report_{i}"])
                        st.session_state.vision_context = vision_context_list
                else:
                    _sd_refs_raw = st.file_uploader(
                        "Reference images (Optional)",
                        type=['png', 'jpg', 'jpeg', 'webp'],
                        accept_multiple_files=True,
                        key="sd_refs_upload",
                        help="PNG, JPG, JPEG",
                    )
                    if _sd_refs_raw:
                        _sd_refs_list = [
                            CachedUploadedFile(f.name, f.getvalue(), f.type)
                            for f in _materialize_multi_file_upload(_sd_refs_raw)
                        ]
                        st.session_state["_persisted_img_8"] = _sd_refs_list
                    elif "_persisted_img_8" in st.session_state:
                        _sd_refs_list = list(st.session_state["_persisted_img_8"])
                    else:
                        _sd_refs_list = []
                    if _sd_refs_list:
                        st.session_state["_cached_sd_refs"] = [
                            CachedUploadedFile(f.name, f.getvalue(), f.type) for f in _sd_refs_list
                        ]
                        if "_sd_ref_saved_names" not in st.session_state:
                            st.session_state["_sd_ref_saved_names"] = set()
                        for f in _sd_refs_list:
                            if f.name not in st.session_state["_sd_ref_saved_names"]:
                                _result = add_to_assets(uploaded_file=f)
                                if _result:
                                    st.session_state["_sd_ref_saved_names"].add(f.name)
                    sd_refs = _sd_refs_list if _sd_refs_list else list(st.session_state.get("_cached_sd_refs") or [])
                    if not _sd_refs_list and sd_refs:
                        st.caption(f"Loaded from session: {', '.join(f.name for f in sd_refs)}")
                    _cat = load_asset_catalog()
                    _active_proj = get_active_project_id()
                    if _active_proj:
                        _cat = [a for a in _cat if a.get("project_id") == _active_proj]
                    _img_assets = [a for a in _cat if a["type"] == "image"]
                    if _img_assets:
                        _sd_opts = {f"{a['name']} ({a['size_str']})": a["id"] for a in _img_assets}
                        _sd_sel = st.multiselect("From Assets", options=list(_sd_opts.keys()),
                                                 default=[x for x in st.session_state.get("_persist_sd_assets_refs", []) if x in _sd_opts],
                                                 key="sd_assets_refs", label_visibility="collapsed",
                                                 placeholder="＋ Pick from Assets...")
                        if _sd_sel:
                            st.session_state["_persist_sd_assets_refs"] = _sd_sel
                        elif not _sd_sel and "sd_assets_refs" in st.session_state:
                            st.session_state.pop("_persist_sd_assets_refs", None)
                        _sd_af = []
                        for _lab in _sd_sel:
                            _aid = _sd_opts[_lab]
                            _a = next((x for x in _img_assets if x["id"] == _aid), None)
                            if _a and os.path.exists(_a["path"]):
                                _sd_af.append(AssetFile(_a["path"], _a["name"], _a["mime"]))
                        sd_refs = list(sd_refs or []) + _sd_af
                    sd_style = st.selectbox("Visual Style Preset", ["None (Raw Prompt)", "Cinematic: Kodak Portra 400 (Nostalgic)", "Design: Guochao Neo-Chinese (Red & Gold)", "Artistic: Chinese Origami Figures", "Artistic: Transparent Ice Sculptures", "Design: 2D Pixel Art (Top-Down)", "Design: Abstract Futuristic (Liquid Silver)", "Artistic: Monet Impressionism (Thick Oil)", "Education: Hand-drawn Infographic"], key="sd_style_select", label_visibility="collapsed")
                    # ── Reference tag info (after uploaders + From Assets) ──
                    if sd_refs:
                        st.info(f"Attached {len(sd_refs)} reference image(s).")
                    _sd_ref_tag_map = {}
                    if sd_refs:
                        for _i, _f in enumerate(sd_refs):
                            _n = getattr(_f, "name", "") or ""
                            if _n:
                                _sd_ref_tag_map[_n] = f"@Image {_i + 1}"
                    st.session_state["_console_ref_tag_map"] = _sd_ref_tag_map

            if st.button("PROJECTS", key="top_projects_btn", use_container_width=True):
                _save_console_param_snapshot()
                st.session_state["_console_was_away"] = True
                st.session_state.active_page = "projects"
                st.rerun()

            if st.button("ASSETS", key="top_assets_btn", use_container_width=True):
                _save_console_param_snapshot()
                st.session_state["_console_was_away"] = True
                st.session_state.active_page = "assets"
                st.rerun()

            json_clicked = st.button("JSON", use_container_width=True, key="json_settings_btn")

            if model_sel == "SEEDANCE 2.0":
                preview_clicked = st.button("PREVIEW PROMPT", use_container_width=True, key="preview_prompt_btn")
            else:
                preview_clicked = st.button("PREVIEW PROMPT (Seedream)", use_container_width=True, key="sd_preview_btn")

            if not _STATIC_SERVING_SUPPORTED:
                st.warning(
                    f"Streamlit {_st_version} doesn't support static serving. Upgrade: pip install --upgrade streamlit --break-system-packages"
                )
            elif not _STATIC_SERVING_OK:
                st.warning("Static serving: static/ directory not found. Restart app.")

        with center_col:
            if model_sel == "SEEDANCE 2.0":
                action_desc = st.text_area(" ", placeholder="Describe the scene...", key="action_desc_s2", height=100, label_visibility="collapsed")
            else:
                sd_prompt = st.text_area(" ", placeholder="Describe your vision...", height=100, key="sd_prompt_input", label_visibility="collapsed")
            if st.button("RESET", key="console_reset_btn", use_container_width=True):
                st.session_state["_console_reset_pending"] = True
                st.rerun()

            with st.expander("CINEMATOGRAPHY", expanded=False):
                if model_sel == "SEEDANCE 2.0":
                    shot_tabs = st.tabs(["SHOT 1 (Base)", "SHOT 2 (Optional)", "SHOT 3 (Optional)"])
                    shots_data = []
                    with shot_tabs[0]: shots_data.append(render_shot_panel(1, key_prefix="s"))
                    with shot_tabs[1]:
                        if st.toggle("Enable Shot 2", key="en_s2"):
                            shots_data.append(render_shot_panel(2, key_prefix="s"))
                    with shot_tabs[2]:
                        if st.toggle("Enable Shot 3", key="en_s3"):
                            shots_data.append(render_shot_panel(3, key_prefix="s"))
                else:
                    with st.expander("Shot type", expanded=False):
                        sd_shot_type = st.selectbox("Shot Type", LIST_SHOT_TYPES, key="sd_shot_type")
                    with st.expander("Style & mood", expanded=False):
                        sd_mood = st.selectbox("Mood", LIST_MOODS, key="sd_mood")
                        sd_period = st.selectbox("Period / Era", LIST_PERIODS, key="sd_period")
                    with st.expander("Gear", expanded=False):
                        sd_camera = st.selectbox("Camera", LIST_CAMERAS, key="sd_camera")
                        sd_lenses = st.selectbox("Lenses", LIST_LENSES, key="sd_lenses")
                        sd_film_stock = st.selectbox("Film Stock", LIST_FILM_STOCKS, key="sd_film_stock")
                        sd_sensor = st.selectbox("Sensor", LIST_SENSORS, key="sd_sensor")
                    with st.expander("Lighting", expanded=False):
                        sd_lighting_source = st.selectbox("Lighting Source", LIST_LIGHTING_SOURCE, key="sd_light_src")
                        sd_lighting_direction = st.selectbox("Lighting Direction", LIST_LIGHTING_DIRECTION, key="sd_light_dir")
                        sd_lighting_type = st.selectbox("Lighting Type", LIST_LIGHTING, key="sd_light_type")

            # ══════════════════════════════════════════════
            # CANVAS — 3 states: Preview btn → Prompt → Result
            # ══════════════════════════════════════════════
            has_result = False
            has_prompt = False
            has_json = bool(st.session_state.get("json_preview"))

            if model_sel == "SEEDANCE 2.0":
                has_result = bool(st.session_state.get("s2_last_result"))
                has_prompt = bool(st.session_state.get("s2_opt_prompt", "").strip())
            elif model_sel == "SEEDREAM 5.0":
                has_result = bool(st.session_state.get("sd_last_result"))
                has_prompt = bool(st.session_state.get("sd_opt_prompt", "").strip())

            generate_clicked = False

            if has_result:
                # ── STATE 3: Video/image result ──
                if model_sel == "SEEDANCE 2.0":
                    r = st.session_state.s2_last_result
                    if r.get("video"): st.video(r["video"])
                    _actual_duration = r.get("duration") or r.get("actual_duration") or r.get("video_duration")
                    if _actual_duration is not None:
                        st.caption(f"Actual duration: {_actual_duration}s")
                elif model_sel == "SEEDREAM 5.0":
                    data = st.session_state.sd_last_result
                    r = data.get("result", {})
                    if data.get("batch") and r.get("images"):
                        for im in r["images"]:
                            if not im.get("error"):
                                img_src = im.get("image_path") if im.get("image_path") and os.path.exists(im.get("image_path", "")) else im.get("image_url")
                                if img_src: st.image(img_src, use_container_width=True)
                    elif r.get("image_url"):
                        st.image(r["image_url"], use_container_width=True)
                # Buttons: PREVIEW + GENERATE
                st.markdown('<div class="generate-btn-wrap">', unsafe_allow_html=True)
                if model_sel == "SEEDANCE 2.0":
                    generate_clicked = st.button("GENERATE", type="primary", use_container_width=True, key="s2_production_opt")
                else:
                    generate_clicked = st.button("GENERATE (Seedream)", type="primary", use_container_width=True, key="sd_production_opt")
                st.markdown('</div>', unsafe_allow_html=True)

            elif has_prompt and not has_result:
                # ── STATE 2: Editable prompt IS the canvas ──
                if model_sel == "SEEDANCE 2.0":
                    _opt_key = "s2_opt_prompt"
                else:
                    _opt_key = "sd_opt_prompt"

                _opt = st.session_state.get(_opt_key, "")

                # The text_area itself IS the canvas — styled via CSS to look like the 16:9 cream box
                edited_prompt = st.text_area(
                    "CANVAS_PROMPT",
                    value=_opt,
                    height=1,
                    key="canvas_prompt_editor",
                    label_visibility="collapsed",
                )
                if edited_prompt != _opt:
                    st.session_state[_opt_key] = edited_prompt

                # Buttons: PREVIEW (redo) + GENERATE
                st.markdown('<div class="generate-btn-wrap">', unsafe_allow_html=True)
                if model_sel == "SEEDANCE 2.0":
                    generate_clicked = st.button("GENERATE", type="primary", use_container_width=True, key="s2_production_opt")
                else:
                    generate_clicked = st.button("GENERATE (Seedream)", type="primary", use_container_width=True, key="sd_production_opt")
                st.markdown('</div>', unsafe_allow_html=True)

            elif has_json and not has_result and not has_prompt:
                # ── STATE 2b: JSON preview in canvas ──
                _json_str = st.session_state.get("json_preview", "{}")
                st.text_area(
                    "CANVAS_PROMPT",
                    value=_json_str,
                    height=1,
                    key="canvas_json_viewer",
                    label_visibility="collapsed",
                    disabled=True,
                )

                st.markdown('<div class="generate-btn-wrap">', unsafe_allow_html=True)
                if model_sel == "SEEDANCE 2.0":
                    generate_clicked = st.button("GENERATE", use_container_width=True, key="s2_production_opt")
                else:
                    generate_clicked = st.button("GENERATE (Seedream)", use_container_width=True, key="sd_production_opt")
                st.markdown('</div>', unsafe_allow_html=True)

            else:
                # ── STATE 1: Empty canvas with PREVIEW centered inside ──
                # Use a styled container with the button inside
                st.markdown(
                    '<div class="empty-canvas-wrap">',
                    unsafe_allow_html=True,
                )
                st.markdown('</div>', unsafe_allow_html=True)
                st.markdown('<div style="height:16px;"></div>', unsafe_allow_html=True)

                # GENERATE visible even before preview
                st.markdown('<div class="generate-btn-wrap">', unsafe_allow_html=True)
                if model_sel == "SEEDANCE 2.0":
                    generate_clicked = st.button("GENERATE", use_container_width=True, key="s2_production_opt")
                else:
                    generate_clicked = st.button("GENERATE (Seedream)", use_container_width=True, key="sd_production_opt")
                st.markdown('</div>', unsafe_allow_html=True)

            if generate_clicked:
                print(f"[DEBUG-CLICK] has_prompt={has_prompt}, has_result={has_result}, model={model_sel}, opt_prompt_len={len(st.session_state.get(chr(115)+chr(50)+chr(95)+chr(111)+chr(112)+chr(116)+chr(95)+chr(112)+chr(114)+chr(111)+chr(109)+chr(112)+chr(116), chr(32)))}")
                st.markdown("""
                    <style>
                    div[data-testid="stButton"][data-key*="s2_production_opt"] > button,
                    div[data-testid="stButton"][data-key*="sd_production_opt"] > button {
                        animation: pulse-generate 0.8s ease-in-out infinite !important;
                    }
                    </style>
                """, unsafe_allow_html=True)

            # Persist clicks across reruns (Streamlit buttons are edge-triggered)
            if preview_clicked:
                if model_sel == "SEEDANCE 2.0":
                    st.session_state["_do_preview_s2"] = True
                else:
                    st.session_state["_do_preview_sd"] = True
            if generate_clicked:
                if not has_prompt and not has_result:
                    if st.session_state.get("json_preview"):
                        st.session_state["_preview_feedback"] = "⚠️ Press PREVIEW PROMPT to build an optimized prompt from your current settings."
                    else:
                        st.session_state["_preview_feedback"] = "⚠️ Press PREVIEW PROMPT first."
                elif model_sel == "SEEDANCE 2.0":
                    st.session_state["_do_generate_s2"] = True
                else:
                    st.session_state["_do_generate_sd"] = True

        with right_col:
            with st.expander("TECHNICAL", expanded=False):
                if model_sel == "SEEDANCE 2.0":
                    if st.session_state.get("video_resolution") not in ("1080p", "720p", "480p"):
                        st.session_state["video_resolution"] = "1080p"
                    if st.session_state.get("video_aspect_ratio") not in ("16:9", "9:16", "4:3", "3:4", "21:9", "1:1", "adaptive"):
                        st.session_state["video_aspect_ratio"] = "adaptive"
                    resolution = st.selectbox("Resolution", ["1080p", "720p", "480p"], key="video_resolution")
                    aspect_ratio = st.selectbox("Aspect Ratio", ["16:9", "9:16", "4:3", "3:4", "21:9", "1:1", "adaptive"], key="video_aspect_ratio")
                    _duration_slider = st.slider("Duration (s)", min_value=4, max_value=15, step=1, key="common_duration")
                    _smart_duration = st.checkbox("Smart Duration (-1)", key="s2_smart_duration")
                    duration = -1 if _smart_duration else _duration_slider
                    gen_mode = st.radio("Processing Mode", ["Standard (Online)", "Draft Mode (Preview)", "Offline (50% Cost)"], horizontal=True, key="s2_gen_mode")
                    st.checkbox("Watermark", key="s2_watermark")
                else:
                    sd_resolution = st.selectbox("Resolution", ["3K", "2K"], key="sd_resolution")
                    sd_ar = st.selectbox("Aspect Ratio", ["Smart", "1:1", "3:4", "4:3", "16:9", "9:16", "2:3", "3:2", "21:9"], key="sd_ar_select")

            with st.expander("SEEDS & CREATIVITY", expanded=False):
                if model_sel == "SEEDANCE 2.0":
                    temperature = st.number_input("Creativity", min_value=0.0, max_value=1.5, step=0.1, key="common_temperature")
                    num_variations = st.number_input("Variations", min_value=1, max_value=5, step=1, key="common_num_variations")
                    cols = st.columns(min(num_variations, 5))
                    for i in range(num_variations):
                        with cols[i % 5]: st.text_input(f"Seed {i+1}", key=f"seed_input_{i}")
                else:
                    sd_optimize = st.selectbox("Optimize prompt", ["None", "standard", "fast"], key="sd_optimize")

            with st.expander("AUDIO & LIP-SYNC", expanded=False):
                if model_sel == "SEEDANCE 2.0":
                    gen_audio = st.toggle("Enable Audio Generation & Sync", key="enable_audio")
                    if gen_audio:
                        v_lang = st.selectbox("Language", LIST_LANGUAGES, key="v_lang")
                        v_emo = st.selectbox("Emotion", LIST_EMOTIONS, key="v_emo")
                        v_timbre = st.selectbox("Timbre", ["Normal", "Deep", "Soft", "Raspy", "Clear"], key="v_timbre")
                        v_pace = st.selectbox("Pace", ["Normal", "Slow", "Very Slow", "Fast"], key="v_pace")
                        audio_details_dict['dialogue'] = st.text_area("Dialogue/Lip-Sync", placeholder="Text to speak...", key="s2_dialogue")
                        audio_details_dict['sfx'] = st.text_input("Sound Effects Notes", key="s2_sfx")
                        audio_details_dict['lang'] = v_lang
                        audio_details_dict['emo'] = v_emo
                        audio_details_dict['timbre'] = v_timbre
                        audio_details_dict['pace'] = v_pace

            _save_console_param_snapshot()

            if st.button("GALLERY", key="top_gallery_btn", use_container_width=True):
                st.session_state["_console_was_away"] = True
                st.session_state.active_page = "gallery"
                st.rerun()
            if st.button("STORYBOARD", key="top_sb_images_btn", use_container_width=True):
                st.session_state["_console_was_away"] = True
                st.session_state.active_page = "storyboard"
                st.rerun()
            if st.button("REFERENCES", key="top_references_quick_btn", use_container_width=True):
                st.session_state["_console_was_away"] = True
                st.session_state.active_page = "references"
                st.rerun()
            if st.button("EDITING", key="top_sb_video_btn", use_container_width=True):
                st.session_state["_console_was_away"] = True
                st.session_state.active_page = "editing"
                st.rerun()

        if json_clicked:
            if model_sel == "SEEDANCE 2.0":
                _seeds = [st.session_state.get(f"seed_input_{i}", "") for i in range(st.session_state.get("common_num_variations", 1))]
                _json = _build_settings_json(
                    model_sel,
                    action_desc=action_desc,
                    entry_point=st.session_state.get("s2_entry_point", ""),
                    workflow=s2_workflow,
                    image_usage=image_usage,
                    resolution=resolution,
                    aspect_ratio=aspect_ratio,
                    duration=duration,
                    gen_mode=gen_mode,
                    temperature=temperature,
                    seeds=_seeds,
                    num_imgs=num_imgs,
                    num_vids=num_vids,
                    num_auds=num_auds,
                    total_files=total_files,
                    gen_audio=gen_audio,
                    audio_details=audio_details_dict,
                    shots_data=shots_data,
                )
            else:
                _json = _build_settings_json(
                    model_sel,
                    prompt=sd_prompt,
                    style=sd_style,
                    shot_type=sd_shot_type,
                    mood=sd_mood,
                    period=sd_period,
                    camera=sd_camera,
                    lenses=sd_lenses,
                    film_stock=sd_film_stock,
                    sensor=sd_sensor,
                    lighting_source=sd_lighting_source,
                    lighting_direction=sd_lighting_direction,
                    lighting_type=sd_lighting_type,
                    resolution=sd_resolution,
                    aspect_ratio=sd_ar,
                    optimize=st.session_state.get("sd_optimize", "None"),
                    num_refs=len(sd_refs) if sd_refs else 0,
                )
            st.session_state.json_preview = json.dumps(_json, indent=2, ensure_ascii=False)
            st.session_state["_json_dict"] = _json
            _save_console_param_snapshot()
            st.rerun()

        st.markdown("<br>", unsafe_allow_html=True)
        # Show preview feedback
        if st.session_state.get("_preview_feedback"):
            fb = st.session_state["_preview_feedback"]
            if fb.startswith("✅"):
                st.success(fb)
            elif fb.startswith("⚠️"):
                st.warning(fb)
            else:
                st.error(fb)

        _raw_val = st.session_state.get("s2_raw_prompt", "") if model_sel == "SEEDANCE 2.0" else st.session_state.get("sd_raw_prompt", "")
        _opt_val = st.session_state.get("s2_opt_prompt", "") if model_sel == "SEEDANCE 2.0" else st.session_state.get("sd_opt_prompt", "")
        st.text_area(label="RAW PROMPT", value=_raw_val, height=100)
        st.text_area(label="OPTIMISED PROMPT", value=_opt_val, height=100)
        # ── Estimated cost display ──
        if _opt_val and _opt_val.strip() and not _opt_val.startswith("[ERROR"):
            if model_sel == "SEEDANCE 2.0":
                _has_video_ref = (num_vids or 0) > 0
                _usage = _estimate_seedance2_usage(
                    duration=duration,
                    resolution=resolution,
                    has_video_input=_has_video_ref,
                )
                _tokens_k = _usage["tokens_consumed"] / 1000.0
                _deduct_k = _usage["tokens_deducted"] / 1000.0
                _est_cost = _usage["estimated_cost"]
                st.markdown(
                    f'<p style="color:#FFEB3B;-webkit-text-fill-color:#FFEB3B;'
                    f'font-size:0.85rem;font-weight:700;font-family:Open Sans,sans-serif;'
                    f'margin:4px 0 0;padding:6px 10px;'
                    f'background:rgba(255,235,59,0.08);border-radius:4px;'
                    f'border-left:3px solid #FFEB3B;">'
                    f'Est. ~{_tokens_k:.1f}K tokens | ~${_est_cost:.3f} | Pack deduction: {_deduct_k:.1f}K tokens</p>',
                    unsafe_allow_html=True,
                )
            else:
                _est_cost = estimate_cost(
                    SEEDREAM_5_0_LITE_MODEL_ID, sd_resolution,
                )
            if model_sel != "SEEDANCE 2.0":
                st.markdown(
                    f'<p style="color:#FFEB3B;-webkit-text-fill-color:#FFEB3B;'
                    f'font-size:0.85rem;font-weight:700;font-family:Open Sans,sans-serif;'
                    f'margin:4px 0 0;padding:6px 10px;'
                    f'background:rgba(255,235,59,0.08);border-radius:4px;'
                    f'border-left:3px solid #FFEB3B;">'
                    f'Estimated cost: {format_cost_str(_est_cost)}</p>',
                    unsafe_allow_html=True,
                )

        # S2.0 preview
        if model_sel == "SEEDANCE 2.0" and st.session_state.get("_do_preview_s2"):
            if not action_desc or not str(action_desc).strip():
                st.error("Write a scene description before pressing PREVIEW.")
                st.session_state["_do_preview_s2"] = False
            elif total_files > 12:
                st.error("Too many files (max 12). Remove some assets.")
                st.session_state["_do_preview_s2"] = False
            else:
                with st.spinner("Building prompt..."):
                    try:
                        builder_args = {
                            "scene_description": action_desc, "workflow_type": s2_workflow,
                            "num_imgs": num_imgs, "num_vids": num_vids, "num_auds": num_auds,
                            "duration": duration, "temperature": temperature, "shots_data": shots_data,
                            "vision_context": st.session_state.get('vision_context', None),
                            "audio_sync": audio_details_dict if gen_audio else None, "image_usage": image_usage,
                            "enforce_stability": st.session_state.get("enforce_stability", False),
                        }
                        s2_prompt_bundle = build_video_prompt(**builder_args)
                        raw = (s2_prompt_bundle or {}).get("raw_prompt", "")
                        opt = (s2_prompt_bundle or {}).get("optimized_prompt", "")
                        err = (s2_prompt_bundle or {}).get("error", "")

                        st.session_state.s2_raw_prompt = raw
                        st.session_state.s2_opt_prompt = opt
                        st.session_state.show_generate_button = True

                        # Debug feedback
                        if err:
                            st.session_state["_preview_feedback"] = f"⚠️ Builder error: {err}"
                        elif not opt or opt.startswith("[LLM ERROR") or opt.startswith("[ERROR"):
                            st.session_state["_preview_feedback"] = f"⚠️ LLM failed: {opt[:200]}"
                        else:
                            st.session_state["_preview_feedback"] = f"✅ Prompt generated ({len(opt.split())} words)"
                    except Exception as e:
                        st.session_state["_preview_feedback"] = f"❌ Exception: {str(e)[:200]}"
                        st.session_state.s2_raw_prompt = ""
                        st.session_state.s2_opt_prompt = f"[ERROR: {e}]"
                    st.session_state["_do_preview_s2"] = False
                st.rerun()

        # S2.0 generate
        if model_sel == "SEEDANCE 2.0" and st.session_state.get("_do_generate_s2"):
            if not GENERATION_ENABLED:
                st.warning("Generation temporarily disabled (demo mode). Preview Prompt is active.")
                st.session_state["_do_generate_s2"] = False
            else:
                chosen_prompt = st.session_state.get("s2_opt_prompt", "")
                print(f"[DEBUG-GEN-S2] s2_images={len(s2_images) if s2_images else 0}, s2_videos={len(s2_videos) if s2_videos else 0}, s2_audio={len(s2_audio) if s2_audio else 0}, workflow={s2_workflow}")
                with st.spinner("Generating Seedance 2.0... please wait 3-5 minutes"):
                    result = generate_video(
                        prompt_text=chosen_prompt, scene_description=(action_desc or "")[:20],
                        images=s2_images, videos=s2_videos, audios=s2_audio,
                        image_usage=image_usage,
                        seed=st.session_state.get('seed_input_0', "-1"),
                        resolution=resolution, aspect_ratio=aspect_ratio, duration=duration,
                        generate_audio=(gen_audio or st.session_state.get("s2_audio_output", False)),
                        audio_details=audio_details_dict,
                        is_draft=(gen_mode == "Draft Mode (Preview)"), is_offline=(gen_mode == "Offline (50% Cost)"),
                        watermark=st.session_state.get("s2_watermark", False),
                        model_id=SEEDANCE_2_0_MODEL_ID, shots_data=shots_data,
                    )
                    if isinstance(result, dict) and result.get("video"):
                        st.session_state.s2_last_result = result
                        _s2_est_cost = estimate_cost(
                            SEEDANCE_2_0_MODEL_ID,
                            resolution,
                            duration,
                            gen_audio,
                            is_draft=(gen_mode == "Draft Mode (Preview)"),
                            is_offline=(gen_mode == "Offline (50% Cost)"),
                            has_video_input=((num_vids or 0) > 0),
                        )
                        _actual_duration = result.get("duration") or result.get("actual_duration") or result.get("video_duration")
                        _duration_for_gallery = _actual_duration if _actual_duration is not None else duration
                        st.session_state.gallery_videos.append({"url": result["video"], "caption": (action_desc or "Seedance 2.0")[:50], "prompt": chosen_prompt, "resolution": resolution, "duration": _duration_for_gallery, "aspect_ratio": aspect_ratio, "video_path": result.get("video_path"), "last_frame_path": result.get("last_frame_path"), "model": "Seedance 2.0", "created_at": datetime.now().isoformat(), "project_id": st.session_state.get("active_project_id"), "estimated_cost": _s2_est_cost})
                        _settings = st.session_state.get("_json_dict")
                        if _settings is None:
                            _seeds_sv = [st.session_state.get(f"seed_input_{i}", "") for i in range(st.session_state.get("common_num_variations", 1))]
                            _settings = _build_settings_json(
                                "SEEDANCE 2.0",
                                action_desc=action_desc,
                                entry_point=st.session_state.get("s2_entry_point", ""),
                                workflow=s2_workflow,
                                image_usage=image_usage,
                                resolution=resolution,
                                aspect_ratio=aspect_ratio,
                                duration=duration,
                                gen_mode=gen_mode,
                                temperature=temperature,
                                seeds=_seeds_sv,
                                num_imgs=num_imgs,
                                num_vids=num_vids,
                                num_auds=num_auds,
                                total_files=total_files,
                                gen_audio=gen_audio,
                                audio_details=audio_details_dict,
                                shots_data=shots_data,
                            )
                        if _settings and result.get("video_path"):
                            try:
                                _json_path = result["video_path"].rsplit(".", 1)[0] + "_settings.json"
                                with open(_json_path, "w", encoding="utf-8") as _jf:
                                    json.dump(_settings, _jf, indent=2, ensure_ascii=False)
                            except Exception:
                                pass
                        save_gallery_to_disk(st.session_state.gallery_videos, st.session_state.gallery_images)
                    else:
                        st.session_state.s2_last_result = None
                        st.error(f"Production Failed: {result}")
                st.session_state["_do_generate_s2"] = False
                st.rerun()

        # Seedream preview
        if model_sel == "SEEDREAM 5.0" and st.session_state.get("_do_preview_sd"):
            if not sd_prompt or not str(sd_prompt).strip():
                st.error("Write a scene description before pressing PREVIEW.")
                st.session_state["_do_preview_sd"] = False
            else:
                with st.spinner("LLM expanding your idea..."):
                    try:
                        bundle = build_image_prompt(
                            prompt=sd_prompt, style_preset=sd_style, aspect_ratio=sd_ar,
                            ref_images=sd_refs if sd_refs else [],
                            shot_type=sd_shot_type, mood=sd_mood, period=sd_period,
                            camera=sd_camera, lenses=sd_lenses, film_stock=sd_film_stock,
                            sensor=sd_sensor, lighting_source=sd_lighting_source,
                            lighting_direction=sd_lighting_direction, lighting_type=sd_lighting_type,
                        )
                        if isinstance(bundle, dict):
                            raw = (bundle.get("raw_prompt") or "").strip() or "[Empty]"
                            opt = (bundle.get("optimized_prompt") or "").strip() or "[Empty]"
                            err = bundle.get("error", "")
                            st.session_state.sd_raw_prompt = raw
                            st.session_state.sd_opt_prompt = opt
                            st.session_state.show_image_generate_button = True

                            if err:
                                st.session_state["_preview_feedback"] = f"⚠️ Builder error: {err}"
                            elif opt.startswith("[LLM ERROR") or opt.startswith("[ERROR") or opt == "[Empty]":
                                st.session_state["_preview_feedback"] = f"⚠️ LLM failed: {opt[:200]}"
                            else:
                                st.session_state["_preview_feedback"] = f"✅ Image prompt generated ({len(opt.split())} words)"
                        else:
                            st.session_state["_preview_feedback"] = f"⚠️ Unexpected result: {str(bundle)[:200]}"
                    except Exception as e:
                        st.session_state["_preview_feedback"] = f"❌ Exception: {str(e)[:200]}"
                        st.session_state.sd_opt_prompt = f"[ERROR: {e}]"
                    st.session_state["_do_preview_sd"] = False
                st.rerun()

        # Seedream generate
        if model_sel == "SEEDREAM 5.0" and st.session_state.get("_do_generate_sd"):
            if not GENERATION_ENABLED:
                st.warning("Generation temporarily disabled (demo mode). Preview Prompt is active.")
                st.session_state["_do_generate_sd"] = False
            else:
                final_prompt = st.session_state.get("sd_opt_prompt", "")
                optimize_mode = None if (st.session_state.get("sd_optimize") == "None") else st.session_state.get("sd_optimize")
                with st.spinner("Seedream is processing..."):
                    result = generate_seedream_image(prompt=final_prompt, ref_images=sd_refs if sd_refs else [], style_preset=sd_style, aspect_ratio=sd_ar, model_id=SEEDREAM_5_0_LITE_MODEL_ID, sequential="disabled", max_images=1, output_format="jpeg", optimize_prompt_mode=optimize_mode, resolution=sd_resolution, watermark=False, watermark_text=None, stream=False)
                    if isinstance(result, dict) and (result.get("images") or result.get("image_url")):
                        st.session_state.sd_last_result = {"result": result, "final_prompt": final_prompt, "batch": bool(result.get("images"))}
                        imgs = result.get("images") or [{"image_url": result.get("image_url"), "image_path": result.get("image_path")}]
                        _settings = st.session_state.get("_json_dict")
                        if _settings is None:
                            _settings = _build_settings_json(
                                "SEEDREAM 5.0",
                                prompt=sd_prompt,
                                style=sd_style,
                                shot_type=sd_shot_type,
                                mood=sd_mood,
                                period=sd_period,
                                camera=sd_camera,
                                lenses=sd_lenses,
                                film_stock=sd_film_stock,
                                sensor=sd_sensor,
                                lighting_source=sd_lighting_source,
                                lighting_direction=sd_lighting_direction,
                                lighting_type=sd_lighting_type,
                                resolution=sd_resolution,
                                aspect_ratio=sd_ar,
                                optimize=st.session_state.get("sd_optimize", "None"),
                                num_refs=len(sd_refs) if sd_refs else 0,
                            )
                        if _settings:
                            for im in imgs:
                                if im.get("error"):
                                    continue
                                if im.get("image_path"):
                                    try:
                                        _json_path = im["image_path"].rsplit(".", 1)[0] + "_settings.json"
                                        with open(_json_path, "w", encoding="utf-8") as _jf:
                                            json.dump(_settings, _jf, indent=2, ensure_ascii=False)
                                    except Exception:
                                        pass
                        for im in imgs:
                            if im.get("error"): continue
                            _sd_est_cost = estimate_cost(SEEDREAM_5_0_LITE_MODEL_ID, sd_resolution)
                            st.session_state.gallery_images.append({"url": im.get("image_url", ""), "caption": (final_prompt or "Seedream 5.0")[:50], "prompt": final_prompt, "style": sd_style, "aspect_ratio": sd_ar, "resolution": sd_resolution, "specs": {}, "image_path": im.get("image_path"), "created_at": datetime.now().isoformat(), "project_id": st.session_state.get("active_project_id"), "estimated_cost": _sd_est_cost})
                        save_gallery_to_disk(st.session_state.gallery_videos, st.session_state.gallery_images)
                    else:
                        st.session_state.sd_last_result = None
                        st.error(f"Dream Failed: {result}")
                st.session_state["_do_generate_sd"] = False
                st.rerun()
