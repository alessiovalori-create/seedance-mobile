import os
import io
import re
import mimetypes
from datetime import datetime

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Persistent data root: Railway Volume /data, or local data/ ──
_PERSIST_DIR = os.getenv("PERSIST_DIR", "")
if not _PERSIST_DIR:
    _PERSIST_DIR = "/data" if os.path.isdir("/data") else os.path.join(_APP_DIR, "data")
os.makedirs(_PERSIST_DIR, exist_ok=True)

_DB_DIR = os.path.join(_PERSIST_DIR, "db")
_GENERATED_DIR = os.path.join(_PERSIST_DIR, "generated")
_ASSETS_DIR = os.path.join(_GENERATED_DIR, "assets")
_REFERENCES_DIR = os.path.join(_GENERATED_DIR, "references")
_EXPORTS_DIR = os.path.join(_GENERATED_DIR, "exports")
_UPLOADS_DIR = os.path.join(_GENERATED_DIR, "uploads")

# Non-project folders under generated/ (library, refs, exports, uploads)
GENERATED_RESERVED_DIRS = frozenset({
    "assets",
    "references",
    "exports",
    "uploads",
})

os.makedirs(_DB_DIR, exist_ok=True)
os.makedirs(_GENERATED_DIR, exist_ok=True)
for _subdir in (_ASSETS_DIR, _REFERENCES_DIR, _EXPORTS_DIR, _UPLOADS_DIR):
    os.makedirs(_subdir, exist_ok=True)

# Legacy alias — some code still references _DOWNLOADS_DIR
_DOWNLOADS_DIR = _GENERATED_DIR
_STATIC_DIR = os.path.join(_APP_DIR, "static")


def sanitize_project_dir_name(project_name):
    """Filesystem-safe folder name for a project under generated/."""
    if not project_name or str(project_name).strip() in ("", "All Projects"):
        return "general"
    slug = re.sub(r"[^\w\-]", "_", str(project_name).strip())
    slug = slug or "general"
    if slug in GENERATED_RESERVED_DIRS:
        slug = f"{slug}_project"
    return slug


def ensure_project_generated_dir(project_name):
    """Create generated/{project}/ when a new project is started."""
    if not project_name or str(project_name).strip() in ("", "All Projects"):
        return None
    project_folder = sanitize_project_dir_name(project_name)
    path = os.path.join(_GENERATED_DIR, project_folder)
    os.makedirs(path, exist_ok=True)
    return path


def generated_output_dir(project_name=None, date=None):
    """Return (and create) generated/{project}/{YYYY-MM-DD}/."""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    project_folder = sanitize_project_dir_name(project_name)
    ensure_project_generated_dir(project_name)
    path = os.path.join(_GENERATED_DIR, project_folder, date)
    os.makedirs(path, exist_ok=True)
    return path


class CachedUploadedFile:
    """Mimics Streamlit UploadedFile from cached bytes, survives page navigation."""
    def __init__(self, name, data, mime_type):
        self.name = name
        self.type = mime_type
        self._data = data
        self.size = len(data)

    def getvalue(self):
        return self._data

    def read(self):
        return self._data


def _materialize_multi_file_upload(raw):
    """Copy Streamlit multi-file uploader output to a list exactly once (avoids iterator / double-read loss)."""
    if raw is None:
        return []
    return list(raw)


class AssetFile:
    """Wraps a file on disk to mimic Streamlit's UploadedFile interface."""
    def __init__(self, path, name, mime_type):
        self.name = name
        self.type = mime_type
        self._path = path
        self.size = os.path.getsize(path) if os.path.exists(path) else 0

    def getvalue(self):
        with open(self._path, 'rb') as f:
            return f.read()
