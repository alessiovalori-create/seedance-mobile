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

try:
    from PIL import Image as PILImage
    import io as _io
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Max image file size for Seedance 2.0 API (official limit: 30MB, safety margin for base64 overhead)
MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20MB
SEEDANCE_IMAGE_API_MAX_BYTES = 30 * 1024 * 1024
SEEDANCE_VIDEO_MAX_BYTES = 50 * 1024 * 1024
SEEDANCE_AUDIO_MAX_BYTES = 25 * 1024 * 1024
# r2v: reference clip(s) must be <= 15.2s (API); trim slightly under for safety
SEEDANCE_REF_VIDEO_MAX_SECONDS = 15.2
SEEDANCE_REF_VIDEO_TRIM_TO_SECONDS = 15.0
SEEDANCE_IMAGE_MIN_PX = 300  # ByteDance Seedance 2.0: 300–6000 px per side
SEEDANCE_REF_VIDEO_MIN_SECONDS = 2.0
SEEDANCE_IMAGE_RECOMMENDED_MIN_PX = 512
SEEDANCE_IMAGE_MAX_PX = 4096
SEEDANCE_ALLOWED_IMAGE_MIMES = frozenset({
    "image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif",
})


def _human_file_size(num_bytes):
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    return f"{num_bytes / 1024:.0f} KB"


def _read_uploaded_bytes(file_obj):
    """Return (bytes, display_name, mime) or (None, name, None) on failure."""
    name = getattr(file_obj, "name", None) or "upload"
    try:
        if hasattr(file_obj, "getvalue"):
            data = file_obj.getvalue()
        elif getattr(file_obj, "path", None) and os.path.isfile(file_obj.path):
            with open(file_obj.path, "rb") as f:
                data = f.read()
        else:
            return None, name, None
        mime = (getattr(file_obj, "type", None) or "").split(";")[0].strip().lower()
        if not mime:
            ext = os.path.splitext(name)[1].lower()
            mime = {
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                ".webp": "image/webp", ".gif": "image/gif",
                ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
                ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
            }.get(ext, "")
        return data, name, mime
    except Exception as e:
        return None, name, str(e)


def _image_pixel_size(data):
    if not PIL_AVAILABLE or not data:
        return None, None
    try:
        img = PILImage.open(_io.BytesIO(data))
        return img.width, img.height
    except Exception:
        return None, None


def _probe_video_duration_from_path(path):
    """Return duration in seconds, or None if unknown."""
    try:
        import subprocess
        r = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0 and (r.stdout or "").strip():
            return float(r.stdout.strip())
    except Exception:
        pass
    if CV2_AVAILABLE:
        try:
            cap = cv2.VideoCapture(path)
            if cap.isOpened():
                fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
                frames = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                cap.release()
                if fps > 0 and frames > 0:
                    return frames / fps
        except Exception:
            pass
    return None


def _video_duration_seconds_from_bytes(vid_bytes, name="video.mp4"):
    import tempfile
    suffix = os.path.splitext(name)[1] or ".mp4"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
        tf.write(vid_bytes)
        path = tf.name
    try:
        return _probe_video_duration_from_path(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _ffprobe_video_valid(path):
    """True if ffprobe can read the file without errors."""
    try:
        import subprocess
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams", path],
            capture_output=True, timeout=30,
        )
        return r.returncode == 0
    except Exception:
        return False


def _safe_media_filename(name, default="reference.mp4"):
    base = os.path.basename(name or default)
    stem, ext = os.path.splitext(base)
    ext = ext.lower() if ext.lower() in (".mp4", ".mov", ".webm", ".m4a", ".mp3", ".wav") else ".mp4"
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem or "reference").strip("._") or "reference"
    return f"{safe_stem[:80]}{ext}"


def _normalize_mime_for_data_url(mime):
    m = (mime or "image/jpeg").split(";")[0].strip().lower()
    if m in ("image/jpg", "image/jpe"):
        return "image/jpeg"
    if m in SEEDANCE_ALLOWED_IMAGE_MIMES:
        return m
    return "image/jpeg"


def _normalize_reference_video_bytes(vid_bytes, name, max_seconds=SEEDANCE_REF_VIDEO_TRIM_TO_SECONDS):
    """
    Re-encode to H.264 + AAC MP4 (yuv420p, faststart). ByteDance requires valid mp4/mov;
    stream-copy trims often produce truncated files that fail as 'Invalid media input'.
    Returns (bytes, name, duration) or (None, name, None).
    """
    import tempfile
    import subprocess
    suffix = os.path.splitext(name)[1] or ".mp4"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as src_f:
        src_f.write(vid_bytes)
        src_path = src_f.name
    out_path = src_path + ".norm.mp4"
    out_name = _safe_media_filename(name, "reference.mp4")
    try:
        cmd = [
            "ffmpeg", "-y", "-i", src_path,
            "-t", str(max_seconds),
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v", "libx264", "-profile:v", "main", "-pix_fmt", "yuv420p",
            "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-ac", "2", "-ar", "48000", "-b:a", "128k",
            "-movflags", "+faststart",
            out_path,
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=180)
        if r.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) < 1024:
            return None, name, None
        if not _ffprobe_video_valid(out_path):
            return None, name, None
        dur = _probe_video_duration_from_path(out_path)
        with open(out_path, "rb") as f:
            return f.read(), out_name, dur
    finally:
        for p in (src_path, out_path):
            try:
                if os.path.exists(p):
                    os.unlink(p)
            except OSError:
                pass


def _verify_fetchable_media_url(url, expect_video=True, auth_headers=None):
    """Check URL returns real media (not HTML error page). Optional Bearer for ARK file URLs."""
    if not url or not str(url).startswith(("http://", "https://")):
        return False
    headers = dict(auth_headers or {})
    try:
        sess = _session_for_ark()
        r = sess.head(url, headers=headers, timeout=30, allow_redirects=True, verify=_ssl_verify)
        if r.status_code >= 400:
            r = sess.get(url, headers=headers, timeout=60, stream=True, verify=_ssl_verify)
        if r.status_code >= 400:
            return False
        ct = (r.headers.get("content-type") or "").lower()
        if "text/html" in ct or "application/json" in ct:
            return False
        if expect_video:
            chunk = b""
            for part in r.iter_content(8192):
                chunk += part
                if len(chunk) >= 12:
                    break
            if len(chunk) >= 8 and chunk[4:8] != b"ftyp":
                return False
        return True
    except Exception:
        return False


def _upload_reference_video_url(vid_bytes, vid_name, session):
    """
    Public URL for ARK to download reference video.
    Prefer ARK Files API (same tenant); fallback to tmpfiles.org with /dl/ URL + verify.
    """
    safe_name = _safe_media_filename(vid_name, "reference.mp4")
    auth = {"Authorization": f"Bearer {API_KEY}"}

    try:
        mock = type("F", (), {
            "name": safe_name,
            "getvalue": lambda: vid_bytes,
            "type": "video/mp4",
        })()
        out = upload_file_to_byteplus(mock)
        if out:
            fid, url = out if isinstance(out, tuple) else (out, None)
            if not url and fid:
                url = f"{FILE_UPLOAD_URL}/{fid}"
            if url and _verify_fetchable_media_url(url, expect_video=True, auth_headers=auth):
                print(f"[DEBUG-VIDEO] ARK Files URL ok: {url[:80]}")
                return url
            print(f"[DEBUG-VIDEO] ARK Files URL not fetchable as video, trying tmpfiles")
    except Exception as e:
        print(f"[DEBUG-VIDEO] ARK Files upload failed: {e}")

    try:
        resp = session.post(
            "https://tmpfiles.org/api/v1/upload",
            files={"file": (safe_name, vid_bytes, "video/mp4")},
            timeout=120,
            verify=_ssl_verify,
        )
        if resp.status_code != 200:
            print(f"[DEBUG-VIDEO] tmpfiles.org failed: {resp.status_code} {resp.text[:120]}")
            return None
        raw_url = (resp.json().get("data") or {}).get("url", "")
        if not raw_url:
            return None
        dl_url = raw_url.replace("https://tmpfiles.org/", "https://tmpfiles.org/dl/")
        for candidate in (dl_url, raw_url):
            if _verify_fetchable_media_url(candidate, expect_video=True):
                print(f"[DEBUG-VIDEO] tmpfiles URL ok: {candidate}")
                return candidate
        print(f"[DEBUG-VIDEO] tmpfiles URL failed media verify")
    except Exception as te:
        print(f"[DEBUG-VIDEO] tmpfiles.org error: {te}")
    return None


def _has_reference_media_inputs(videos=None, audios=None):
    return bool((videos or [])[:3] or (audios or [])[:3])


def validate_seedance_video_inputs(images=None, videos=None, audios=None, image_usage="auto"):
    """
    Pre-flight checks before calling the Seedance 2.0 video API.
    Returns {"ok": bool, "errors": [str], "warnings": [str]}.
    """
    errors = []
    warnings = []
    is_first_last = image_usage == "first_last_frame"
    image_files = (images or [])[:2] if is_first_last else (images or [])[:9]
    video_files = (videos or [])[:3]
    audio_files = (audios or [])[:3]
    has_ref_media = _has_reference_media_inputs(videos, audios)

    if has_ref_media and is_first_last:
        errors.append(
            "First + Last Frame mode cannot be combined with reference videos or audio. "
            "Remove reference media or switch Entry Point to All-in-One Reference."
        )
    elif has_ref_media and image_usage == "first_frame":
        errors.append(
            "Image usage “First frame” cannot be combined with reference videos or audio. "
            "Remove reference media, set Image usage to Reference only, or use Entry Point “First Frame”."
        )
    elif has_ref_media and image_usage == "auto" and len(images or []) == 1:
        warnings.append(
            "With one image plus reference video/audio, the image is sent as reference only "
            "(not as first frame) — required by the Seedance API."
        )

    if is_first_last and len(images or []) > 2:
        errors.append(
            f"First + Last Frame mode accepts exactly 2 images; you attached {len(images)}. "
            "Remove extras or change Image Usage."
        )
    elif len(images or []) > 9:
        errors.append(f"Too many images ({len(images)}). Seedance 2.0 allows at most 9 reference images.")

    total_files = len(image_files) + len(video_files) + len(audio_files)
    if total_files > 12:
        errors.append(
            f"Too many input files ({total_files}). Maximum is 12 combined images, videos, and audio."
        )

    for idx, file_obj in enumerate(image_files, start=1):
        data, name, mime_or_err = _read_uploaded_bytes(file_obj)
        label = f"Image {idx} ({name})"
        if data is None:
            errors.append(f"{label}: could not read file — {mime_or_err or 'unknown error'}.")
            continue
        mime = mime_or_err if isinstance(mime_or_err, str) else ""
        if mime and mime not in SEEDANCE_ALLOWED_IMAGE_MIMES:
            errors.append(
                f"{label}: unsupported format ({mime or 'unknown'}). "
                "Use JPEG, PNG, WebP, or GIF."
            )
        size = len(data)
        if size > SEEDANCE_IMAGE_API_MAX_BYTES:
            errors.append(
                f"{label}: file is too large ({_human_file_size(size)}). "
                f"Maximum is {_human_file_size(SEEDANCE_IMAGE_API_MAX_BYTES)} per image."
            )
        elif size > MAX_IMAGE_BYTES:
            warnings.append(
                f"{label}: {_human_file_size(size)} — will be compressed before upload "
                f"(target under {_human_file_size(MAX_IMAGE_BYTES)})."
            )
        w, h = _image_pixel_size(data)
        if w is None or h is None:
            errors.append(f"{label}: invalid or corrupted image file.")
            continue
        if w < SEEDANCE_IMAGE_MIN_PX or h < SEEDANCE_IMAGE_MIN_PX:
            errors.append(
                f"{label}: resolution {w}×{h} is too small. "
                f"Minimum is {SEEDANCE_IMAGE_MIN_PX}px per side."
            )
        elif w > SEEDANCE_IMAGE_MAX_PX or h > SEEDANCE_IMAGE_MAX_PX:
            errors.append(
                f"{label}: resolution {w}×{h} exceeds {SEEDANCE_IMAGE_MAX_PX}px per side. "
                "Resize the image before uploading."
            )
        elif w < SEEDANCE_IMAGE_RECOMMENDED_MIN_PX or h < SEEDANCE_IMAGE_RECOMMENDED_MIN_PX:
            warnings.append(
                f"{label}: {w}×{h} is below recommended {SEEDANCE_IMAGE_RECOMMENDED_MIN_PX}px — "
                "motion quality may be soft; use 1024×1024 or larger when possible."
            )

    total_ref_video_seconds = 0.0
    for idx, file_obj in enumerate(video_files, start=1):
        data, name, mime_or_err = _read_uploaded_bytes(file_obj)
        label = f"Video {idx} ({name})"
        if data is None:
            errors.append(f"{label}: could not read file — {mime_or_err or 'unknown error'}.")
            continue
        if len(data) > SEEDANCE_VIDEO_MAX_BYTES:
            errors.append(
                f"{label}: file is too large ({_human_file_size(len(data))}). "
                f"Try under {_human_file_size(SEEDANCE_VIDEO_MAX_BYTES)}."
            )
        dur = _video_duration_seconds_from_bytes(data, name)
        if dur is not None:
            total_ref_video_seconds += dur
            if dur < SEEDANCE_REF_VIDEO_MIN_SECONDS:
                errors.append(
                    f"{label}: {dur:.1f}s is too short (minimum {SEEDANCE_REF_VIDEO_MIN_SECONDS}s per clip)."
                )
            elif dur > SEEDANCE_REF_VIDEO_MAX_SECONDS:
                warnings.append(
                    f"{label}: {dur:.1f}s — will be re-encoded and trimmed to ≤{SEEDANCE_REF_VIDEO_TRIM_TO_SECONDS}s."
                )
        else:
            warnings.append(
                f"{label}: could not read duration; will re-encode with ffmpeg before upload."
            )

    if total_ref_video_seconds > SEEDANCE_REF_VIDEO_MAX_SECONDS:
        errors.append(
            f"Combined reference video duration ({total_ref_video_seconds:.1f}s) exceeds "
            f"{SEEDANCE_REF_VIDEO_MAX_SECONDS}s total. Use fewer/shorter clips."
        )

    for idx, file_obj in enumerate(audio_files, start=1):
        data, name, mime_or_err = _read_uploaded_bytes(file_obj)
        label = f"Audio {idx} ({name})"
        if data is None:
            errors.append(f"{label}: could not read file — {mime_or_err or 'unknown error'}.")
            continue
        if len(data) > SEEDANCE_AUDIO_MAX_BYTES:
            errors.append(
                f"{label}: file is too large ({_human_file_size(len(data))}). "
                f"Try under {_human_file_size(SEEDANCE_AUDIO_MAX_BYTES)}."
            )

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def format_video_generation_failure(result):
    """
    Normalize generate_video error returns into {title, details} for the UI.
    """
    if result is None:
        return {"title": "Video generation failed", "details": ["No response from the API."]}

    if isinstance(result, dict):
        if result.get("video"):
            return None
        details = list(result.get("details") or [])
        primary = result.get("error") or result.get("message")
        if primary:
            details = [str(primary)] + [d for d in details if d != primary]
        if not details:
            details = ["Unknown error."]
        out = {"title": "Video generation failed", "details": _enrich_api_error_details(details)}
        if result.get("warnings"):
            out["warnings"] = list(result["warnings"])
        return out

    if isinstance(result, str):
        if result == "API_KEY_ERROR":
            return {
                "title": "Video generation failed",
                "details": ["ARK_API_KEY is missing. Set it in your environment and restart the app."],
            }
        return {"title": "Video generation failed", "details": _enrich_api_error_details([result])}

    return {"title": "Video generation failed", "details": [str(result)]}


def _enrich_api_error_details(lines):
    """Add actionable hints when API messages mention size, format, or dimensions."""
    out = []
    seen = set()
    for line in lines:
        s = str(line).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
        low = s.lower()
        if any(k in low for k in ("too large", "file size", "exceed", "payload", "30mb", "30 mb", "size limit")):
            out.append(
                "Hint: compress or resize reference images (max 30 MB each, recommended 1024×1024 or larger)."
            )
        elif any(k in low for k in ("dimension", "resolution", "width", "height", "pixel")):
            out.append(
                "Hint: use images between 512×512 and 4096×4096 px; avoid extremely small or huge files."
            )
        elif any(
            k in low
            for k in (
                "invalid media", "corrupted", "truncated", "container format",
                "servicerbadrequest", "reference media",
            )
        ):
            out.append(
                "Hint: reference video must be MP4/MOV, 2–15s total, H.264 — re-export or let Arkitect "
                "normalize with ffmpeg. Images: JPEG/PNG/WebP, 300–6000px. For Video Editing use "
                "All-in-One + reference_video + reference_image (not first_frame)."
            )
        elif any(k in low for k in ("format", "mime", "unsupported", "invalid image", "corrupt")):
            out.append(
                "Hint: images JPEG/PNG/WebP (300–6000px); videos MP4 H.264, 2–15s total, under 50MB."
            )
        elif "first_frame" in low or "last_frame" in low:
            out.append("Hint: First + Last Frame mode requires exactly two images.")
        elif "cannot be mixed" in low or "reference media" in low:
            out.append(
                "Hint: Use Entry Point “First Frame” or “First and Last Frames” for frame-based "
                "generation only, or “All-in-One Reference” for @Video/@Audio — do not combine both."
            )
        elif "15.2" in s or ("total duration" in low and "video" in low):
            out.append(
                f"Hint: reference @Video clips must be ≤ {SEEDANCE_REF_VIDEO_MAX_SECONDS}s each "
                f"(trim in an editor, or let Arkitect auto-trim if ffmpeg is installed)."
            )
    # dedupe hints
    deduped = []
    hint_seen = set()
    for item in out:
        if item.startswith("Hint:"):
            if item in hint_seen:
                continue
            hint_seen.add(item)
        deduped.append(item)
    return deduped


def _auto_resize_image(file_obj, max_bytes=MAX_IMAGE_BYTES):
    """If image exceeds max_bytes, resize it down. Returns (bytes, mime_type, was_resized)."""
    raw = file_obj.getvalue()
    mime = (getattr(file_obj, 'type', None) or "image/jpeg").split(";")[0].strip()
    if len(raw) <= max_bytes:
        return raw, mime, False
    if not PIL_AVAILABLE:
        return raw, mime, False
    try:
        img = PILImage.open(_io.BytesIO(raw))
        if img.mode == 'RGBA':
            img = img.convert('RGB')
            mime = "image/jpeg"
        quality = 85
        scale = 0.9
        for _ in range(10):
            w, h = int(img.width * scale), int(img.height * scale)
            resized = img.resize((w, h), PILImage.LANCZOS)
            buf = _io.BytesIO()
            fmt = "JPEG" if "jpeg" in mime or "jpg" in mime else "PNG"
            resized.save(buf, format=fmt, quality=quality, optimize=True)
            if buf.tell() <= max_bytes:
                return buf.getvalue(), mime, True
            scale *= 0.85
            quality = max(60, quality - 5)
        resized = img.resize((img.width // 3, img.height // 3), PILImage.LANCZOS)
        buf = _io.BytesIO()
        resized.save(buf, format="JPEG", quality=70, optimize=True)
        return buf.getvalue(), "image/jpeg", True
    except Exception:
        return raw, mime, False

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
# Seedance 2.0: multimodal (text, images, videos, audio), 4–15s, 480P–2K, Video Extension/Editing
SEEDANCE_2_0_MODEL_ID = os.getenv("SEEDANCE_2_MODEL_ID", "dreamina-seedance-2-0-260128")
SEEDANCE_2_0_FAST_MODEL_ID = "dreamina-seedance-2-0-fast-260128"
SEEDANCE_2_MODEL_ID = SEEDANCE_2_0_MODEL_ID  # Alias for backward compat
SEEDREAM_4_5_MODEL_ID = "seedream-4-5-251128"     # ByteDance-Seedream-4.5
# ByteDance-Seedream-5.0-lite (260128): text, single/multi-image, image sets.
SEEDREAM_5_0_LITE_MODEL_ID = os.getenv("SEEDREAM_5_MODEL_ID", "seedream-5-0-260128") 

# ── Cost estimation ──────────────────────────────────────────
def _estimate_seedance2_tokens(duration=5, resolution="720p"):
    """Estimate Seedance 2.0 tokens from official 5s 720p baseline."""
    try:
        dur = int(duration)
    except (ValueError, TypeError):
        dur = 5
    if dur == -1:
        dur = 5  # smart duration unknown before generation; use official baseline
    dur = max(1, dur)
    res_factor = 0.465 if str(resolution).strip() == "480p" else 1.0
    # Official baseline: 5s 720p ~= 108,900 tokens
    return int(round(108900 * (dur / 5.0) * res_factor))


def _estimate_seedance2_usage(duration=5, resolution="720p", has_video_input=False):
    """Return consumed tokens, pack deduction, and pay-as-you-go cost for Seedance 2.0."""
    tokens_consumed = _estimate_seedance2_tokens(duration=duration, resolution=resolution)
    rate_per_1k = 0.0043 if has_video_input else 0.0070
    estimated_cost = (tokens_consumed / 1000.0) * rate_per_1k
    deduction_ratio = 1.0 if has_video_input else 1.6279
    tokens_deducted = int(round(tokens_consumed * deduction_ratio))
    return {
        "tokens_consumed": tokens_consumed,
        "tokens_deducted": tokens_deducted,
        "estimated_cost": estimated_cost,
        "has_video_input": bool(has_video_input),
    }


def estimate_cost(model_id, resolution="720p", duration=5, generate_audio=False, is_draft=False, is_offline=False, aspect_ratio="16:9", has_video_input=False):
    """Return estimated cost in USD based on current ByteDance ARK pricing."""

    # ── Seedream (images) ──
    if "seedream" in str(model_id).lower():
        # Image tokens = (width × height) / 784, ~$0.035 per 1K image
        res_cost = {"3K": 0.14, "2K": 0.07, "1K": 0.035, "4K": 0.14}
        return round(res_cost.get(resolution, 0.035), 4)

    usage = _estimate_seedance2_usage(duration=duration, resolution=resolution, has_video_input=has_video_input)
    cost = usage["estimated_cost"]

    # Add LLM prompt refinement cost (~$0.0005)
    cost += 0.0005

    return round(cost, 4)


def format_cost_str(cost):
    """Format cost for display: $0.49 or <$0.01."""
    if cost < 0.01:
        return "<$0.01"
    return f"${cost:.2f}"

COST_PER_SEC = {
    "seedance-2": {"with_video_input": 0.0043, "without_video_input": 0.0070},  # $ / 1K tokens
}
COST_SEEDREAM_PER_IMAGE = 0.040
COST_SEED18_INPUT_PER_TOKEN = 0.000001
COST_SEED18_OUTPUT_PER_TOKEN = 0.000002

GENERATION_LOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "generation_log.csv"
)

# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────
def save_video_with_metadata(video_url, prompt_text, scene_description, resolution, aspect_ratio, 
                             duration, seed, generate_audio, is_draft, is_offline, model_id, has_video_input=False):
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
            if "seedance-2" in str(model_id).lower():
                usage = _estimate_seedance2_usage(
                    duration=duration,
                    resolution=resolution,
                    has_video_input=has_video_input,
                )
                f.write(f"Estimated tokens consumed: {usage['tokens_consumed']}\n")
                f.write(f"Resource pack tokens deducted: {usage['tokens_deducted']}\n")
                f.write(f"Estimated cost (pay-as-you-go): ${usage['estimated_cost']:.4f}\n")
                f.write(f"Input type: {'With video reference' if usage['has_video_input'] else 'Text/Image only'}\n")
            else:
                # Non-Seedance-2 fallback (unexpected model id for video)
                pass
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
            _est = estimate_cost(model_id or "", resolution)
            f.write(f"Estimated Cost: {format_cost_str(_est)}\n")
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
# 1. VIDEO GENERATION (SEEDANCE 2.0) — JSON strict validation
# ──────────────────────────────────────────────
def _estimate_cost(model, duration=None, resolution=None,
                   service_tier="Online", input_tokens=0, output_tokens=0):
    cost = 0.0
    breakdown = []
    m = model.lower()

    if "seedance-2" in m:
        has_video_input = str(service_tier).lower() == "with_video_input"
        usage = _estimate_seedance2_usage(duration=(duration or 10), resolution=(resolution or "720p"), has_video_input=has_video_input)
        base = usage["estimated_cost"]
        cost += base
        mode_lbl = "with video input" if has_video_input else "without video input"
        breakdown.append(f"Seedance 2.0 {duration}s {resolution} ({mode_lbl}): ${base:.4f}, tokens={usage['tokens_consumed']}, pack={usage['tokens_deducted']}")
    elif "seedream" in m:
        cost += COST_SEEDREAM_PER_IMAGE
        breakdown.append(f"Seedream image: ${COST_SEEDREAM_PER_IMAGE:.4f}")

    if input_tokens or output_tokens:
        llm_cost = (input_tokens * COST_SEED18_INPUT_PER_TOKEN) + \
                   (output_tokens * COST_SEED18_OUTPUT_PER_TOKEN)
        cost += llm_cost
        breakdown.append(f"Seed 1.8 {input_tokens}in/{output_tokens}out: ${llm_cost:.4f}")

    return {"total_usd": round(cost, 4), "breakdown": breakdown}


def _log_generation_cost(model, duration, resolution, service_tier,
                          cost_dict, prompt_preview=""):
    import csv
    file_exists = os.path.isfile(GENERATION_LOG_PATH)
    row = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model": model,
        "provider": "ARK Direct" if "seedance-2" in str(model).lower() else "",
        "duration_s": duration or "",
        "resolution": resolution or "",
        "service_tier": service_tier or "",
        "cost_usd": cost_dict["total_usd"],
        "breakdown": " | ".join(cost_dict["breakdown"]),
        "prompt_preview": (prompt_preview or "")[:80],
    }
    with open(GENERATION_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def generate_video(prompt_text, scene_description, images=[], videos=[], audios=[], 
                   seed="-1", resolution="1080p", aspect_ratio="16:9", duration=8, 
                   generate_audio=False, audio_details={}, is_draft=False, is_offline=False, 
                   model_id=None, shots_data=None, camera_fixed=None, **kwargs):
    if not API_KEY:
        return {"error": "API_KEY_ERROR", "details": ["ARK_API_KEY is missing."]}

    image_usage = kwargs.get("image_usage", "auto")
    preflight = validate_seedance_video_inputs(
        images=images, videos=videos, audios=audios, image_usage=image_usage,
    )
    if not preflight["ok"]:
        return {
            "error": "Reference files failed validation",
            "details": preflight["errors"],
            "warnings": preflight.get("warnings") or [],
        }

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    
    # Prompt must be narrative-only; strip any legacy --param flags
    clean_prompt = re.sub(r'\s*--\w+\s+\S+', '', (prompt_text or "").strip()).strip() or prompt_text or ""
    content_list = [{"type": "text", "text": clean_prompt}]
    
    model = model_id or SEEDANCE_2_MODEL_ID

    is_first_last_mode = image_usage == "first_last_frame"
    has_ref_media = _has_reference_media_inputs(videos, audios)
    if is_first_last_mode:
        # First+Last frame: exactly 2 images, regardless of model or resolution
        image_files = (images or [])[:2]
    else:
        image_files = (images or [])[:9]

    # Images: inline base64 data URLs (ByteDance: jpeg/png/webp, 300–6000px)
    image_process_errors = []
    image_content_items = []
    for i, file in enumerate(image_files):
        name = getattr(file, "name", None) or f"image_{i + 1}"
        try:
            raw_bytes, mime, was_resized = _auto_resize_image(file)
            mime = _normalize_mime_for_data_url(mime)
            if len(raw_bytes) > SEEDANCE_IMAGE_API_MAX_BYTES:
                image_process_errors.append(
                    f"Image {i + 1} ({name}): still too large ({_human_file_size(len(raw_bytes))}) "
                    f"after compression. Maximum is {_human_file_size(SEEDANCE_IMAGE_API_MAX_BYTES)}."
                )
                continue
            b64 = base64.b64encode(raw_bytes).decode("utf-8")
            item = {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
            if is_first_last_mode and not has_ref_media:
                item["role"] = "first_frame" if i == 0 else "last_frame"
            elif (
                not has_ref_media
                and i == 0
                and image_usage in ("first_frame", "auto")
                and len(image_files) == 1
            ):
                item["role"] = "first_frame"
            else:
                item["role"] = "reference_image"
            image_content_items.append(item)
        except Exception as e:
            image_process_errors.append(f"Image {i + 1} ({name}): {e}")
    if image_process_errors and not image_content_items:
        return {
            "error": "Could not prepare reference images",
            "details": image_process_errors,
        }

    # Videos: normalize to H.264 MP4, then public URL (ARK Files or tmpfiles)
    _session = _session_for_ark()
    video_content_items = []
    _vid_files = list((videos or [])[:3])
    _per_vid_max = (
        SEEDANCE_REF_VIDEO_TRIM_TO_SECONDS / len(_vid_files)
        if len(_vid_files) > 1
        else SEEDANCE_REF_VIDEO_TRIM_TO_SECONDS
    )
    for file in _vid_files:
        _vid_url = None
        _vid_name = getattr(file, "name", "video.mp4")
        _vid_bytes = None

        # Read bytes
        try:
            if hasattr(file, "getvalue"):
                _vid_bytes = file.getvalue()
            elif hasattr(file, "path") and os.path.exists(file.path):
                with open(file.path, "rb") as _f:
                    _vid_bytes = _f.read()
            elif isinstance(file, str) and os.path.exists(file):
                with open(file, "rb") as _f:
                    _vid_bytes = _f.read()
        except Exception as _re:
            print(f"[DEBUG-VIDEO] Failed to read file: {_re}")

        if not _vid_bytes:
            print(f"[DEBUG-VIDEO] Could not read bytes for {_vid_name}")
            continue

        # Auto-convert MOV to MP4 (compatibility fix)
        if _vid_name.lower().endswith('.mov'):
            try:
                import tempfile, subprocess
                with tempfile.NamedTemporaryFile(suffix='.mov', delete=False) as _src:
                    _src.write(_vid_bytes)
                    _src_path = _src.name
                _mp4_path = _src_path + '.mp4'
                _conv = subprocess.run(
                    ['ffmpeg', '-i', _src_path,
                     '-c:v', 'libx264', '-c:a', 'aac',
                     '-movflags', '+faststart', '-y', _mp4_path],
                    capture_output=True, timeout=120
                )
                if os.path.exists(_mp4_path) and os.path.getsize(_mp4_path) > 0:
                    with open(_mp4_path, 'rb') as _f:
                        _vid_bytes = _f.read()
                    _vid_name = _vid_name[:-4] + '.mp4'
                    print(f"[DEBUG-VIDEO] MOV→MP4 converted: {len(_vid_bytes)//1024}KB")
                os.unlink(_src_path)
                if os.path.exists(_mp4_path):
                    os.unlink(_mp4_path)
            except Exception as _ce:
                print(f"[DEBUG-VIDEO] MOV conversion failed: {_ce}")

        _max_sec = min(_per_vid_max, SEEDANCE_REF_VIDEO_TRIM_TO_SECONDS)
        _norm, _norm_name, _vid_dur = _normalize_reference_video_bytes(
            _vid_bytes, _vid_name, max_seconds=_max_sec,
        )
        if not _norm:
            return {
                "error": "Could not prepare reference video",
                "details": [
                    f"{_vid_name}: failed to normalize to H.264 MP4 (install ffmpeg). "
                    f"Clips must be {SEEDANCE_REF_VIDEO_MIN_SECONDS}–{SEEDANCE_REF_VIDEO_MAX_SECONDS}s, "
                    "MP4/MOV, under 50MB."
                ],
            }
        _vid_bytes, _vid_name = _norm, _norm_name
        if _vid_dur is not None and _vid_dur < SEEDANCE_REF_VIDEO_MIN_SECONDS:
            return {
                "error": "Reference video too short",
                "details": [
                    f"{_vid_name}: {_vid_dur:.1f}s — minimum is {SEEDANCE_REF_VIDEO_MIN_SECONDS}s."
                ],
            }
        print(
            f"[DEBUG-VIDEO] Normalized {len(_vid_bytes)//1024}KB"
            + (f", {_vid_dur:.1f}s" if _vid_dur else "")
        )

        _vid_url = _upload_reference_video_url(_vid_bytes, _vid_name, _session)
        if _vid_url:
            video_content_items.append({
                "type": "video_url",
                "video_url": {"url": _vid_url},
                "role": "reference_video",
            })
        else:
            return {
                "error": "Could not publish reference video URL",
                "details": [
                    f"{_vid_name}: ARK could not fetch a valid public video URL. "
                    "Re-export as MP4 (H.264 + AAC) or retry."
                ],
            }

    # ByteDance: @Video N / @Image N order follows content array (videos before images in r2v)
    if has_ref_media and video_content_items:
        content_list.extend(video_content_items)
        content_list.extend(image_content_items)
    else:
        content_list.extend(image_content_items)
        content_list.extend(video_content_items)
    if generate_audio:
        for file in (audios or [])[:3]:
            out = upload_file_to_byteplus(file)
            if out:
                fid, url = out if isinstance(out, tuple) else (out, f"{FILE_UPLOAD_URL}/{out}")
                if url:
                    content_list.append({"type": "audio_url", "audio_url": {"url": url}, "role": "reference_audio"})

    # Validate total mixed input files (max 12 for Seedance 2.0)
    _file_count = sum(1 for it in content_list if isinstance(it, dict) and it.get("type") in ("image_url", "video_url", "audio_url"))
    if _file_count > 12:
        return {
            "error": "Too many input files",
            "details": [
                f"{_file_count} files attached; Seedance 2.0 allows at most 12 combined images, videos, and audio."
            ],
        }

    print(f"[DEBUG-GV] content_list items: {len(content_list)}, types: {[it.get('type') for it in content_list if isinstance(it, dict)]}")

    try:
        seed_int = int(seed) if seed and str(seed).strip() != "-1" else None
    except (ValueError, TypeError):
        seed_int = None

    # Duration: -1 = smart/autonomous; otherwise clamp to Seedance 2.0 range (4–15s)
    try:
        duration_int = int(duration)
    except (ValueError, TypeError):
        duration_int = 8
    if duration_int != -1:
        if duration_int < 4 or duration_int > 15:
            duration_int = max(4, min(15, duration_int))

    if camera_fixed is None:
        camera_fixed = False

    # service_tier is still used for polling timeout / cost logging only
    service_tier = "Offline" if is_offline else "Online"
    if is_draft:
        service_tier = "Online"

    _res_out = "480p" if is_draft else (resolution or "720p")
    if "seedance-2" in str(model).lower() and _res_out not in ("480p", "720p", "1080p"):
        _res_out = "720p"  # Seedance 2.0 API: 480p / 720p / 1080p

    payload = {
        "model": model,
        "content": content_list,
        "resolution": _res_out,
        "ratio": aspect_ratio,
        "duration": duration_int,
        "seed": seed_int if seed_int is not None else -1,
        "generate_audio": bool(generate_audio),
        "watermark": bool(kwargs.get("watermark", False)),
        "return_last_frame": True,
    }
    # service_tier not supported in r2v mode (reference images present)
    _has_ref_image = any(
        isinstance(it, dict) and it.get("role") == "reference_image"
        for it in content_list
    )
    if service_tier and service_tier.lower() in ("flex", "offline") and not _has_ref_image:
        payload["service_tier"] = "flex"
    has_video_reference = any((it or {}).get("type") == "video_url" for it in content_list if isinstance(it, dict))

    print(f"[DEBUG-GV] payload keys: {list(payload.keys())}, model: {payload.get('model')}")

    try:
        print(f"[DEBUG-GV] calling API...")
        try:
            response = _session.post(VIDEO_TASK_URL, headers=headers, json=payload, timeout=30, verify=_ssl_verify)
            print(f"[DEBUG-GV] API response status: {response.status_code}")
            print(f"[DEBUG-GV] API response: {response.text[:200]}")
        except Exception as e:
            print(f"[DEBUG-GV-ERROR] {type(e).__name__}: {e}")
            return {"error": f"Video API request failed: {e}", "details": []}
        if not response.ok:
            try:
                err_body = response.json()
                err_msg = err_body.get("message") or err_body.get("Error", {}).get("Message") or str(err_body)
            except Exception:
                err_msg = response.text[:500]
            return {
                "error": f"Video API rejected the request (HTTP {response.status_code})",
                "details": [err_msg],
            }
        res_json = response.json()
        task_data = res_json.get("data") if isinstance(res_json, dict) else None
        task_id = (task_data or {}).get("id") if isinstance(task_data, dict) else None
        if not task_id:
            task_id = res_json.get("id") if isinstance(res_json, dict) else None
        if not task_id:
            return {"error": "API did not return a task id", "details": [str(res_json)[:500]]}
        
        # Polling Loop
        poll_max = 600 if is_offline else 120
        status_url = f"{VIDEO_TASK_URL}/{task_id}"
        
        for _ in range(poll_max):
            time.sleep(5)
            s_res = _session.get(status_url, headers=headers, timeout=10, verify=_ssl_verify)
            s_json = s_res.json()
            s_data = s_json.get("data") if isinstance(s_json, dict) and isinstance(s_json.get("data"), dict) else s_json
            status = s_data.get("status")
            if status == "succeeded":
                content_obj = s_data.get("content", {}) if isinstance(s_data, dict) else {}
                video_url = content_obj.get("video_url")
                if not video_url:
                    outputs = s_data.get("outputs") if isinstance(s_data, dict) else None
                    if isinstance(outputs, list) and outputs:
                        video_url = outputs[0]
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
                        model_id=model,
                        has_video_input=has_video_reference,
                    )
                    return {
                        "video": video_url,
                        "video_path": saved_paths.get("video_path"),
                        "last_frame_path": saved_paths.get("last_frame_path"),
                        "info_file_path": saved_paths.get("info_file_path")
                    }
                return {"video": video_url}
            elif status == "failed":
                err_obj = s_data.get("error") if isinstance(s_data, dict) else None
                if isinstance(err_obj, dict):
                    err_msg = err_obj.get("message") or err_obj.get("code") or str(err_obj)
                else:
                    err_msg = s_data.get("message") if isinstance(s_data, dict) else None
                return {"error": "Video generation failed on the server", "details": [err_msg or "Unknown error"]}
        return {"error": "Video generation timed out", "details": ["The task did not complete in time. Try Draft mode or fewer reference files."]}
    except requests.exceptions.HTTPError as e:
        try:
            err_body = e.response.json()
            err_msg = err_body.get("message") or str(err_body)
        except Exception:
            err_msg = (e.response.text[:500] if e.response else str(e))
        return {
            "error": f"Video API error (HTTP {e.response.status_code if e.response else '?'})",
            "details": [err_msg],
        }
    except requests.exceptions.SSLError as e:
        return {
            "error": "Connection error (SSL)",
            "details": [str(e), "Set ARK_SSL_VERIFY=0 in your environment and restart."],
        }
    except requests.exceptions.ConnectionError as e:
        return {
            "error": "Connection error",
            "details": [str(e), "Check network, firewall, or VPN and try again."],
        }
    except Exception as e:
        return {"error": "Request failed", "details": [str(e)]}

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
