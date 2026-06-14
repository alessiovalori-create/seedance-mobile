"""LAB Analysis Schemas — Cinematographic parameter extraction definitions. Each
of 8 groups defines a system prompt (DOP voice), a user instruction, and a strict
JSON schema for the vision model to populate."""

from typing import Dict, List, Optional, Any

# ──────────────────────────────────────────────
# SHARED VOICE
# ──────────────────────────────────────────────

SHARED_SYSTEM_PROMPT = (
    "You are a professional Director of Photography with decades of experience "
    "analyzing cinematic still frames and references. Your task is to look at the "
    "provided image and extract precise, descriptive observations using authentic "
    "cinematography vocabulary. Be specific and confident — avoid vague hedging "
    "language. When a property cannot be determined from the image, set the field "
    "to the string 'undetermined' rather than guessing. Use natural professional "
    "phrasing, not technical jargon dumps. Keep each field concise (typically a "
    "noun phrase or short sentence) so the output can be used directly as prompt "
    "fragments."
)


# ──────────────────────────────────────────────
# GROUP DEFINITIONS
# ──────────────────────────────────────────────

GROUP_SCENE_SETTING = {
    "id": "scene_setting",
    "label": "Scene & Setting",
    "description": "Location, environment, era, time of day, and weather of the frame.",
    "system_prompt": SHARED_SYSTEM_PROMPT,
    "user_prompt": (
        "Analyze the scene and setting in this image. Identify the location type, "
        "the specific environment, the historical era inferred from visual cues, "
        "the time of day, and the weather conditions. Be precise."
    ),
    "schema_name": "scene_setting_analysis",
    "video_only": False,
    "schema": {
        "type": "object",
        "properties": {
            "scene_description": {"type": "string", "description": "One concise sentence describing the overall scene as a DP would in a shot list."},
            "location": {"type": "string", "description": "Geographic and environmental context (e.g. 'Mediterranean coastal village', 'dense urban canyon', 'high alpine forest')."},
            "specific_setting": {"type": "string", "description": "Interior or exterior plus type (e.g. 'abandoned industrial warehouse interior', 'rooftop exterior at dusk')."},
            "era_period": {"type": "string", "description": "Historical era inferred from visual cues (e.g. 'late 19th century', '1970s', 'contemporary', 'undated/timeless')."},
            "time_of_day": {"type": "string", "description": "Inferred time (golden hour, blue hour, midday, night, dawn, dusk, etc.)."},
            "weather": {"type": "string", "description": "Weather conditions (clear, overcast, rain, snow, fog, haze, etc.)."},
        },
        "required": ["scene_description", "location", "specific_setting", "era_period", "time_of_day", "weather"],
        "additionalProperties": False,
    },
}

GROUP_CINEMATOGRAPHY = {
    "id": "cinematography",
    "label": "Cinematography",
    "description": "Shot size, angle, movement, lens, composition, and aspect ratio.",
    "system_prompt": SHARED_SYSTEM_PROMPT,
    "user_prompt": (
        "Analyze the cinematography of this frame. Identify shot size, camera angle, "
        "apparent camera movement (static if no motion blur or implied movement), "
        "lens characteristics, compositional strategy, and aspect ratio."
    ),
    "schema_name": "cinematography_analysis",
    "video_only": False,
    "schema": {
        "type": "object",
        "properties": {
            "shot_size": {"type": "string", "description": "Shot size (extreme wide, wide, medium wide, medium, medium close-up, close-up, extreme close-up)."},
            "camera_angle": {"type": "string", "description": "Camera angle (low angle, high angle, eye-level, dutch tilt, overhead, worm's eye)."},
            "camera_movement": {"type": "string", "description": "Implied camera movement (static, slow push-in, pan, tilt, dolly, crane, handheld, steadicam, gimbal). State 'static' if uncertain."},
            "lens_characteristics": {"type": "string", "description": "Lens behavior visible in the frame (wide / normal / telephoto, anamorphic vs spherical cues, depth of field characteristics, lens flares, distortion)."},
            "composition": {"type": "string", "description": "Compositional strategy (rule of thirds, symmetry, leading lines, frame within frame, negative space, centered, off-center)."},
            "aspect_ratio": {"type": "string", "description": "Visual aspect ratio (2.39:1, 2.00:1, 1.85:1, 16:9, 4:3, 1:1, etc.)."},
        },
        "required": ["shot_size", "camera_angle", "camera_movement", "lens_characteristics", "composition", "aspect_ratio"],
        "additionalProperties": False,
    },
}

GROUP_LIGHT = {
    "id": "light",
    "label": "Light",
    "description": "Quality, direction, contrast, color temperature, sources, and atmosphere.",
    "system_prompt": SHARED_SYSTEM_PROMPT,
    "user_prompt": (
        "Analyze the lighting in this frame with a cinematographer's eye. Identify "
        "quality, direction, contrast, color temperature, motivated sources, and "
        "atmospheric quality."
    ),
    "schema_name": "light_analysis",
    "video_only": False,
    "schema": {
        "type": "object",
        "properties": {
            "lighting_quality": {"type": "string", "description": "Hard, soft, diffused, or specular — describe the dominant quality."},
            "key_direction": {"type": "string", "description": "Direction of the key light (front, side, three-quarter front, three-quarter back, back/rim, top, underlight)."},
            "contrast_ratio": {"type": "string", "description": "Contrast quality (high-key, low-key, balanced, high-contrast chiaroscuro, flat)."},
            "color_temperature": {"type": "string", "description": "Color temperature feel (tungsten warm, daylight neutral, mixed sources, cool/teal, warm/amber)."},
            "motivated_sources": {"type": "string", "description": "Apparent practical or naturalistic light sources (window, practical lamp, fire, sun, fluorescent, ambient sky, undetermined)."},
            "atmospheric_quality": {"type": "string", "description": "Atmospheric elements (clean air, haze, smoke, dust, particulates, volumetric beams, none)."},
        },
        "required": ["lighting_quality", "key_direction", "contrast_ratio", "color_temperature", "motivated_sources", "atmospheric_quality"],
        "additionalProperties": False,
    },
}

GROUP_COLOR = {
    "id": "color",
    "label": "Color & Look",
    "description": "Palette, accents, grading feel, stock character, and grain/texture.",
    "system_prompt": SHARED_SYSTEM_PROMPT,
    "user_prompt": (
        "Analyze the color palette and grading look of this frame. Identify the "
        "dominant palette, accent colors, the grading feel, the film stock or digital "
        "character, and grain/texture."
    ),
    "schema_name": "color_analysis",
    "video_only": False,
    "schema": {
        "type": "object",
        "properties": {
            "dominant_palette": {"type": "string", "description": "Three to five dominant colors in plain language (e.g. 'desaturated teal, dirty cream, deep umber, muted rust')."},
            "accent_colors": {"type": "string", "description": "Accent colors that punctuate the frame, if any (or 'none')."},
            "grading_feel": {"type": "string", "description": "Color grading character (teal-orange, bleach bypass, sepia, desaturated, vibrant, monochrome, naturalistic, undetermined)."},
            "stock_feel": {"type": "string", "description": "Film stock or digital character (35mm photochemical, 16mm grainy, Super 8 saturated, digital clean, vintage video, etc.)."},
            "grain_texture": {"type": "string", "description": "Grain or texture (fine grain, heavy grain, clean digital, noise, halation, none)."},
        },
        "required": ["dominant_palette", "accent_colors", "grading_feel", "stock_feel", "grain_texture"],
        "additionalProperties": False,
    },
}

GROUP_PRODUCTION_DESIGN = {
    "id": "production_design",
    "label": "Production Design",
    "description": "Architecture, materials, surface textures, and key props.",
    "system_prompt": SHARED_SYSTEM_PROMPT,
    "user_prompt": (
        "Analyze the production design. Identify architectural style, materials "
        "visible in frame, surface textures, and key props or set dressing."
    ),
    "schema_name": "production_design_analysis",
    "video_only": False,
    "schema": {
        "type": "object",
        "properties": {
            "architectural_style": {"type": "string", "description": "Architectural style (brutalist, art deco, baroque, mid-century modern, industrial, vernacular, contemporary, undetermined)."},
            "materials_in_frame": {"type": "string", "description": "Primary materials visible (wood, marble, concrete, glass, fabric, leather, metal, stone, plaster — list the dominant ones)."},
            "surface_textures": {"type": "string", "description": "Texture quality (weathered, polished, rough, glossy, matte, patina, distressed, pristine)."},
            "key_props": {"type": "string", "description": "Notable props or set dressing that define the scene (brief comma-separated list)."},
        },
        "required": ["architectural_style", "materials_in_frame", "surface_textures", "key_props"],
        "additionalProperties": False,
    },
}

GROUP_WARDROBE = {
    "id": "wardrobe",
    "label": "Wardrobe & Characters",
    "description": "Wardrobe by group, hair/makeup, casting feel, and body language.",
    "system_prompt": SHARED_SYSTEM_PROMPT,
    "user_prompt": (
        "Analyze the wardrobe and physical presentation of characters in this frame. "
        "Describe women's wardrobe, men's wardrobe, hair and makeup, general casting "
        "feel, and body language. Skip categories that don't apply (use 'not "
        "applicable' for absent groups)."
    ),
    "schema_name": "wardrobe_analysis",
    "video_only": False,
    "schema": {
        "type": "object",
        "properties": {
            "womens_wardrobe": {"type": "string", "description": "Women's wardrobe (silhouette, fabric, era cues, accessories), or 'not applicable'."},
            "mens_wardrobe": {"type": "string", "description": "Men's wardrobe (silhouette, fabric, era cues, accessories), or 'not applicable'."},
            "childrens_wardrobe": {"type": "string", "description": "Children's wardrobe if visible, or 'not applicable'."},
            "hair_makeup": {"type": "string", "description": "Hair and makeup cues — period-accurate styling notes, or 'not applicable'."},
            "casting_feel": {"type": "string", "description": "General physical description of subjects (do NOT use real names — describe physical/ethnic/age type)."},
            "body_language": {"type": "string", "description": "Body language and blocking (static, dynamic, intimate, distant, confrontational, contemplative, gestural)."},
        },
        "required": ["womens_wardrobe", "mens_wardrobe", "childrens_wardrobe", "hair_makeup", "casting_feel", "body_language"],
        "additionalProperties": False,
    },
}

GROUP_MOOD = {
    "id": "mood",
    "label": "Mood & Reference",
    "description": "Emotional tone, genre association, and stylistic reference (no names).",
    "system_prompt": SHARED_SYSTEM_PROMPT,
    "user_prompt": (
        "Analyze the emotional tone and genre association of this frame. Describe its "
        "mood, the genre it evokes, and the broader cinematic feel — without naming "
        "specific films, directors, or DPs."
    ),
    "schema_name": "mood_analysis",
    "video_only": False,
    "schema": {
        "type": "object",
        "properties": {
            "emotional_tone": {"type": "string", "description": "Emotional tone (melancholic, tense, joyful, oneiric, contemplative, menacing, romantic, etc.)."},
            "genre_association": {"type": "string", "description": "Genre association (noir, western, sci-fi, period drama, thriller, romance, documentary, art-house, etc.)."},
            "cinematic_reference": {"type": "string", "description": "Stylistic reference described in pure visual terms (NO film titles, NO director or DP names — describe the look itself: 'European art-house naturalism with handheld intimacy', 'painterly Renaissance-influenced chiaroscuro', etc.)."},
        },
        "required": ["emotional_tone", "genre_association", "cinematic_reference"],
        "additionalProperties": False,
    },
}

GROUP_MOTION = {
    "id": "motion",
    "label": "Motion",
    "description": "Subject movement, pace/rhythm, and the beat's action arc (video only).",
    "system_prompt": SHARED_SYSTEM_PROMPT,
    "user_prompt": (
        "Analyze motion in this video clip — both subject movement and the pace/rhythm "
        "of action. Describe what physically happens in the beat of this shot."
    ),
    "schema_name": "motion_analysis",
    "video_only": True,
    "schema": {
        "type": "object",
        "properties": {
            "subject_movement": {"type": "string", "description": "Subject movement (static, walking, running, dancing, gesture, sitting, turning, etc.)."},
            "pace_rhythm": {"type": "string", "description": "Pace and rhythm of action (slow and deliberate, frenetic, syncopated, hesitant, fluid, staccato)."},
            "beat_action": {"type": "string", "description": "What happens in this shot's beat — one or two sentences describing the action arc."},
        },
        "required": ["subject_movement", "pace_rhythm", "beat_action"],
        "additionalProperties": False,
    },
}


# ──────────────────────────────────────────────
# AGGREGATES
# ──────────────────────────────────────────────

ALL_GROUPS = [
    GROUP_SCENE_SETTING,
    GROUP_CINEMATOGRAPHY,
    GROUP_LIGHT,
    GROUP_COLOR,
    GROUP_PRODUCTION_DESIGN,
    GROUP_WARDROBE,
    GROUP_MOOD,
    GROUP_MOTION,
]

GROUPS_BY_ID = {g["id"]: g for g in ALL_GROUPS}


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────

def get_image_groups() -> List[dict]:
    """Return the groups usable on still images (video_only is False)."""
    return [g for g in ALL_GROUPS if not g["video_only"]]


def get_video_groups() -> List[dict]:
    """Return all groups (image groups apply to videos via keyframes, plus Motion)."""
    return list(ALL_GROUPS)


def get_group(group_id: str) -> dict:
    """Return the group dict by id, or raise KeyError with a clear message."""
    try:
        return GROUPS_BY_ID[group_id]
    except KeyError:
        raise KeyError(
            f"Unknown group id '{group_id}'. Valid ids: {', '.join(GROUPS_BY_ID.keys())}"
        )


# ──────────────────────────────────────────────
# SELF-TEST
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import json

    REQUIRED_KEYS = {"id", "label", "schema_name", "system_prompt", "user_prompt", "video_only", "schema"}
    problems = []

    image_count = len(get_image_groups())
    video_only_count = sum(1 for g in ALL_GROUPS if g["video_only"])

    print(f"Total groups: {len(ALL_GROUPS)}")
    print(f"Image-usable groups (video_only False): {image_count}")
    print(f"Video-only groups (video_only True): {video_only_count}")
    print(f"get_video_groups() count: {len(get_video_groups())}")
    print()

    for g in ALL_GROUPS:
        gid = g.get("id", "<missing id>")

        # Required top-level keys
        missing = REQUIRED_KEYS - set(g.keys())
        if missing:
            problems.append(f"[{gid}] missing top-level keys: {sorted(missing)}")
            continue

        schema = g["schema"]

        # Schema structural keys
        for sk in ("type", "properties", "required", "additionalProperties"):
            if sk not in schema:
                problems.append(f"[{gid}] schema missing key '{sk}'")

        if schema.get("type") != "object":
            problems.append(f"[{gid}] schema type is not 'object'")
        if schema.get("additionalProperties") is not False:
            problems.append(f"[{gid}] additionalProperties is not False")

        props = schema.get("properties", {})
        required = schema.get("required", [])

        # required must match properties keys exactly
        if set(required) != set(props.keys()):
            problems.append(
                f"[{gid}] required {sorted(required)} != properties {sorted(props.keys())}"
            )

        # all sub-fields must be string type with a description
        for fname, fdef in props.items():
            if fdef.get("type") != "string":
                problems.append(f"[{gid}.{fname}] type is not 'string'")
            if not fdef.get("description"):
                problems.append(f"[{gid}.{fname}] missing description")

        print(f"  {gid:18s} — {len(props)} sub-fields, video_only={g['video_only']}")

    print()
    print("Example group (GROUP_SCENE_SETTING):")
    print(json.dumps(GROUP_SCENE_SETTING, indent=2, ensure_ascii=False))
    print()

    if problems:
        print("FAIL — structural issues found:")
        for p in problems:
            print(f"  - {p}")
    else:
        print("ALL GROUPS VALID")
