import json
import os
import random
import time
from datetime import datetime

import streamlit as st

from arkitect.clip_naming import clip_meta_json_path
from arkitect.shared import CachedUploadedFile, AssetFile, _materialize_multi_file_upload
from arkitect.storage import (
    add_to_assets,
    get_active_project_id,
    get_active_project_name,
    load_asset_catalog,
    save_gallery_to_disk,
)
from arkitect.tone_pills import render_tone_pills_section
from arkitect.console_state import (
    _CONSOLE_SNAPSHOT_SKIP,
    _clear_console_param_keys,
    _delete_project_console_settings,
    _save_console_param_snapshot,
    _save_project_console_settings,
    consume_assets_to_console_pending,
    consume_assets_to_console_pending_seedream,
    build_console_reference_tag_map,
)
from arkitect.media_server import _STATIC_SERVING_OK, _STATIC_SERVING_SUPPORTED
from arkitect.ratings import set_rating_for_item
from builder import build_prompt as build_video_prompt, analyze_cinematography, build_image_prompt
from generator import (
    SEEDANCE_2_0_MODEL_ID,
    SEEDANCE_2_0_FAST_MODEL_ID,
    SEEDREAM_5_0_LITE_MODEL_ID,
    generate_video,
    generate_seedream_image,
    format_video_generation_failure,
    estimate_cost,
    format_cost_str,
    _estimate_seedance2_usage,
)

GENERATION_ENABLED = True

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
        data.update(render_tone_pills_section(k))
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

def _resolve_s2_seed_for_generate() -> str:
    """Resolve seed for the next 2.0 generation (API accepts int or -1 for random)."""
    manual = (st.session_state.get("s2_seed_manual") or "").strip()
    if manual:
        return manual
    if st.session_state.get("s2_lock_seed"):
        last = st.session_state.get("s2_last_seed")
        if last is not None:
            return str(last)
    return str(random.randint(1, 2147483647))

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
            "speed": kwargs.get("speed", "Standard"),
        }
        settings["seeds"] = kwargs.get("seeds", [])
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
        settings["creativity"] = {
            "num_variations": kwargs.get("num_variations", 1),
            "variation_mode": kwargs.get("variation_mode", "Independent (per seed)"),
            "seeds": kwargs.get("seeds", []),
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


def _render_s2_generation_error_box():
    """Persistent error panel below GENERATE (survives st.rerun)."""
    err = st.session_state.get("s2_generation_error")
    if not err:
        return
    title = err.get("title", "Video generation failed") if isinstance(err, dict) else str(err)
    details = err.get("details", []) if isinstance(err, dict) else [str(err)]
    st.markdown(
        '<div class="generation-error-box" style="margin-top:12px; padding:12px 14px; '
        'border:1px solid #c62828; border-radius:8px; background:rgba(198,40,40,0.08);">',
        unsafe_allow_html=True,
    )
    st.markdown(f"**{title}**")
    for line in details:
        st.markdown(f"- {line}")
    warnings = err.get("warnings", []) if isinstance(err, dict) else []
    for line in warnings:
        st.markdown(f"- ⚠️ {line}")
    st.markdown("</div>", unsafe_allow_html=True)


def render_console_page():
    """Render the Console page — model params, preview, generate."""

    # Apply Assets → Console transfer before any widgets (avoids session_state key conflicts)
    _applied_from_assets, _assets_msg = consume_assets_to_console_pending()
    _applied_from_assets_sd, _assets_msg_sd = consume_assets_to_console_pending_seedream()

    model_sel = st.session_state.get("model_selector", "SEEDANCE 2.0")
    if _applied_from_assets:
        model_sel = "SEEDANCE 2.0"
    elif _applied_from_assets_sd:
        model_sel = "SEEDREAM 5.0"
        st.toast(f"📷 Loaded {_assets_msg_sd}")
    total_files = num_imgs = num_vids = num_auds = 0
    action_desc = ""
    shots_data = []
    s2_workflow = "Standard Generation"
    image_usage = "auto"
    duration = 15
    s2_speed = "Standard"
    resolution = "1080p"
    aspect_ratio = "16:9"
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

    if st.session_state.get("_console_reset_pending"):
        del st.session_state["_console_reset_pending"]
        _delete_project_console_settings(st.session_state.get("active_project_id"))
        _clear_console_param_keys()
        for k in (
            "action_desc_s2", "sd_prompt_input",
            "s2_opt_prompt", "s2_raw_prompt",
            "sd_opt_prompt", "sd_raw_prompt",
            "json_preview", "_json_dict",
            "s2_last_result", "sd_last_result",
            "show_generate_button", "_preview_feedback",
            "_do_preview_s2", "_do_preview_sd",
            "_do_generate_s2", "_do_generate_sd",
            "canvas_prompt_editor",
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
            "_console_was_away", "_console_just_restored",
            "s2_generation_error",
            "assets_selected_ordered",
            "s2_seed_manual", "s2_seed_mode",
        ):
            st.session_state.pop(k, None)
        for i in range(15):
            st.session_state.pop(f"sd_seed_input_{i}", None)
        st.session_state["_console_param_snapshot"] = {}
        st.rerun()

    left_col, center_col, right_col = st.columns([1, 2, 1], vertical_alignment="top")

    with left_col:
        with st.expander("MODELS", expanded=False):
            # Handle programmatic switch from Seedream → Seedance
            if st.session_state.pop("_switch_to_seedance", False):
                _model_default_idx = 0  # SEEDANCE 2.0
            elif st.session_state.pop("_switch_to_seedream", False):
                _model_default_idx = 1  # SEEDREAM 5.0
            else:
                _model_options = ["SEEDANCE 2.0", "SEEDREAM 5.0"]
                _current = st.session_state.get("model_selector", "SEEDANCE 2.0")
                _model_default_idx = _model_options.index(_current) if _current in _model_options else 0
            st.radio("Model", ["SEEDANCE 2.0", "SEEDREAM 5.0"],
                     index=_model_default_idx,
                     key="model_selector",
                     label_visibility="collapsed",
                     horizontal=False)

        with st.expander("WORKFLOW", expanded=False):
            if model_sel == "SEEDANCE 2.0":
                if _applied_from_assets and _assets_msg:
                    st.success(_assets_msg)
                s2_entry_point = st.radio("Entry Point", ["First Frame", "First and Last Frames", "All-in-One Reference"], key="s2_entry_point")
                is_first_last = s2_entry_point == "First and Last Frames"
                is_first_frame = s2_entry_point == "First Frame"
                if is_first_last:
                    s2_workflow = st.selectbox("Creation Workflow", ["Standard Generation"], key="s2_workflow_fl", disabled=True)
                elif is_first_frame:
                    s2_workflow = st.selectbox("Creation Workflow", ["Standard Generation"], key="s2_workflow_ff", disabled=True)
                else:
                    s2_workflow = st.selectbox(
                        "Creation Workflow",
                        ["Text to Video", "Standard Generation",
                         "Video Extension", "Video Editing"],
                        key="s2_workflow",
                    )

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
                    if s2_workflow == "Text to Video":
                        st.caption(
                            "Pure text generation — no reference images needed. "
                            "Describe your scene in detail for best results."
                        )
                        s2_images = []
                        s2_videos = []
                        s2_audio = []
                        num_imgs = 0
                        num_vids = 0
                        num_auds = 0
                        total_files = 0
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
                        # From Assets — images
                        _cat = load_asset_catalog()
                        _active_proj = get_active_project_id()
                        if _active_proj:
                            _cat = [a for a in _cat if a.get("project_id") == _active_proj]
                        _img_assets = [a for a in _cat if a["type"] == "image"]
                        _img_asset_files = []
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
                            for _lab in _img_selected:
                                _aid = _img_opts[_lab]
                                _a = next((x for x in _img_assets if x["id"] == _aid), None)
                                if _a and os.path.exists(_a["path"]):
                                    _img_asset_files.append(AssetFile(_a["path"], _a["name"], _a["mime"]))
                        if _s2_img_list or _img_asset_files:
                            s2_images = list(_s2_img_list) + list(_img_asset_files)
                            st.session_state["_cached_s2_images"] = s2_images
                        else:
                            s2_images = list(st.session_state.get("_cached_s2_images") or [])
                        if s2_images and not _s2_img_list and not _img_asset_files:
                            st.caption(f"Loaded from session: {', '.join(f.name for f in s2_images)}")
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
                        # From Assets — videos
                        _vid_assets = [a for a in _cat if a["type"] == "video"]
                        _vid_asset_files = []
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
                            for _lab in _vid_selected:
                                _aid = _vid_opts[_lab]
                                _a = next((x for x in _vid_assets if x["id"] == _aid), None)
                                if _a and os.path.exists(_a["path"]):
                                    _vid_asset_files.append(AssetFile(_a["path"], _a["name"], _a["mime"]))
                        if _s2_vid_list or _vid_asset_files:
                            s2_videos = list(_s2_vid_list) + list(_vid_asset_files)
                            st.session_state["_cached_s2_videos"] = s2_videos
                        else:
                            s2_videos = list(st.session_state.get("_cached_s2_videos") or [])
                        if s2_videos and not _s2_vid_list and not _vid_asset_files:
                            st.caption(f"Loaded from session: {', '.join(f.name for f in s2_videos)}")
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
                        # From Assets — audio
                        _aud_assets = [a for a in _cat if a["type"] == "audio"]
                        _aud_asset_files = []
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
                            for _lab in _aud_selected:
                                _aid = _aud_opts[_lab]
                                _a = next((x for x in _aud_assets if x["id"] == _aid), None)
                                if _a and os.path.exists(_a["path"]):
                                    _aud_asset_files.append(AssetFile(_a["path"], _a["name"], _a["mime"]))
                        if _s2_aud_list or _aud_asset_files:
                            s2_audio = list(_s2_aud_list) + list(_aud_asset_files)
                            st.session_state["_cached_s2_audio"] = s2_audio
                        else:
                            s2_audio = list(st.session_state.get("_cached_s2_audio") or [])
                        if s2_audio and not _s2_aud_list and not _aud_asset_files:
                            st.caption(f"Loaded from session: {', '.join(f.name for f in s2_audio)}")
                        num_imgs = len(s2_images) if s2_images else 0
                        num_vids = len(s2_videos) if s2_videos else 0
                        num_auds = len(s2_audio) if s2_audio else 0
                        total_files = num_imgs + num_vids + num_auds

                # Safety net: all-in-one only — if uploads are empty on rerun, restore from session cache
                if (
                    not is_first_last
                    and not is_first_frame
                    and st.session_state.get("s2_workflow") != "Text to Video"
                ):
                    _seedream_ref = st.session_state.pop("_seedream_to_seedance_ref", None)
                    if _seedream_ref is not None:
                        s2_images = [_seedream_ref]
                        st.session_state["_cached_s2_images"] = [_seedream_ref]
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

                # Image usage — after cache safety net so num_imgs reflects loaded references
                if (
                    not is_first_last
                    and not is_first_frame
                    and st.session_state.get("s2_workflow") != "Text to Video"
                ):
                    if num_imgs > 0 and "Video Extension" not in st.session_state.get("s2_workflow", ""):
                        image_usage = st.selectbox(
                            "Image usage",
                            ["auto", "first_frame", "reference_only", "composite"],
                            format_func=lambda x: {"auto": "Auto", "first_frame": "First frame", "reference_only": "Reference only", "composite": "Composite"}[x],
                            key="s2_image_usage",
                        )
                    elif num_imgs > 0:
                        image_usage = st.session_state.get("s2_image_usage", image_usage)

                    if (num_vids or num_auds) and image_usage == "first_frame":
                        st.error(
                            "Reference videos/audio cannot be combined with Image usage “First frame”. "
                            "Remove media, choose Reference only, or use Entry Point “First Frame”."
                        )
                    elif (num_vids or num_auds) and num_imgs == 1 and image_usage == "auto":
                        st.info(
                            "One image with reference video/audio: the image is sent as a reference "
                            "(not locked as first frame), per Seedance API rules."
                        )

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
                _ref_cat = load_asset_catalog()
                _ref_proj = get_active_project_id()
                if _ref_proj:
                    _ref_cat = [a for a in _ref_cat if a.get("project_id") == _ref_proj]
                st.session_state["_console_ref_tag_map"] = (
                    build_console_reference_tag_map(_ref_cat) if total_files > 0 else {}
                )

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
                _cat = load_asset_catalog()
                _active_proj = get_active_project_id()
                if _active_proj:
                    _cat = [a for a in _cat if a.get("project_id") == _active_proj]
                _img_assets = [a for a in _cat if a["type"] == "image"]
                _sd_af = []
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
                    for _lab in _sd_sel:
                        _aid = _sd_opts[_lab]
                        _a = next((x for x in _img_assets if x["id"] == _aid), None)
                        if _a and os.path.exists(_a["path"]):
                            _sd_af.append(AssetFile(_a["path"], _a["name"], _a["mime"]))
                if _sd_refs_list or _sd_af:
                    sd_refs = list(_sd_refs_list) + list(_sd_af)
                    st.session_state["_cached_sd_refs"] = sd_refs
                else:
                    sd_refs = list(st.session_state.get("_cached_sd_refs") or [])
                if sd_refs and not _sd_refs_list and not _sd_af:
                    st.caption(f"Loaded from session: {', '.join(f.name for f in sd_refs)}")
                sd_style = st.selectbox("Visual Style Preset", ["None (Raw Prompt)", "Cinematic: Kodak Portra 400 (Nostalgic)", "Design: Guochao Neo-Chinese (Red & Gold)", "Artistic: Chinese Origami Figures", "Artistic: Transparent Ice Sculptures", "Design: 2D Pixel Art (Top-Down)", "Design: Abstract Futuristic (Liquid Silver)", "Artistic: Monet Impressionism (Thick Oil)", "Education: Hand-drawn Infographic"], key="sd_style_select", label_visibility="collapsed")
                # ── Reference tag info (after uploaders + From Assets) ──
                if sd_refs:
                    st.info(f"Attached {len(sd_refs)} reference image(s).")
                st.session_state["_console_ref_tag_map"] = (
                    build_console_reference_tag_map(_cat) if sd_refs else {}
                )

        if st.button("PROJECTS", key="top_projects_btn", use_container_width=True):
            _save_console_param_snapshot()
            _save_project_console_settings()
            st.session_state["_console_was_away"] = True
            st.session_state.active_page = "projects"
            st.rerun()

        if st.button("ASSETS", key="top_assets_btn", use_container_width=True):
            _save_console_param_snapshot()
            _save_project_console_settings()
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
                f"Streamlit {st.__version__} doesn't support static serving. Upgrade: pip install --upgrade streamlit --break-system-packages"
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

                # Auto-sync Duration slider to max shot end time
                _duration_synced_now = False
                if shots_data:
                    _max_shot_end = 0
                    for _shot in shots_data:
                        _m1_end = _shot.get('m1_end') or 0
                        _m2_end = _shot.get('m2_end') or 0
                        _max_shot_end = max(_max_shot_end, int(_m1_end), int(_m2_end))
                    if _max_shot_end >= 4:
                        # Clamp to valid range [4, 15]
                        _max_shot_end = min(max(_max_shot_end, 4), 15)
                        _prev_duration = st.session_state.get('common_duration')
                        if _prev_duration != _max_shot_end:
                            st.session_state['common_duration'] = _max_shot_end
                            st.session_state["_duration_auto_synced"] = {"from": _prev_duration, "to": _max_shot_end}
                            _duration_synced_now = True
                if not _duration_synced_now:
                    st.session_state.pop("_duration_auto_synced", None)
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
                _sd_img_path = None
                _sd_img_url = None
                if data.get("batch") and r.get("images"):
                    for im in r["images"]:
                        if not im.get("error"):
                            img_src = im.get("image_path") if im.get("image_path") and os.path.exists(im.get("image_path", "")) else im.get("image_url")
                            if img_src:
                                st.image(img_src, width="stretch")
                            if _sd_img_path is None:
                                _sd_img_path = im.get("image_path")
                                _sd_img_url = im.get("image_url")
                elif r.get("image_url"):
                    st.image(r["image_url"], width="stretch")
                    _sd_img_path = r.get("image_path")
                    _sd_img_url = r.get("image_url")

                if st.button(
                    "ANIMATE WITH SEEDANCE",
                    key="animate_with_seedance_btn",
                    use_container_width=True,
                    type="primary"
                ):
                    try:
                        # Determine source path — prefer local file over URL
                        _src_path = None
                        _src_url = None
                        if _sd_img_path and os.path.exists(_sd_img_path):
                            _src_path = _sd_img_path
                        elif _sd_img_url:
                            _src_url = _sd_img_url

                        # Save to project Assets
                        _active_pid = st.session_state.get("active_project_id")
                        _asset_result = add_to_assets(
                            source_path=_src_path,
                            original_name=f"seedream_character_{int(time.time())}.jpg",
                            provenance={
                                "source": "seedream_5_0",
                                "prompt": st.session_state.get("sd_opt_prompt", "")[:200],
                                "style": st.session_state.get("sd_style_select", ""),
                                "project_id": _active_pid,
                            }
                        )

                        # Build CachedUploadedFile from the saved asset path
                        _asset_path = _asset_result.get("path") if isinstance(_asset_result, dict) else _src_path
                        if _asset_path and os.path.exists(_asset_path):
                            with open(_asset_path, "rb") as _f:
                                _img_bytes = _f.read()
                        elif _src_url:
                            import requests as _req
                            _r = _req.get(_src_url, timeout=30)
                            _r.raise_for_status()
                            _img_bytes = _r.content
                        else:
                            raise ValueError("No image source available")

                        _cached_char = CachedUploadedFile(
                            name=os.path.basename(_asset_path or f"seedream_{int(time.time())}.jpg"),
                            data=_img_bytes,
                            mime_type="image/jpeg"
                        )

                        # Switch to SEEDANCE 2.0 (via flag — avoid mutating model_selector after widget exists)
                        st.session_state["_switch_to_seedance"] = True

                        # Pre-load as reference @Image 1
                        st.session_state["_seedream_to_seedance_ref"] = _cached_char
                        st.session_state["s2_entry_point"] = "All-in-One Reference"
                        st.session_state["s2_image_usage"] = "reference_only"

                        # Clear previous Seedance state
                        st.session_state.pop("s2_last_result", None)
                        st.session_state.pop("s2_opt_prompt", None)
                        st.session_state.pop("s2_raw_prompt", None)

                        st.success(f"Image saved to Assets and loaded as @Image 1 in Seedance 2.0")
                        st.rerun()

                    except Exception as _ae:
                        st.error(f"Failed to transfer image to Seedance: {_ae}")
                        import traceback
                        traceback.print_exc()
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
            st.session_state.pop("s2_generation_error", None)
            if not has_prompt and not has_result:
                if st.session_state.get("json_preview"):
                    st.session_state["_preview_feedback"] = "⚠️ Press PREVIEW PROMPT to build an optimized prompt from your current settings."
                else:
                    st.session_state["_preview_feedback"] = "⚠️ Press PREVIEW PROMPT first."
            elif model_sel == "SEEDANCE 2.0":
                st.session_state["_do_generate_s2"] = True
            else:
                st.session_state["_do_generate_sd"] = True

        _render_s2_generation_error_box()

    with right_col:
        with st.expander("TECHNICAL", expanded=False):
            if model_sel == "SEEDANCE 2.0":
                if st.session_state.get("video_resolution") not in ("480p", "720p", "1080p"):
                    st.session_state["video_resolution"] = "1080p"
                if st.session_state.get("video_aspect_ratio") not in ("16:9", "9:16", "4:3", "3:4", "21:9", "1:1", "adaptive"):
                    st.session_state["video_aspect_ratio"] = "adaptive"
                resolution = st.selectbox("Quality", ["480p", "720p", "1080p"], key="video_resolution")
                aspect_ratio = st.selectbox("Aspect Ratio", ["16:9", "9:16", "4:3", "3:4", "21:9", "1:1", "adaptive"], key="video_aspect_ratio")
                _duration_slider = st.slider("Duration (s)", min_value=4, max_value=15, step=1, key="common_duration")
                _sync_info = st.session_state.get("_duration_auto_synced")
                if _sync_info:
                    _from = _sync_info.get("from")
                    _to = _sync_info.get("to")
                    if _from is None:
                        st.caption(f"⏱ Duration auto-set to {_to}s to fit shot timeline")
                    else:
                        st.caption(f"⏱ Duration auto-adjusted from {_from}s to {_to}s to fit shot timeline")
                _smart_duration = st.checkbox("Smart Duration (-1)", key="s2_smart_duration")
                duration = -1 if _smart_duration else _duration_slider
                s2_speed = st.selectbox(
                    "Speed",
                    ["Standard", "Fast"],
                    key="s2_speed_mode",
                    help="Standard: full-quality model. Fast: accelerated model.",
                )
                st.checkbox("Watermark", key="s2_watermark")
            else:
                sd_resolution = st.selectbox("Resolution", ["3K", "2K"], key="sd_resolution")
                sd_ar = st.selectbox("Aspect Ratio", ["Smart", "1:1", "3:4", "4:3", "16:9", "9:16", "2:3", "3:2", "21:9"], key="sd_ar_select")

        with st.expander("SEEDS", expanded=False):
            if model_sel == "SEEDANCE 2.0":
                _seed_mode = st.radio(
                    "Seed",
                    ["🎲 New variation", "🔒 Lock take"],
                    horizontal=True,
                    key="s2_seed_mode",
                )
                st.session_state["s2_lock_seed"] = (_seed_mode == "🔒 Lock take")
                if st.session_state.get("s2_lock_seed"):
                    _ls = st.session_state.get("s2_last_seed")
                    if _ls is not None:
                        st.caption(f"Locked seed: {_ls}")
                    else:
                        st.caption("Nessun take precedente — la prima generazione userà un seed nuovo.")
                with st.expander("Seed avanzato", expanded=False):
                    st.text_input(
                        "Seed manuale",
                        key="s2_seed_manual",
                        placeholder="Vuoto = usa modalità sopra. Range 0–2147483647.",
                        help="Override esplicito; ha priorità su New variation / Lock take.",
                    )
            else:
                sd_optimize = st.selectbox(
                    "Optimize prompt",
                    ["None", "standard", "fast"],
                    key="sd_optimize",
                    help="API-side prompt refinement (standard = higher quality, fast = quicker).",
                )
                _sd_ref_n = len(sd_refs) if sd_refs else 0
                _sd_max_var = max(1, min(15, 15 - _sd_ref_n))
                if st.session_state.get("sd_num_variations", 1) > _sd_max_var:
                    st.session_state["sd_num_variations"] = _sd_max_var
                sd_num_variations = st.number_input(
                    "Variations",
                    min_value=1,
                    max_value=_sd_max_var,
                    step=1,
                    key="sd_num_variations",
                    help=(
                        f"Number of images to generate. "
                        f"Reference images ({_sd_ref_n}) + variations must be ≤ 15."
                    ),
                )
                _sd_var_n = int(st.session_state.get("sd_num_variations", 1))
                if _sd_var_n > 1:
                    sd_variation_mode = st.radio(
                        "Variation mode",
                        ["Independent (per seed)", "Coherent series (1 batch)"],
                        key="sd_variation_mode",
                        horizontal=False,
                        help=(
                            "Independent: one API call per variation (each with its own seed). "
                            "Coherent series: one batch call — images share a coherent style/sequence."
                        ),
                    )
                else:
                    sd_variation_mode = st.session_state.get(
                        "sd_variation_mode", "Independent (per seed)"
                    )
                _sd_seed_cols = st.columns(min(_sd_var_n, 5))
                for _si in range(_sd_var_n):
                    with _sd_seed_cols[_si % 5]:
                        st.text_input(
                            f"Seed {_si + 1}",
                            key=f"sd_seed_input_{_si}",
                            placeholder="Random",
                            help="Leave empty for random. Range: 0–2147483647.",
                        )
                if st.button("↻ Randomize seeds", key="sd_randomize_seeds_btn", use_container_width=True):
                    for _si in range(_sd_var_n):
                        st.session_state[f"sd_seed_input_{_si}"] = str(
                            random.randint(0, 2147483647)
                        )
                    st.rerun()

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
            _save_console_param_snapshot()
            _save_project_console_settings()
            st.session_state["_console_was_away"] = True
            st.session_state.active_page = "gallery"
            st.rerun()
        if st.button("STORYBOARD", key="top_sb_images_btn", use_container_width=True):
            _save_console_param_snapshot()
            _save_project_console_settings()
            st.session_state["_console_was_away"] = True
            st.session_state.active_page = "storyboard"
            st.rerun()
        if st.button("REFERENCES", key="top_references_quick_btn", use_container_width=True):
            _save_console_param_snapshot()
            _save_project_console_settings()
            st.session_state["_console_was_away"] = True
            st.session_state.active_page = "references"
            st.rerun()
        if st.button("EDITING", key="top_sb_video_btn", use_container_width=True):
            _save_console_param_snapshot()
            _save_project_console_settings()
            st.session_state["_console_was_away"] = True
            st.session_state.active_page = "editing"
            st.rerun()
        if st.button("LAB", key="top_lab_btn", use_container_width=True):
            _save_console_param_snapshot()
            _save_project_console_settings()
            st.session_state["_console_was_away"] = True
            st.session_state.active_page = "lab"
            st.rerun()

    if json_clicked:
        if model_sel == "SEEDANCE 2.0":
            _seeds = [_resolve_s2_seed_for_generate()]
            _json = _build_settings_json(
                model_sel,
                action_desc=action_desc,
                entry_point=st.session_state.get("s2_entry_point", ""),
                workflow=s2_workflow,
                image_usage=image_usage,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                duration=duration,
                speed=s2_speed,
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
            _sd_var_n_json = int(st.session_state.get("sd_num_variations", 1))
            _sd_seeds_json = [
                st.session_state.get(f"sd_seed_input_{i}", "")
                for i in range(_sd_var_n_json)
            ]
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
                num_variations=_sd_var_n_json,
                variation_mode=st.session_state.get("sd_variation_mode", "Independent (per seed)"),
                seeds=_sd_seeds_json,
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
            _sd_var_cost = int(st.session_state.get("sd_num_variations", 1))
            _est_cost = estimate_cost(
                SEEDREAM_5_0_LITE_MODEL_ID, sd_resolution,
            ) * max(1, _sd_var_cost)
        if model_sel != "SEEDANCE 2.0":
            _sd_cost_lbl = format_cost_str(_est_cost)
            _sd_var_lbl = int(st.session_state.get("sd_num_variations", 1))
            _sd_cost_note = (
                f" × {_sd_var_lbl} variations" if _sd_var_lbl > 1 else ""
            )
            st.markdown(
                f'<p style="color:#FFEB3B;-webkit-text-fill-color:#FFEB3B;'
                f'font-size:0.85rem;font-weight:700;font-family:Open Sans,sans-serif;'
                f'margin:4px 0 0;padding:6px 10px;'
                f'background:rgba(255,235,59,0.08);border-radius:4px;'
                f'border-left:3px solid #FFEB3B;">'
                f'Estimated cost: {_sd_cost_lbl}{_sd_cost_note}</p>',
                unsafe_allow_html=True,
            )

    # S2.0 preview
    if model_sel == "SEEDANCE 2.0" and st.session_state.get("_do_preview_s2"):
        # Clear previous result so canvas shows new prompt
        st.session_state.pop("s2_last_result", None)
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
                        "duration": duration, "shots_data": shots_data,
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
        st.session_state["_do_generate_s2"] = False  # Reset immediately to prevent double-generation
        if not GENERATION_ENABLED:
            st.warning("Generation temporarily disabled (demo mode). Preview Prompt is active.")
            st.session_state["_do_generate_s2"] = False
        else:
            chosen_prompt = st.session_state.get("s2_opt_prompt", "")
            print(f"[DEBUG-GEN-S2] s2_images={len(s2_images) if s2_images else 0}, s2_videos={len(s2_videos) if s2_videos else 0}, s2_audio={len(s2_audio) if s2_audio else 0}, workflow={s2_workflow}")
            if s2_images:
                for _i, _img in enumerate(s2_images):
                    _has_getval = hasattr(_img, 'getvalue')
                    _has_name = hasattr(_img, 'name')
                    _type = type(_img).__name__
                    print(f"[DEBUG-IMG-{_i}] type={_type}, has_getvalue={_has_getval}, has_name={_has_name}, value={str(_img)[:80] if not _has_getval else 'file_obj'}")
            with st.spinner("Generating Seedance 2.0... please wait 3-5 minutes"):
                print(f"[DEBUG-PRE-GENERATE] About to call generate_video, images type: {type(s2_images)}, first image type: {type(s2_images[0]) if s2_images else 'none'}")
                _s2_seed_used = _resolve_s2_seed_for_generate()
                _s2_model_id = (
                    SEEDANCE_2_0_FAST_MODEL_ID
                    if st.session_state.get("s2_speed_mode", "Standard") == "Fast"
                    else SEEDANCE_2_0_MODEL_ID
                )
                try:
                    result = generate_video(
                        prompt_text=chosen_prompt, scene_description=(action_desc or "")[:20],
                        full_scene_description=(action_desc or "").strip(),
                        images=s2_images, videos=s2_videos, audios=s2_audio,
                        image_usage=image_usage,
                        seed=_s2_seed_used,
                        resolution=resolution, aspect_ratio=aspect_ratio, duration=duration,
                        generate_audio=(gen_audio or st.session_state.get("s2_audio_output", False)),
                        audio_details=audio_details_dict,
                        watermark=st.session_state.get("s2_watermark", False),
                        model_id=_s2_model_id, shots_data=shots_data,
                        project_name=get_active_project_name(),
                    )
                    print(f"[DEBUG-POST-GENERATE] result type={type(result).__name__}, value={str(result)[:200]}")
                except Exception as e:
                    print(f"[DEBUG-GENERATE-ERROR] {type(e).__name__}: {e}")
                    import traceback
                    traceback.print_exc()
                    result = {"error": str(e)}
                if isinstance(result, dict) and result.get("video"):
                    st.session_state.pop("s2_generation_error", None)
                    st.session_state.s2_last_result = result
                    try:
                        st.session_state["s2_last_seed"] = int(_s2_seed_used)
                    except (ValueError, TypeError):
                        pass
                    _s2_est_cost = estimate_cost(
                        _s2_model_id,
                        resolution,
                        duration,
                        gen_audio,
                        has_video_input=((num_vids or 0) > 0),
                    )
                    _actual_duration = result.get("duration") or result.get("actual_duration") or result.get("video_duration")
                    _duration_for_gallery = _actual_duration if _actual_duration is not None else duration

                    _seeds_payload = [_s2_seed_used] if _s2_seed_used else []

                    _audio_payload = {}
                    if gen_audio:
                        _audio_payload = {
                            "language": st.session_state.get("v_lang", ""),
                            "emotion": st.session_state.get("v_emo", ""),
                            "timbre": st.session_state.get("v_timbre", ""),
                            "pace": st.session_state.get("v_pace", ""),
                            "dialogue": st.session_state.get("s2_dialogue", ""),
                            "sfx": st.session_state.get("s2_sfx", ""),
                        }

                    _ref_labels = []
                    _s2_entry = st.session_state.get("s2_entry_point", "")
                    if _s2_entry == "First Frame":
                        _fo_lab = st.session_state.get("_persist_s2_assets_first_only")
                        if _fo_lab:
                            _ref_labels.append(_fo_lab)
                    elif _s2_entry == "First and Last Frames":
                        for _pk in ("_persist_s2_assets_first_frame", "_persist_s2_assets_last_frame"):
                            _plab = st.session_state.get(_pk)
                            if _plab:
                                _ref_labels.append(_plab)
                    else:
                        for _pk in (
                            "_persist_s2_assets_images",
                            "_persist_s2_assets_videos",
                            "_persist_s2_assets_audio",
                        ):
                            _plabs = st.session_state.get(_pk)
                            if isinstance(_plabs, list):
                                _ref_labels.extend(_plabs)
                            elif _plabs:
                                _ref_labels.append(_plabs)

                    _ref_catalog = load_asset_catalog()
                    _ref_proj = get_active_project_id()
                    if _ref_proj:
                        _ref_catalog = [a for a in _ref_catalog if a.get("project_id") == _ref_proj]
                    _ref_label_to_id = {
                        f"{a['name']} ({a.get('size_str', '')})": a["id"]
                        for a in _ref_catalog
                        if a.get("id")
                    }
                    _ref_asset_ids = [
                        _ref_label_to_id[lab] for lab in _ref_labels if lab in _ref_label_to_id
                    ]

                    _gallery_shots = []
                    for _shot in (shots_data or []):
                        _gs = dict(_shot)
                        _cp = _gs.get("color_palette")
                        if _cp and isinstance(_cp, list) and isinstance(_cp[0], tuple):
                            _gs["color_palette"] = [{"hex": h, "target": t} for h, t in _cp]
                        _gallery_shots.append(_gs)

                    _sidecar_path = ""
                    if result.get("video_path"):
                        _sidecar_path = clip_meta_json_path(result["video_path"])

                    _gv_entry = {
                        "url": result["video"],
                        "caption": (action_desc or "Seedance 2.0")[:50],
                        "prompt": chosen_prompt,
                        "resolution": resolution,
                        "duration": _duration_for_gallery,
                        "aspect_ratio": aspect_ratio,
                        "video_path": result.get("video_path"),
                        "last_frame_path": result.get("last_frame_path"),
                        "model": "Seedance 2.0",
                        "created_at": datetime.now().isoformat(),
                        "project_id": st.session_state.get("active_project_id"),
                        "estimated_cost": _s2_est_cost,
                        "scene_description": st.session_state.get("action_desc_s2", ""),
                        "raw_prompt": st.session_state.get("s2_raw_prompt", ""),
                        "optimized_prompt": chosen_prompt,
                        "entry_point": st.session_state.get("s2_entry_point", ""),
                        "workflow": s2_workflow,
                        "image_usage": image_usage,
                        "speed": s2_speed,
                        "watermark": st.session_state.get("s2_watermark", False),
                        "seeds": _seeds_payload,
                        "audio_enabled": gen_audio,
                        "audio_settings": _audio_payload,
                        "reference_asset_ids": _ref_asset_ids,
                        "shots_data": _gallery_shots,
                        "settings_sidecar_path": _sidecar_path,
                        "schema_version": "1",
                    }
                    st.session_state.gallery_videos.append(_gv_entry)
                    set_rating_for_item(_gv_entry, "green")
                    _settings = st.session_state.get("_json_dict")
                    if _settings is None:
                        _seeds_sv = [_s2_seed_used]
                        _settings = _build_settings_json(
                            "SEEDANCE 2.0",
                            action_desc=action_desc,
                            entry_point=st.session_state.get("s2_entry_point", ""),
                            workflow=s2_workflow,
                            image_usage=image_usage,
                            resolution=resolution,
                            aspect_ratio=aspect_ratio,
                            duration=duration,
                            speed=s2_speed,
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
                            _json_path = clip_meta_json_path(result["video_path"])
                            with open(_json_path, "w", encoding="utf-8") as _jf:
                                json.dump(_settings, _jf, indent=2, ensure_ascii=False)
                        except Exception:
                            pass
                    save_gallery_to_disk(st.session_state.gallery_videos, st.session_state.gallery_images)
                else:
                    st.session_state.s2_last_result = None
                    st.session_state["s2_generation_error"] = format_video_generation_failure(result)
            st.session_state["_do_generate_s2"] = False
            st.rerun()

    # Seedream preview
    if model_sel == "SEEDREAM 5.0" and st.session_state.get("_do_preview_sd"):
        # Clear previous result so canvas shows new prompt
        st.session_state.pop("sd_last_result", None)
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
            _sd_var_n_gen = int(st.session_state.get("sd_num_variations", 1))
            _sd_var_mode_gen = st.session_state.get("sd_variation_mode", "Independent (per seed)")
            _sd_seeds_gen = [
                st.session_state.get(f"sd_seed_input_{i}", "")
                for i in range(_sd_var_n_gen)
            ]
            _sd_gen_common = dict(
                prompt=final_prompt,
                ref_images=sd_refs if sd_refs else [],
                style_preset=sd_style,
                aspect_ratio=sd_ar,
                model_id=SEEDREAM_5_0_LITE_MODEL_ID,
                output_format="jpeg",
                optimize_prompt_mode=optimize_mode,
                resolution=sd_resolution,
                watermark=False,
                watermark_text=None,
                stream=False,
                project_name=get_active_project_name(),
            )
            with st.spinner(
                f"Seedream is processing ({_sd_var_n_gen} variation"
                f"{'' if _sd_var_n_gen == 1 else 's'})..."
            ):
                imgs = []
                _sd_errors = []
                if (
                    _sd_var_n_gen > 1
                    and _sd_var_mode_gen == "Coherent series (1 batch)"
                ):
                    result = generate_seedream_image(
                        **_sd_gen_common,
                        sequential="auto",
                        max_images=_sd_var_n_gen,
                        seed=_sd_seeds_gen[0] if _sd_seeds_gen else None,
                    )
                    if isinstance(result, dict):
                        if result.get("images"):
                            imgs.extend(result["images"])
                        elif result.get("image_url"):
                            imgs.append(result)
                    elif isinstance(result, str):
                        _sd_errors.append(result)
                else:
                    for _vi in range(_sd_var_n_gen):
                        _seed_v = _sd_seeds_gen[_vi] if _vi < len(_sd_seeds_gen) else ""
                        result = generate_seedream_image(
                            **_sd_gen_common,
                            sequential="disabled",
                            max_images=1,
                            seed=_seed_v,
                        )
                        if isinstance(result, dict):
                            if result.get("images"):
                                imgs.extend(result["images"])
                            elif result.get("image_url"):
                                imgs.append(result)
                            elif result.get("error"):
                                _sd_errors.append(str(result.get("error")))
                        elif isinstance(result, str):
                            _sd_errors.append(result)

                imgs = [im for im in imgs if isinstance(im, dict) and not im.get("error")]
                if imgs:
                    _batch = len(imgs) > 1
                    _result_payload = (
                        {"images": imgs} if _batch else imgs[0]
                    )
                    st.session_state.sd_last_result = {
                        "result": _result_payload,
                        "final_prompt": final_prompt,
                        "batch": _batch,
                    }
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
                            num_variations=_sd_var_n_gen,
                            variation_mode=_sd_var_mode_gen,
                            seeds=_sd_seeds_gen,
                            num_refs=len(sd_refs) if sd_refs else 0,
                        )
                    if _settings:
                        for im in imgs:
                            if im.get("image_path"):
                                try:
                                    _json_path = clip_meta_json_path(im["image_path"])
                                    with open(_json_path, "w", encoding="utf-8") as _jf:
                                        json.dump(_settings, _jf, indent=2, ensure_ascii=False)
                                except Exception:
                                    pass
                    for im in imgs:
                        _sd_est_cost = estimate_cost(SEEDREAM_5_0_LITE_MODEL_ID, sd_resolution)
                        _gi_entry = {
                            "url": im.get("image_url", ""),
                            "caption": (final_prompt or "Seedream 5.0")[:50],
                            "prompt": final_prompt,
                            "style": sd_style,
                            "aspect_ratio": sd_ar,
                            "resolution": sd_resolution,
                            "specs": {},
                            "image_path": im.get("image_path"),
                            "created_at": datetime.now().isoformat(),
                            "project_id": st.session_state.get("active_project_id"),
                            "estimated_cost": _sd_est_cost,
                        }
                        st.session_state.gallery_images.append(_gi_entry)
                        set_rating_for_item(_gi_entry, "green")
                    save_gallery_to_disk(st.session_state.gallery_videos, st.session_state.gallery_images)
                    if _sd_errors:
                        st.warning("Some variations failed: " + "; ".join(_sd_errors[:3]))
                else:
                    st.session_state.sd_last_result = None
                    st.error(
                        "Dream Failed: "
                        + (_sd_errors[0] if _sd_errors else "No images returned.")
                    )
            st.session_state["_do_generate_sd"] = False
            st.rerun()

    # Persist params after widgets render (navigation restore reads this snapshot).
    if not st.session_state.pop("_console_just_restored", False):
        _save_console_param_snapshot()
        _save_project_console_settings()
