"""Throwaway feasibility test: Doubao Seed 2.0 Lite vision + JSON schema.

Verifies a single-image call to the BytePlus ARK chat completions endpoint
returns valid structured JSON for the "Scene & Setting" cinematography group.

Run once, then delete. Does NOT touch builder.py / generator.py.
"""
import os
import sys
import json
import glob
import base64
import mimetypes

import requests

ENDPOINT = "https://ark.ap-southeast.bytepluses.com/api/v3/chat/completions"
MODEL_ID = "seed-2-0-lite-260428"
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "generated", "assets")

# Pricing for this test's cost estimate
INPUT_USD_PER_M = 0.25
OUTPUT_USD_PER_M = 2.00


def _find_sample_image():
    patterns = ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG")
    for root, _dirs, _files in os.walk(ASSETS_DIR):
        for pat in patterns:
            hits = sorted(glob.glob(os.path.join(root, pat)))
            if hits:
                return hits[0]
    return None


def main():
    api_key = os.getenv("ARK_API_KEY")
    if not api_key:
        print("ERROR: ARK_API_KEY is not set in the environment. Stopping.")
        sys.exit(1)

    img_path = _find_sample_image()
    if not img_path:
        print(f"ERROR: no .jpg/.png image found under {ASSETS_DIR}. Stopping.")
        sys.exit(1)
    print(f"[image] Using: {img_path}")

    mime = mimetypes.guess_type(img_path)[0] or "image/jpeg"
    with open(img_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    data_url = f"data:{mime};base64,{b64}"

    payload = {
        "model": MODEL_ID,
        "thinking": {"type": "disabled"},
        "messages": [
            {
                "role": "system",
                "content": "You are a professional cinematographer analyzing a visual reference. Extract structured information about the Scene & Setting only. Be precise, descriptive, and use cinematic language.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": "Analyze this image and return the requested Scene & Setting fields."},
                ],
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "scene_setting_analysis",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "scene_description": {"type": "string", "description": "One concise sentence describing the overall scene."},
                        "location": {"type": "string", "description": "Geographic and environmental context (e.g. coastal Mediterranean, dense urban, alpine forest)."},
                        "specific_setting": {"type": "string", "description": "Interior or exterior + type (e.g. abandoned warehouse interior, rooftop exterior)."},
                        "era_period": {"type": "string", "description": "Historical era inferred from visual cues (e.g. late 19th century, 1970s, contemporary)."},
                        "time_of_day": {"type": "string", "description": "Inferred time (golden hour, blue hour, midday, night, dawn, etc.)."},
                        "weather": {"type": "string", "description": "Weather conditions (clear, overcast, rain, snow, fog, etc.)."},
                    },
                    "required": ["scene_description", "location", "specific_setting", "era_period", "time_of_day", "weather"],
                    "additionalProperties": False,
                },
            },
        },
    }

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        resp = requests.post(ENDPOINT, headers=headers, json=payload, timeout=60)
    except Exception as e:
        print(f"ERROR: request failed: {type(e).__name__}: {e}")
        sys.exit(1)

    print(f"[http] status: {resp.status_code}")
    if not resp.ok:
        print(f"[http] error body: {resp.text[:2000]}")
        sys.exit(1)

    body = resp.json()

    # Structured content
    try:
        content = body["choices"][0]["message"]["content"]
        print("\n=== MODEL CONTENT (raw) ===")
        print(content)
        print("\n=== MODEL CONTENT (parsed JSON) ===")
        print(json.dumps(json.loads(content), indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"WARNING: could not parse choices[0].message.content as JSON: {e}")
        print("Full response below.")

    print("\n=== FULL RESPONSE ===")
    print(json.dumps(body, indent=2, ensure_ascii=False))

    usage = body.get("usage", {}) or {}
    pt = usage.get("prompt_tokens", 0)
    ct = usage.get("completion_tokens", 0)
    tt = usage.get("total_tokens", pt + ct)
    print("\n=== USAGE ===")
    print(f"prompt_tokens={pt}  completion_tokens={ct}  total_tokens={tt}")

    cost = (pt / 1_000_000) * INPUT_USD_PER_M + (ct / 1_000_000) * OUTPUT_USD_PER_M
    print("\n=== ESTIMATED COST (this call) ===")
    print(f"${cost:.6f}  (input ${INPUT_USD_PER_M}/M, output ${OUTPUT_USD_PER_M}/M)")


if __name__ == "__main__":
    main()
