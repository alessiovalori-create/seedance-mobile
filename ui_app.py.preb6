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
from arkitect.pages.projects_page import render_projects_page
from arkitect.pages.storyboard import render_storyboard_page, render_editing_page

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
_REFS_STOCK_IFRAME_CSS = """<style>
*{margin:0;padding:0;box-sizing:border-box;}
body{background:transparent;font-family:'Open Sans',sans-serif;}
.ref-stock-masonry{
  column-count:3;
  column-gap:8px;
  padding:4px;
}
@media (max-width:480px){
  .ref-stock-masonry{column-count:2;}
}
.gal-card.ref-stock-card{
  position:relative;
  background:#1a1a18;
  border-radius:6px;
  overflow:visible;
  border:2px solid transparent;
  transition:border-color .2s,box-shadow .2s;
  cursor:pointer;
  break-inside:avoid;
  page-break-inside:avoid;
  margin-bottom:8px;
  display:block;
  width:100%;
  min-height:0;
}
.gal-card.ref-stock-card:hover{border-color:rgba(255,235,59,.35)!important;box-shadow:0 4px 16px rgba(0,0,0,.35);}
.ref-stock-img-wrap{
  display:block;
  width:100%;
  line-height:0;
  background:#121210;
  position:relative;
  border-radius:4px;
  overflow:hidden;
}
.ref-stock-img-wrap.ref-stock-selected{
  outline:2px solid #FFEB3B;
  outline-offset:-2px;
  box-shadow:0 0 0 1px #FFEB3B, 0 0 14px rgba(255,235,59,0.28);
}
.ref-stock-sel-check{
  position:absolute;
  bottom:8px;
  right:6px;
  background:#FFEB3B;
  color:#000;
  width:18px;
  height:18px;
  border-radius:50%;
  font-size:11px;
  font-weight:700;
  display:flex;
  align-items:center;
  justify-content:center;
  z-index:4;
  pointer-events:none;
  line-height:1;
  box-sizing:border-box;
}
.ref-stock-img{
  position:relative;
  z-index:1;
  width:100%;
  height:auto;
  max-height:none;
  object-fit:contain;
  vertical-align:top;
  border-radius:4px;
  display:block;
  -webkit-user-drag:none;
  user-select:none;
  pointer-events:none;
}
.gal-badge{position:absolute;top:4px;left:4px;background:rgba(0,0,0,.75);color:#fff;font-size:9px;font-weight:700;padding:1px 6px;border-radius:3px;z-index:2;pointer-events:none;}
.gal-expand{position:absolute;top:4px;right:4px;color:#999;cursor:pointer;z-index:6;width:20px;height:20px;display:flex;align-items:center;justify-content:center;border-radius:3px;background:rgba(0,0,0,0.55);transition:color .15s,background .15s;}
.gal-expand:hover{color:#FFEB3B;background:rgba(0,0,0,0.85);}
.gal-caption{color:#999;font-size:9px;padding:3px 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.ref-stock-ph{
  position:absolute;
  inset:0;
  z-index:0;
  background:var(--ref-ph,#121210);
  border-radius:4px;
  pointer-events:none;
}
.ref-stock-img-wrap.ref-stock-no-dims{min-height:140px;}
</style>"""


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


    if st.session_state.get("active_page") == "gallery":
        render_gallery_page()

    elif st.session_state.get("active_page") == "projects":
        render_projects_page()
    elif st.session_state.get("active_page") == "assets":
        render_assets_page()

    elif st.session_state.get("active_page") == "references":
        render_references_page()

    elif st.session_state.get("active_page") == "storyboard":
        render_storyboard_page()

    elif st.session_state.get("active_page") == "editing":
        render_editing_page()

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
