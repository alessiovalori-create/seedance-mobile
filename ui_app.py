# REQUIREMENTS: Streamlit >= 1.31.0 for static file serving (video timeline)
# Upgrade: pip install --upgrade streamlit

import os
import uuid
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
from arkitect.gallery_paths import repair_gallery_media_paths
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
from lab_vision import analyze_image, ACTIVE_MODEL
from lab_schemas import get_image_groups, get_video_groups

_LAB_IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp")
_LAB_VID_EXTS = (".mp4", ".mov", ".webm")


def _download_to_lab_cache(url):
    """Download a remote URL once into the temp lab_cache dir keyed by URL hash. Returns the cached path or None."""
    import hashlib as _hashlib
    import tempfile as _tempfile
    cache_dir = os.path.join(_tempfile.gettempdir(), "lab_cache")
    os.makedirs(cache_dir, exist_ok=True)
    key = _hashlib.md5(url.encode("utf-8")).hexdigest()[:16]
    ext = ".jpg"
    for candidate in (".jpg", ".jpeg", ".png", ".webp"):
        if candidate in url.lower():
            ext = candidate
            break
    cached = os.path.join(cache_dir, f"{key}{ext}")
    if os.path.exists(cached):
        return cached
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200:
            with open(cached, "wb") as f:
                f.write(r.content)
            return cached
    except Exception:
        pass
    return None


def _download_to_lab_cache_video(url):
    """Download a remote video URL into lab_cache. Returns local path or None."""
    import hashlib as _hashlib
    import tempfile as _tempfile
    cache_dir = os.path.join(_tempfile.gettempdir(), "lab_cache")
    os.makedirs(cache_dir, exist_ok=True)
    key = _hashlib.md5(url.encode("utf-8")).hexdigest()[:16]
    ext = ".mp4"
    for candidate in _LAB_VID_EXTS:
        if candidate in url.lower():
            ext = candidate
            break
    cached = os.path.join(cache_dir, f"{key}{ext}")
    if os.path.exists(cached):
        return cached
    try:
        r = requests.get(url, timeout=60, stream=True)
        if r.status_code == 200:
            with open(cached, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
            return cached
    except Exception:
        pass
    return None


def _extract_lab_frame_from_video(video_path, last_frame_path=None):
    """Return a local image path (poster frame) suitable for vision analysis."""
    if last_frame_path and os.path.exists(last_frame_path):
        return last_frame_path
    if not video_path:
        return None
    if not os.path.exists(video_path):
        return None
    try:
        import cv2
        import hashlib as _hashlib
        import tempfile as _tempfile
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        target = max(0, frame_count // 2) if frame_count > 0 else 0
        if target > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, target)
        ret, frame = cap.read()
        if not ret:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = cap.read()
        cap.release()
        if not ret:
            return None
        cache_dir = os.path.join(_tempfile.gettempdir(), "lab_cache")
        os.makedirs(cache_dir, exist_ok=True)
        key = _hashlib.md5(video_path.encode("utf-8")).hexdigest()[:16]
        out_path = os.path.join(cache_dir, f"frame_{key}.jpg")
        if not os.path.exists(out_path):
            cv2.imwrite(out_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
        return out_path if os.path.exists(out_path) else None
    except Exception:
        return None


def _resolve_gallery_video_path(item):
    """Local or downloadable path for a gallery video entry."""
    vpath = (item.get("video_path") or "").strip()
    if vpath and os.path.exists(vpath):
        return vpath
    url = (item.get("url") or "").strip()
    if url:
        if os.path.exists(url):
            return url
        return _download_to_lab_cache_video(url)
    return None


def _resolve_media_path_for_analysis(selected_media):
    """Resolve a local image path for vision analysis (still frame if video)."""
    if not selected_media:
        return None
    kind = selected_media.get("kind", "image")
    source = selected_media.get("source")
    data = selected_media.get("data", {}) or {}

    if kind == "video":
        vpath = None
        lfp = data.get("last_frame_path")
        if source == "gallery":
            vpath = _resolve_gallery_video_path(data)
        elif source in ("assets", "upload"):
            vpath = (data.get("path") or data.get("video_path") or "").strip()
            if vpath and not os.path.exists(vpath) and vpath.startswith(("http://", "https://")):
                vpath = _download_to_lab_cache_video(vpath)
        return _extract_lab_frame_from_video(vpath, lfp)

    if source == "upload":
        return data.get("path")
    if source == "assets":
        return data.get("path")
    if source == "gallery":
        local = data.get("file_path") or data.get("local_path") or data.get("image_path")
        if local and os.path.exists(local):
            return local
        url = data.get("url")
        if url:
            return _download_to_lab_cache(url)
    return None


def _compute_media_fingerprint(selected_media):
    """Stable identity for the currently selected media (used for results cache invalidation)."""
    if not selected_media:
        return None
    source = selected_media.get("source")
    kind = selected_media.get("kind", "image")
    data = selected_media.get("data") or {}
    ident = (
        data.get("path")
        or data.get("video_path")
        or data.get("url")
        or data.get("image_path")
        or data.get("id")
        or str(id(data))
    )
    return f"{source}:{kind}:{ident}"


def _lab_field_label(field_name: str) -> str:
    return field_name.replace("_", " ").title()


def _lab_basket_dedupe_key(field_name: str, value: str) -> str:
    return f"{field_name}::{str(value).strip()}"


def _lab_compose_basket_text(basket: list) -> str:
    """Chronological fragment string for Describe the scene (semicolon-separated)."""
    ordered = sorted(basket, key=lambda x: x.get("order", 0))
    parts = []
    for item in ordered:
        label = item.get("label") or _lab_field_label(item.get("field_name", ""))
        val = (item.get("value") or "").strip()
        if val:
            parts.append(f"{label}: {val}")
    return " ; ".join(parts)


def _lab_basket_add(group_label: str, field_name: str, value) -> tuple[bool, str]:
    val = str(value).strip()
    if not val or val.lower() == "undetermined":
        return False, "empty"
    basket = st.session_state.setdefault("_lab_basket", [])
    dkey = _lab_basket_dedupe_key(field_name, val)
    if any(item.get("_dkey") == dkey for item in basket):
        return False, "duplicate"
    seq = int(st.session_state.get("_lab_basket_seq", 0)) + 1
    st.session_state["_lab_basket_seq"] = seq
    basket.append({
        "id": uuid.uuid4().hex[:10],
        "order": seq,
        "_dkey": dkey,
        "group_label": group_label,
        "field_name": field_name,
        "label": _lab_field_label(field_name),
        "value": val,
    })
    return True, "added"


def _lab_basket_remove(item_id: str) -> None:
    basket = st.session_state.get("_lab_basket", [])
    st.session_state["_lab_basket"] = [b for b in basket if b.get("id") != item_id]


def _lab_send_basket_to_console() -> None:
    """Queue scene text for Console — applied after snapshot restore (restore would overwrite action_desc_s2)."""
    text = _lab_compose_basket_text(st.session_state.get("_lab_basket", []))
    st.session_state["_lab_pending_action_desc"] = text
    st.session_state["model_selector"] = "SEEDANCE 2.0"
    st.session_state["_switch_to_seedance"] = True
    st.session_state.active_page = "console"


def _render_lab_fragment_basket() -> None:
    basket = st.session_state.get("_lab_basket", [])
    st.divider()
    st.subheader("Fragment Basket")
    n = len(basket)
    if n == 0:
        st.caption(
            "Click **+** next to any analysis field to collect prompt fragments. "
            "They are added in the order you select them."
        )
    else:
        for item in sorted(basket, key=lambda x: x.get("order", 0)):
            _bcols = st.columns([0.5, 5, 0.6])
            with _bcols[0]:
                st.caption(f"{item.get('order', '')}.")
            with _bcols[1]:
                st.markdown(f"**{item.get('label', '')}:** {item.get('value', '')}")
            with _bcols[2]:
                if st.button("×", key=f"_lab_basket_rm_{item['id']}", help="Remove from basket"):
                    _lab_basket_remove(item["id"])
                    st.rerun()
        with st.expander("Preview — text sent to Console", expanded=False):
            st.code(_lab_compose_basket_text(basket), language=None)

    _bc1, _bc2, _bc3 = st.columns([2, 2, 2])
    with _bc1:
        if st.button(
            "Send to Console",
            key="_lab_basket_send_console",
            type="primary",
            disabled=(n == 0),
            use_container_width=True,
        ):
            _lab_send_basket_to_console()
            st.toast("Fragments loaded into Describe the scene (Seedance 2.0)", icon="📤")
            st.rerun()
    with _bc2:
        if st.button("Clear basket", key="_lab_basket_clear", disabled=(n == 0), use_container_width=True):
            st.session_state["_lab_basket"] = []
            st.rerun()
    with _bc3:
        if n:
            st.caption(f"{n} fragment(s) · chronological order")


def render_lab_page():
    # RESERVED widget key for the upcoming step (do NOT use yet):
    #   future analyze btn: "_lab_analyze"
    # State hygiene
    if "_lab_active_picker" not in st.session_state:
        st.session_state["_lab_active_picker"] = None
    if "_lab_selected_media" not in st.session_state:
        st.session_state["_lab_selected_media"] = None
    if "_lab_run_analysis" not in st.session_state:
        st.session_state["_lab_run_analysis"] = False
    if "_lab_results" not in st.session_state:
        st.session_state["_lab_results"] = None
    if "_lab_totals" not in st.session_state:
        st.session_state["_lab_totals"] = None
    if "_lab_basket" not in st.session_state:
        st.session_state["_lab_basket"] = []
    if "_lab_basket_seq" not in st.session_state:
        st.session_state["_lab_basket_seq"] = 0

    # Clear LAB state when the active project changes (mirrors storyboard/editing pattern)
    _active_project_id = st.session_state.get("active_project_id")
    if st.session_state.get("_lab_last_project_id") != _active_project_id:
        st.session_state["_lab_selected_media"] = None
        st.session_state["_lab_results"] = None
        st.session_state["_lab_totals"] = None
        st.session_state["_lab_active_picker"] = None
        st.session_state["_lab_basket"] = []
        st.session_state["_lab_basket_seq"] = 0
        st.session_state["_lab_last_project_id"] = _active_project_id

    # ── Cache invalidation: drop stale results when the selected media changes ──
    # (Only clear if results actually exist; the analyzed-media key is updated ONLY
    #  after a successful analysis run, never here.)
    _media_fingerprint = _compute_media_fingerprint(st.session_state.get("_lab_selected_media"))
    if st.session_state.get("_lab_last_analyzed_media_key") != _media_fingerprint:
        if st.session_state.get("_lab_results"):
            st.session_state["_lab_results"] = None
            st.session_state["_lab_totals"] = None

    # ── In-page navigation (mirrors gallery.py / storyboard.py) ──
    if "lab_nav" not in st.session_state:
        st.session_state.lab_nav = "LAB"
    elif st.session_state.lab_nav not in ("Console", "Projects", "Gallery", "Assets", "References", "Storyboard", "Editing", "LAB"):
        st.session_state.lab_nav = "LAB"

    def _on_lab_nav_change():
        val = st.session_state.lab_nav
        if val == "Console":
            st.session_state.lab_nav = "LAB"
            st.session_state["_console_was_away"] = True
            st.session_state.active_page = "console"
        elif val == "Projects":
            st.session_state.lab_nav = "LAB"
            st.session_state.active_page = "projects"
        elif val == "Gallery":
            st.session_state.lab_nav = "LAB"
            st.session_state.active_page = "gallery"
        elif val == "Assets":
            st.session_state.lab_nav = "LAB"
            st.session_state.active_page = "assets"
        elif val == "References":
            st.session_state.lab_nav = "LAB"
            st.session_state.active_page = "references"
        elif val == "Storyboard":
            st.session_state.lab_nav = "LAB"
            st.session_state.active_page = "storyboard"
        elif val == "Editing":
            st.session_state.lab_nav = "LAB"
            st.session_state.active_page = "editing"

    # "LAB" per primo: un reset sporadico del radio non seleziona "Console" → main page
    _LAB_NAV_ORDER = ["LAB", "Console", "Projects", "Gallery", "Assets", "References", "Storyboard", "Editing"]
    _lab_nav_col, _lab_proj_col = st.columns([4, 1])
    with _lab_nav_col:
        st.radio(
            "lab_nav_label",
            _LAB_NAV_ORDER,
            horizontal=True,
            key="lab_nav",
            on_change=_on_lab_nav_change,
            label_visibility="collapsed",
        )
    with _lab_proj_col:
        _render_project_name_inline_right()

    st.title("LAB")
    st.caption("Reverse engineer cinematic references — extract structured parameters from images and videos.")
    st.divider()

    # ──────────────────────────────────────────────────────────────
    # CANVAS — focal reference (always rendered)
    # ──────────────────────────────────────────────────────────────
    _selected = st.session_state.get("_lab_selected_media")
    if not _selected:
        with st.container(border=True):
            _cv_pl, _cv_pc, _cv_pr = st.columns([1, 2, 1])
            with _cv_pc:
                st.caption("No reference loaded — import an image or video below")
    else:
        _data = _selected.get("data", {}) or {}
        _src_kind = _selected.get("source", "")
        _media_kind = _selected.get("kind", "image")
        if _src_kind == "gallery":
            if _media_kind == "video":
                _canvas_src = _data.get("video_path") or _data.get("url") or ""
            else:
                _canvas_src = _data.get("url") or _data.get("image_path") or ""
            _canvas_name = _data.get("caption") or _data.get("prompt") or "Gallery item"
            _canvas_from = "from Gallery"
        elif _src_kind == "assets":
            _canvas_src = _data.get("path") or ""
            _canvas_name = _data.get("name") or _data.get("id") or "Asset"
            _canvas_from = "from Assets"
        else:
            _canvas_src = _data.get("path") or ""
            _canvas_name = _data.get("filename") or "Uploaded file"
            _canvas_from = "from Upload"

        _cv_l, _cv_r = st.columns([3, 1])
        with _cv_l:
            _shown = False
            if _canvas_src:
                try:
                    if _media_kind == "video":
                        st.video(_canvas_src)
                        _shown = True
                    else:
                        st.image(_canvas_src, use_container_width=True)
                        _shown = True
                except Exception:
                    _shown = False
            if not _shown:
                st.warning("Preview unavailable")
        with _cv_r:
            st.markdown(f"**{_canvas_name}**")
            st.caption(f"{_canvas_from} · {'Video' if _media_kind == 'video' else 'Image'}")
            if _media_kind == "video":
                _dur = _data.get("duration")
                if _dur:
                    st.write(f"Duration: {_dur}s")
                st.caption("Analysis uses a keyframe from this clip.")
            else:
                _is_local = bool(_canvas_src) and not str(_canvas_src).startswith(("http://", "https://"))
                if _is_local and os.path.exists(_canvas_src):
                    try:
                        from PIL import Image as _PILImage
                        with _PILImage.open(_canvas_src) as _im:
                            _w, _h = _im.size
                        st.write(f"{_w} × {_h} px")
                    except Exception:
                        pass
            if st.button("Change reference", key="_lab_change_reference"):
                st.session_state["_lab_selected_media"] = None
                st.session_state["_lab_active_picker"] = None
                st.rerun()

    # ── ANALYSIS ──
    st.divider()
    st.subheader("Analysis")

    _btn_label = f"Analyze with {ACTIVE_MODEL}"
    _btn_disabled = st.session_state.get("_lab_selected_media") is None
    if st.button(_btn_label, key="_lab_analyze", type="primary", disabled=_btn_disabled):
        st.session_state["_lab_run_analysis"] = True
        st.rerun()

    if st.session_state.get("_lab_run_analysis"):
        st.session_state["_lab_run_analysis"] = False  # RESET FIRST — mirrors _do_generate_s2 guard

        _resolved_path = _resolve_media_path_for_analysis(st.session_state["_lab_selected_media"])
        if _resolved_path is None or not os.path.exists(_resolved_path):
            st.error("Cannot resolve media for analysis (missing file or could not extract a video frame).")
        else:
            try:
                _sel = st.session_state.get("_lab_selected_media") or {}
                _analysis_kind = _sel.get("kind", "image")
                groups = get_video_groups() if _analysis_kind == "video" else get_image_groups()
                with st.status("Analyzing reference...", expanded=True) as status:
                    results = {}
                    total_cost = 0.0
                    total_tokens_in = 0
                    total_tokens_out = 0

                    for group in groups:
                        status.write(f"⏳ {group['label']}...")
                        try:
                            result = analyze_image(
                                image_path=_resolved_path,
                                system_prompt=group["system_prompt"],
                                user_prompt=group["user_prompt"],
                                json_schema=group["schema"],
                                schema_name=group["schema_name"],
                            )
                            results[group["id"]] = {"group": group, "result": result}
                            if result.get("success"):
                                total_cost += result.get("cost_usd") or 0
                                usage = result.get("usage") or {}
                                total_tokens_in += usage.get("prompt_tokens", 0)
                                total_tokens_out += usage.get("completion_tokens", 0)
                                status.write(f"✅ {group['label']} ({result.get('duration_seconds', 0):.1f}s)")
                            else:
                                status.write(f"❌ {group['label']}: {result.get('error', 'unknown error')}")
                        except Exception as e:
                            results[group["id"]] = {"group": group, "result": {"success": False, "error": f"{type(e).__name__}: {e}"}}
                            status.write(f"❌ {group['label']}: exception — {e}")

                    status.update(
                        label=f"Analysis complete • ${total_cost:.4f} • {total_tokens_in}/{total_tokens_out} tokens",
                        state="complete",
                        expanded=False,
                    )

                st.session_state["_lab_results"] = results
                st.session_state["_lab_totals"] = {
                    "cost_usd": total_cost,
                    "tokens_in": total_tokens_in,
                    "tokens_out": total_tokens_out,
                }
                st.session_state["_lab_last_analyzed_media_key"] = _compute_media_fingerprint(
                    st.session_state.get("_lab_selected_media")
                )
            except Exception as _cfg_err:
                # Config/programming errors raised by analyze_image's pre-check
                # (e.g. missing ARK_API_KEY) bubble here — surface once and stop.
                st.error(f"Analysis could not start: {_cfg_err}")

    # ── RESULTS DISPLAY ──
    _results = st.session_state.get("_lab_results")
    if _results:
        _totals = st.session_state.get("_lab_totals") or {}
        _mc1, _mc2, _mc3 = st.columns([2, 2, 1])
        _mc1.metric("Total cost", f"${_totals.get('cost_usd', 0):.4f}")
        _mc2.metric("Tokens", f"{_totals.get('tokens_in', 0)} / {_totals.get('tokens_out', 0)}")
        with _mc3:
            if st.button("Clear results", key="_lab_clear_results"):
                st.session_state["_lab_results"] = None
                st.session_state["_lab_totals"] = None
                st.rerun()

        for group_id, entry in _results.items():
            group = entry["group"]
            result = entry["result"]
            _icon = "✅" if result.get("success") else "❌"
            with st.expander(f"{_icon} {group['label']}", expanded=False):
                if not result.get("success"):
                    st.error(result.get("error", "Unknown error"))
                    continue

                data = result.get("data") or {}
                for field_name, field_value in data.items():
                    _field_desc = group["schema"]["properties"].get(field_name, {}).get("description", "")
                    _row = st.columns([2, 6, 1])
                    with _row[0]:
                        st.markdown(f"**{field_name.replace('_', ' ').title()}**")
                        if _field_desc:
                            _short = _field_desc if len(_field_desc) <= 80 else _field_desc[:77] + "..."
                            st.caption(_short)
                    with _row[1]:
                        st.write(field_value)
                    with _row[2]:
                        if st.button(
                            "+",
                            key=f"_lab_add_{group_id}_{field_name}",
                            help="Add to fragment basket",
                        ):
                            _ok, _reason = _lab_basket_add(group["label"], field_name, field_value)
                            if _ok:
                                _preview = str(field_value)
                                if len(_preview) > 40:
                                    _preview = _preview[:37] + "..."
                                st.toast(f"Added: {_preview}", icon="🪣")
                            elif _reason == "duplicate":
                                st.toast("Already in basket", icon="🪣")
                            else:
                                st.toast("Nothing to add", icon="🪣")
                            st.rerun()

    _render_lab_fragment_basket()

    # ──────────────────────────────────────────────────────────────
    # IMPORT REFERENCE — change source / load new (bottom tool)
    # ──────────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Import reference")
    st.caption("Load a new image or video from one of these sources. The current reference will be replaced.")

    _active_picker = st.session_state.get("_lab_active_picker")
    _imp1, _imp2, _imp3 = st.columns([1, 1, 1])
    with _imp1:
        if st.button(
            "From Gallery",
            key="_lab_open_gallery_picker",
            use_container_width=True,
            type="primary" if _active_picker == "gallery" else "secondary",
        ):
            st.session_state["_lab_active_picker"] = None if _active_picker == "gallery" else "gallery"
            st.rerun()
    with _imp2:
        if st.button(
            "From Assets",
            key="_lab_open_assets_picker",
            use_container_width=True,
            type="primary" if _active_picker == "assets" else "secondary",
        ):
            st.session_state["_lab_active_picker"] = None if _active_picker == "assets" else "assets"
            st.rerun()
    with _imp3:
        if st.button(
            "Upload from Desktop",
            key="_lab_open_upload_picker",
            use_container_width=True,
            type="primary" if _active_picker == "upload" else "secondary",
        ):
            st.session_state["_lab_active_picker"] = None if _active_picker == "upload" else "upload"
            st.rerun()

    # ── PICKER: GALLERY ──
    if _active_picker == "gallery":
        with st.container():
            _active_pid = st.session_state.get("active_project_id")
            if not _active_pid:
                st.warning("No active project. Select a project to see its gallery.")
                _imgs = []
                _vids = []
            else:
                _gallery_images = st.session_state.get("gallery_images", []) or []
                _gallery_videos = st.session_state.get("gallery_videos", []) or []
                _imgs = [
                    it for it in _gallery_images
                    if it.get("project_id") == _active_pid
                    and not (it.get("video_path") or it.get("kind") == "video")
                ]
                _vids = [
                    it for it in _gallery_videos
                    if it.get("project_id") == _active_pid
                ]
                _imgs = sorted(_imgs, key=lambda x: x.get("created_at", ""), reverse=True)
                _vids = sorted(_vids, key=lambda x: x.get("created_at", ""), reverse=True)

            _gal_tab_img, _gal_tab_vid = st.tabs(["Images", "Videos"])
            with _gal_tab_img:
                if not _imgs:
                    st.warning("No images in this project's gallery.")
                else:
                    _cols = st.columns(4)
                    for idx, item in enumerate(_imgs):
                        with _cols[idx % 4]:
                            _thumb = item.get("url") or item.get("image_path") or ""
                            if _thumb:
                                try:
                                    st.image(_thumb, use_container_width=True)
                                except Exception:
                                    st.caption("Preview unavailable")
                            if st.button("Select", key=f"_lab_pick_gallery_img_{idx}", use_container_width=True):
                                st.session_state["_lab_selected_media"] = {"source": "gallery", "data": item, "kind": "image"}
                                st.session_state["_lab_active_picker"] = None
                                st.rerun()
            with _gal_tab_vid:
                if not _vids:
                    st.warning("No videos in this project's gallery.")
                else:
                    _cols = st.columns(3)
                    for idx, item in enumerate(_vids):
                        with _cols[idx % 3]:
                            _vsrc = item.get("video_path") or item.get("url") or ""
                            _lfp = item.get("last_frame_path")
                            if _lfp and os.path.exists(_lfp):
                                try:
                                    st.image(_lfp, use_container_width=True)
                                except Exception:
                                    if _vsrc:
                                        st.video(_vsrc)
                            elif _vsrc:
                                try:
                                    st.video(_vsrc)
                                except Exception:
                                    st.caption("Preview unavailable")
                            else:
                                st.caption("No video source")
                            st.caption((item.get("caption") or "Video")[:40])
                            if st.button("Select", key=f"_lab_pick_gallery_vid_{idx}", use_container_width=True):
                                st.session_state["_lab_selected_media"] = {"source": "gallery", "data": item, "kind": "video"}
                                st.session_state["_lab_active_picker"] = None
                                st.rerun()

    # ── PICKER: ASSETS ──
    elif _active_picker == "assets":
        with st.container():
            try:
                _catalog = load_asset_catalog()
            except Exception:
                _catalog = []
            _assets_pid = st.session_state.get("active_project_id")
            _all_assets = [a for a in _catalog if a.get("path") and os.path.exists(a["path"])]
            if _assets_pid:
                _all_assets = [a for a in _all_assets if a.get("project_id") == _assets_pid]
            _img_assets = [
                a for a in _all_assets
                if a.get("type") == "image"
                or os.path.splitext(a.get("path", ""))[1].lower() in _LAB_IMG_EXTS
            ]
            _vid_assets = [
                a for a in _all_assets
                if a.get("type") == "video"
                or os.path.splitext(a.get("path", ""))[1].lower() in _LAB_VID_EXTS
            ]

            _ast_tab_img, _ast_tab_vid = st.tabs(["Images", "Videos"])
            with _ast_tab_img:
                if not _img_assets:
                    st.warning("No image assets in the catalog.")
                else:
                    _cols = st.columns(4)
                    for idx, asset in enumerate(_img_assets):
                        with _cols[idx % 4]:
                            try:
                                st.image(asset["path"], use_container_width=True)
                            except Exception:
                                st.caption("Preview unavailable")
                            if st.button("Select", key=f"_lab_pick_asset_img_{idx}", use_container_width=True):
                                st.session_state["_lab_selected_media"] = {"source": "assets", "data": asset, "kind": "image"}
                                st.session_state["_lab_active_picker"] = None
                                st.rerun()
            with _ast_tab_vid:
                if not _vid_assets:
                    st.warning("No video assets in the catalog.")
                else:
                    _cols = st.columns(3)
                    for idx, asset in enumerate(_vid_assets):
                        with _cols[idx % 3]:
                            try:
                                st.video(asset["path"])
                            except Exception:
                                st.caption("Preview unavailable")
                            st.caption((asset.get("name") or asset.get("id") or "Video")[:40])
                            if st.button("Select", key=f"_lab_pick_asset_vid_{idx}", use_container_width=True):
                                st.session_state["_lab_selected_media"] = {"source": "assets", "data": asset, "kind": "video"}
                                st.session_state["_lab_active_picker"] = None
                                st.rerun()

    # ── PICKER: UPLOAD FROM DESKTOP ──
    elif _active_picker == "upload":
        _up = st.file_uploader(
            "Choose an image or video file",
            type=["jpg", "jpeg", "png", "webp", "mp4", "mov", "webm"],
            accept_multiple_files=False,
            key="_lab_uploader",
        )
        if _up is not None:
            _cached = CachedUploadedFile(_up.name, _up.getvalue(), _up.type)
            _bytes = _cached.getvalue()
            _ext = os.path.splitext(_cached.name)[1].lower() or ".png"
            _is_vid = _ext in _LAB_VID_EXTS
            _digest = hashlib.md5(_bytes).hexdigest()[:16]
            _subdir = "videos" if _is_vid else "images"
            _dest_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "assets", _subdir)
            os.makedirs(_dest_dir, exist_ok=True)
            _dest_path = os.path.join(_dest_dir, f"{_digest}{_ext}")
            if not os.path.exists(_dest_path):
                try:
                    with open(_dest_path, "wb") as _f:
                        _f.write(_bytes)
                except Exception:
                    st.warning("Could not save the uploaded file.")
            st.session_state["_lab_selected_media"] = {
                "source": "upload",
                "data": {"path": _dest_path, "filename": _cached.name},
                "kind": "video" if _is_vid else "image",
            }
            st.session_state["_lab_active_picker"] = None
            st.rerun()


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
        div[data-testid="stTextInput"]:has(input[aria-label="gal_rat_bridge_inp"]),
        div[data-testid="stTextInput"]:has(input[aria-label="assets_rat_bridge_inp"]),
        div[data-testid="stTextInput"]:has(input[aria-label="refs_pexels_sel_bridge"]),
        div[data-testid="stTextInput"]:has(input[aria-label="refs_unsplash_sel_bridge"]),
        div[data-testid="stTextInput"]:has(input[aria-label="gallery_action_input_img"]),
        div[data-testid="stTextInput"]:has(input[aria-label="proj_pick_bridge"]),
        div[data-testid="stTextInput"]:has(input[aria-label="sb_pick_bridge"]),
        div[data-testid="stTextInput"]:has(input[aria-label="ed_pick_bridge"]),
        div[data-testid="stTextInput"]:has(input[aria-label="ed_sync_bridge"]),
        div[data-testid="stTextInput"]:has(input[aria-label="ed_export_bridge"]),
        div[data-testid="stTextInput"]:has(input[aria-label^="sb_action_input_"]) {
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
    if 'gallery_selected_ordered' not in st.session_state:
        st.session_state.gallery_selected_ordered = []
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
        if repair_gallery_media_paths(loaded_videos, loaded_images):
            save_gallery_to_disk(loaded_videos, loaded_images)
        if 'gallery_videos' not in st.session_state: st.session_state.gallery_videos = loaded_videos
        if 'gallery_images' not in st.session_state: st.session_state.gallery_images = loaded_images
    if 'active_page' not in st.session_state: st.session_state.active_page = 'console'
    # Detect return to Console from another page (Assets, Gallery, …)
    _prev_page = st.session_state.get("_prev_active_page", "console")
    _curr_page = st.session_state.get("active_page", "console")
    if _curr_page == "console" and _prev_page not in ("console", None):
        st.session_state["_console_was_away"] = True
    st.session_state["_prev_active_page"] = _curr_page
    _lab_pending_desc = st.session_state.pop("_lab_pending_action_desc", None)
    _restore_console_param_snapshot()
    if _lab_pending_desc is not None:
        st.session_state["action_desc_s2"] = _lab_pending_desc
        _snap = st.session_state.get("_console_param_snapshot")
        if isinstance(_snap, dict):
            _snap["action_desc_s2"] = _lab_pending_desc
    if 'model_selector' not in st.session_state: st.session_state.model_selector = 'SEEDANCE 2.0'
    if 'video_resolution' not in st.session_state: st.session_state.video_resolution = "1080p"
    if 'video_aspect_ratio' not in st.session_state: st.session_state.video_aspect_ratio = "adaptive"
    if 'common_duration' not in st.session_state: st.session_state.common_duration = 15
    if 's2_smart_duration' not in st.session_state: st.session_state.s2_smart_duration = False
    if 's2_watermark' not in st.session_state: st.session_state.s2_watermark = False
    if 's2_speed_mode' not in st.session_state: st.session_state.s2_speed_mode = "Standard"
    if 's2_seed_mode' not in st.session_state: st.session_state.s2_seed_mode = "🎲 New variation"
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

    elif st.session_state.get("active_page") == "lab":
        render_lab_page()

    else:
        render_console_page()
