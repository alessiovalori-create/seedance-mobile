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
from arkitect.console_state import (
    _CONSOLE_FILE_AND_ASSET_PICKER_KEYS,
    _console_session_state_assign_forbidden,
    _clear_console_prompts_for_project_change,
    _console_snapshot_key_list,
    _CONSOLE_SNAPSHOT_SKIP,
    _save_console_param_snapshot,
    _restore_console_param_snapshot,
    _project_settings_path,
    _default_console_params,
    _migrate_legacy_projects_to_per_project_settings,
    _save_project_console_settings,
    _load_project_console_settings,
    _delete_project_console_settings,
)


from builder import build_prompt as build_video_prompt, analyze_cinematography, build_image_prompt
from generator import generate_video, generate_seedream_image, SEEDANCE_2_0_MODEL_ID, SEEDREAM_5_0_LITE_MODEL_ID, SEEDREAM_4_5_MODEL_ID, PEXELS_API_KEY, UNSPLASH_API_KEY, estimate_cost, format_cost_str, _estimate_seedance2_usage
GENERATION_ENABLED = True  # ← Set to False to disable generation
from arkitect.pages.console import render_console_page
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


from arkitect.ui_helpers import (
    _section_title,
    _inject_pulse_css,
    _render_project_name_inline_right,
)


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
        /* Console — Tones pill selectors (one row per parameter) */
        div[data-testid="stRadio"][data-key*="_pill_"] > div {
            flex-wrap: wrap !important;
            gap: 6px !important;
            background: transparent !important;
            border: none !important;
            padding: 0 !important;
        }
        div[data-testid="stRadio"][data-key*="_pill_"] label {
            margin: 0 !important;
            padding: 6px 14px !important;
            border-radius: 999px !important;
            border: 1px solid rgba(255,255,255,0.22) !important;
            background: rgba(255,255,255,0.04) !important;
            color: #b8b8a8 !important;
            font-size: 0.72rem !important;
            font-weight: 600 !important;
            letter-spacing: 0.03em !important;
            cursor: pointer !important;
            transition: background 0.15s, border-color 0.15s, color 0.15s !important;
        }
        div[data-testid="stRadio"][data-key*="_pill_"] label:hover {
            border-color: rgba(0,229,204,0.45) !important;
            color: #e8e8dc !important;
        }
        div[data-testid="stRadio"][data-key*="_pill_"] label:has(input:checked) {
            background: rgba(0,229,204,0.18) !important;
            border-color: #00E5CC !important;
            color: #00E5CC !important;
        }
        div[data-testid="stRadio"][data-key*="_pill_"] input[type="radio"] {
            display: none !important;
        }
        div[data-testid="stRadio"][data-key*="_pill_"] label > div:first-child {
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
    # Detect return to Console from another page (Assets, Gallery, …)
    _prev_page = st.session_state.get("_prev_active_page", "console")
    _curr_page = st.session_state.get("active_page", "console")
    if _curr_page == "console" and _prev_page not in ("console", None):
        st.session_state["_console_was_away"] = True
    st.session_state["_prev_active_page"] = _curr_page
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
            if f"{_k}_pill_grain" not in st.session_state: st.session_state[f"{_k}_pill_grain"] = "None"
            if f"{_k}_pill_vignette" not in st.session_state: st.session_state[f"{_k}_pill_vignette"] = "None"
            if f"{_k}_pill_focus" not in st.session_state: st.session_state[f"{_k}_pill_focus"] = "Sharp"
            if f"{_k}_pill_dof" not in st.session_state: st.session_state[f"{_k}_pill_dof"] = "Medium"
            if f"{_k}_pill_brightness" not in st.session_state: st.session_state[f"{_k}_pill_brightness"] = "Normal"
            if f"{_k}_pill_contrast" not in st.session_state: st.session_state[f"{_k}_pill_contrast"] = "Normal"
            if f"{_k}_pill_saturation" not in st.session_state: st.session_state[f"{_k}_pill_saturation"] = "Natural"
            if f"{_k}_pill_temperature" not in st.session_state: st.session_state[f"{_k}_pill_temperature"] = "Neutral"
            if f"{_k}_pill_chromatic" not in st.session_state: st.session_state[f"{_k}_pill_chromatic"] = "None"
            if f"{_k}_pill_motion" not in st.session_state: st.session_state[f"{_k}_pill_motion"] = "None"
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

    # Increment run ID each script execution to reset page guards
    if "_streamlit_run_id" not in st.session_state:
        st.session_state["_streamlit_run_id"] = 0
    st.session_state["_streamlit_run_id"] += 1

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
        render_console_page()
