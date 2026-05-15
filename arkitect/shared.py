import os
import io
import mimetypes

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Persistent data root: Railway Volume /data, or local data/ ──
_PERSIST_DIR = os.getenv("PERSIST_DIR", "")
if not _PERSIST_DIR:
    _PERSIST_DIR = "/data" if os.path.isdir("/data") else os.path.join(_APP_DIR, "data")
os.makedirs(_PERSIST_DIR, exist_ok=True)

_DB_DIR = os.path.join(_PERSIST_DIR, "db")
_GENERATED_DIR = os.path.join(_PERSIST_DIR, "generated")
_REFERENCES_DIR = os.path.join(_PERSIST_DIR, "references")
os.makedirs(_DB_DIR, exist_ok=True)
os.makedirs(_GENERATED_DIR, exist_ok=True)
os.makedirs(_REFERENCES_DIR, exist_ok=True)

# Legacy alias — some code still references _DOWNLOADS_DIR
_DOWNLOADS_DIR = _GENERATED_DIR
_STATIC_DIR = os.path.join(_APP_DIR, "static")


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
