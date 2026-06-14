import os
import re
import base64 as _b64

import streamlit as st

from arkitect.shared import (
    _APP_DIR,
    _PERSIST_DIR,
    _DOWNLOADS_DIR,
    _STATIC_DIR,
)

_STATIC_SERVING_OK = False

# ── Local media server for serving ANY local video inside component iframes ──
_MEDIA_SERVER_PORT = None


def _setup_static_serving():
    """Ensure static serving is configured. Returns True if likely working."""
    global _STATIC_SERVING_OK

    # 1. Ensure downloads/ exists
    os.makedirs(_DOWNLOADS_DIR, exist_ok=True)

    # 2. Ensure .streamlit/config.toml has enableStaticServing
    config_dir = os.path.join(_APP_DIR, ".streamlit")
    config_path = os.path.join(config_dir, "config.toml")
    os.makedirs(config_dir, exist_ok=True)

    config_ok = False
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "enableStaticServing" in content:
            config_ok = True

    if not config_ok:
        existing = ""
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                existing = f.read()
        existing = re.sub(
            r"\[server\]\s*\n\s*enableStaticServing\s*=\s*\w+\s*\n?",
            "",
            existing,
        ).strip()
        with open(config_path, "w", encoding="utf-8") as f:
            f.write("[server]\nenableStaticServing = true\n\n")
            if existing:
                f.write(existing + "\n")

    # 3. Ensure static/ directory links to _PERSIST_DIR (serves generated/, references/, assets/)
    if os.path.islink(_STATIC_DIR):
        target = os.path.realpath(_STATIC_DIR)
        if target != os.path.realpath(_PERSIST_DIR):
            os.remove(_STATIC_DIR)
            os.symlink(_PERSIST_DIR, _STATIC_DIR, target_is_directory=True)
    elif os.path.isdir(_STATIC_DIR):
        pass  # Don't delete user's static/ if it has content
    elif not os.path.exists(_STATIC_DIR):
        try:
            os.symlink(_PERSIST_DIR, _STATIC_DIR, target_is_directory=True)
        except OSError:
            os.makedirs(_STATIC_DIR, exist_ok=True)

    _STATIC_SERVING_OK = os.path.exists(_STATIC_DIR)
    return _STATIC_SERVING_OK


def _ensure_media_server():
    """Start a lightweight HTTP server (daemon thread) that can serve any local
    video file by its base64-encoded absolute path.
    URL format: http://127.0.0.1:<port>/media/<base64_of_abspath>
    Only binds to 127.0.0.1 (localhost only, not exposed to network)."""
    global _MEDIA_SERVER_PORT
    if _MEDIA_SERVER_PORT is not None:
        return _MEDIA_SERVER_PORT
    try:
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        _ALLOWED_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
        _MIME_MAP = {
            ".mp4": "video/mp4",
            ".mov": "video/quicktime",
            ".webm": "video/webm",
            ".mkv": "video/x-matroska",
            ".avi": "video/x-msvideo",
            ".m4v": "video/x-m4v",
        }

        class _MediaHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # suppress console spam

            def do_GET(self):
                if not self.path.startswith("/media/"):
                    self.send_error(404)
                    return
                token = self.path[7:].split("?")[0]  # strip /media/ prefix and query
                try:
                    decoded = _b64.b64decode(token).decode("utf-8")
                    file_path = os.path.realpath(os.path.abspath(decoded))
                except Exception:
                    self.send_error(400)
                    return
                ext = os.path.splitext(file_path)[1].lower()
                if ext not in _ALLOWED_EXT or not os.path.isfile(file_path):
                    self.send_error(404)
                    return
                mime = _MIME_MAP.get(ext, "application/octet-stream")
                try:
                    file_size = os.path.getsize(file_path)
                    # Support Range requests for seeking
                    range_header = self.headers.get("Range")
                    if range_header:
                        start, end = 0, file_size - 1
                        r = range_header.replace("bytes=", "").strip()
                        parts = r.split("-")
                        start = int(parts[0]) if parts[0] else 0
                        end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1
                        end = min(end, file_size - 1)
                        length = end - start + 1
                        self.send_response(206)
                        self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                        self.send_header("Content-Length", str(length))
                        self.send_header("Content-Type", mime)
                        self.send_header("Accept-Ranges", "bytes")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        with open(file_path, "rb") as f:
                            f.seek(start)
                            self.wfile.write(f.read(length))
                    else:
                        self.send_response(200)
                        self.send_header("Content-Type", mime)
                        self.send_header("Content-Length", str(file_size))
                        self.send_header("Accept-Ranges", "bytes")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        with open(file_path, "rb") as f:
                            while True:
                                chunk = f.read(65536)
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception:
                    self.send_error(500)

            def do_OPTIONS(self):
                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Range")
                self.end_headers()

        for port in range(8502, 8520):
            try:
                server = HTTPServer(("127.0.0.1", port), _MediaHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                _MEDIA_SERVER_PORT = port
                return port
            except OSError:
                continue
    except Exception:
        pass
    return None


def _to_media_url(file_path):
    """Convert ANY local video file path to an HTTP URL via the local media server."""
    if not file_path:
        return ""
    if file_path.startswith("http://") or file_path.startswith("https://"):
        return file_path
    real = os.path.realpath(os.path.abspath(file_path))
    if not os.path.isfile(real):
        return ""
    port = _ensure_media_server()
    if port is None:
        return _to_static_url(file_path)  # fallback
    token = _b64.b64encode(real.encode("utf-8")).decode("ascii")
    return f"http://127.0.0.1:{port}/media/{token}"


try:
    _st_version = st.__version__
    _st_parts = _st_version.split(".")
    _st_major, _st_minor = int(_st_parts[0]), int(_st_parts[1])
    _STATIC_SERVING_SUPPORTED = (_st_major > 1) or (_st_major == 1 and _st_minor >= 31)
except Exception:
    _st_version = "unknown"
    _STATIC_SERVING_SUPPORTED = False

if not _STATIC_SERVING_SUPPORTED:
    print(f"⚠️ Streamlit {_st_version} — static serving requires >= 1.31.0. Run: pip install --upgrade streamlit")


def _to_static_url(file_path):
    """Convert a local file path to a Streamlit static URL.
    Serves generated/ (projects, assets, references, exports) via static/.
    Returns original path as fallback if conversion fails."""
    if not file_path:
        return ""
    if file_path.startswith("http://") or file_path.startswith("https://"):
        return file_path
    if not _STATIC_SERVING_OK:
        return file_path

    try:
        real_file = os.path.realpath(os.path.abspath(file_path))
    except OSError:
        return file_path

    real_persist = os.path.realpath(_PERSIST_DIR)
    if real_file == real_persist or real_file.startswith(real_persist + os.sep):
        rel = os.path.relpath(real_file, real_persist)
        return f"/_stcore/static/{rel.replace(os.sep, '/')}"

    real_static = os.path.realpath(_STATIC_DIR)
    if real_file == real_static or real_file.startswith(real_static + os.sep):
        rel = os.path.relpath(real_file, real_static)
        return f"/_stcore/static/{rel.replace(os.sep, '/')}"

    return file_path


_setup_static_serving()
