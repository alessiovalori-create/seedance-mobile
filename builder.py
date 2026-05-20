# ──────────────────────────────────────────────
# BUILDER.PY — Prompt Builder for Seedance 2.0 (video) + Seedream 5.0 (image)
# Architecture:
#   - Official ByteDance SKILL.md three-paragraph structure
#   - Eight core elements enforcement via Seed 1.8 system prompt
#   - @Asset N disambiguation (noun after every reference)
#   - ONE camera movement per time slice (SKILL.md constraint)
#   - Mandatory quality + anti-distortion paragraph
#   - Builders: build_prompt() for video, build_image_prompt() for images
# Based on official ByteDance SKILL.md prompt engineering framework (2026)
# ──────────────────────────────────────────────
import os
import re
import traceback
import requests
import json
import base64

# Centralized API key (from generator)
from generator import API_KEY
# ByteDance Directorial Formula — Parameter Expansion for Seedance 2.0
try:
    from builder_cinematic_dict import CINEMATIC_DICTIONARY
except ImportError:
    CINEMATIC_DICTIONARY = {}
    import warnings
    warnings.warn("builder_cinematic_dict not found. Parameter expansion disabled.")

# Model IDs and endpoints
SEED_1_8_ID = "seed-1-8-251228"  # Seed 1.8 — LLM / vision for prompt refinement
SEED_2_0_MINI_ID = "seed-2-0-mini-260215"  # ByteDance-Seed-2.0-mini (when available)
LLM_ENDPOINT_ID = SEED_1_8_ID  # Seed 2.0 mini not yet active; use Seed 1.8 for prompt generation
VISION_MODEL_ID = SEED_1_8_ID  # Keep Seed 1.8 for vision analysis (Seed 2.0 mini may not support vision endpoint)

# LLM endpoint — override with ARK_LLM_URL if needed
LLM_API_URL = os.getenv("ARK_LLM_URL", "https://ark.ap-southeast.bytepluses.com/api/v3/chat/completions")


# ──────────────────────────────────────────────
# UNIFIED UTILITY FUNCTIONS
# ──────────────────────────────────────────────
def clean_param(val):
    """Return stripped string if val is non-null, non-empty, and not 'Not specified'; else None.
    Unified replacement for the old _omit_if_empty, _opt_cine, and clean_param."""
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() == "not specified":
        return None
    return s


def _expand_cinematic(val):
    """Parameter expansion: if key is in CINEMATIC_DICTIONARY return expanded description; else return original. Skip empty/not-specified."""
    cleaned = clean_param(val)
    if cleaned is None:
        return None
    return CINEMATIC_DICTIONARY.get(cleaned, cleaned)


def _truncate_prompt(text, max_words=500):
    """Truncate prompt to max_words to avoid quality degradation.
    Seedream 5.0: official limit 600 words (we use 500 for safety margin).
    Seedance 2.0: no official limit, but >500 words degrades quality.
    Truncates at the last complete sentence before the limit."""
    if not text or not text.strip():
        return text
    words = text.split()
    if len(words) <= max_words:
        return text
    truncated = " ".join(words[:max_words])
    for end_char in ['. ', '.\n', '."', ".'", '! ', '? ']:
        last_pos = truncated.rfind(end_char)
        if last_pos > len(truncated) * 0.7:
            return truncated[:last_pos + 1].strip()
    return truncated.strip()


# Legacy constraints — disabled by default (not in official ByteDance documentation).
# Enable via enforce_stability=True kwarg for specific use cases (e.g. talking head stability).
SEEDANCE_2_0_CONSTRAINTS_TAIL = ""


def _build_technical_blueprint(ui_params):
    """
    Builds the structured Technical Blueprint block from UI params for Seedance 2.0.
    Uses CINEMATIC_DICTIONARY.get() to expand values; omits null/empty/'Not specified'.
    """
    if not ui_params:
        return ""
    parts = []
    shot_type = clean_param(ui_params.get("shot_type"))
    camera_angle = clean_param(ui_params.get("camera_angle"))
    movement_type = clean_param(ui_params.get("movement_type"))
    lighting_type = clean_param(ui_params.get("lighting_type"))
    lighting_direction = clean_param(ui_params.get("lighting_direction"))
    visual_style = clean_param(ui_params.get("visual_style"))
    mood = clean_param(ui_params.get("mood"))

    if shot_type or camera_angle or movement_type:
        st_exp = CINEMATIC_DICTIONARY.get(shot_type, shot_type) if shot_type else ""
        ca_exp = CINEMATIC_DICTIONARY.get(camera_angle, camera_angle) if camera_angle else ""
        mt_exp = CINEMATIC_DICTIONARY.get(movement_type, movement_type) if movement_type else ""
        line_parts = []
        if st_exp:
            line_parts.append(f"Camera direction: {st_exp}.")
        if ca_exp or mt_exp:
            mid = f"Shot from a {ca_exp}, the camera executes a {mt_exp}." if (ca_exp and mt_exp) else (f"Shot from a {ca_exp}." if ca_exp else f"The camera executes a {mt_exp}.")
            line_parts.append(mid)
        if line_parts:
            parts.append("Camera Language: " + " ".join(line_parts))

    if lighting_type or lighting_direction:
        lt_exp = CINEMATIC_DICTIONARY.get(lighting_type, lighting_type) if lighting_type else ""
        ld_exp = CINEMATIC_DICTIONARY.get(lighting_direction, lighting_direction) if lighting_direction else ""
        if lt_exp and ld_exp:
            parts.append(f"Lighting: Lighting setup: {lt_exp} combined with {ld_exp}.")
        elif lt_exp:
            parts.append(f"Lighting: Lighting setup: {lt_exp}.")
        elif ld_exp:
            parts.append(f"Lighting: Lighting setup: {ld_exp}.")

    if visual_style or mood:
        vs_exp = CINEMATIC_DICTIONARY.get(visual_style, visual_style) if visual_style else ""
        m_exp = CINEMATIC_DICTIONARY.get(mood, mood) if mood else ""
        if vs_exp and m_exp:
            parts.append(f"Style: Visual aesthetic: {vs_exp} evoking a {m_exp} atmosphere.")
        elif vs_exp:
            parts.append(f"Style: Visual aesthetic: {vs_exp}.")
        elif m_exp:
            parts.append(f"Style: Visual aesthetic evoking a {m_exp} atmosphere.")

    return "\n".join(parts)


# Default/neutral values for TONES (0–10). Only inject into prompt when value differs from default.
TONE_DEFAULTS_2_0 = {
    "tone_contrast": 5,
    "tone_brightness": 5,
    "tone_bokeh": 3,
    "tone_saturation": 5,
    "tone_temperature": 5,
    "tone_sharpness": 5,
    "tone_vignette": 0,
    "tone_chromatic": 0,
    "tone_grain": 0,
    "tone_softness": 0,
    "tone_motionblur": 5,
}


def _critical_override_tones_2_0(shots_data):
    """Seedance 2.0 only: build CRITICAL OVERRIDE lines only when the user has deviated from default.
    A parameter is added ONLY if its value is non-default: extreme (>=8) or minimum (<=2).
    If the value is at default/neutral (e.g. Vignette=0, Brightness=5), nothing is added."""
    TONE_KEYS = (
        ("tone_contrast", "Contrast"),
        ("tone_brightness", "Brightness"),
        ("tone_bokeh", "Background Bokeh"),
        ("tone_saturation", "Saturation"),
        ("tone_temperature", "Temperature"),
        ("tone_sharpness", "Sharpness"),
        ("tone_vignette", "Vignette"),
        ("tone_chromatic", "Chromatic Aberration"),
        ("tone_grain", "Grain"),
        ("tone_softness", "Softness"),
        ("tone_motionblur", "Motion Blur"),
    )
    lines = []
    for shot in shots_data or []:
        for key, name in TONE_KEYS:
            default_val = TONE_DEFAULTS_2_0.get(key, 5)
            v = shot.get(key)
            try:
                n = int(float(v))
            except (TypeError, ValueError):
                continue
            if n == default_val:
                continue
            if n >= 8:
                lines.append(f"CRITICAL OVERRIDE: Apply extreme {name}.")
            elif n <= 2:
                lines.append(f"CRITICAL OVERRIDE: Apply absolute minimum {name}.")

        # Atmosphere & VFX — always include when set (no threshold needed)
        atmos = clean_param(shot.get("vfx_atmos"))
        vfx = clean_param(shot.get("vfx_effects"))
        if atmos:
            lines.append(f"CRITICAL OVERRIDE: Scene atmosphere must include {atmos}.")
        if vfx:
            lines.append(f"CRITICAL OVERRIDE: Apply VFX: {vfx}.")
    return "\n".join(lines) if lines else ""


def strip_prompt_flags(text):
    """Remove legacy technical flags (--dur, --fps, --cf, --rs) from prompt text; prompt must be narrative-only."""
    if not text or not text.strip():
        return (text or "").strip()
    return re.sub(r'\s*--(?:dur|fps|cf|rs)\s+\S+', '', text).strip()

def encode_image(uploaded_file):
    """Encodes a Streamlit uploaded file (BytesIO) to base64."""
    return base64.b64encode(uploaded_file.getvalue()).decode('utf-8')


# ──────────────────────────────────────────────
# SEEDANCE PROMPT HELPERS (Timeline + Tones)
# ──────────────────────────────────────────────

def _translate_tones(shot):
    """
    Translates 0–10 tone values into a single discursive English sentence for the LLM.
    Only adds phrases when the value deviates from default/neutral (ignore-if-default).
    Avoids cluttering the prompt with "no vignette" / "neutral X" when sliders are at default.
    """
    parts = []
    b = shot.get('tone_brightness', 5)
    c = shot.get('tone_contrast', 5)
    sat = shot.get('tone_saturation', 5)
    temp = shot.get('tone_temperature', 5)
    bokeh = shot.get('tone_bokeh', 3)
    sharp = shot.get('tone_sharpness', 5)
    vig = shot.get('tone_vignette', 0)
    chrom = shot.get('tone_chromatic', 0)
    grain = shot.get('tone_grain', 0)
    soft = shot.get('tone_softness', 0)
    motion = shot.get('tone_motionblur', 5)

    default_b, default_c = TONE_DEFAULTS_2_0.get("tone_brightness", 5), TONE_DEFAULTS_2_0.get("tone_contrast", 5)
    default_sat = TONE_DEFAULTS_2_0.get("tone_saturation", 5)
    default_temp = TONE_DEFAULTS_2_0.get("tone_temperature", 5)
    default_bokeh = TONE_DEFAULTS_2_0.get("tone_bokeh", 3)
    default_sharp = TONE_DEFAULTS_2_0.get("tone_sharpness", 5)
    default_vig = TONE_DEFAULTS_2_0.get("tone_vignette", 0)
    default_chrom = TONE_DEFAULTS_2_0.get("tone_chromatic", 0)
    default_grain = TONE_DEFAULTS_2_0.get("tone_grain", 0)
    default_soft = TONE_DEFAULTS_2_0.get("tone_softness", 0)
    default_motion = TONE_DEFAULTS_2_0.get("tone_motionblur", 5)

    # Contrast + brightness (only when non-default)
    if c != default_c or b != default_b:
        if c > 7 and b < 4:
            parts.append("Low-key cinematic lighting with deep shadows and strong contrast")
        elif c > 6 and b >= 4:
            parts.append("Strong contrast with defined shadows")
        elif c < 3:
            parts.append("Flat, low-contrast look with soft tonal range")
        elif b > 7 and c <= 5:
            parts.append("bright, high-key lighting")
        elif b < 3:
            parts.append("very dark, underexposed atmosphere")

    if sat != default_sat:
        if sat >= 7:
            parts.append("vivid, saturated colors")
        elif sat <= 3:
            parts.append("desaturated, muted color palette")

    if temp != default_temp:
        if temp >= 7:
            parts.append("warm, golden color temperature")
        elif temp <= 3:
            parts.append("cold, blue color temperature")

    if bokeh != default_bokeh:
        if bokeh >= 6:
            parts.append("heavy background bokeh and shallow depth of field")
        elif bokeh < 2:
            parts.append("sharp background with minimal blur")

    if sharp != default_sharp:
        if sharp >= 7:
            parts.append("crisp, sharp detail")
        elif sharp <= 3:
            parts.append("soft, diffused sharpness")

    if vig != default_vig and vig >= 5:
        parts.append("visible vignette darkening the edges")
    if chrom != default_chrom and chrom >= 5:
        parts.append("subtle chromatic aberration")
    if grain != default_grain and grain >= 5:
        parts.append("noticeable film grain")
    if soft != default_soft and soft >= 5:
        parts.append("soft bloom or glow")
    if motion != default_motion and motion >= 7:
        parts.append("pronounced motion blur on movement")

    if not parts:
        return ""
    return ". ".join(parts).strip() + "."


def _format_timeline(shots_data):
    """
    Builds script from shots_data for the LLM (Seedance 2.0).
    Rigid timestamped format: Ns-Ms: Primary action... with parameter expansion (CINEMATIC_DICTIONARY).
    """
    lines = []
    for shot in shots_data:
        m1_start = shot.get('m1_start', 0)
        m1_end = shot.get('m1_end', 4)
        m1_type_raw = clean_param(shot.get('m1_type')) or "static"
        m1_type = m1_type_raw or "static"
        m1_pace_raw = clean_param(shot.get('m1_pace')) or "Normal"
        m1_pace_exp = _expand_cinematic(m1_pace_raw) if m1_pace_raw and m1_pace_raw.lower() != "not specified" else _expand_cinematic("Normal") or "Normal"
        m1_angle = clean_param(shot.get('m1_angle')) or "eye-level"
        assets = clean_param(shot.get('assets')) or "scene"
        style = clean_param(shot.get('style')) or ""
        mood = clean_param(shot.get('mood')) or ""
        lighting = clean_param(shot.get('lighting')) or ""
        tone_desc = _translate_tones(shot)
        extra = []
        if style:
            extra.append(f"Style: {style}")
        if mood:
            extra.append(f"Mood: {mood}")
        if lighting:
            extra.append(f"Lighting: {lighting}")
        extra_str = ". ".join(extra) + "." if extra else ""

        m1_type_exp = _expand_cinematic(m1_type) or m1_type
        m1_angle_exp = _expand_cinematic(m1_angle) or m1_angle
        style_exp = _expand_cinematic(style) or style
        mood_exp = _expand_cinematic(mood) or mood
        lighting_exp = _expand_cinematic(lighting) or lighting
        extra_2_0 = []
        if style_exp:
            extra_2_0.append(f"Style: {style_exp}")
        if mood_exp:
            extra_2_0.append(f"Mood: {mood_exp}")
        if lighting_exp:
            extra_2_0.append(f"Lighting: {lighting_exp}")
        extra_str_2_0 = ". ".join(extra_2_0) + "." if extra_2_0 else extra_str
        line = f"{int(m1_start)}s-{int(m1_end)}s: Primary action with {m1_type_exp} camera movement. {m1_pace_exp}. Angle: {m1_angle_exp}. Target: {assets}."
        if tone_desc:
            line += f" Visual tone: {tone_desc}"
        if extra_str_2_0:
            line += f" {extra_str_2_0}"

        atmos = clean_param(shot.get("vfx_atmos"))
        vfx = clean_param(shot.get("vfx_effects"))
        if atmos:
            line += f" Atmosphere: {atmos}."
        if vfx:
            line += f" VFX: {vfx}."

        color_palette = shot.get("color_palette")
        if color_palette and isinstance(color_palette, list) and len(color_palette) > 0:
            color_parts = [f"{target} in {hex_val}" for hex_val, target in color_palette]
            line += f" Color grading: {', '.join(color_parts)}."
        lines.append(line)

        m2_type_raw = clean_param(shot.get('m2_type'))
        m2_type_exp = _expand_cinematic(m2_type_raw) or m2_type_raw if m2_type_raw else None
        if m2_type_exp:
            m2_start = shot.get('m2_start', m1_end)
            m2_end = shot.get('m2_end', m2_start + 4)
            m2_pace_raw = clean_param(shot.get('m2_pace')) or "Normal"
            m2_pace_exp = _expand_cinematic(m2_pace_raw) if m2_pace_raw and m2_pace_raw.lower() != "not specified" else _expand_cinematic("Normal") or "Normal"
            m2_angle_raw = clean_param(shot.get('m2_angle')) or "eye-level"
            m2_angle_exp = _expand_cinematic(m2_angle_raw) or m2_angle_raw
            m2_shot = clean_param(shot.get('m2_shot')) or ""
            line2 = f"{int(m2_start)}s-{int(m2_end)}s: Secondary action with {m2_type_exp} camera movement. {m2_pace_exp}. Angle: {m2_angle_exp}."
            if m2_shot:
                line2 += f" Context: {m2_shot}."
            lines.append(line2)

    return "\n".join(lines) if lines else ""


def _get_workflow_system_instruction(workflow_type, image_usage, num_vids, num_imgs):
    """
    Returns the workflow-specific system instruction block for the LLM.
    Replaces generic if/else logic with clear, modular templates per workflow.
    """
    # FIRST+LAST FRAME — must be checked BEFORE other conditions
    if image_usage == "first_last_frame" and num_imgs >= 2:
        return (
            "The video starts from @Image 1 (first frame) and ends at @Image 2 (last frame). "
            "Describe the transition, motion, and action that takes the scene FROM the opening frame "
            "TO the closing frame. Do not re-describe the static content of either image; "
            "reference them and describe the evolution between them."
        )
    if workflow_type == "Video Extension" and num_vids > 0:
        return (
            "You are a video editor. You must ONLY describe what happens in the new extension "
            "that follows the original clip (@Video 1). Do NOT describe the beginning or the existing clip."
        )
    if (image_usage == "first_frame" or workflow_type == "Image-to-video") and num_imgs > 0:
        return (
            "The action starts exactly from the frame @Image 1. "
            "Describe the evolution of the action starting from that point."
        )
    if workflow_type == "Video Editing" and num_vids > 0:
        return (
            "You are editing existing video. State explicitly what to replace or modify using @Video and @Image tags "
            "(e.g. replace character in @Video 1 with figure from @Image 1). Do not describe the clip from scratch."
        )
    if image_usage == "reference_only" and num_imgs > 0:
        return (
            "Use the uploaded image(s) as REFERENCE ONLY for style, character, or environment. "
            "Describe a NEW scene that matches the reference; do not say the video 'starts from' the image."
        )
    if image_usage == "composite" and num_imgs >= 2:
        return (
            "Multiple reference images are available. Use each @Image tag ONLY for the purpose "
            "the draft assigns it. If the draft specifies @Image 1 as a diver and @Image 2 as crates, "
            "respect that — do NOT force a character+environment composite formula. "
            "Use attribute locking phrasing: '(referenced from @Image X)' for each tag's role."
        )
    return (
        "Standard generation. Use @ tags to state how each asset is used (reference, first frame, etc.) "
        "as appropriate to the narrative."
    )


# ... The rest of your builder.py code (analyze_cinematography, etc.) follows below ...

# ──────────────────────────────────────────────
# VISION ANALYSIS AGENT (from working backup - Seed 1.8)
# ──────────────────────────────────────────────
def analyze_cinematography(uploaded_file, image_label):
    """Sends image to Seed-1.8 to reverse-engineer exact UI parameters."""
    if not uploaded_file: return None
    
    mime_type = uploaded_file.type
    base64_image = encode_image(uploaded_file)
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    vision_prompt = f"""
    You are an expert Cinematographer and Colorist. Analyze this image and extract its precise technical parameters so I can replicate it in a 3D/AI engine.

    Provide the output strictly in this readable Markdown format:

    ### 🎬 {image_label} Cinematography Report
    **Subject & Framing:**
    * **Subject:** (Brief description)
    * **Shot Size:** (Wide Shot, Medium Shot, Close-up, etc.)
    * **Camera Angle:** (Eye-level, High Angle, Low Angle, etc.)
    * **Subject Orientation:** (Front View, Profile, Back View, etc.)

    **🌌 Visuals & Tones:**
    * **Atmosphere Notes:** (1 sentence on mood and lighting)

    **Image Quality Tones (Estimate on a strict 0 to 10 scale):**
    * Brightness: [0-10]
    * Contrast: [0-10]
    * Saturation: [0-10]
    * Color Temp (0=Cold, 10=Warm): [0-10]
    * Background Bokeh (0=Sharp, 10=Heavy Blur): [0-10]
    * Sharpness: [0-10]
    * Vignette: [0-10]
    * Film Grain: [0-10]
    * Softness (Bloom): [0-10]

    **🎨 Color Grading (Provide 3 dominant HEX codes):**
    1. `HEX` - [Target Object/Area, e.g., Sky]
    2. `HEX` - [Target Object/Area]
    3. `HEX` - [Target Object/Area]
    """

    payload = {
        "model": VISION_MODEL_ID,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": vision_prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
                ]
            }
        ],
        "max_completion_tokens": 8192,
        "reasoning_effort": "medium"
    }

    try:
        response = requests.post(LLM_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    except requests.exceptions.HTTPError as e:
        try:
            error_details = e.response.text[:500] if e.response else str(e)
        except Exception:
            error_details = str(e)
        return f"**API Error:** Check Endpoint and API Key. Details: {e}\nResponse: {error_details}"
    except Exception as e:
        return f"**System Error:** Failed to analyze {image_label}. {str(e)}"

def call_llm_for_prompt(system_instruction, user_content, temperature=0.5, model_id=None):
    """Call LLM for prompt generation (from working backup - Seed 1.8)."""
    model = model_id or LLM_ENDPOINT_ID
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_content}
        ],
        "temperature": float(temperature),
        "max_completion_tokens": 8192,
        "reasoning_effort": "high"
    }
    try:
        # timeout=90 (come Seedance 2.0) per evitare che il server stacchi la connessione
        response = requests.post(LLM_API_URL, headers=headers, json=payload, timeout=90)
        response.raise_for_status()
        data = response.json()
        choice = (data.get('choices') or [None])[0]
        if not choice:
            return f"[LLM ERROR: No choices in response]. Model: {model}"
        msg = choice.get('message') or {}
        content = msg.get('content')
        if content is None:
            content = msg.get('text') or msg.get('output') or ""
        # Some APIs return content as list of parts, e.g. [{"type":"text","text":"..."}]
        if isinstance(content, list):
            text = "".join(
                p.get("text", p.get("content", "")) if isinstance(p, dict) else str(p)
                for p in content
            ).strip()
        else:
            text = (content or "").strip()
        if not text:
            return f"[LLM ERROR: Empty content from model]. Model: {model}. Check API response format."
        return text
    except requests.exceptions.HTTPError as e:
        error_detail = f"HTTP {e.response.status_code}"
        try:
            error_body = e.response.json()
            error_detail += f": {error_body}"
        except:
            error_detail += f": {e.response.text[:200]}"
        return f"[LLM ERROR ({error_detail})]. Model: {model}, URL: {LLM_API_URL}"
    except Exception as e: 
        return f"[LLM ERROR: {str(e)}]. Model: {model}"

# ──────────────────────────────────────────────
# MODEL-SPECIFIC SYSTEM PROMPTS (based on official ByteDance guides)
# ──────────────────────────────────────────────

def _system_prompt_seedance_2_0(workflow_instruction, creative_rule):
    return f"""You are a Seedance 2.0 cinematic prompt specialist.
Your ONLY task is to refine the structured draft below into fluid
cinematic prose following the official ByteDance three-paragraph format.

PRIMARY RULE — NO SILENT MODIFICATION:
You are STRICTLY FORBIDDEN from adding ANY element not present in the
draft. This means:
- NO default lighting (do not add "golden hour", "soft light",
  "ambient light" unless the draft specifies it)
- NO default camera movements (do not add "static", "slow pan"
  unless the draft specifies it)
- NO default mood or atmosphere (do not add "melancholic", "tense",
  "dreamy" unless the draft specifies it)
- NO default quality descriptors beyond what Paragraph 3 provides
  (do not add "sharp focus" if not in draft, do not add "cinematic"
  as a filler word)
- NO invented subject details (do not describe the woman's hair color,
  clothing details, or expression unless the draft states them)
- NO invented environment details (do not add "city lights", "urban
  skyline", "birds flying" unless the draft states them)
If an element is missing from the draft, LEAVE IT ABSENT. Do not fill
gaps with assumptions. A sparse prompt is better than an invented one.

OUTPUT FORMAT — Three paragraphs ONLY:

PARAGRAPH 1 — Global Settings (2–4 sentences maximum)
Declare @Asset mapping with noun disambiguation.
First/last frame constraints if present.
Nothing else.

PARAGRAPH 2 — Time Slice Storyboard
One paragraph per time slice, timestamp preserved exactly.
Each slice: subject action + ONE camera movement + atmosphere
(only what the draft provides).
NEVER merge two slices into one.
NEVER add a camera movement not in the draft.
When a named visual style (e.g. "Golden Hour Cinematography") is
present, it defines lighting and color — do NOT add a contradictory
mood-based lighting description alongside it.

PARAGRAPH 3 — Technical Quality Constraints
Reproduce Paragraph 3 from the draft with these rules:
- Keep ALL specific technical constraints verbatim
- If draft says "soft focus maintained", NEVER add "sharp focus"
- If draft says "heavy grain", NEVER add "clean" or "crisp"
- Only rephrase for fluency — never weaken or contradict
- NEVER add generic defaults ("sharp focus", "crisp detail",
  "vibrant colors") unless explicitly in the draft

ASSET RULES:
- Keep ALL @Image N, @Video N, @Audio N tags exactly as in draft
- After every @Image N add noun in parentheses: @Image 1 (the woman)
- NEVER add @Asset tags not in the draft
- NEVER renumber @Asset tags

CAMERA RULES:
- Use native Seedance trigger words: dolly-in, dolly-out, pan, tilt,
  track, orbit, zoom, crane, handheld, steadicam, eye-level, low angle,
  high angle, bird's eye, worm's eye
- ONE camera movement per time slice maximum
- NEVER expand camera terms into mechanical descriptions

SHOT STRUCTURE:
- NEVER collapse multiple time slices into one
- Two shots = two slices = one editorial CUT between them
- Preserve all timestamps exactly as written

TARGET: 80–250 words. Output ONLY the final prompt.
No preamble. No explanations. No markdown. English only.

{workflow_instruction}

{creative_rule if creative_rule else ''}"""


# ──────────────────────────────────────────────
# DIRECTOR AGENT (PROMPT BUILDER)
# ──────────────────────────────────────────────

def _build_quality_paragraph(shots_data=None, enforce_stability=False,
                              workflow_type="Standard", num_imgs=0,
                              image_usage="auto"):
    """
    Builds Paragraph 3 (Image quality, style and constraints) dynamically
    from actual technical parameters entered in the CINEMATOGRAPHY panel.

    Based on official ByteDance SKILL.md mandatory constraints:
    - Always include image quality descriptors
    - Always include anti-distortion fallback
    - Add technical constraints specific to chosen gear/tone/VFX
    """
    parts = []
    constraints = []

    # ── BASE QUALITY (always present) ──────────────────────────────
    parts.append("4K HD, rich details, sharp focus")

    # ── GEAR-SPECIFIC QUALITY DESCRIPTORS ──────────────────────────
    # Extract from first shot (gear is typically global across shots)
    first_shot = (shots_data or [{}])[0] if shots_data else {}

    lenses_raw = clean_param(first_shot.get("lenses"))
    film_stock_raw = clean_param(first_shot.get("film_stock"))
    sensor_raw = clean_param(first_shot.get("sensor"))

    if lenses_raw:
        lenses_lower = lenses_raw.lower()
        if "anamorphic" in lenses_lower:
            parts.append("anamorphic lens character with horizontal flare")
            constraints.append("lens flare consistent and directional throughout")
        elif "fisheye" in lenses_lower:
            parts.append("fisheye distortion consistent throughout")
        elif "macro" in lenses_lower:
            parts.append("macro depth of field shallow and consistent")
        elif "tilt" in lenses_lower or "shift" in lenses_lower:
            parts.append("tilt-shift miniature effect consistent")
        elif any(x in lenses_lower for x in ["vintage", "old", "soviet", "helios"]):
            parts.append("vintage lens rendering with characteristic swirl bokeh")

    if film_stock_raw:
        stock_lower = film_stock_raw.lower()
        if any(x in stock_lower for x in ["35mm", "16mm", "8mm"]):
            parts.append(f"{film_stock_raw} film texture")
            constraints.append("film grain consistent across all frames")
        elif "reversal" in stock_lower or "slide" in stock_lower:
            parts.append("high-contrast reversal film look")
        elif "negative" in stock_lower:
            parts.append("film negative color science")

    if sensor_raw:
        sensor_lower = sensor_raw.lower()
        if any(x in sensor_lower for x in ["vintage", "old", "ccd"]):
            parts.append("vintage sensor rendering")
        elif "full frame" in sensor_lower:
            parts.append("full frame sensor perspective")

    # ── TONE SLIDER EXTREMES → QUALITY CONSTRAINTS ─────────────────
    # Only inject when values are extreme (≥8 or ≤2) — not for neutral values
    for shot in (shots_data or []):
        grain = shot.get("tone_grain", 0)
        vig = shot.get("tone_vignette", 0)
        chrom = shot.get("tone_chromatic", 0)
        soft = shot.get("tone_softness", 0)
        sharp = shot.get("tone_sharpness", 5)
        bokeh = shot.get("tone_bokeh", 3)
        motion = shot.get("tone_motionblur", 5)

        try:
            if int(float(grain)) >= 8:
                constraints.append("heavy film grain preserved consistently across all frames")
            if int(float(vig)) >= 8:
                constraints.append("heavy vignette consistent at frame edges")
            if int(float(chrom)) >= 7:
                constraints.append("chromatic aberration consistent and directional")
            if int(float(soft)) >= 8:
                constraints.append("soft bloom/glow consistent throughout")
            if int(float(sharp)) <= 2:
                constraints.append("soft focus maintained consistently — do not sharpen")
            if int(float(bokeh)) >= 9:
                constraints.append("extreme shallow depth of field — background fully dissolved")
            if int(float(motion)) >= 8:
                constraints.append("heavy motion blur on moving elements — do not stabilize")
        except (TypeError, ValueError):
            continue
        break  # Only read first shot for tone extremes (global look)

    # ── VFX CONTINUITY CONSTRAINTS ──────────────────────────────────
    for shot in (shots_data or []):
        vfx_atmos = clean_param(shot.get("vfx_atmos"))
        vfx_effects = clean_param(shot.get("vfx_effects"))
        if vfx_atmos:
            constraints.append(f"{vfx_atmos} consistent and stable throughout")
        if vfx_effects:
            constraints.append(f"VFX ({vfx_effects}) consistent across all frames")

    # ── COLOR GRADING CONSISTENCY ───────────────────────────────────
    for shot in (shots_data or []):
        color_palette = shot.get("color_palette")
        if color_palette and isinstance(color_palette, list) and len(color_palette) > 0:
            constraints.append("color grading consistent — no color drift between frames")
            break

    # ── ANTI-DISTORTION FALLBACK (SKILL.md mandatory) ───────────────
    # Varies based on workflow and content type
    if enforce_stability:
        # Strict stability for talking heads, lip sync, etc.
        constraints.append(
            "character faces stable and not distorted, facial features clear and sharp, "
            "no face jumping between frames, no clipping through objects"
        )
    elif image_usage in ("first_frame", "first_last_frame"):
        # First frame constraint — subject must remain consistent with reference
        constraints.append(
            "subject appearance consistent with reference frame throughout, "
            "no identity drift, no facial distortion"
        )
    elif workflow_type == "Video Editing":
        # Editing — background must remain stable
        constraints.append(
            "unedited areas of the frame remain completely unchanged, "
            "no background drift, no temporal flickering"
        )
    elif num_imgs > 0:
        # Any image reference — character consistency
        constraints.append(
            "character features consistent with reference images, "
            "no distortion, no visual artifacts, no clipping"
        )
    else:
        # Standard generation — basic anti-distortion
        constraints.append("no distortion, no visual artifacts, no clipping")

    # ── ASSEMBLE PARAGRAPH 3 ────────────────────────────────────────
    quality_line = ", ".join(parts) + "."
    if constraints:
        constraint_line = ". ".join(c.capitalize() for c in constraints) + "."
        return f"{quality_line} {constraint_line}"
    return quality_line


def _pre_format_seedance_2_0(scene_description, shots_data, num_imgs, num_vids, num_auds,
                              audio_sync, vision_context, image_usage, workflow_type, duration,
                              enforce_stability=False, **kwargs):
    """
    Pre-formatter: produces a draft in official ByteDance three-paragraph structure.

    Paragraph 1 — Global settings: asset declarations with @Image N (noun) disambiguation.
    Paragraph 2 — Time slice storyboard: timestamps with ONE camera movement per slice.
    Paragraph 3 — Quality + anti-distortion constraints (always appended).

    Based on official ByteDance SKILL.md prompt engineering framework.
    """
    paragraphs = []

    # ── PARAGRAPH 1: GLOBAL SETTINGS ──────────────────────────────────
    # Asset declarations with noun disambiguation (SKILL.md mandatory pattern)
    p1_parts = []

    # Workflow-specific opening declaration
    if workflow_type == "Video Extension" and num_vids > 0:
        dur_sec = int(duration) if duration is not None else 5
        p1_parts.append(f"Extend @Video 1 by {dur_sec}s.")

    elif image_usage == "first_last_frame" and num_imgs >= 2:
        p1_parts.append(
            "@Image 1 (opening frame constraint) transitions to "
            "@Image 2 (closing frame constraint)."
        )

    elif image_usage == "first_frame" and num_imgs > 0:
        p1_parts.append("@Image 1 (first frame) — the scene animates from this composition.")

    elif workflow_type == "Video Editing" and num_vids > 0:
        if num_imgs > 0:
            p1_parts.append(
                "Replace the subject in @Video 1 (source video) with the figure "
                "from @Image 1 (replacement reference)."
            )
        else:
            p1_parts.append("Edit @Video 1 (source video) as described below.")

    elif image_usage == "composite" and num_imgs >= 2:
        p1_parts.append(
            "@Image 1 (character reference — maintain physical appearance and clothing). "
            "@Image 2 (environment reference — maintain architectural and lighting style)."
        )

    elif image_usage == "reference_only" and num_imgs > 0:
        refs = " ".join([f"@Image {i+1} (style/character reference)" for i in range(min(num_imgs, 4))])
        p1_parts.append(refs)

    # Additional image references beyond the ones declared above
    if num_imgs > 0 and image_usage not in ("first_last_frame", "composite", "reference_only", "first_frame"):
        refs = " ".join([f"@Image {i+1}" for i in range(min(num_imgs, 9))])
        if refs and not any(refs[:8] in p for p in p1_parts):
            p1_parts.append(f"Reference assets: {refs}.")

    # Video references for multimodal (not Extension/Editing)
    if num_vids > 0 and workflow_type not in ("Video Extension", "Video Editing"):
        vid_refs = ", ".join([f"@Video {i+1} (motion/style reference)" for i in range(min(num_vids, 3))])
        p1_parts.append(f"Camera and motion referenced from {vid_refs}.")

    # Audio references
    if num_auds > 0:
        aud_refs = ", ".join([f"@Audio {i+1} (background music/timbre reference)" for i in range(min(num_auds, 3))])
        p1_parts.append(f"Audio referenced from {aud_refs}.")

    # Vision context (AI image analysis results)
    if vision_context and num_imgs > 0:
        for i, desc in enumerate(vision_context):
            desc_val = clean_param(desc)
            if desc_val:
                p1_parts.append(f"@Image {i+1} context: {desc_val}.")

    # Scene + subject declaration
    scene_val = clean_param(scene_description)
    if scene_val:
        # Normalize shorthand tags: "@1" → "@Image 1", "image @1" → "@Image 1"
        scene_val = re.sub(r'(?i)image\s*@\s*(\d+)', lambda m: f"@Image {m.group(1)}", scene_val)
        scene_val = re.sub(r'(?<![A-Za-z])@(\d+)', lambda m: f"@Image {m.group(1)}", scene_val)
        p1_parts.append(f"Scene: {scene_val}")

    if p1_parts:
        paragraphs.append("\n".join(p1_parts))

    # ── PARAGRAPH 2: TIME SLICE STORYBOARD ──────────────────────────────
    # Each slice: action + ONE camera movement + setting/light
    p2_parts = []

    if shots_data:
        for idx, shot in enumerate(shots_data):
            # Timestamps
            m1_start = int(shot.get('m1_start', 0))
            m1_end = int(shot.get('m1_end', 4))
            timestamp = f"{m1_start}–{m1_end}s"

            # Subject/action
            assets_raw = clean_param(shot.get("assets"))
            shot_type_raw = clean_param(shot.get("shot_type"))
            shot_type_exp = _expand_cinematic(shot_type_raw) if shot_type_raw else None

            # Camera — ONE per slice (primary only; secondary gets its own slice)
            m1_type_raw = clean_param(shot.get("m1_type"))
            m1_type_exp = None
            if m1_type_raw and m1_type_raw.lower() not in ("static", "not specified", "none"):
                m1_type_exp = _expand_cinematic(m1_type_raw) or m1_type_raw
            m1_angle_raw = clean_param(shot.get("m1_angle")) or ""
            m1_angle_exp = _expand_cinematic(m1_angle_raw) if m1_angle_raw else ""
            m1_pace_raw = clean_param(shot.get("m1_pace")) or ""
            pace_map = {
                "extremely slow": "very slowly", "slow": "slowly",
                "normal": "", "fast": "rapidly", "dynamic": "dynamically",
                "time-lapse": "in time-lapse"
            }
            m1_pace_str = pace_map.get((m1_pace_raw or "").lower(), "")

            # Atmosphere: lighting + style + mood
            lighting_raw = clean_param(shot.get("lighting"))
            lighting_dir_raw = clean_param(shot.get("lighting_direction"))
            style_raw = clean_param(shot.get("style"))
            mood_raw = clean_param(shot.get("mood"))
            lighting_exp = _expand_cinematic(lighting_raw) if lighting_raw else None
            lighting_dir_exp = _expand_cinematic(lighting_dir_raw) if lighting_dir_raw else None
            style_exp = _expand_cinematic(style_raw) if style_raw else None
            mood_exp = _expand_cinematic(mood_raw) if mood_raw else None

            # Tones (only non-default)
            tone_desc = _translate_tones(shot)

            # Cinematic gear
            lenses_raw = clean_param(shot.get("lenses"))
            film_stock_raw = clean_param(shot.get("film_stock"))
            sensor_raw = clean_param(shot.get("sensor"))
            lenses_exp = _expand_cinematic(lenses_raw) if lenses_raw else None
            film_stock_exp = _expand_cinematic(film_stock_raw) if film_stock_raw else None
            sensor_exp = _expand_cinematic(sensor_raw) if sensor_raw else None

            # VFX
            vfx_atmos = clean_param(shot.get("vfx_atmos"))
            vfx_effects = clean_param(shot.get("vfx_effects"))

            # Build slice
            slice_parts = []

            # Action line
            action = assets_raw or (scene_val.strip() if idx == 0 and scene_val else "the scene")
            if shot_type_exp:
                slice_parts.append(f"{timestamp}: {shot_type_exp} — {action}.")
            else:
                slice_parts.append(f"{timestamp}: {action}.")

            # Camera (ONE movement, following SKILL.md restriction)
            if m1_type_exp:
                cam_str = f"Camera: {m1_pace_str + ' ' if m1_pace_str else ''}{m1_type_exp}"
                if m1_angle_exp:
                    cam_str += f" from {m1_angle_exp}"
                cam_str += "."
                slice_parts.append(cam_str)

            # Atmosphere (only on first slice unless changed; SKILL.md: state once, inherit)
            if idx == 0:
                atmos = []
                if lighting_exp and lighting_dir_exp:
                    atmos.append(f"{lighting_exp} with {lighting_dir_exp}")
                elif lighting_exp:
                    atmos.append(lighting_exp)
                if style_exp:
                    atmos.append(f"{style_exp} aesthetic")
                if mood_exp:
                    atmos.append(f"{mood_exp} mood")
                if tone_desc:
                    atmos.append(tone_desc.rstrip("."))
                if atmos:
                    slice_parts.append("Atmosphere: " + ", ".join(atmos) + ".")

            # Cinematic gear (first slice only)
            if idx == 0:
                gear = []
                if lenses_exp:
                    gear.append(f"lens: {lenses_exp}")
                if film_stock_exp:
                    gear.append(f"film stock: {film_stock_exp}")
                if sensor_exp:
                    gear.append(f"sensor: {sensor_exp}")
                if gear:
                    slice_parts.append("Gear: " + ", ".join(gear) + ".")

            # VFX
            if vfx_atmos:
                slice_parts.append(f"Atmosphere FX: {vfx_atmos}.")
            if vfx_effects:
                slice_parts.append(f"VFX: {vfx_effects}.")

            # Color grading
            color_palette = shot.get("color_palette")
            if color_palette and isinstance(color_palette, list) and len(color_palette) > 0:
                color_parts = [f"{target} ({hex_val})" for hex_val, target in color_palette if hex_val and target]
                if color_parts:
                    slice_parts.append(f"Color grading: {', '.join(color_parts)}.")

            # Signal editorial cut between shots
            if idx > 0:
                # Prepend CUT marker to this slice so Seed 1.8 never collapses it
                slice_parts[0] = f"CUT. {slice_parts[0]}"

            p2_parts.append(" ".join(slice_parts))

            # Secondary movement gets its own slice
            m2_type_raw = clean_param(shot.get("m2_type"))
            if m2_type_raw and m2_type_raw.lower() not in ("static", "not specified", "none"):
                m2_type_exp = _expand_cinematic(m2_type_raw) or m2_type_raw
                m2_start = int(shot.get('m2_start', m1_end))
                m2_end = int(shot.get('m2_end', m2_start + 4))
                m2_angle_raw = clean_param(shot.get("m2_angle")) or ""
                m2_angle_exp = _expand_cinematic(m2_angle_raw) if m2_angle_raw else ""
                m2_pace_raw = clean_param(shot.get("m2_pace")) or ""
                m2_pace_str = pace_map.get((m2_pace_raw or "").lower(), "")
                m2_shot_ctx = clean_param(shot.get("m2_shot")) or ""
                m2_cam = f"{m2_start}–{m2_end}s: Camera: {m2_pace_str + ' ' if m2_pace_str else ''}{m2_type_exp}"
                if m2_angle_exp:
                    m2_cam += f" from {m2_angle_exp}"
                if m2_shot_ctx:
                    m2_cam += f". {m2_shot_ctx}"
                m2_cam += "."
                p2_parts.append(m2_cam)

    else:
        # No shots configured — build single slice from scene description
        dur = int(duration) if duration else 15
        if scene_val:
            # Detect multi-shot text cues
            cut_parts = re.split(
                r'(?i)(?:,\s*)?(?:cut\s+(?:to\s+)?shot\s*\d*|cut\s+shot\s*\d*|'
                r'cut\s+to|taglio|stacco|poi\s+si\s+passa\s+a)',
                scene_val
            )
            cut_parts = [p.strip() for p in cut_parts if p and p.strip()]
            if len(cut_parts) >= 2:
                per = dur // len(cut_parts)
                rem = dur % len(cut_parts)
                t = 0
                for ci, cpart in enumerate(cut_parts):
                    t_end = min(t + per + (1 if ci < rem else 0), dur)
                    p2_parts.append(f"{t}–{t_end}s: {cpart}.")
                    t = t_end
            else:
                p2_parts.append(f"0–{dur}s: {scene_val}.")
        else:
            p2_parts.append(f"0–{dur}s: Scene as described.")

    if p2_parts:
        paragraphs.append("\n".join(p2_parts))

    # ── AUDIO & SOUND CUES ──────────────────────────────────────────────
    if audio_sync is not None:
        dialogue = clean_param(audio_sync.get("dialogue"))
        sfx = clean_param(audio_sync.get("sfx"))
        bgm = clean_param(audio_sync.get("bgm"))
        if dialogue or sfx or bgm:
            audio_parts = []
            if dialogue:
                lang = audio_sync.get("lang", "English")
                emo = audio_sync.get("emo", "Calm")
                timbre = audio_sync.get("timbre", "Normal")
                pace = audio_sync.get("pace", "Normal")
                lines_raw = [l.strip() for l in dialogue.strip().split("\n") if l.strip()]
                if len(lines_raw) > 1 and any(":" in l or "\uff1a" in l for l in lines_raw):
                    audio_parts.append(f"Dialogue ({lang}, lip-sync required):")
                    for line in lines_raw:
                        audio_parts.append(f"  {line}")
                else:
                    audio_parts.append(
                        f"In a {str(emo).lower()} emotional state, with a {str(timbre).lower()} tone "
                        f"and a {str(pace).lower()} speaking pace, say in {lang}: \"{dialogue}\""
                    )
            if bgm:
                audio_parts.append(f"Background Music: {bgm}")
            if sfx:
                audio_parts.append(f"Sound Effects: {sfx}")
            paragraphs.append("Audio & Sound Cues: " + " | ".join(audio_parts))

    # ── PARAGRAPH 3: QUALITY + CONSTRAINTS (dynamic, SKILL.md mandatory) ──
    paragraphs.append(_build_quality_paragraph(
        shots_data=shots_data,
        enforce_stability=enforce_stability,
        workflow_type=workflow_type,
        num_imgs=num_imgs,
        image_usage=image_usage,
    ))

    return "\n\n".join(paragraphs).strip()



def build_prompt(scene_description, duration=8, temperature=0.5,
                 workflow_type="Standard",
                 num_imgs=0, num_vids=0, num_auds=0, shots_data=[], audio_sync=None,
                 vision_context=None, image_usage="auto", enforce_stability=False, **kwargs):
    """
    image_usage: "auto" | "first_frame" | "reference_only" | "composite"
    enforce_stability: if True, appends stability constraints to Seedance 2.0 prompts (disable for morphing/transformation scenes).
    """
    # Validate Seedance 2.0 file limits (official: max 12 mixed files, max 9 images, max 3 videos, max 3 audio)
    total_files = num_imgs + num_vids + num_auds
    if total_files > 12:
        import warnings
        warnings.warn(f"Seedance 2.0 supports max 12 mixed files. You have {total_files}. Results may be unpredictable.")
    if num_imgs > 9:
        import warnings
        warnings.warn(f"Seedance 2.0 supports max 9 images. You have {num_imgs}.")
    if num_vids > 3:
        import warnings
        warnings.warn(f"Seedance 2.0 supports max 3 video clips. You have {num_vids}.")
    if num_auds > 3:
        import warnings
        warnings.warn(f"Seedance 2.0 supports max 3 audio files. You have {num_auds}.")

    # 0. Resolve image usage intent for prompt strategy
    if image_usage == "auto":
        if workflow_type == "Video Editing" and num_imgs > 0:
            image_usage = "reference_only"  # edit video using image as reference
        elif num_imgs == 1 and num_vids == 0:
            image_usage = "first_frame"  # single image → likely animate from it
        elif num_imgs >= 2:
            image_usage = "composite"  # multiple images → often composite/reference
        else:
            image_usage = "reference_only"
    
    # 1. Compile Global Asset Tags
    available_tags = []
    vision_notes = ""
    
    if num_imgs > 0: 
        available_tags.append(", ".join([f"@Image {i+1}" for i in range(num_imgs)]))
        if vision_context:
            vision_notes = "\nAI VISION & INTENT ANALYSIS:\n"
            for i, desc in enumerate(vision_context):
                vision_notes += f"- @Image {i+1}: {desc}\n"

    if num_vids > 0: available_tags.append(", ".join([f"@Video {i+1}" for i in range(num_vids)]))
    if num_auds > 0: available_tags.append(", ".join([f"@Audio {i+1}" for i in range(num_auds)]))
    tag_string = " | ".join(available_tags) if available_tags else "No media tags available."

    # 2. Timeline: rigid timestamps for Seedance 2.0
    timeline_script = _format_timeline(shots_data)
    has_any_movement = any(
        clean_param(s.get('m1_type')) or clean_param(s.get('m2_type')) for s in shots_data
    )
    shots_context = ""
    if timeline_script:
        shots_context = f"""
TIMELINE (you MUST respect these timestamps rigidly; do not shift or merge them):
{timeline_script}
"""

    # 3. Audio / Lip-Sync (Seedance 2.0 native audio-video)
    audio_str = "None"
    if audio_sync:
        audio_parts = []
        dialogue = clean_param(audio_sync.get('dialogue'))
        sfx = clean_param(audio_sync.get('sfx'))
        bgm = clean_param(audio_sync.get('bgm'))

        if dialogue:
            lang = audio_sync.get('lang', 'English')
            emo = audio_sync.get('emo', 'Calm')
            timbre = audio_sync.get('timbre', 'Normal')
            pace = audio_sync.get('pace', 'Normal')

            # Check for multi-character dialogue (lines separated by newlines with "Character:" pattern)
            lines_raw = [l.strip() for l in dialogue.strip().split('\n') if l.strip()]
            if len(lines_raw) > 1 and any(':' in l or '：' in l for l in lines_raw):
                # Multi-person dialogue format (official ByteDance format)
                audio_parts.append(f"Dialogue ({lang}, lip-sync required):")
                for line in lines_raw:
                    audio_parts.append(f"  {line}")
            else:
                # Single speaker format (official ByteDance format)
                audio_parts.append(
                    f"In a {emo.lower()} emotional state, with a {timbre.lower()} tone "
                    f"and a {pace.lower()} speaking pace, say in {lang}: \"{dialogue}\""
                )

        if bgm:
            audio_parts.append(f"Background Music: {bgm}")
        if sfx:
            audio_parts.append(f"Sound Effects: {sfx}")

        if audio_parts:
            audio_str = "\n".join(audio_parts)

    elif num_vids > 0 and num_auds == 0:
        audio_str = "Note: You can reference audio from uploaded videos (e.g., 'use the audio from @Video 1 as background music' or 'reference the timbre of the voiceover in @Video 1')."

    # --- REQUEST CONTEXT: how to use assets (visual/narrative only; no duration or technical vars) ---
    if workflow_type == "Video Extension" and num_vids > 0:
        dur_sec = int(duration) if duration is not None else 5
        request_context = f"""
    REQUEST TYPE: VIDEO EXTENSION
    - The user wants to EXTEND an existing video. Your output MUST start with the EXACT phrase: "Extend @Video 1 by {dur_sec}s." (the number MUST match the Generation Duration slider).
    - After that phrase, describe ONLY the new segment: what happens next, same style and continuity.
    - Do NOT repeat the existing video content; focus on the extension.
    """
    elif workflow_type == "Video Editing" and num_vids > 0:
        request_context = """
    REQUEST TYPE: VIDEO EDITING
    - The user wants to EDIT or modify content in the uploaded video using the uploaded image(s).
    - Explicitly state what to replace/edit: e.g. "Replace the character in @Video 1 with the figure from @Image 1" or "Apply the style of @Image 1 to the scene in @Video 1".
    - Use @Image tags for the replacement/source and @Video for the target clip.
    """
    elif image_usage == "first_last_frame" and num_imgs >= 2:
        request_context = """
    REQUEST TYPE: FIRST + LAST FRAME
    - @Image 1 is the OPENING frame. @Image 2 is the CLOSING frame.
    - Describe the action, motion, and camera that transitions FROM @Image 1 TO @Image 2.
    - Do NOT re-describe the static content of either image. Reference them and describe the journey between.
    - Example: "Starting from @Image 1, the camera slowly pulls back as [action]. The scene evolves through [transition] until arriving at the composition in @Image 2."
    """
    elif image_usage == "first_frame" and num_imgs > 0:
        request_context = f"""
    REQUEST TYPE: FIRST FRAME (animate from image)
    - The user wants @Image 1 (and any other @Image X) to serve as the FIRST FRAME of the generated video.
    - Your prompt MUST state that the scene STARTS from @Image 1 (e.g. "The video starts from the frame in @Image 1. Then..." or "Using @Image 1 as the first frame, the scene evolves with...").
    - Describe how the scene evolves after that frame: motion, camera, action. Do not re-describe the static content of the image; reference it and continue the action.
    """
    elif image_usage == "reference_only" and num_imgs > 0:
        request_context = """
    REQUEST TYPE: REFERENCE ONLY (style/character reference)
    - The user wants the uploaded image(s) used as REFERENCE ONLY for style, character look, or environment mood—NOT as the first frame.
    - Use phrasing like: "The character (physical appearance and clothing referenced from @Image 1)", "The environment (style and lighting referenced from @Image 2)", "Maintain the visual style of @Image 1".
    - Generate a NEW scene/shot that matches the reference; do not say the video "starts from" the image.
    """
    elif image_usage == "composite" and num_imgs >= 2:
        _user_has_explicit_tags_bp = bool(
            re.search(r'@(?:Image|Video|Audio)\s*\d|@\d', scene_description or "")
        )
        if _user_has_explicit_tags_bp:
            request_context = f"""
    REQUEST TYPE: USER-DIRECTED MULTI-REFERENCE
    - The user has {num_imgs} images and has EXPLICITLY assigned @Image tags in their scene description.
    - RESPECT the user's @Image assignments exactly as written — each tag has a specific role the user defined.
    - NEVER renumber or reassign tags. @Image 1 means @Image 1, @Image 2 means @Image 2.
    - NEVER add a composite header like "The character from @Image 1 is located in the environment of @Image 2" — the user has already specified what each image does.
    - Use attribute locking phrasing ONLY for the tags the user explicitly mentions and in the role the user assigned.
    - If the user says @Image 1 is a diver reference and @Image 2 is a crate reference, respect that — do not swap or merge roles.
    """
        else:
            request_context = f"""
    REQUEST TYPE: COMPOSITE (multi-image reference)
    - The user wants to combine elements from {num_imgs} images. Each @Image should have a clear purpose.
    - Common patterns (use whichever fits the user's intent):
      * Character + Environment: "The character (referenced from @Image 1) is located within the environment (referenced from @Image 2)."
      * Character + Environment + Material: "The character from @Image 1, in the environment of @Image 2, with the surface material referencing @Image 3."
      * Character + Camera from Video: "Feature the character from @Image 1, with camera movements referencing @Video 1."
      * Multiple characters: "The spear-wielding character from @Image 1 and @Image 2, and the dual-blade character from @Image 3 and @Image 4."
    - ALWAYS describe as ONE composite state from the start — no journey from one image to the other.
    - Use attribute locking: "The character (physical attributes and clothing referenced from @Image X)"
    - Then add motion, camera, and action within the composite scene.
    """
    else:
        request_context = "\n    REQUEST TYPE: Standard generation. Use @ tags to state how each asset is used (reference, first frame, etc.) as appropriate to the narrative.\n"
    
    # Seedance 2.0: Technical Blueprint + CRITICAL OVERRIDE
    technical_blueprint_block = ""
    critical_override_block = ""
    ui_params = {}
    if shots_data:
        s0 = shots_data[0]
        ui_params = {
            "shot_type": clean_param(s0.get("shot_type")),
            "camera_angle": clean_param(s0.get("m1_angle")),
            "movement_type": clean_param(s0.get("m1_type")),
            "lighting_type": clean_param(s0.get("lighting")),
            "lighting_direction": clean_param(s0.get("lighting_direction")),
            "visual_style": clean_param(s0.get("style")),
            "mood": clean_param(s0.get("mood")),
        }
    ui_params.update({k: v for k, v in (kwargs or {}).items() if k in ("shot_type", "camera_angle", "movement_type", "lighting_type", "lighting_direction", "visual_style", "mood") and clean_param(v)})
    technical_blueprint_block = _build_technical_blueprint(ui_params)
    technical_blueprint_block = "\n    [Technical Blueprint]\n    " + technical_blueprint_block.replace("\n", "\n    ")
    if shots_data:
        critical_override_block = _critical_override_tones_2_0(shots_data)
        if critical_override_block:
            critical_override_block = "\n    CRITICAL OVERRIDE (tones — apply these directives):\n    " + critical_override_block.replace("\n", "\n    ")

    # TASK 1: raw_data for LLM user message (pre-formatted Seedance 2.0 draft)
    draft_2_0 = _pre_format_seedance_2_0(
        scene_description=scene_description,
        shots_data=shots_data,
        num_imgs=num_imgs, num_vids=num_vids, num_auds=num_auds,
        audio_sync=audio_sync,
        vision_context=vision_context,
        image_usage=image_usage,
        workflow_type=workflow_type,
        duration=duration,
        enforce_stability=enforce_stability,
    )
    raw_data = f"""STRUCTURED DRAFT (official ByteDance three-paragraph format):

{draft_2_0}

INSTRUCTIONS FOR REFINEMENT:
- Follow the three-paragraph structure exactly
- Ensure every @Image N and @Video N is followed by a descriptive noun in parentheses
- Verify only ONE camera movement per time slice
- Paragraph 3 must end with quality and anti-distortion constraints
- Do not add details not present in the draft"""
    raw_prompt = draft_2_0

    # --- CONDITIONAL CREATIVITY LOGIC ---
    creative_rule = ""
    if float(temperature) > 0.6:
        creative_rule = """
CREATIVE LICENSE (AUTHORIZED): The user has requested high creativity.
You are authorized to add cinematic details, emotional micro-expressions, and atmospheric lighting to enhance the scene.
You may expand on simple prompts (e.g., turn "A man walks" into "A weary man trudges through heavy mist"), provided you maintain strict Asset Links."""

    # Workflow-specific system instruction (modular template)
    workflow_instruction = _get_workflow_system_instruction(workflow_type, image_usage, num_vids, num_imgs)

    system_prompt = _system_prompt_seedance_2_0(workflow_instruction, creative_rule)

    final_narrative = call_llm_for_prompt(system_prompt, raw_data, temperature=temperature)
    
    # If LLM returned empty or an error, use core narrative as fallback and show the real error so user can fix it
    if not final_narrative or not final_narrative.strip() or final_narrative.startswith("[LLM ERROR"):
        fallback = strip_prompt_flags(scene_description or "Describe the scene.")
        err_msg = final_narrative.strip() if final_narrative and final_narrative.startswith("[LLM ERROR") else "LLM returned empty response"
        final_narrative = f"[{err_msg} — using your narrative as-is.] {fallback}"
    
    # Strip any existing legacy flags from narrative (e.g. from previous prompts or LLM slip)
    final_narrative = strip_prompt_flags(final_narrative)

    # STEP 5: Truncate if LLM generated excessively long prompt (degrades quality)
    if final_narrative and not final_narrative.startswith("[LLM ERROR"):
        final_narrative = _truncate_prompt(final_narrative, max_words=500)

    # Video Extension: force exact leading formula so prompt matches Generation Duration slider
    if workflow_type == "Video Extension" and num_vids > 0 and duration is not None:
        try:
            dur_int = int(duration)
            prefix = f"Extend @Video 1 by {dur_int}s. "
            if not final_narrative.strip().lower().startswith("extend @video 1"):
                final_narrative = prefix + final_narrative.strip()
        except (ValueError, TypeError):
            pass

    # Seedance 2.0: optionally inject stability constraints (disabled by default per official docs)
    if enforce_stability and final_narrative and not final_narrative.startswith("[LLM ERROR"):
        pass

    # Return both RAW and OPTIMISED prompts so the UI can choose which one to send to Seedance
    return {
        "raw_prompt": raw_prompt,
        "optimized_prompt": final_narrative,
    }

# ──────────────────────────────────────────────
# IMAGE PROMPT BUILDER (SEEDREAM 5.0)
# ──────────────────────────────────────────────



def _build_cinematography_string(**params):
    """
    Assembles cinematography parameters (from UI) into a single clean string for the LLM.
    All values are expanded via CINEMATIC_DICTIONARY.get(val, val) (Parameter Expansion for Seedream 5.0).
    Only includes fields that are present; empty or None are ignored.
    """
    def _expand(val):
        if val is None or (isinstance(val, str) and not val.strip()): return None
        return CINEMATIC_DICTIONARY.get(str(val).strip(), str(val).strip())

    shot_type = clean_param(params.get("shot_type"))
    camera = clean_param(params.get("camera"))
    lenses = clean_param(params.get("lenses"))
    lighting_type = clean_param(params.get("lighting_type"))
    lighting_direction = clean_param(params.get("lighting_direction"))
    lighting_source = clean_param(params.get("lighting_source"))
    mood = clean_param(params.get("mood"))
    period = clean_param(params.get("period"))
    film_stock = clean_param(params.get("film_stock"))
    sensor = clean_param(params.get("sensor"))

    shot_type_exp = _expand(shot_type) if shot_type else None
    camera_exp = _expand(camera) if camera else None
    lenses_exp = _expand(lenses) if lenses else None
    lighting_type_exp = _expand(lighting_type) if lighting_type else None
    lighting_direction_exp = _expand(lighting_direction) if lighting_direction else None
    lighting_source_exp = _expand(lighting_source) if lighting_source else None
    mood_exp = _expand(mood) if mood else None
    period_exp = _expand(period) if period else None
    film_stock_exp = _expand(film_stock) if film_stock else None
    sensor_exp = _expand(sensor) if sensor else None

    # Raw prompt: always write parameter name first, then expanded description ('Full Shot': 'Frames the subject...')
    parts = []
    if shot_type and shot_type_exp:
        parts.append(f"'{shot_type}': '{shot_type_exp}'")
    if camera and camera_exp:
        parts.append(f"'{camera}': '{camera_exp}'")
    if lenses and lenses_exp:
        parts.append(f"'{lenses}': '{lenses_exp}'")
    if lighting_type and lighting_type_exp:
        parts.append(f"'{lighting_type}': '{lighting_type_exp}'")
    if lighting_direction and lighting_direction_exp:
        parts.append(f"'{lighting_direction}': '{lighting_direction_exp}'")
    if lighting_source and lighting_source_exp:
        parts.append(f"'{lighting_source}': '{lighting_source_exp}'")
    if mood and mood_exp:
        parts.append(f"'{mood}': '{mood_exp}'")
    if period and period_exp:
        parts.append(f"'{period}': '{period_exp}'")
    if film_stock and film_stock_exp:
        parts.append(f"'{film_stock}': '{film_stock_exp}'")
    if sensor and sensor_exp:
        parts.append(f"'{sensor}': '{sensor_exp}'")

    if not parts:
        return ""
    return "[Technical Blueprint]\n" + "\n".join(parts) + "."


def _pre_format_seedream_5_0(prompt, style_preset="None", ref_images=None, **kwargs):
    """
    Pre-formats UI parameters into a draft already in Seedream 5.0
    photography grammar. Single paragraph describing a still image.
    Structure: Subject + Composition + Lighting + Style + Mood/Period + Technical gear.
    Uses CINEMATIC_DICTIONARY full expansions for gear (lenses, film, sensors).
    Uses short labels for composition (shot_type) and mood.
    Reference images: "image 1" lowercase, NO @ symbol.
    """
    parts = []

    # ── SECTION 7: REFERENCE IMAGES (at the start) ──
    if ref_images and len(ref_images) > 0:
        if len(ref_images) == 1:
            parts.append("Using image 1 as reference,")
        else:
            parts.append(f"Using image 1 through image {len(ref_images)} as reference,")

    # ── SECTION 1: SUBJECT (user's prompt / scene idea) ──
    if prompt and prompt.strip():
        subject = prompt.strip()
        # If refs precede, lowercase first char for flow
        if parts and subject and len(subject) > 1:
            subject = subject[0].lower() + subject[1:]
        parts.append(subject.rstrip('.') + '.')

    # ── SECTION 2: COMPOSITION (shot_type — short label only) ──
    shot_type = clean_param(kwargs.get("shot_type"))
    if shot_type:
        parts.append(f"Framed as a {shot_type.lower()}.")

    # ── SECTION 3: LIGHTING (type + direction + source) ──
    lighting_type = clean_param(kwargs.get("lighting_type"))
    lighting_direction = clean_param(kwargs.get("lighting_direction"))
    lighting_source = clean_param(kwargs.get("lighting_source"))

    # Use FULL dictionary expansions for lighting type and direction
    lt_exp = _expand_cinematic(lighting_type) if lighting_type else None
    ld_exp = _expand_cinematic(lighting_direction) if lighting_direction else None

    light_parts = []
    if lt_exp and ld_exp:
        light_parts.append(f"{lt_exp}, combined with {ld_exp}")
    elif lt_exp:
        light_parts.append(lt_exp)
    elif ld_exp:
        light_parts.append(ld_exp)

    if lighting_source:
        light_parts.append(f"{lighting_source.lower()} source")

    if light_parts:
        parts.append("Lit by " + ", ".join(light_parts) + ".")

    # ── SECTION 4: STYLE PRESET ──
    STYLE_MAP = {
        "Cinematic: Kodak Portra 400 (Nostalgic)": "Kodak Portra 400 film aesthetic with nostalgic color cast, visible grain, and hard flash effects.",
        "Design: Guochao Neo-Chinese (Red & Gold)": "Guochao Neo-Chinese design with warm red and gilded gold palette, intricate embroidery textures.",
        "Artistic: Chinese Origami Figures": "Chinese-style origami figures with paper texture and soft lighting.",
        "Artistic: Transparent Ice Sculptures": "Transparent ice sculptures with blue-to-purple gradient and cold ethereal atmosphere.",
        "Design: 2D Pixel Art (Top-Down)": "2D pixel art scene in top-down view with textured cartoon style.",
        "Design: Abstract Futuristic (Liquid Silver)": "Abstract futuristic style with liquid metal and silver-gray cool tones.",
        "Artistic: Monet Impressionism (Thick Oil)": "Monet Impressionism with thick oil paint textures and visible brushstrokes.",
        "Education: Hand-drawn Infographic": "Hand-drawn educational infographic style.",
    }
    if style_preset and str(style_preset).strip() and "None" not in str(style_preset):
        style_desc = STYLE_MAP.get(style_preset, f"{style_preset} visual style.")
        parts.append(f"Visual style: {style_desc}")

    # ── SECTION 5: MOOD + PERIOD ──
    mood = clean_param(kwargs.get("mood"))
    period = clean_param(kwargs.get("period"))

    if mood:
        parts.append(f"{mood} atmosphere.")
    if period:
        # Full expansion for period (contains costume, set, color info)
        period_exp = _expand_cinematic(period) or period
        parts.append(period_exp.rstrip('.') + '.')

    # ── SECTION 6: TECHNICAL GEAR (full expansions) ──
    camera = clean_param(kwargs.get("camera"))
    lenses = clean_param(kwargs.get("lenses"))
    film_stock = clean_param(kwargs.get("film_stock"))
    sensor = clean_param(kwargs.get("sensor"))

    gear_parts = []
    if sensor:
        sensor_exp = _expand_cinematic(sensor) or sensor
        gear_parts.append(f"shot on {sensor_exp}")
    if camera:
        camera_exp = _expand_cinematic(camera) or camera
        gear_parts.append(f"camera: {camera_exp}")
    if lenses:
        lenses_exp = _expand_cinematic(lenses) or lenses
        gear_parts.append(f"lens: {lenses_exp}")
    if film_stock:
        film_exp = _expand_cinematic(film_stock) or film_stock
        gear_parts.append(f"film: {film_exp}")

    if gear_parts:
        # Capitalize first, join with semicolons for readability
        gear_line = "; ".join(gear_parts)
        gear_line = gear_line[0].upper() + gear_line[1:] if gear_line else ""
        parts.append(gear_line.rstrip('.') + '.')

    return " ".join(parts).strip()


def build_image_prompt(prompt, style_preset="None", aspect_ratio="1:1", ref_images=None, temperature=0.5, **kwargs):
    """
    Builds a Seedream 5.0 draft and asks Seed 1.8 to polish it.
    Aspect ratio / resolution remain payload-only (not part of LLM semantics).
    """
    if not prompt or not prompt.strip():
        return {"raw_prompt": "[ERROR: Prompt is required]", "optimized_prompt": "[ERROR: Prompt is required]"}

    # Reference images: use Seedream format (lowercase "image X", no @ symbol)
    ref_context = ""
    if ref_images and len(ref_images) > 0:
        if len(ref_images) == 1:
            ref_context = "A reference image (image 1) is provided for style/content guidance."
        else:
            ref_context = f"{len(ref_images)} reference images are provided (image 1 through image {len(ref_images)}). Reference them as 'image 1', 'image 2', etc."

    # ─── Pre-format draft in Seedream 5.0 photography grammar ───
    draft_5_0 = _pre_format_seedream_5_0(
        prompt=prompt,
        style_preset=style_preset,
        ref_images=ref_images,
        shot_type=kwargs.get("shot_type"),
        camera=kwargs.get("camera"),
        lenses=kwargs.get("lenses"),
        lighting_type=kwargs.get("lighting_type"),
        lighting_direction=kwargs.get("lighting_direction"),
        lighting_source=kwargs.get("lighting_source"),
        mood=kwargs.get("mood"),
        period=kwargs.get("period"),
        film_stock=kwargs.get("film_stock"),
        sensor=kwargs.get("sensor"),
    )

    system_instruction = """You are a professional photographer polishing a pre-formatted draft for the Seedream 5.0 image generation engine.

TASK: Refine the draft into ONE cohesive paragraph. TARGET: 30-100 words.

RULES:
1. Keep ALL technical terms (lens names, film stocks, sensor types) exactly as written.
2. Integrate everything into natural photographer prose — as if describing a frame to an assistant.
3. Reference images: use "image 1", "image 2" (lowercase, NO @ symbol).
4. Do NOT add camera movement — this is a still image.
5. Do NOT add details the user did not specify.
6. If a visual style preset is described, it MUST appear in your output.
7. For image editing (when draft starts with "Keep" or "Using image"): use direct instructions like "Keep [X] unchanged. Change [Y] to [Z]."
8. NEVER exceed 100 words.

Output ONLY the final prompt. No explanations. No markdown. English only."""

    user_content = f"""DRAFT IN SEEDREAM 5.0 FORMAT (refine into polished prose):

{draft_5_0}
"""

    raw_blueprint_string = draft_5_0

    try:
        expanded_prompt = call_llm_for_prompt(
            system_instruction, user_content, temperature=temperature, model_id=SEED_1_8_ID
        )
        if expanded_prompt and str(expanded_prompt).strip():
            # Seedream 5.0 official limit: 600 words. Use 500 for safety margin.
            expanded_prompt = _truncate_prompt(expanded_prompt, max_words=500)
            if "\n\n" in expanded_prompt.strip():
                expanded_prompt = expanded_prompt.strip().split("\n\n")[0].strip()
        else:
            expanded_prompt = "[ERROR: LLM returned empty. Check API key and endpoint.]"
        return {"raw_prompt": raw_blueprint_string, "optimized_prompt": expanded_prompt}
    except Exception as e:
        traceback.print_exc()
        return {"raw_prompt": raw_blueprint_string, "optimized_prompt": "", "error": str(e)}
