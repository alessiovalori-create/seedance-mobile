"""LAB Vision Analysis — Doubao Seed 2.0 Lite multimodal analysis of images and
videos for the LAB section. Extracts structured cinematic parameters as JSON for
use in prompt building."""

import os
import base64
import json
import requests
import traceback
import time
import hashlib
from pathlib import Path
from typing import Optional, Dict, List, Any

# ──────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────

# Model switching — change ACTIVE_MODEL to fall back to Seed 1.8 if Lite has issues
SEED_2_0_LITE_ID = "seed-2-0-lite-260428"
SEED_1_8_ID = "seed-1-8-251228"
ACTIVE_MODEL = SEED_1_8_ID  # change to SEED_2_0_LITE_ID once Lite entitlement is active

# API endpoint (same as builder.py / generator.py)
ARK_BASE_URL = os.getenv("ARK_LLM_URL", "https://ark.ap-southeast.bytepluses.com/api/v3/chat/completions")

# Pricing for cost estimation (USD per million tokens)
PRICING = {
    SEED_2_0_LITE_ID: {"input": 0.25, "output": 2.00},
    SEED_1_8_ID: {"input": 0.50, "output": 2.00},  # placeholder — verify Seed 1.8 pricing on BytePlus ARK console
    # TODO: verify Seed 1.8 pricing on BytePlus ARK console
}

# Request defaults
DEFAULT_TIMEOUT = 90  # seconds
DEFAULT_MAX_TOKENS = 2048


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────

def _get_api_key() -> str:
    """Read ARK_API_KEY from environment. Raise RuntimeError if missing."""
    key = os.getenv("ARK_API_KEY")
    if not key:
        raise RuntimeError(
            "ARK_API_KEY is not set in the environment. "
            "Set it (same key used by builder.py / generator.py) and retry."
        )
    return key


def _encode_image_to_data_url(image_path: str) -> str:
    """Base64-encode an image file and return a data URL string.

    Format: "data:image/<mime>;base64,<base64-string>"
    Raises FileNotFoundError if the path does not exist.
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    ext = os.path.splitext(image_path)[1].lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    mime = mime_map.get(ext, "image/jpeg")

    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _compute_cost(prompt_tokens: int, completion_tokens: int, model_id: str) -> float:
    """Return estimated cost in USD using the PRICING dict.

    Falls back to Lite pricing if model_id is not present.
    """
    rates = PRICING.get(model_id, PRICING[SEED_2_0_LITE_ID])
    return (
        (prompt_tokens / 1_000_000) * rates["input"]
        + (completion_tokens / 1_000_000) * rates["output"]
    )


def _strip_code_fences(text: str) -> str:
    """Remove surrounding markdown code fences (```json ... ``` or ``` ... ```)."""
    s = (text or "").strip()
    if s.startswith("```"):
        # drop the opening fence line (``` or ```json)
        nl = s.find("\n")
        if nl != -1:
            s = s[nl + 1:]
        # drop trailing fence
        if s.rstrip().endswith("```"):
            s = s.rstrip()[: -3]
    return s.strip()


def _extract_json_substring(text: str) -> Optional[str]:
    """Return the substring from the first '{' to the matching/last '}', or None."""
    s = text or ""
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        return s[start: end + 1]
    return None


def _parse_with_fallbacks(raw_content: str):
    """Try to parse JSON from raw model content using ordered fallbacks.

    Returns (parsed_dict_or_None, mode) where mode is:
      - "fallback_prompt"  : direct json.loads or fence-stripped json.loads succeeded
      - "fallback_extract" : succeeded only after extracting a { ... } substring
      - None               : all strategies failed
    """
    # 1) direct
    try:
        return json.loads(raw_content), "fallback_prompt"
    except Exception:
        pass
    # 2) strip markdown fences
    try:
        return json.loads(_strip_code_fences(raw_content)), "fallback_prompt"
    except Exception:
        pass
    # 3) extract first { ... last }
    sub = _extract_json_substring(raw_content)
    if sub is not None:
        try:
            return json.loads(sub), "fallback_extract"
        except Exception:
            pass
    return None, None


# ──────────────────────────────────────────────
# MAIN FUNCTION
# ──────────────────────────────────────────────

def analyze_image(
    image_path: str,
    system_prompt: str,
    user_prompt: str,
    json_schema: dict,
    schema_name: str = "analysis",
    model_id: Optional[str] = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """
    Analyze a single image with the configured vision model.

    Returns a dict with this structure:
    {
        "success": bool,
        "model_used": str,
        "data": dict or None,       # parsed JSON from model response (matches json_schema)
        "raw_content": str or None, # raw content string from model
        "error": str or None,       # error message if success is False
        "usage": {                  # token usage breakdown
            "prompt_tokens": int,
            "completion_tokens": int,
            "total_tokens": int,
        } or None,
        "cost_usd": float or None,  # estimated cost in USD
        "duration_seconds": float,  # wall-clock duration of the API call(s)
        "schema_mode": str or None, # "strict" | "fallback_prompt" | "fallback_extract"
    }

    Strict json_schema mode is attempted first. If the model/endpoint does not
    support response_format json_schema (HTTP error mentioning it) OR returns
    content that is not valid JSON, the request is retried ONCE without
    response_format, appending an explicit "return only JSON" instruction to the
    user prompt, then parsed with ordered fallbacks.

    The function never raises exceptions for API errors — it captures them in the "error" field
    so the UI layer can display them gracefully. It DOES raise for programming errors
    (missing file, missing API key, invalid schema).
    """
    model_used = model_id or ACTIVE_MODEL

    # Programming-error checks (these DO raise)
    api_key = _get_api_key()
    data_url = _encode_image_to_data_url(image_path)
    if not isinstance(json_schema, dict) or not json_schema:
        raise ValueError("json_schema must be a non-empty dict.")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def _base_result(**over):
        out = {
            "success": False,
            "model_used": model_used,
            "data": None,
            "raw_content": None,
            "error": None,
            "usage": None,
            "cost_usd": None,
            "duration_seconds": 0.0,
            "schema_mode": None,
        }
        out.update(over)
        return out

    def _build_payload(user_text: str, with_schema: bool) -> dict:
        p = {
            "model": model_used,
            "thinking": {"type": "disabled"},
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": user_text},
                    ],
                },
            ],
        }
        if with_schema:
            p["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": json_schema,
                },
            }
        return p

    def _post(payload: dict) -> dict:
        """Single HTTP call. Returns dict with net_error/status/text/body/raw_content/duration."""
        out = {"net_error": None, "status": None, "text": "", "body": None,
               "raw_content": None, "duration": 0.0}
        _t0 = time.perf_counter()
        try:
            resp = requests.post(ARK_BASE_URL, headers=headers, json=payload, timeout=timeout)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            out["net_error"] = f"{type(e).__name__}: {e}"
            out["duration"] = time.perf_counter() - _t0
            return out
        except Exception as e:
            out["net_error"] = f"Unexpected request error — {type(e).__name__}: {e}"
            out["duration"] = time.perf_counter() - _t0
            return out
        out["duration"] = time.perf_counter() - _t0
        out["status"] = resp.status_code
        out["text"] = resp.text or ""
        if resp.status_code == 200:
            try:
                out["body"] = resp.json()
                out["raw_content"] = out["body"]["choices"][0]["message"]["content"]
            except Exception as e:
                out["net_error"] = f"Bad response envelope — {type(e).__name__}: {e}"
        return out

    def _usage_cost(body: dict):
        u = (body or {}).get("usage", {}) or {}
        pt = int(u.get("prompt_tokens", 0) or 0)
        ct = int(u.get("completion_tokens", 0) or 0)
        tt = int(u.get("total_tokens", pt + ct) or (pt + ct))
        return {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": tt}, _compute_cost(pt, ct, model_used)

    _SCHEMA_HINTS = ("response_format", "json_schema", "unsupported")

    # ── Attempt 1: strict json_schema mode ──
    r1 = _post(_build_payload(user_prompt, with_schema=True))
    total_dur = r1["duration"]

    needs_fallback = False
    if r1["net_error"] and r1["status"] is None:
        # pure network failure on first attempt — report, no retry
        return _base_result(error=r1["net_error"], duration_seconds=round(total_dur, 3))

    if r1["status"] == 200 and r1["raw_content"] is not None:
        usage1, cost1 = _usage_cost(r1["body"])
        try:
            parsed = json.loads(r1["raw_content"])
            return _base_result(
                success=True, data=parsed, raw_content=r1["raw_content"],
                usage=usage1, cost_usd=cost1, duration_seconds=round(total_dur, 3),
                schema_mode="strict",
            )
        except Exception:
            # strict mode likely ignored — content not valid JSON → fallback
            needs_fallback = True
    else:
        # non-200 or bad envelope. Fallback only if it looks schema-related.
        err_blob = f"{r1.get('text','')} {r1.get('net_error','')}".lower()
        if any(h in err_blob for h in _SCHEMA_HINTS):
            needs_fallback = True
        else:
            return _base_result(
                error=f"HTTP {r1['status']}: {r1.get('text','')[:4000]}" if r1["status"] else r1["net_error"],
                duration_seconds=round(total_dur, 3),
            )

    if not needs_fallback:
        # Shouldn't reach here, but guard against silent fall-through.
        return _base_result(error="Unknown strict-mode failure.", duration_seconds=round(total_dur, 3))

    # ── Attempt 2: fallback without response_format + explicit JSON instruction ──
    fb_user_prompt = user_prompt + (
        "\n\nIMPORTANT: Return ONLY a valid JSON object matching this exact structure "
        "(no markdown, no code fences, no preamble):\n" + json.dumps(json_schema, indent=2)
    )
    r2 = _post(_build_payload(fb_user_prompt, with_schema=False))
    total_dur += r2["duration"]

    if r2["net_error"] and r2["status"] is None:
        return _base_result(error=f"Fallback network failure — {r2['net_error']}",
                            duration_seconds=round(total_dur, 3))
    if r2["status"] != 200 or r2["raw_content"] is None:
        return _base_result(
            error=f"Fallback HTTP {r2['status']}: {r2.get('text','')[:4000]}"
                  if r2["status"] else f"Fallback envelope error — {r2.get('net_error')}",
            duration_seconds=round(total_dur, 3),
        )

    usage2, cost2 = _usage_cost(r2["body"])
    parsed, mode = _parse_with_fallbacks(r2["raw_content"])
    if parsed is None:
        return _base_result(
            error="json_parse_failed: model did not return parseable JSON after fallback retry.",
            raw_content=r2["raw_content"],
            usage=usage2, cost_usd=cost2, duration_seconds=round(total_dur, 3),
            schema_mode=None,
        )

    return _base_result(
        success=True, data=parsed, raw_content=r2["raw_content"],
        usage=usage2, cost_usd=cost2, duration_seconds=round(total_dur, 3),
        schema_mode=mode,
    )


# ──────────────────────────────────────────────
# SELF-TEST
# ──────────────────────────────────────────────

if __name__ == "__main__":
    def _find_sample_image() -> Optional[str]:
        assets = Path(__file__).resolve().parent / "data" / "assets"
        exts = {".jpg", ".jpeg", ".png"}
        candidates = [
            p for p in sorted(assets.rglob("*"))
            if p.is_file() and p.suffix.lower() in exts
        ]
        return str(candidates[0]) if candidates else None

    try:
        sample_image = _find_sample_image()
        if not sample_image:
            print("SELF-TEST: no sample image found under data/generated/assets/. Stopping.")
        else:
            print(f"SELF-TEST: using image {sample_image}")

            sample_schema = {
                "type": "object",
                "properties": {
                    "scene_description": {"type": "string"},
                    "location": {"type": "string"},
                    "era_period": {"type": "string"},
                },
                "required": ["scene_description", "location", "era_period"],
                "additionalProperties": False,
            }

            result = analyze_image(
                image_path=sample_image,
                system_prompt=(
                    "You are a professional cinematographer analyzing a visual reference. "
                    "Extract structured information about the Scene & Setting only. "
                    "Be precise, descriptive, and use cinematic language."
                ),
                user_prompt="Analyze this image and return the requested Scene & Setting fields.",
                json_schema=sample_schema,
                schema_name="scene_setting_smoke_test",
            )
            print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception:
        print("SELF-TEST failed with an exception:")
        traceback.print_exc()
