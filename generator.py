"""Pure backend module. No Streamlit dependency. Load credentials from environment variables only."""

import os
import time
import ssl
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
import json
import re
import base64
from datetime import datetime
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class _SSLAdapter(HTTPAdapter):
    """Adapter che disabilita la verifica SSL per bypassare proxy/firewall (SSLEOFError)."""
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

# Try importing cv2 for frame extraction (optional dependency)
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

# ──────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────
# 1. FIXED ENDPOINTS - use same base as working builder (bytepluses.com) for video/images/tasks
# Override with ARK_API_BASE env var if your console uses a different endpoint
API_BASE = os.getenv("ARK_API_BASE", "https://ark.ap-southeast.bytepluses.com/api/v3")
VIDEO_TASK_URL = f"{API_BASE}/contents/generations/tasks"
FILE_UPLOAD_URL = f"{API_BASE}/files"
# Image generation: BytePlus ModelArk uses /images/generations (Seedream 4.5)
IMAGE_GEN_URL = f"{API_BASE}/images/generations"
IMAGE_TASK_URL = f"{API_BASE}/contents/generations/tasks"  # Task API (video-style); image may use sync only

# 2. CREDENTIALS
API_KEY = os.getenv("ARK_API_KEY") or "YOUR_API_KEY_HERE"
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
# Unsplash: Access Key from https://unsplash.com/oauth/applications (Client-ID auth header)
UNSPLASH_API_KEY = os.getenv("UNSPLASH_ACCESS_KEY") or os.getenv("UNSPLASH_API_KEY")

# SSL verify: set ARK_SSL_VERIFY=0 or false to disable (proxy/firewall / SSLEOFError)
_ssl_verify = os.getenv("ARK_SSL_VERIFY", "1").strip().lower() not in ("0", "false", "no")


def _session_for_ark():
    """Sessione per chiamate Ark: con adapter SSL senza verifica se _ssl_verify è False."""
    s = requests.Session()
    if not _ssl_verify:
        s.mount("https://", _SSLAdapter())
    return s

# 3. MODELS (full IDs from ModelArk console - Asia Pacific / Johor)
# Seedance 1.5 Pro: 480P/720P/1080P, 4–12s, 24fps, text+image only, first/last frame
SEEDANCE_1_5_MODEL_ID = "seedance-1-5-pro-251215"  # ByteDance-Seedance-1.5-pro
# Seedance 2.0: multimodal (text, images, videos, audio), 4–15s, 480P–2K, Video Extension/Editing
SEEDANCE_2_0_MODEL_ID = os.getenv("SEEDANCE_2_MODEL_ID", "seedance-2-0-pro-260210")  # Update from ModelArk console when available
SEEDANCE_2_MODEL_ID = SEEDANCE_2_0_MODEL_ID  # Alias for backward compat
SEEDREAM_4_5_MODEL_ID = "seedream-4-5-251128"     # ByteDance-Seedream-4.5
# ByteDance-Seedream-5.0-lite (260128): text, single/multi-image, image sets.
SEEDREAM_5_0_LITE_MODEL_ID = os.getenv("SEEDREAM_5_MODEL_ID", "seedream-5-0-260128") 

# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────
def save_video_with_metadata(video_url, prompt_text, scene_description, resolution, aspect_ratio, 
                             duration, seed, generate_audio, is_draft, is_offline, model_id):
    """
    Download video, extract last frame, and save metadata file.
    Returns dict with paths: video_path, last_frame_path, info_file_path
    """
    # Create downloads directory structure: downloads/YYYY-MM-DD/
    today = datetime.now().strftime("%Y-%m-%d")
    _persist = os.getenv("PERSIST_DIR", "")
    if not _persist:
        _persist = "/data" if os.path.isdir("/data") else os.path.join(os.path.dirname(__file__), "data")
    base_dir = os.path.join(_persist, "generated", today)
    os.makedirs(base_dir, exist_ok=True)
    
    # Generate filename from scene description (first 30 chars, sanitized)
    scene_slug = re.sub(r'[^\w\s-]', '', scene_description[:30]).strip().replace(' ', '_').lower() or "video"
    
    # Find next available index
    index = 1
    while os.path.exists(os.path.join(base_dir, f"{scene_slug}_{index:03d}.mp4")):
        index += 1
    
    filename_base = f"{scene_slug}_{index:03d}"
    video_path = os.path.join(base_dir, f"{filename_base}.mp4")
    last_frame_path = os.path.join(base_dir, f"{filename_base}_last.png")
    info_file_path = os.path.join(base_dir, f"{filename_base}.txt")
    
    # Download video
    try:
        _session = _session_for_ark()
        video_response = _session.get(video_url, timeout=120, stream=True, verify=_ssl_verify)
        video_response.raise_for_status()
        with open(video_path, 'wb') as f:
            for chunk in video_response.iter_content(chunk_size=8192):
                f.write(chunk)
    except Exception as e:
        return {"error": f"Failed to download video: {e}"}
    
    # Extract last frame if cv2 available
    if CV2_AVAILABLE:
        try:
            cap = cv2.VideoCapture(video_path)
            if cap.isOpened():
                # Get total frames
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                # Seek to last frame
                cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames - 1)
                ret, last_frame = cap.read()
                if ret and last_frame is not None:
                    cv2.imwrite(last_frame_path, last_frame)
                cap.release()
        except Exception as e:
            pass  # Frame extraction is optional
    
    # Create info file
    try:
        with open(info_file_path, 'w', encoding='utf-8') as f:
            f.write(f"Prompt Sent: {prompt_text}\n")
            f.write(f"Seed: {seed if seed != '-1' else 'Random'}\n")
            f.write(f"Resolution: {resolution}\n")
            f.write(f"Aspect Ratio: {aspect_ratio}\n")
            f.write(f"Duration: {duration}s\n")
            f.write(f"Model: {model_id}\n")
            f.write(f"Audio Enabled: {generate_audio}\n")
            f.write(f"Draft Mode: {is_draft}\n")
            f.write(f"Offline Mode: {is_offline}\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    except Exception as e:
        pass  # Info file is optional
    
    return {
        "video_path": video_path,
        "last_frame_path": last_frame_path if CV2_AVAILABLE and os.path.exists(last_frame_path) else None,
        "info_file_path": info_file_path
    }


def save_image_with_metadata(image_url, prompt_text, style_preset="None", aspect_ratio="1:1", model_id=None, resolution="2K", optimize_prompt_mode=None):
    """
    Download image from URL and save metadata .txt file.
    Returns dict with image_path, info_file_path.
    optimize_prompt_mode: "standard", "fast", or None — included in info file when set (affects generation for 5.0 lite).
    """
    today = datetime.now().strftime("%Y-%m-%d")
    _persist = os.getenv("PERSIST_DIR", "")
    if not _persist:
        _persist = "/data" if os.path.isdir("/data") else os.path.join(os.path.dirname(__file__), "data")
    base_dir = os.path.join(_persist, "generated", today)
    os.makedirs(base_dir, exist_ok=True)
    scene_slug = re.sub(r'[^\w\s-]', '', (prompt_text or "image")[:30]).strip().replace(' ', '_').lower() or "image"
    index = 1
    while os.path.exists(os.path.join(base_dir, f"{scene_slug}_{index:03d}.png")):
        index += 1
    filename_base = f"{scene_slug}_{index:03d}"
    image_path = os.path.join(base_dir, f"{filename_base}.png")
    info_file_path = os.path.join(base_dir, f"{filename_base}.txt")
    try:
        _session = _session_for_ark()
        img_resp = _session.get(image_url, timeout=120, stream=True, verify=_ssl_verify)
        img_resp.raise_for_status()
        with open(image_path, 'wb') as f:
            for chunk in img_resp.iter_content(chunk_size=8192):
                f.write(chunk)
    except Exception as e:
        return {"error": str(e), "info_file_path": None}
    try:
        with open(info_file_path, 'w', encoding='utf-8') as f:
            f.write(f"Prompt: {prompt_text}\n")
            f.write(f"Style: {style_preset}\n")
            f.write(f"Resolution: {resolution}\n")
            f.write(f"Aspect Ratio: {aspect_ratio}\n")
            f.write(f"Model: {model_id or SEEDREAM_4_5_MODEL_ID}\n")
            if optimize_prompt_mode in ("standard", "fast"):
                f.write(f"Optimize prompt: {optimize_prompt_mode}\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    except Exception:
        pass
    return {"image_path": image_path, "info_file_path": info_file_path}


def upload_file_to_byteplus(streamlit_file):
    """Upload file; returns (id, url) for use in content. URL may be from response or constructed."""
    headers = {"Authorization": f"Bearer {API_KEY}"}
    files = {'file': (streamlit_file.name, streamlit_file.getvalue(), streamlit_file.type)}
    data = {'purpose': 'user_data'}
    try:
        _session = _session_for_ark()
        response = _session.post(FILE_UPLOAD_URL, headers=headers, files=files, data=data, verify=_ssl_verify)
        response.raise_for_status()
        data = response.json()
        fid = data.get("id")
        url = data.get("url") or (f"{FILE_UPLOAD_URL}/{fid}" if fid else None)
        return (fid, url) if fid else None
    except Exception as e:
        return None

# ──────────────────────────────────────────────
# 1. VIDEO GENERATION (SEEDANCE 1.5 / 2.0) — JSON strict validation
# ──────────────────────────────────────────────
def _has_camera_movement(shots_data):
    """True if any shot has explicit camera movement (m1_type or m2_type). Used to set camera_fixed."""
    if not shots_data:
        return False
    for shot in shots_data:
        m1 = (shot.get("m1_type") or "").strip().lower()
        m2 = (shot.get("m2_type") or "").strip().lower()
        if m1 and m1 not in ("not specified", "static", ""):
            return True
        if m2 and m2 not in ("not specified", "static", ""):
            return True
    return False


def generate_video(prompt_text, scene_description, images=[], videos=[], audios=[], 
                   seed="-1", resolution="1080p", aspect_ratio="16:9", duration=8, 
                   generate_audio=False, audio_details={}, is_draft=False, is_offline=False, 
                   model_id=None, shots_data=None, camera_fixed=None, **kwargs):
    if not API_KEY: return "API_KEY_ERROR"
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    
    # Prompt must be narrative-only; strip any legacy --param flags
    clean_prompt = re.sub(r'\s*--\w+\s+\S+', '', (prompt_text or "").strip()).strip() or prompt_text or ""
    content_list = [{"type": "text", "text": clean_prompt}]
    
    model = model_id or SEEDANCE_2_MODEL_ID
    is_1_5 = (model == SEEDANCE_1_5_MODEL_ID)
    res_normalized = (resolution or "1080p").strip().lower()

    is_first_last_mode = kwargs.get("image_usage") == "first_last_frame"
    if is_first_last_mode:
        # First+Last frame: exactly 2 images, regardless of model or resolution
        image_files = (images or [])[:2]
    elif is_1_5 and res_normalized == "1080p":
        image_files = (images or [])[:1]
    else:
        image_files = (images or [])[:9]

    # Images: use inline base64 (1.5 and 2.0 both need base64; 1.5 supports first/last frame)
    for file in image_files:
        try:
            b64 = base64.b64encode(file.getvalue()).decode("utf-8")
            mime = (file.type or "image/jpeg").split(";")[0].strip()
            content_list.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
        except Exception:
            pass
    # Videos/Audio: Seedance 1.5 is Text-to-video + Image-to-video ONLY — no video/audio input
    if not is_1_5:
        for file in (videos or [])[:3]:
            out = upload_file_to_byteplus(file)
            if out:
                fid, url = out if isinstance(out, tuple) else (out, f"{FILE_UPLOAD_URL}/{out}")
                if url:
                    content_list.append({"type": "video_url", "video_url": {"url": url}})
        if generate_audio:
            for file in (audios or [])[:3]:
                out = upload_file_to_byteplus(file)
                if out:
                    fid, url = out if isinstance(out, tuple) else (out, f"{FILE_UPLOAD_URL}/{out}")
                    if url:
                        content_list.append({"type": "audio_url", "audio_url": {"url": url}})

    try:
        seed_int = int(seed) if seed and str(seed).strip() != "-1" else None
    except (ValueError, TypeError):
        seed_int = None

    # Duration: -1 = autonomous (API chooses 4–12s for 1.5); otherwise clamp to model range
    try:
        duration_int = int(duration)
    except (ValueError, TypeError):
        duration_int = 8
    if duration_int != -1:
        if model == SEEDANCE_1_5_MODEL_ID and (duration_int < 4 or duration_int > 12):
            duration_int = max(4, min(12, duration_int))
        elif model != SEEDANCE_1_5_MODEL_ID and (duration_int < 4 or duration_int > 15):
            duration_int = max(4, min(15, duration_int))

    # camera_fixed: from explicit arg, or from shots_data (has movement → camera_fixed=False)
    if camera_fixed is None and is_1_5 and shots_data:
        camera_fixed = not _has_camera_movement(shots_data)
    if camera_fixed is None:
        camera_fixed = False

    # service_tier: 'Online' (default/fast) or 'Offline' (flex batch, 50% cost)
    service_tier = "Offline" if is_offline else "Online"
    if is_draft:
        service_tier = "Online"  # draft uses online

    payload = {
        "model": model,
        "content": content_list,
        "seed": seed_int,
        "resolution": "480p" if is_draft else resolution,
        "ratio": aspect_ratio,
        "duration": duration_int,
        "camera_fixed": bool(camera_fixed),
        "generate_audio": bool(generate_audio),
    }
    # service_tier (Online/Offline) only supported by Seedance 2.0; 1.5 Pro t2v rejects it
    if not is_1_5:
        payload["service_tier"] = service_tier
    if is_draft:
        payload["draft"] = True
    # 1080p: disable Adaptive Aspect Ratio per production rules
    if is_1_5 and res_normalized == "1080p":
        payload["adaptive_aspect_ratio"] = False

    try:
        _session = _session_for_ark()
        response = _session.post(VIDEO_TASK_URL, headers=headers, json=payload, timeout=30, verify=_ssl_verify)
        if not response.ok:
            try:
                err_body = response.json()
                err_msg = err_body.get("message") or err_body.get("Error", {}).get("Message") or str(err_body)
            except Exception:
                err_msg = response.text[:500]
            return f"Video API Error ({response.status_code}): {err_msg}"
        res_json = response.json()
        task_id = res_json.get("id")
        if not task_id:
            return f"API did not return task id: {res_json}"
        
        # Polling Loop
        poll_max = 600 if is_offline else 120
        status_url = f"{VIDEO_TASK_URL}/{task_id}"
        
        for _ in range(poll_max):
            time.sleep(5)
            s_res = _session.get(status_url, headers=headers, timeout=10, verify=_ssl_verify)
            status = s_res.json().get("status")
            if status == "succeeded":
                video_url = s_res.json().get("content", {}).get("video_url")
                if video_url:
                    # Save video, extract last frame, and create info file
                    saved_paths = save_video_with_metadata(
                        video_url=video_url,
                        prompt_text=prompt_text,
                        scene_description=scene_description,
                        resolution=resolution,
                        aspect_ratio=aspect_ratio,
                        duration=duration_int,
                        seed=seed,
                        generate_audio=generate_audio,
                        is_draft=is_draft,
                        is_offline=is_offline,
                        model_id=model
                    )
                    return {
                        "video": video_url,
                        "video_path": saved_paths.get("video_path"),
                        "last_frame_path": saved_paths.get("last_frame_path"),
                        "info_file_path": saved_paths.get("info_file_path")
                    }
                return {"video": video_url}
            elif status == "failed": 
                return f"Failed: {s_res.json().get('error', {}).get('message')}"
        return "Timeout."
    except requests.exceptions.HTTPError as e:
        try:
            err_body = e.response.json()
            err_msg = err_body.get("message") or str(err_body)
        except Exception:
            err_msg = (e.response.text[:500] if e.response else str(e))
        return f"Video API Error ({e.response.status_code if e.response else '?'}): {err_msg}"
    except requests.exceptions.SSLError as e:
        return f"Connection error (SSL): {e}. Set ARK_SSL_VERIFY=0 in your environment and restart."
    except requests.exceptions.ConnectionError as e:
        return f"Connection error: {e}. Check network, firewall, or try again."
    except Exception as e:
        return f"Request Failed: {e}"

# ──────────────────────────────────────────────
# 2. SEEDREAM 5.0 / 4.5 GENERATION (IMAGE)
# ──────────────────────────────────────────────
def generate_seedream_image(prompt, ref_images=[], style_preset="None", aspect_ratio="1:1",
                            model_id=None, sequential="disabled", max_images=1,
                            output_format="jpeg", optimize_prompt_mode=None, resolution="2K", watermark=False, watermark_text=None, stream=False):
    """
    model_id: SEEDREAM_5_0_LITE_MODEL_ID or SEEDREAM_4_5_MODEL_ID
    sequential: "disabled" (single) or "auto" (batch)
    max_images: 1-15, used when sequential="auto"
    output_format: "jpeg" or "png" (5.0 lite only)
    optimize_prompt_mode: "standard", "fast", or None (5.0 lite / 4.5 standard mode)
    resolution: "1K", "2K", or "4K" — output dimensions (1K only for 5.0 lite)
    watermark: if True, enable watermark (API: boolean; doc uses False)
    watermark_text: optional custom text for watermark (sent if API supports it)
    stream: if True, use streaming output (results as each image is ready; 5.0 lite, 4.5, 4.0)
    Multi-image: ref_images (list) → API "image" array; use prompt e.g. "Replace X in image 1 with Y from image 2" for blending.
    """
    if not API_KEY: return "API_KEY_ERROR"
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    model = model_id or SEEDREAM_5_0_LITE_MODEL_ID
    is_5_0 = model == SEEDREAM_5_0_LITE_MODEL_ID

    # 1. Apply Style Presets
    styled_prompt = prompt
    if style_preset and style_preset != "None":
        if "Kodak" in style_preset: styled_prompt = f"Kodak Portra 400 style, grain, nostalgic color cast, hard flash. {prompt}"
        elif "Guochao" in style_preset: styled_prompt = f"Guochao Neo-Chinese style, warm red and gilded gold palette, intricate embroidery textures. {prompt}"
        elif "Origami" in style_preset: styled_prompt = f"Cute Chinese-style origami figures, paper texture, soft lighting. {prompt}"
        elif "Ice" in style_preset: styled_prompt = f"Transparent ice sculptures, blue-to-purple gradient, cold ethereal atmosphere. {prompt}"
        elif "Pixel" in style_preset: styled_prompt = f"2D pixel art scene, top-down view, textured cartoon style. {prompt}"
        elif "Abstract" in style_preset: styled_prompt = f"Abstract futuristic visual style, liquid metal, silver-gray cool tone. {prompt}"
        else: styled_prompt = f"{style_preset}. {prompt}"

    # 2. Size — Method 2: exact width x height (pixels). Official recommended dimensions per model.
    # 5.0 lite: 2K, 3K (max pixels 10,404,496). 4.5: 2K, 4K (max 16,777,216). Method 1 = size "2K"/"3K"/"4K" + aspect in prompt; we use Method 2.
    MAX_PIXELS_5_0 = 10_404_496
    MAX_PIXELS_4_5 = 16_777_216
    # Recommended 2K (5.0 lite & 4.5) — doc table
    size_map_2k = {"Smart": "2848x1600", "1:1": "2048x2048", "3:4": "1728x2304", "4:3": "2304x1728", "16:9": "2848x1600", "9:16": "1600x2848", "3:2": "2496x1664", "2:3": "1664x2496", "21:9": "3136x1344"}
    # Recommended 3K (5.0 lite only)
    size_map_3k = {"Smart": "4096x2304", "1:1": "3072x3072", "3:4": "2592x3456", "4:3": "3456x2592", "16:9": "4096x2304", "9:16": "2304x4096", "3:2": "3744x2496", "2:3": "2496x3744", "21:9": "4704x2016"}
    # Recommended 4K (4.5 only; doc allows up to 16.7M)
    size_map_4k = {"Smart": "5504x3040", "1:1": "4096x4096", "3:4": "3520x4704", "4:3": "4704x3520", "16:9": "5504x3040", "9:16": "3040x5504", "3:2": "4992x3328", "2:3": "3328x4992", "21:9": "6240x2656"}
    res = (str(resolution or "2K").strip().upper())
    if res == "3K" and is_5_0:
        size_map = size_map_3k
    elif res == "4K":
        size_map = size_map_4k
    else:
        size_map = size_map_2k
    size = size_map.get(aspect_ratio, size_map.get("Smart", list(size_map.values())[0]))
    # Clamp to model-specific pixel limit for custom ratios
    try:
        w, h = map(int, size.split("x"))
        cap = MAX_PIXELS_5_0 if is_5_0 else MAX_PIXELS_4_5
        if w * h > cap:
            scale = (cap / (w * h)) ** 0.5
            w, h = int(w * scale), int(h * scale)
            w, h = max(1, w), max(1, h)
            size = f"{w}x{h}"
    except (ValueError, AttributeError):
        pass

    # 3. Reference images — up to 14 refs (5.0 lite, 4.5, 4.0)
    image_input = None
    if ref_images:
        ref_list = []
        for file in ref_images[:14]:
            try:
                b64 = base64.b64encode(file.getvalue()).decode("utf-8")
                mime = (file.type or "image/jpeg").split(";")[0].strip().lower()
                subtype = "jpeg" if "jpeg" in mime or "jpg" in mime else "png"
                ref_list.append(f"data:image/{subtype};base64,{b64}")
            except Exception:
                pass
        if ref_list:
            image_input = ref_list[0] if len(ref_list) == 1 else ref_list

    try:
        # Single image: sequential must be "disabled" and no batch options. Batch: "auto" + max_images.
        sequential_val = "auto" if sequential == "auto" else "disabled"
        payload = {
            "model": model,
            "prompt": styled_prompt,
            "size": size,
            "sequential_image_generation": sequential_val,
            "response_format": "url",
        }
        if image_input is not None:
            payload["image"] = image_input
        payload["watermark"] = bool(watermark)
        if watermark and watermark_text and str(watermark_text).strip():
            payload["watermark_text"] = str(watermark_text).strip()
        if sequential_val == "auto":
            payload["sequential_image_generation_options"] = {"max_images": max(1, min(15, int(max_images)))}
        # When disabled, do not send sequential_image_generation_options at all (single image)
        if is_5_0 and output_format in ("png", "jpeg"):
            payload["output_format"] = output_format
        if optimize_prompt_mode in ("standard", "fast"):
            payload["optimize_prompt_options"] = {"mode": optimize_prompt_mode}
        if stream:
            payload["stream"] = True

        # Retry on SSL/connection errors (transient network / proxy issues)
        max_retries = 5
        retry_delay = 5
        for attempt in range(max_retries):
            try:
                _session = _session_for_ark()
                if stream:
                    response = _session.post(IMAGE_GEN_URL, headers=headers, json=payload, timeout=300, stream=True, verify=_ssl_verify)
                else:
                    response = _session.post(IMAGE_GEN_URL, headers=headers, json=payload, timeout=180, verify=_ssl_verify)
                break
            except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    return f"Generation Error: Connection failed after {max_retries} attempts. {type(e).__name__}: {e}. Check network or VPN."

        if stream:
            if response.status_code != 200:
                try:
                    err_body = response.json()
                    err_msg = err_body.get("error", {}).get("message") or err_body.get("message") or str(err_body)
                except Exception:
                    err_msg = response.text[:500] if response.text else f"HTTP {response.status_code}"
                return f"Image API {response.status_code}: {err_msg}"
            results = []
            for line in response.iter_lines(decode_unicode=True):
                if not line or not line.strip():
                    continue
                line = line.strip()
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]" or line == "[done]":
                    break
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event_type = ev.get("type") or ev.get("event") or ev.get("event_type")
                if event_type == "image_generation.partial_failed":
                    err = ev.get("error") or {}
                    msg = err.get("message") or err.get("code") or str(err)
                    results.append({"error": msg})
                elif event_type == "image_generation.partial_succeeded":
                    image_url = ev.get("url") or ev.get("image_url")
                    if image_url:
                        saved = save_image_with_metadata(
                            image_url, styled_prompt, style_preset, aspect_ratio, model, resolution=res,
                            optimize_prompt_mode=optimize_prompt_mode
                        )
                        out = {"image_url": image_url}
                        if saved.get("image_path"):
                            out["image_path"] = saved["image_path"]
                        if saved.get("info_file_path"):
                            out["info_file_path"] = saved["info_file_path"]
                        results.append(out)
                elif event_type == "image_generation.completed":
                    break
            if not results:
                return "Image generation failed: no images from stream."
            if len(results) == 1 and "image_url" in results[0]:
                return results[0]
            return {"images": results}
        else:
            if response.status_code != 200:
                try:
                    err_body = response.json()
                    err_msg = err_body.get("error", {}).get("message") or err_body.get("message") or str(err_body)
                except Exception:
                    err_msg = response.text[:500]
                return f"Image API {response.status_code}: {err_msg}"

            res_json = response.json()
            if "data" not in res_json or not res_json["data"]:
                if "error" in res_json:
                    return f"Image API error: {res_json['error'].get('message', res_json['error'])}"
                return f"Error: unexpected response: {res_json}"

            results = []
            for idx, item in enumerate(res_json["data"]):
                if not isinstance(item, dict):
                    continue
                if "error" in item:
                    results.append({"error": item["error"].get("message", item["error"])})
                    continue
                image_url = item.get("url")
                if not image_url:
                    continue
                saved = save_image_with_metadata(
                    image_url, styled_prompt, style_preset, aspect_ratio, model, resolution=res,
                    optimize_prompt_mode=optimize_prompt_mode
                )
                out = {"image_url": image_url}
                if saved.get("image_path"):
                    out["image_path"] = saved["image_path"]
                if saved.get("info_file_path"):
                    out["info_file_path"] = saved["info_file_path"]
                results.append(out)

            if not results:
                return f"Image generation failed: no valid images in response."
            if len(results) == 1 and "image_url" in results[0]:
                return results[0]
            return {"images": results}
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return f"404 Not Found: Image endpoint may have changed. Tried: {IMAGE_GEN_URL}. Check BytePlus Ark API docs."
        try:
            err_body = e.response.json()
            err_msg = err_body.get("error", {}).get("message") or err_body.get("message") or str(err_body)
        except Exception:
            err_msg = e.response.text[:500]
        return f"Generation Error: {err_msg}"
    except Exception as e:
        return f"Generation Error: {str(e)}"

# Placeholder
def generate_image(prompt): return generate_seedream_image(prompt)
