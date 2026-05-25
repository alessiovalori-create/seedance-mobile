"""Discrete tone pill selectors for Console cinematography (Seedance 2.0)."""

import streamlit as st

# ── Look (grain, vignette, focus, DOF) ─────────────────────────────────────
TONE_PILL_GRAIN = ["None", "Subtle", "Moderate", "Heavy"]
TONE_PILL_VIGNETTE = ["None", "Light", "Heavy"]
TONE_PILL_FOCUS = ["Sharp", "Soft", "Dreamy"]
TONE_PILL_DOF = ["Deep", "Medium", "Shallow", "Extreme bokeh"]

_GRAIN_TO_NUM = {"None": 0, "Subtle": 5, "Moderate": 8, "Heavy": 9}
_VIGNETTE_TO_NUM = {"None": 0, "Light": 6, "Heavy": 9}
_FOCUS_TO_NUM = {
    "Sharp": {"tone_sharpness": 7, "tone_softness": 0},
    "Soft": {"tone_sharpness": 2, "tone_softness": 6},
    "Dreamy": {"tone_sharpness": 1, "tone_softness": 9},
}
_DOF_TO_NUM = {"Deep": 1, "Medium": 4, "Shallow": 7, "Extreme bokeh": 10}

_LOOK_DEFAULTS = {
    "grain": "None",
    "vignette": "None",
    "focus": "Sharp",
    "dof": "Medium",
}

# ── Exposure & color ───────────────────────────────────────────────────────
TONE_PILL_BRIGHTNESS = ["Dark", "Normal", "Bright", "High-key"]
TONE_PILL_CONTRAST = ["Flat", "Normal", "Strong", "Crushed"]
TONE_PILL_SATURATION = ["Muted", "Natural", "Vivid", "Hyper"]
TONE_PILL_TEMPERATURE = ["Cool", "Neutral", "Warm", "Golden"]
TONE_PILL_CHROMATIC = ["None", "Subtle", "Visible", "Heavy"]
TONE_PILL_MOTION = ["None", "Light", "Moderate", "Heavy"]

_BRIGHTNESS_TO_NUM = {"Dark": 2, "Normal": 5, "Bright": 7, "High-key": 9}
_CONTRAST_TO_NUM = {"Flat": 2, "Normal": 5, "Strong": 7, "Crushed": 9}
_SATURATION_TO_NUM = {"Muted": 2, "Natural": 5, "Vivid": 8, "Hyper": 10}
_TEMPERATURE_TO_NUM = {"Cool": 2, "Neutral": 5, "Warm": 7, "Golden": 9}
_CHROMATIC_TO_NUM = {"None": 0, "Subtle": 5, "Visible": 7, "Heavy": 9}
_MOTION_TO_NUM = {"None": 5, "Light": 6, "Moderate": 8, "Heavy": 9}

_EXPOSURE_DEFAULTS = {
    "brightness": "Normal",
    "contrast": "Normal",
    "saturation": "Natural",
    "temperature": "Neutral",
    "chromatic": "None",
    "motion": "None",
}


def _num_to_brightness_pill(n):
    try:
        v = int(float(n))
    except (TypeError, ValueError):
        return _EXPOSURE_DEFAULTS["brightness"]
    if v >= 8:
        return "High-key"
    if v >= 6:
        return "Bright"
    if v <= 2:
        return "Dark"
    return "Normal"


def _num_to_contrast_pill(n):
    try:
        v = int(float(n))
    except (TypeError, ValueError):
        return _EXPOSURE_DEFAULTS["contrast"]
    if v >= 8:
        return "Crushed"
    if v >= 6:
        return "Strong"
    if v <= 2:
        return "Flat"
    return "Normal"


def _num_to_saturation_pill(n):
    try:
        v = int(float(n))
    except (TypeError, ValueError):
        return _EXPOSURE_DEFAULTS["saturation"]
    if v >= 9:
        return "Hyper"
    if v >= 6:
        return "Vivid"
    if v <= 2:
        return "Muted"
    return "Natural"


def _num_to_temperature_pill(n):
    try:
        v = int(float(n))
    except (TypeError, ValueError):
        return _EXPOSURE_DEFAULTS["temperature"]
    if v >= 8:
        return "Golden"
    if v >= 6:
        return "Warm"
    if v <= 2:
        return "Cool"
    return "Neutral"


def _num_to_chromatic_pill(n):
    try:
        v = int(float(n))
    except (TypeError, ValueError):
        return _EXPOSURE_DEFAULTS["chromatic"]
    if v >= 8:
        return "Heavy"
    if v >= 6:
        return "Visible"
    if v >= 4:
        return "Subtle"
    return "None"


def _num_to_motion_pill(n):
    try:
        v = int(float(n))
    except (TypeError, ValueError):
        return _EXPOSURE_DEFAULTS["motion"]
    if v >= 8:
        return "Heavy"
    if v >= 6:
        return "Moderate"
    if v > 5:
        return "Light"
    return "None"


def _num_to_grain_pill(n):
    try:
        v = int(float(n))
    except (TypeError, ValueError):
        return _LOOK_DEFAULTS["grain"]
    if v >= 8:
        return "Heavy"
    if v >= 6:
        return "Moderate"
    if v >= 4:
        return "Subtle"
    return "None"


def _num_to_vignette_pill(n):
    try:
        v = int(float(n))
    except (TypeError, ValueError):
        return _LOOK_DEFAULTS["vignette"]
    if v >= 8:
        return "Heavy"
    if v >= 4:
        return "Light"
    return "None"


def _num_to_focus_pill(sharp, soft):
    try:
        s = int(float(sharp))
        o = int(float(soft))
    except (TypeError, ValueError):
        return _LOOK_DEFAULTS["focus"]
    if o >= 7:
        return "Dreamy"
    if s <= 2:
        return "Soft"
    return "Sharp"


def _num_to_dof_pill(n):
    try:
        v = int(float(n))
    except (TypeError, ValueError):
        return _LOOK_DEFAULTS["dof"]
    if v >= 9:
        return "Extreme bokeh"
    if v >= 6:
        return "Shallow"
    if v >= 3:
        return "Medium"
    return "Deep"


def sync_tone_pills_from_legacy(k: str):
    """Map old 0–10 slider session keys to pill labels (one-time migration)."""
    if f"{k}_pill_grain" not in st.session_state:
        if f"{k}_tg" in st.session_state:
            st.session_state[f"{k}_pill_grain"] = _num_to_grain_pill(st.session_state[f"{k}_tg"])
        else:
            st.session_state[f"{k}_pill_grain"] = _LOOK_DEFAULTS["grain"]
    if f"{k}_pill_vignette" not in st.session_state:
        if f"{k}_tv" in st.session_state:
            st.session_state[f"{k}_pill_vignette"] = _num_to_vignette_pill(st.session_state[f"{k}_tv"])
        else:
            st.session_state[f"{k}_pill_vignette"] = _LOOK_DEFAULTS["vignette"]
    if f"{k}_pill_focus" not in st.session_state:
        sharp = st.session_state.get(f"{k}_tsh", 5)
        soft = st.session_state.get(f"{k}_tso", 0)
        if f"{k}_tsh" in st.session_state or f"{k}_tso" in st.session_state:
            st.session_state[f"{k}_pill_focus"] = _num_to_focus_pill(sharp, soft)
        else:
            st.session_state[f"{k}_pill_focus"] = _LOOK_DEFAULTS["focus"]
    if f"{k}_pill_dof" not in st.session_state:
        if f"{k}_tbo" in st.session_state:
            st.session_state[f"{k}_pill_dof"] = _num_to_dof_pill(st.session_state[f"{k}_tbo"])
        else:
            st.session_state[f"{k}_pill_dof"] = _LOOK_DEFAULTS["dof"]

    if f"{k}_pill_brightness" not in st.session_state:
        if f"{k}_tb" in st.session_state:
            st.session_state[f"{k}_pill_brightness"] = _num_to_brightness_pill(st.session_state[f"{k}_tb"])
        else:
            st.session_state[f"{k}_pill_brightness"] = _EXPOSURE_DEFAULTS["brightness"]
    if f"{k}_pill_contrast" not in st.session_state:
        if f"{k}_tc" in st.session_state:
            st.session_state[f"{k}_pill_contrast"] = _num_to_contrast_pill(st.session_state[f"{k}_tc"])
        else:
            st.session_state[f"{k}_pill_contrast"] = _EXPOSURE_DEFAULTS["contrast"]
    if f"{k}_pill_saturation" not in st.session_state:
        if f"{k}_ts" in st.session_state:
            st.session_state[f"{k}_pill_saturation"] = _num_to_saturation_pill(st.session_state[f"{k}_ts"])
        else:
            st.session_state[f"{k}_pill_saturation"] = _EXPOSURE_DEFAULTS["saturation"]
    if f"{k}_pill_temperature" not in st.session_state:
        if f"{k}_tt" in st.session_state:
            st.session_state[f"{k}_pill_temperature"] = _num_to_temperature_pill(st.session_state[f"{k}_tt"])
        else:
            st.session_state[f"{k}_pill_temperature"] = _EXPOSURE_DEFAULTS["temperature"]
    if f"{k}_pill_chromatic" not in st.session_state:
        if f"{k}_tca" in st.session_state:
            st.session_state[f"{k}_pill_chromatic"] = _num_to_chromatic_pill(st.session_state[f"{k}_tca"])
        else:
            st.session_state[f"{k}_pill_chromatic"] = _EXPOSURE_DEFAULTS["chromatic"]
    if f"{k}_pill_motion" not in st.session_state:
        if f"{k}_tmb" in st.session_state:
            st.session_state[f"{k}_pill_motion"] = _num_to_motion_pill(st.session_state[f"{k}_tmb"])
        else:
            st.session_state[f"{k}_pill_motion"] = _EXPOSURE_DEFAULTS["motion"]


def _render_tone_pill_row(label: str, options: list, key: str, default: str, first_row: bool = False):
    margin_top = "4px" if first_row else "10px"
    cols = st.columns([1.15, 5], gap="small")
    with cols[0]:
        st.markdown(
            f'<p style="color:#9E9E8A; font-size:0.72rem; font-weight:600; '
            f'margin:{margin_top} 0 0 0; letter-spacing:0.04em;">{label}</p>',
            unsafe_allow_html=True,
        )
    with cols[1]:
        if key not in st.session_state:
            st.session_state[key] = default
        choice = st.radio(
            label,
            options,
            horizontal=True,
            key=key,
            label_visibility="collapsed",
        )
    return choice


def render_tone_pills_section(k: str) -> dict:
    """
    Render all Tones pill rows (look + exposure & color).
    Returns numeric tone_* fields for builder compatibility.
    """
    sync_tone_pills_from_legacy(k)
    out = {}

    grain_pill = _render_tone_pill_row(
        "Film Grain", TONE_PILL_GRAIN, f"{k}_pill_grain", _LOOK_DEFAULTS["grain"], first_row=True,
    )
    vig_pill = _render_tone_pill_row(
        "Vignette", TONE_PILL_VIGNETTE, f"{k}_pill_vignette", _LOOK_DEFAULTS["vignette"],
    )
    focus_pill = _render_tone_pill_row(
        "Focus", TONE_PILL_FOCUS, f"{k}_pill_focus", _LOOK_DEFAULTS["focus"],
    )
    dof_pill = _render_tone_pill_row(
        "DOF", TONE_PILL_DOF, f"{k}_pill_dof", _LOOK_DEFAULTS["dof"],
    )

    focus_nums = _FOCUS_TO_NUM.get(focus_pill, _FOCUS_TO_NUM["Sharp"])
    out.update({
        "tone_grain": _GRAIN_TO_NUM.get(grain_pill, 0),
        "tone_vignette": _VIGNETTE_TO_NUM.get(vig_pill, 0),
        "tone_sharpness": focus_nums["tone_sharpness"],
        "tone_softness": focus_nums["tone_softness"],
        "tone_bokeh": _DOF_TO_NUM.get(dof_pill, 4),
        "tone_grain_pill": grain_pill,
        "tone_vignette_pill": vig_pill,
        "tone_focus_pill": focus_pill,
        "tone_dof_pill": dof_pill,
    })

    st.markdown(
        '<p style="color:#7a7a6e; font-size:0.65rem; margin:16px 0 2px 0; '
        'letter-spacing:0.06em; text-transform:uppercase;">Exposure &amp; color</p>',
        unsafe_allow_html=True,
    )

    bright_pill = _render_tone_pill_row(
        "Brightness", TONE_PILL_BRIGHTNESS, f"{k}_pill_brightness",
        _EXPOSURE_DEFAULTS["brightness"], first_row=True,
    )
    contrast_pill = _render_tone_pill_row(
        "Contrast", TONE_PILL_CONTRAST, f"{k}_pill_contrast", _EXPOSURE_DEFAULTS["contrast"],
    )
    sat_pill = _render_tone_pill_row(
        "Saturation", TONE_PILL_SATURATION, f"{k}_pill_saturation", _EXPOSURE_DEFAULTS["saturation"],
    )
    temp_pill = _render_tone_pill_row(
        "Color Temp.", TONE_PILL_TEMPERATURE, f"{k}_pill_temperature", _EXPOSURE_DEFAULTS["temperature"],
    )
    chrom_pill = _render_tone_pill_row(
        "Chromatic", TONE_PILL_CHROMATIC, f"{k}_pill_chromatic", _EXPOSURE_DEFAULTS["chromatic"],
    )
    motion_pill = _render_tone_pill_row(
        "Motion Blur", TONE_PILL_MOTION, f"{k}_pill_motion", _EXPOSURE_DEFAULTS["motion"],
    )

    out.update({
        "tone_brightness": _BRIGHTNESS_TO_NUM.get(bright_pill, 5),
        "tone_contrast": _CONTRAST_TO_NUM.get(contrast_pill, 5),
        "tone_saturation": _SATURATION_TO_NUM.get(sat_pill, 5),
        "tone_temperature": _TEMPERATURE_TO_NUM.get(temp_pill, 5),
        "tone_chromatic": _CHROMATIC_TO_NUM.get(chrom_pill, 0),
        "tone_motionblur": _MOTION_TO_NUM.get(motion_pill, 5),
        "tone_brightness_pill": bright_pill,
        "tone_contrast_pill": contrast_pill,
        "tone_saturation_pill": sat_pill,
        "tone_temperature_pill": temp_pill,
        "tone_chromatic_pill": chrom_pill,
        "tone_motion_pill": motion_pill,
    })
    return out


def tone_pill_snapshot_keys(k: str):
    """Session keys to persist across page navigation."""
    return [
        f"{k}_pill_grain", f"{k}_pill_vignette", f"{k}_pill_focus", f"{k}_pill_dof",
        f"{k}_pill_brightness", f"{k}_pill_contrast", f"{k}_pill_saturation",
        f"{k}_pill_temperature", f"{k}_pill_chromatic", f"{k}_pill_motion",
    ]
