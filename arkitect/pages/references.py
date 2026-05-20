import os
import re
import json
import hashlib
import random
import html as _html_stdlib
import base64 as _b64
from datetime import datetime
from urllib.parse import quote

import requests
import streamlit as st
import streamlit.components.v1 as components

from generator import PEXELS_API_KEY, UNSPLASH_API_KEY
from arkitect.shared import _REFERENCES_DIR
from arkitect.storage import add_to_assets
from arkitect.storyboard_io import _autosave_storyboard_snapshot
from arkitect.ui_helpers import _render_project_name_inline_right

_REFS_STOCK_IFRAME_CSS = """<style>
*{margin:0;padding:0;box-sizing:border-box;}
body{background:transparent;font-family:'Open Sans',sans-serif;}
.ref-stock-masonry{
  column-count:3;
  column-gap:8px;
  padding:4px;
}
@media (max-width:480px){
  .ref-stock-masonry{column-count:2;}
}
.gal-card.ref-stock-card{
  position:relative;
  background:#1a1a18;
  border-radius:6px;
  overflow:visible;
  border:2px solid transparent;
  transition:border-color .2s,box-shadow .2s;
  cursor:pointer;
  break-inside:avoid;
  page-break-inside:avoid;
  margin-bottom:8px;
  display:block;
  width:100%;
  min-height:0;
}
.gal-card.ref-stock-card:hover{border-color:rgba(255,235,59,.35)!important;box-shadow:0 4px 16px rgba(0,0,0,.35);}
.ref-stock-img-wrap{
  display:block;
  width:100%;
  line-height:0;
  background:#121210;
  position:relative;
  border-radius:4px;
  overflow:hidden;
}
.ref-stock-img-wrap.ref-stock-selected{
  outline:2px solid #FFEB3B;
  outline-offset:-2px;
  box-shadow:0 0 0 1px #FFEB3B, 0 0 14px rgba(255,235,59,0.28);
}
.ref-stock-sel-check{
  position:absolute;
  bottom:8px;
  right:6px;
  background:#FFEB3B;
  color:#000;
  width:18px;
  height:18px;
  border-radius:50%;
  font-size:11px;
  font-weight:700;
  display:flex;
  align-items:center;
  justify-content:center;
  z-index:4;
  pointer-events:none;
  line-height:1;
  box-sizing:border-box;
}
.ref-stock-img{
  position:relative;
  z-index:1;
  width:100%;
  height:auto;
  max-height:none;
  object-fit:contain;
  vertical-align:top;
  border-radius:4px;
  display:block;
  -webkit-user-drag:none;
  user-select:none;
  pointer-events:none;
}
.gal-badge{position:absolute;top:4px;left:4px;background:rgba(0,0,0,.75);color:#fff;font-size:9px;font-weight:700;padding:1px 6px;border-radius:3px;z-index:2;pointer-events:none;}
.gal-expand{position:absolute;top:4px;right:4px;color:#999;cursor:pointer;z-index:6;width:20px;height:20px;display:flex;align-items:center;justify-content:center;border-radius:3px;background:rgba(0,0,0,0.55);transition:color .15s,background .15s;}
.gal-expand:hover{color:#FFEB3B;background:rgba(0,0,0,0.85);}
.gal-caption{color:#999;font-size:9px;padding:3px 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.ref-stock-ph{
  position:absolute;
  inset:0;
  z-index:0;
  background:var(--ref-ph,#121210);
  border-radius:4px;
  pointer-events:none;
}
.ref-stock-img-wrap.ref-stock-no-dims{min-height:140px;}
</style>"""

def _refs_sanitize_hex_color(raw):
    """Return #rgb or #rrggbb safe for CSS custom properties, or '' if invalid."""
    if not raw or not isinstance(raw, str):
        return ""
    s = raw.strip()
    if s.startswith("#"):
        body = s[1:]
    else:
        body = s
    if len(body) == 3 and all(c in "0123456789abcdefABCDEF" for c in body):
        return "#" + body.lower()
    if len(body) == 6 and all(c in "0123456789abcdefABCDEF" for c in body):
        return "#" + body.lower()
    return ""


def _refs_placeholder_style_attr(api_color):
    """Inline style setting --ref-ph when API provides avg_color / color."""
    safe = _refs_sanitize_hex_color(api_color)
    return f' style="--ref-ph:{safe};"' if safe else ""

def toggle_refs_selection(image_id, source="pexels"):
    """ReferencesRoom: add/remove API photo id in selection sets.

    High-res URL and width/height are not stored on the selection itself; they are
    resolved at STORYBOARD/ASSET time from ``_refs_pexels_by_id`` / ``_refs_unsplash_by_id``
    (full API payloads from the last search).
    """
    sid = str(image_id)
    _key_map = {
        "pexels": "refs_selected_pexels",
        "unsplash": "refs_selected_unsplash",
        "art_chicago": "refs_selected_art_chicago",
        "met": "refs_selected_met",
        "google_arts": "refs_selected_google_arts",
        "wiki": "refs_selected_wiki",
    }
    key = _key_map.get(source, "refs_selected_unsplash")

    if key not in st.session_state:
        st.session_state[key] = set()
    s = st.session_state[key]

    will_add = sid not in s
    if will_add:
        s.add(sid)
    else:
        s.discard(sid)

    # Optional: keep a small "global" view of selected images + metadata.
    # This is mainly for UI/inspection; the app still uses the per-source sets
    # for storyboard/assets export.
    if "selected_images" not in st.session_state:
        st.session_state.selected_images = {}
    sel_key = f"{source}:{sid}"
    if will_add:
        item = _refs_resolve_selected_image_meta(sid, source=source)
        if item is not None:
            st.session_state.selected_images[sel_key] = item
    else:
        st.session_state.selected_images.pop(sel_key, None)


def _refs_resolve_selected_image_meta(image_id, source="pexels"):
    """Best-effort metadata resolver for `st.session_state.selected_images`."""
    sid = str(image_id)

    try:
        if source == "pexels":
            by_p = st.session_state.get("_refs_pexels_by_id") or {}
            ph = by_p.get(sid)
            if not ph:
                return None
            url = _refs_pexels_high_res_url(ph)
            if not url:
                return None
            cap = (ph.get("alt") or ph.get("photographer") or f"Pexels {sid}")[:120]
            prov = _refs_pexels_provenance(ph, sid, url)
            return {
                "source": "pexels",
                "id": sid,
                "url": url,
                "caption": cap,
                "provenance": prov,
                "original_width": prov.get("original_width"),
                "original_height": prov.get("original_height"),
            }

        if source == "unsplash":
            by_u = st.session_state.get("_refs_unsplash_by_id") or {}
            uc = by_u.get(sid)
            if not uc:
                return None
            full_url = uc.get("full_url")
            if not full_url:
                return None
            un = uc.get("user_name") or "Photographer"
            cap = f"{un} · Unsplash"[:120]
            prov = _refs_unsplash_provenance(uc, sid, full_url)
            return {
                "source": "unsplash",
                "id": sid,
                "url": full_url,
                "caption": cap,
                "provenance": prov,
                "original_width": prov.get("original_width"),
                "original_height": prov.get("original_height"),
            }

        if source == "art_chicago":
            by_a = st.session_state.get("_refs_art_chicago_by_id") or {}
            rec = by_a.get(sid)
            if not rec:
                return None
            url = _refs_art_chicago_iiif_url(rec)
            if not url:
                return None
            title = rec.get("title") or "Untitled"
            artist = rec.get("artist_display") or "Unknown artist"
            cap = f"{title} — {artist}"[:140]
            prov = _refs_art_chicago_provenance(rec, sid, url)
            return {
                "source": "art_chicago",
                "id": sid,
                "url": url,
                "caption": cap,
                "provenance": prov,
                "original_width": prov.get("original_width"),
                "original_height": prov.get("original_height"),
            }

        if source == "met":
            by_m = st.session_state.get("_refs_met_by_id") or {}
            rec = by_m.get(sid)
            if not rec:
                return None
            url = rec.get("full_url") or rec.get("image_url")
            if not url:
                return None
            title = rec.get("title") or "Untitled"
            artist = rec.get("artist_display") or "Unknown"
            cap = f"{title} — {artist}"[:140]
            return {
                "source": "met",
                "id": sid,
                "url": url,
                "caption": cap,
                "provenance": {
                    "vendor": "met",
                    "api_asset_id": sid,
                    "url": url,
                    "title": title,
                    "artist_display": artist,
                },
                "original_width": rec.get("original_width"),
                "original_height": rec.get("original_height"),
            }

        if source == "google_arts":
            by_g = st.session_state.get("_refs_google_arts_by_id") or {}
            rec = by_g.get(sid)
            if not rec:
                return None
            page_url = rec.get("page_url") or ""
            img_url = rec.get("image_url") or ""
            url = img_url or page_url
            if not url:
                return None
            title = (rec.get("title") or "Arts & Culture")[:100]
            cap = f"{title} · Google Arts & Culture"[:140]
            return {
                "source": "google_arts",
                "id": sid,
                "url": url,
                "caption": cap,
                "provenance": {
                    "vendor": "google_arts",
                    "page_url": page_url,
                    "image_url": img_url,
                    "title": rec.get("title", ""),
                },
                "original_width": None,
                "original_height": None,
            }
        if source == "wiki":
            by_w = st.session_state.get("_refs_wiki_by_id") or {}
            rec = by_w.get(sid)
            if not rec:
                return None
            img_url = rec.get("image_url") or ""
            full_url = rec.get("full_url") or img_url
            url = full_url or img_url
            if not url:
                return None
            title = rec.get("title") or "Wikimedia"
            artist = rec.get("artist_display") or "Unknown"
            cap = f"{title} — {artist}"[:140]
            return {
                "source": "wiki",
                "id": sid,
                "url": url,
                "caption": cap,
                "provenance": {
                    "vendor": "wikimedia",
                    "id": sid,
                    "title": title,
                    "artist_display": artist,
                    "image_url": img_url,
                    "full_url": full_url,
                },
                "original_width": rec.get("original_width"),
                "original_height": rec.get("original_height"),
            }
    except Exception:
        # Never break selection UI if metadata resolution fails.
        return None

    return None


def _refs_google_arts_thumb_from_cse_item(item):
    """Best-effort thumbnail URL from a Google Custom Search JSON API item."""
    pm = (item or {}).get("pagemap") or {}
    for key in ("cse_image", "cse_thumbnail"):
        for it in pm.get(key) or []:
            src = (it or {}).get("src")
            if src:
                return src
    for mt in pm.get("metatags") or []:
        og = (mt or {}).get("og:image")
        if og:
            return og
    return ""


def _refs_sel_bridge_on_change(bridge_key: str, source: str) -> None:
    raw = (st.session_state.get(bridge_key) or "").strip()
    st.session_state[bridge_key] = ""
    token = raw.split("|")[0].strip()
    if token.startswith("t:"):
        token = token[2:]
    if token:
        toggle_refs_selection(token, source=source)


def _refs_download_url_to_downloads(url: str, basename: str):
    """Download remote image into downloads/ with a unique filename. Returns absolute path or None."""
    if not url or (not url.startswith("http://") and not url.startswith("https://")):
        return None
    os.makedirs(_REFERENCES_DIR, exist_ok=True)
    safe = re.sub(r"[^\w.\-]", "_", basename) or "ref_image.jpg"
    base, ext = os.path.splitext(safe)
    _img_exts = (".jpg", ".jpeg", ".png", ".webp", ".gif")
    _vid_exts = (".mp4", ".mov", ".webm")
    if not ext or ext.lower() not in (_img_exts + _vid_exts):
        ext = ".jpg"
    dest = os.path.join(_REFERENCES_DIR, f"{base}{ext}")
    n = 1
    while os.path.exists(dest):
        dest = os.path.join(_REFERENCES_DIR, f"{base}_{n}{ext}")
        n += 1
    try:
        r = requests.get(
            url,
            timeout=90,
            headers={"User-Agent": "AI-DOP-Console/1.0 (references; +https://github.com)"},
        )
        r.raise_for_status()
        with open(dest, "wb") as f:
            f.write(r.content)
        return dest
    except Exception:
        return None


def _refs_pexels_high_res_url(ph):
    src = ph.get("src") or {}
    return src.get("original") or src.get("large2x") or src.get("large")


def _refs_pexels_provenance(ph, sid, high_res_url):
    """Metadata from Pexels API for Storyboard/Assets (not thumbnail URLs)."""
    w = h = None
    try:
        iw = int(ph.get("width") or 0)
        ih = int(ph.get("height") or 0)
        if iw > 0 and ih > 0:
            w, h = iw, ih
    except (TypeError, ValueError):
        pass
    return {
        "vendor": "pexels",
        "api_asset_id": str(sid),
        "high_res_url": high_res_url,
        "original_width": w,
        "original_height": h,
        "photographer": ph.get("photographer"),
        "source_page_url": ph.get("url"),
    }


def _refs_unsplash_provenance(uc, sid, high_res_url):
    """Metadata from Unsplash API for Storyboard/Assets (full-size URL + native dimensions)."""
    photo = uc.get("photo") or {}
    w = h = None
    try:
        iw = int(photo.get("width") or 0)
        ih = int(photo.get("height") or 0)
        if iw > 0 and ih > 0:
            w, h = iw, ih
    except (TypeError, ValueError):
        pass
    return {
        "vendor": "unsplash",
        "api_asset_id": str(sid),
        "high_res_url": high_res_url,
        "original_width": w,
        "original_height": h,
        "photographer_name": uc.get("user_name"),
    }


def _refs_art_chicago_iiif_url(rec):
    """IIIF image URL builder for Art Institute of Chicago artworks."""
    image_id = rec.get("image_id")
    if not image_id:
        return None
    # Standard IIIF: region=full, width=843, height=auto (: /0), format=default.jpg
    return f"https://www.artic.edu/iiif/2/{image_id}/full/843,/0/default.jpg"


def _refs_art_chicago_provenance(rec, sid, iiif_url):
    """Provenance metadata for Storyboard/Assets."""
    title = rec.get("title") or "Untitled"
    artist = rec.get("artist_display") or "Unknown artist"
    return {
        "vendor": "art_chicago",
        "api_asset_id": str(sid),
        "iiif_url": iiif_url,
        "image_id": rec.get("image_id"),
        "title": title,
        "artist_display": artist,
        "original_width": rec.get("original_width"),
        "original_height": rec.get("original_height"),
    }


def _refs_send_selected_to_storyboard():
    """Download selected reference images to downloads/, append to sb_active_images, persist snapshot."""
    p_ids = set(st.session_state.get("refs_selected_pexels") or set())
    u_ids = set(st.session_state.get("refs_selected_unsplash") or set())
    a_ids = set(st.session_state.get("refs_selected_art_chicago") or set())
    m_ids = set(st.session_state.get("refs_selected_met") or set())
    w_ids = set(st.session_state.get("refs_selected_wiki") or set())
    g_ids = set(st.session_state.get("refs_selected_google_arts") or set())
    if not p_ids and not u_ids and not a_ids and not m_ids and not w_ids and not g_ids:
        return 0, 0, 0

    if st.session_state.sb_mode not in ("new", "loaded"):
        st.session_state.sb_mode = "new"
        st.session_state.sb_active_name = ""
        st.session_state.sb_active_images = []

    existing_paths = {item.get("image_path") for item in st.session_state.sb_active_images if item.get("image_path")}
    existing_urls = {item.get("url") for item in st.session_state.sb_active_images if item.get("url")}
    by_p = st.session_state.get("_refs_pexels_by_id") or {}
    by_u = st.session_state.get("_refs_unsplash_by_id") or {}
    by_a = st.session_state.get("_refs_art_chicago_by_id") or {}
    by_m = st.session_state.get("_refs_met_by_id") or {}
    by_w = st.session_state.get("_refs_wiki_by_id") or {}
    by_g = st.session_state.get("_refs_google_arts_by_id") or {}
    added = 0
    skipped_dup = 0
    failed = 0

    def _sort_ref_ids(ids):
        def _key(x):
            xs = str(x)
            return (0, int(xs)) if xs.isdigit() else (1, xs)

        return sorted(ids, key=_key)

    for sid in _sort_ref_ids(p_ids):
        ph = by_p.get(str(sid))
        if not ph:
            failed += 1
            continue
        url = _refs_pexels_high_res_url(ph)
        if not url:
            failed += 1
            continue
        if url in existing_urls:
            skipped_dup += 1
            continue
        path = _refs_download_url_to_downloads(url, f"pexels_{sid}.jpg")
        if not path:
            failed += 1
            continue
        if path in existing_paths:
            skipped_dup += 1
            continue
        cap = (ph.get("alt") or ph.get("photographer") or f"Pexels {sid}")[:120]
        prov = _refs_pexels_provenance(ph, sid, url)
        item = {
            "image_path": path,
            "url": url,
            "src": url,
            "caption": cap,
            "prompt": "",
            "specs": {},
            "project_id": st.session_state.get("active_project_id"),
            "created_at": datetime.now().isoformat(),
            "reference_provenance": prov,
            "original_width": prov.get("original_width"),
            "original_height": prov.get("original_height"),
        }
        st.session_state.sb_active_images.append(item)
        existing_paths.add(path)
        existing_urls.add(url)
        added += 1

    for sid in _sort_ref_ids(u_ids):
        uc = by_u.get(str(sid))
        if not uc:
            failed += 1
            continue
        full_url = uc["full_url"]
        if full_url in existing_urls:
            skipped_dup += 1
            continue
        dep = uc.get("download_endpoint")
        if dep and UNSPLASH_API_KEY:
            try:
                requests.get(
                    dep,
                    headers={"Authorization": f"Client-ID {UNSPLASH_API_KEY}"},
                    timeout=15,
                )
            except Exception:
                pass
        path = _refs_download_url_to_downloads(full_url, f"unsplash_{sid}.jpg")
        if not path:
            failed += 1
            continue
        if path in existing_paths:
            skipped_dup += 1
            continue
        un = uc.get("user_name") or "Photographer"
        prov = _refs_unsplash_provenance(uc, sid, full_url)
        item = {
            "image_path": path,
            "url": full_url,
            "src": full_url,
            "caption": f"{un} · Unsplash"[:120],
            "prompt": "",
            "specs": {},
            "project_id": st.session_state.get("active_project_id"),
            "created_at": datetime.now().isoformat(),
            "reference_provenance": prov,
            "original_width": prov.get("original_width"),
            "original_height": prov.get("original_height"),
        }
        st.session_state.sb_active_images.append(item)
        existing_paths.add(path)
        existing_urls.add(full_url)
        added += 1

    for sid in _sort_ref_ids(a_ids):
        rec = by_a.get(str(sid))
        if not rec:
            failed += 1
            continue
        url = _refs_art_chicago_iiif_url(rec)
        if not url:
            failed += 1
            continue
        if url in existing_urls:
            skipped_dup += 1
            continue
        path = _refs_download_url_to_downloads(url, f"artic_{sid}.jpg")
        if not path:
            failed += 1
            continue
        if path in existing_paths:
            skipped_dup += 1
            continue
        title = rec.get("title") or "Untitled"
        artist = rec.get("artist_display") or "Unknown artist"
        cap = f"{title} — {artist}"[:120]
        prov = _refs_art_chicago_provenance(rec, sid, url)
        item = {
            "image_path": path,
            "url": url,
            "src": url,
            "caption": cap,
            "prompt": "",
            "specs": {},
            "project_id": st.session_state.get("active_project_id"),
            "created_at": datetime.now().isoformat(),
            "reference_provenance": prov,
            "original_width": prov.get("original_width"),
            "original_height": prov.get("original_height"),
        }
        st.session_state.sb_active_images.append(item)
        existing_paths.add(path)
        existing_urls.add(url)
        added += 1

    for sid in _sort_ref_ids(m_ids):
        rec = by_m.get(str(sid))
        if not rec:
            failed += 1
            continue
        url = rec.get("full_url") or rec.get("image_url")
        if not url:
            failed += 1
            continue
        if url in existing_urls:
            skipped_dup += 1
            continue
        path = _refs_download_url_to_downloads(url, f"met_{sid}.jpg")
        if not path:
            failed += 1
            continue
        if path in existing_paths:
            skipped_dup += 1
            continue
        title = rec.get("title") or "Untitled"
        artist = rec.get("artist_display") or "Unknown"
        cap = f"{title} — {artist}"[:120]
        prov = {
            "vendor": "met",
            "api_asset_id": str(sid),
            "high_res_url": url,
            "title": title,
            "artist_display": artist,
        }
        item = {
            "image_path": path,
            "url": url,
            "src": url,
            "caption": cap,
            "prompt": "",
            "specs": {},
            "project_id": st.session_state.get("active_project_id"),
            "created_at": datetime.now().isoformat(),
            "reference_provenance": prov,
            "original_width": rec.get("original_width"),
            "original_height": rec.get("original_height"),
        }
        st.session_state.sb_active_images.append(item)
        existing_paths.add(path)
        existing_urls.add(url)
        added += 1

    for sid in _sort_ref_ids(w_ids):
        rec = by_w.get(str(sid))
        if not rec:
            failed += 1
            continue
        url = rec.get("full_url") or rec.get("image_url")
        if not url:
            failed += 1
            continue
        if url in existing_urls:
            skipped_dup += 1
            continue
        path = _refs_download_url_to_downloads(url, f"wiki_{sid}.jpg")
        if not path:
            failed += 1
            continue
        if path in existing_paths:
            skipped_dup += 1
            continue
        title = rec.get("title") or "Wikimedia"
        artist = rec.get("artist_display") or "Unknown"
        cap = f"{title} — {artist}"[:120]
        prov = {
            "vendor": "wikimedia",
            "api_asset_id": str(sid),
            "high_res_url": url,
            "title": title,
            "artist_display": artist,
        }
        item = {
            "image_path": path,
            "url": url,
            "src": url,
            "caption": cap,
            "prompt": "",
            "specs": {},
            "project_id": st.session_state.get("active_project_id"),
            "created_at": datetime.now().isoformat(),
            "reference_provenance": prov,
            "original_width": rec.get("original_width"),
            "original_height": rec.get("original_height"),
        }
        st.session_state.sb_active_images.append(item)
        existing_paths.add(path)
        existing_urls.add(url)
        added += 1

    for sid in _sort_ref_ids(g_ids):
        rec = by_g.get(str(sid))
        if not rec:
            failed += 1
            continue
        img_url = (rec.get("image_url") or "").strip()
        if not img_url or not (img_url.startswith("http://") or img_url.startswith("https://")):
            failed += 1
            continue
        if img_url in existing_urls:
            skipped_dup += 1
            continue
        path = _refs_download_url_to_downloads(img_url, f"google_arts_{sid}.jpg")
        if not path:
            failed += 1
            continue
        if path in existing_paths:
            skipped_dup += 1
            continue
        title = (rec.get("title") or "Arts & Culture")[:120]
        cap = f"{title} · Google Arts & Culture"[:120]
        page_url = rec.get("page_url") or ""
        prov = {
            "vendor": "google_arts",
            "api_asset_id": str(sid),
            "image_url": img_url,
            "page_url": page_url,
            "title": rec.get("title", ""),
        }
        item = {
            "image_path": path,
            "url": img_url,
            "src": img_url,
            "caption": cap,
            "prompt": "",
            "specs": {},
            "project_id": st.session_state.get("active_project_id"),
            "created_at": datetime.now().isoformat(),
            "reference_provenance": prov,
            "original_width": None,
            "original_height": None,
        }
        st.session_state.sb_active_images.append(item)
        existing_paths.add(path)
        existing_urls.add(img_url)
        added += 1

    st.session_state.refs_selected_pexels = set()
    st.session_state.refs_selected_unsplash = set()
    st.session_state.refs_selected_art_chicago = set()
    st.session_state.refs_selected_met = set()
    st.session_state.refs_selected_wiki = set()
    st.session_state.refs_selected_google_arts = set()
    st.session_state.selected_images = {}
    _autosave_storyboard_snapshot()
    return added, skipped_dup, failed


def _refs_send_selected_to_assets():
    """Download selected reference images and add copies to Assets (same pattern as Gallery → ASSETS)."""
    p_ids = set(st.session_state.get("refs_selected_pexels") or set())
    u_ids = set(st.session_state.get("refs_selected_unsplash") or set())
    a_ids = set(st.session_state.get("refs_selected_art_chicago") or set())
    m_ids = set(st.session_state.get("refs_selected_met") or set())
    w_ids = set(st.session_state.get("refs_selected_wiki") or set())
    g_ids = set(st.session_state.get("refs_selected_google_arts") or set())
    if not p_ids and not u_ids and not a_ids and not m_ids and not w_ids and not g_ids:
        return 0, 0

    by_p = st.session_state.get("_refs_pexels_by_id") or {}
    by_u = st.session_state.get("_refs_unsplash_by_id") or {}
    by_a = st.session_state.get("_refs_art_chicago_by_id") or {}
    by_m = st.session_state.get("_refs_met_by_id") or {}
    by_w = st.session_state.get("_refs_wiki_by_id") or {}
    by_g = st.session_state.get("_refs_google_arts_by_id") or {}
    saved = 0
    failed = 0

    def _sort_ref_ids(ids):
        def _key(x):
            xs = str(x)
            return (0, int(xs)) if xs.isdigit() else (1, xs)

        return sorted(ids, key=_key)

    for sid in _sort_ref_ids(p_ids):
        ph = by_p.get(str(sid))
        if not ph:
            failed += 1
            continue
        url = _refs_pexels_high_res_url(ph)
        if not url:
            failed += 1
            continue
        path = _refs_download_url_to_downloads(url, f"pexels_{sid}.jpg")
        if not path:
            failed += 1
            continue
        prov = _refs_pexels_provenance(ph, sid, url)
        result = add_to_assets(
            source_path=path,
            original_name=f"pexels_{sid}.jpg",
            provenance=prov,
        )
        if result:
            saved += 1
        else:
            failed += 1

    for sid in _sort_ref_ids(u_ids):
        uc = by_u.get(str(sid))
        if not uc:
            failed += 1
            continue
        full_url = uc["full_url"]
        dep = uc.get("download_endpoint")
        if dep and UNSPLASH_API_KEY:
            try:
                requests.get(
                    dep,
                    headers={"Authorization": f"Client-ID {UNSPLASH_API_KEY}"},
                    timeout=15,
                )
            except Exception:
                pass
        path = _refs_download_url_to_downloads(full_url, f"unsplash_{sid}.jpg")
        if not path:
            failed += 1
            continue
        prov = _refs_unsplash_provenance(uc, sid, full_url)
        result = add_to_assets(
            source_path=path,
            original_name=f"unsplash_{sid}.jpg",
            provenance=prov,
        )
        if result:
            saved += 1
        else:
            failed += 1

    for sid in _sort_ref_ids(a_ids):
        rec = by_a.get(str(sid))
        if not rec:
            failed += 1
            continue
        url = _refs_art_chicago_iiif_url(rec)
        if not url:
            failed += 1
            continue
        path = _refs_download_url_to_downloads(url, f"artic_{sid}.jpg")
        if not path:
            failed += 1
            continue
        prov = _refs_art_chicago_provenance(rec, sid, url)
        result = add_to_assets(
            source_path=path,
            original_name=f"artic_{sid}.jpg",
            provenance=prov,
        )
        if result:
            saved += 1
        else:
            failed += 1

    for sid in _sort_ref_ids(m_ids):
        rec = by_m.get(str(sid))
        if not rec:
            failed += 1
            continue
        url = rec.get("full_url") or rec.get("image_url")
        if not url:
            failed += 1
            continue
        path = _refs_download_url_to_downloads(url, f"met_{sid}.jpg")
        if not path:
            failed += 1
            continue
        result = add_to_assets(
            source_path=path,
            original_name=f"met_{sid}.jpg",
            provenance={
                "source": "met",
                "id": str(sid),
                "title": rec.get("title", ""),
                "artist": rec.get("artist_display", ""),
                "url": url,
            },
        )
        if result:
            saved += 1
        else:
            failed += 1

    for sid in _sort_ref_ids(w_ids):
        rec = by_w.get(str(sid))
        if not rec:
            failed += 1
            continue
        url = rec.get("full_url") or rec.get("image_url")
        if not url:
            failed += 1
            continue
        path = _refs_download_url_to_downloads(url, f"wiki_{sid}.jpg")
        if not path:
            failed += 1
            continue
        result = add_to_assets(
            source_path=path,
            original_name=f"wiki_{sid}.jpg",
            provenance={"source": "wikimedia", "id": str(sid), "title": rec.get("title", ""), "artist": rec.get("artist_display", ""), "url": url},
        )
        if result:
            saved += 1
        else:
            failed += 1

    for sid in _sort_ref_ids(g_ids):
        rec = by_g.get(str(sid))
        if not rec:
            failed += 1
            continue
        img_url = (rec.get("image_url") or "").strip()
        if not img_url or not (img_url.startswith("http://") or img_url.startswith("https://")):
            failed += 1
            continue
        path = _refs_download_url_to_downloads(img_url, f"google_arts_{sid}.jpg")
        if not path:
            failed += 1
            continue
        page_url = rec.get("page_url") or ""
        result = add_to_assets(
            source_path=path,
            original_name=f"google_arts_{sid}.jpg",
            provenance={
                "source": "google_arts",
                "id": str(sid),
                "title": rec.get("title", ""),
                "page_url": page_url,
                "image_url": img_url,
            },
        )
        if result:
            saved += 1
        else:
            failed += 1

    st.session_state.refs_selected_pexels = set()
    st.session_state.refs_selected_unsplash = set()
    st.session_state.refs_selected_art_chicago = set()
    st.session_state.refs_selected_met = set()
    st.session_state.refs_selected_wiki = set()
    st.session_state.refs_selected_google_arts = set()
    st.session_state.selected_images = {}
    return saved, failed


def render_references_page():
    """Render the References page (Pexels/Unsplash/Wikimedia/Met/Google Arts)."""
    # ── Navigation (same active_page routing pattern) ──
    if "refs_nav" not in st.session_state:
        st.session_state.refs_nav = "References"
    elif st.session_state.refs_nav not in ("Console", "Projects", "Gallery", "Assets", "References", "Storyboard", "Editing"):
        st.session_state.refs_nav = "References"

    def _on_refs_nav_change():
        val = st.session_state.refs_nav
        if val == "Console":
            st.session_state.refs_nav = "References"
            st.session_state["_console_was_away"] = True
            st.session_state.active_page = "console"
        elif val == "Projects":
            st.session_state.refs_nav = "References"
            st.session_state.active_page = "projects"
        elif val == "Gallery":
            st.session_state.refs_nav = "References"
            st.session_state.active_page = "gallery"
        elif val == "Assets":
            st.session_state.refs_nav = "References"
            st.session_state.active_page = "assets"
        elif val == "Storyboard":
            st.session_state.refs_nav = "References"
            st.session_state.active_page = "storyboard"
        elif val == "Editing":
            st.session_state.refs_nav = "References"
            st.session_state.active_page = "editing"

    _refs_nav_col, _refs_proj_col = st.columns([4, 1])
    with _refs_nav_col:
        st.radio(
            "refs_nav_label",
            ["Console", "Projects", "Gallery", "Assets", "References", "Storyboard", "Editing"],
            horizontal=True,
            key="refs_nav",
            on_change=_on_refs_nav_change,
            label_visibility="collapsed",
        )
    with _refs_proj_col:
        _render_project_name_inline_right()

    st.markdown("### REFERENCES")
    st.caption("Reference materials for prompt building in the current project.")

    src_tab1, src_tab2, src_tab3, src_tab4, src_tab5, src_tab6, src_tab7, src_tab8, src_tab9 = st.tabs(
        [
            "PEXELS",
            "UNSPLASH",
            "Art Chicago",
            "The Met",
            "Pexels Video",
            "Pixabay Video",
            "Coverr Video",
            "Google Arts",
            "Wikimedia",
        ]
    )

    with src_tab1:
        pexels_query = st.text_input(
            "Search reference images",
            placeholder="Type a keyword (e.g. cyberpunk city, cinematic portrait...)",
            key="pexels_query",
        )
        pexels_per_page = st.slider(
            "Results", min_value=3, max_value=30, value=12, step=3, key="pexels_per_page"
        )

        _refs_n_sel = (
            len(st.session_state.get("refs_selected_pexels") or set())
            + len(st.session_state.get("refs_selected_unsplash") or set())
            + len(st.session_state.get("refs_selected_art_chicago") or set())
        )
        if _refs_n_sel > 0:
            with st.container(border=True):
                st.markdown(
                    '<div style="height:1px;background:linear-gradient(90deg,transparent,rgba(245,245,220,0.4),transparent);'
                    'margin:0 0 0.65rem;"></div>'
                    f'<p style="margin:0 0 12px;color:#9E9E8A;font-size:0.74rem;font-family:\'Open Sans\',sans-serif;">'
                    f'<span style="color:var(--refs-cream, #F5F5DC);font-weight:700;">{_refs_n_sel}</span> '
                    f"image(s) selected — send to workspace</p>",
                    unsafe_allow_html=True,
                )
                _n_pex_tab = len(st.session_state.get("refs_selected_pexels") or set())
                col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1], gap="small")
                with col_btn1:
                    if st.button(
                        "STORYBOARD",
                        key="refs_bar_storyboard_btn_pexels",
                        width="stretch",
                    ):
                        _a, _dup, _fail = _refs_send_selected_to_storyboard()
                        _parts = []
                        if _a:
                            _parts.append(f"Added {_a} image(s) to Storyboard")
                        if _dup:
                            _parts.append(f"{_dup} duplicate(s) skipped")
                        if _fail:
                            _parts.append(f"{_fail} failed (refresh search or check network)")
                        st.toast(
                            ". ".join(_parts)
                            if _parts
                            else "Nothing added — repeat the search, then select again."
                        )
                        st.rerun()
                with col_btn2:
                    if st.button(
                        "ASSET",
                        key="refs_bar_asset_btn_pexels",
                        width="stretch",
                    ):
                        _sv, _fl = _refs_send_selected_to_assets()
                        if _sv:
                            st.toast(f"Saved {_sv} image(s) to Assets" + (f" ({_fl} failed)" if _fl else ""))
                        elif _fl:
                            st.toast(f"Could not save ({_fl} failed). Check network or search again.")
                        else:
                            st.toast("Nothing saved — repeat the search, then select again.")
                        st.rerun()
                with col_btn3:
                    if st.button(
                        "CLEAR",
                        key="refs_pexels_clear_sel",
                        width="stretch",
                        disabled=(_n_pex_tab == 0),
                    ):
                        st.session_state.refs_selected_pexels = set()
                        if "selected_images" in st.session_state:
                            for _k in list(st.session_state.selected_images.keys()):
                                if str(_k).startswith("pexels:"):
                                    del st.session_state.selected_images[_k]
                        st.rerun()

        if pexels_query and str(pexels_query).strip():
            pexels_api_key = PEXELS_API_KEY
            if not pexels_api_key:
                st.error("PEXELS_API_KEY is missing. Add it to environment variables to enable image search.")
            else:
                try:
                    resp = requests.get(
                        "https://api.pexels.com/v1/search",
                        headers={"Authorization": pexels_api_key},
                        params={"query": pexels_query.strip(), "per_page": int(pexels_per_page), "page": 1},
                        timeout=15,
                    )
                    if resp.status_code != 200:
                        st.error(f"Pexels API error ({resp.status_code}).")
                    else:
                        payload = resp.json() or {}
                        photos = payload.get("photos") or []
                        if not photos:
                            st.warning("No results found for your search term.")
                        else:
                            st.session_state["_refs_pexels_by_id"] = {
                                str(ph.get("id")): ph
                                for ph in photos
                                if ph.get("id") is not None
                            }
                            _pex_sig = pexels_query.strip()
                            if st.session_state.get("_refs_pexels_query_sig") != _pex_sig:
                                st.session_state._refs_pexels_query_sig = _pex_sig
                                st.session_state.refs_selected_pexels = set()
                                if "selected_images" in st.session_state:
                                    for _k in list(st.session_state.selected_images.keys()):
                                        if str(_k).startswith("pexels:"):
                                            del st.session_state.selected_images[_k]

                            def _refs_pex_bridge_cb():
                                _refs_sel_bridge_on_change("refs_pexels_sel_bridge", "pexels")

                            st.text_input(
                                "refs_pexels_sel_bridge",
                                key="refs_pexels_sel_bridge",
                                on_change=_refs_pex_bridge_cb,
                                label_visibility="collapsed",
                            )
                            _n_pex = len(st.session_state.refs_selected_pexels)
                            _pex_ab1, _pex_ab2 = st.columns([2, 1])
                            with _pex_ab1:
                                st.markdown(
                                    f'<p style="color:#FFEB3B;font-size:0.8rem;font-weight:600;'
                                    f'font-family:Open Sans,sans-serif;margin:4px 0 8px;">'
                                    f"{_n_pex} selected</p>",
                                    unsafe_allow_html=True,
                                )
                            # CLEAR moved to the top STORYBOARD/ASSET/CLEAR dock row.

                            _pex_gal_exp = (
                                '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" '
                                'xmlns="http://www.w3.org/2000/svg">'
                                '<path d="M1 4.5V1H4.5M7.5 1H11V4.5M11 7.5V11H7.5M4.5 11H1V7.5" '
                                'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
                                'stroke-linejoin="round"/></svg>'
                            )
                            _pex_cards_html = ""
                            _pex_n = 0
                            for _i, ph in enumerate(photos):
                                _pid = ph.get("id")
                                src = ph.get("src") or {}
                                hi_res = src.get("large2x") or src.get("large") or src.get("original")
                                if not hi_res or _pid is None:
                                    continue
                                _pex_n += 1
                                _sid = str(_pid)
                                _safe_src = (
                                    str(hi_res)
                                    .replace("&", "&amp;")
                                    .replace('"', "&quot;")
                                    .replace("<", "&lt;")
                                )
                                _iw = _ih = None
                                try:
                                    _iw = int(ph.get("width") or 0)
                                    _ih = int(ph.get("height") or 0)
                                except (TypeError, ValueError):
                                    _iw = _ih = 0
                                _pex_wh_attr = (
                                    f' width="{_iw}" height="{_ih}"'
                                    if _iw and _ih
                                    else ""
                                )
                                _zoom_u = (
                                    src.get("original")
                                    or src.get("large2x")
                                    or src.get("large")
                                    or hi_res
                                )
                                _zoom_attr = (
                                    str(_zoom_u)
                                    .replace("&", "&amp;")
                                    .replace('"', "&quot;")
                                    .replace("'", "&#39;")
                                )
                                _is_sel = _sid in st.session_state.refs_selected_pexels
                                _wrap_sel = " ref-stock-selected" if _is_sel else ""
                                _wrap_nd = (
                                    " ref-stock-no-dims"
                                    if not (_iw and _ih)
                                    else ""
                                )
                                _ph_style = _refs_placeholder_style_attr(ph.get("avg_color"))
                                _sel_chk = (
                                    '<div class="ref-stock-sel-check">&#10003;</div>'
                                    if _is_sel
                                    else ""
                                )
                                _pex_cards_html += f"""<div class="gal-card ref-stock-card" onclick="refsPexelsSel('{_sid}')">
<div class="gal-badge">{_pex_n}</div>
<div class="ref-stock-img-wrap{_wrap_sel}{_wrap_nd}"{_ph_style}>
<div class="ref-stock-ph" aria-hidden="true"></div>
<div class="gal-expand" data-zoom="{_zoom_attr}" onclick="event.stopPropagation();event.preventDefault();var z=this.getAttribute('data-zoom');if(z)window.open(z,'_blank','noopener,noreferrer');" title="Open full size">{_pex_gal_exp}</div>
{_sel_chk}
<img class="ref-stock-img" src="{_safe_src}" alt="" loading="lazy" decoding="async"{_pex_wh_attr} draggable="false"/>
</div>
<div class="gal-caption">Pexels</div>
</div>"""

                            if not _pex_cards_html:
                                st.warning("No preview URLs in results.")
                            else:
                                _pex_h = min(5600, 360 + _pex_n * 280)
                                _pex_html = (
                                    _REFS_STOCK_IFRAME_CSS
                                    + f'<div class="ref-stock-masonry">{_pex_cards_html}</div>'
                                    + """
<script>
function refsPexelsSel(id) {
var inp = window.parent.document.querySelector('input[aria-label="refs_pexels_sel_bridge"]');
if (!inp) return;
var ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
var payload = String(id) + '|' + Date.now();
ns.call(inp, payload);
inp.dispatchEvent(new Event('input', {bubbles:true}));
inp.dispatchEvent(new Event('change', {bubbles:true}));
try { inp.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertFromPaste', data: payload })); } catch (e) {}
try { inp.focus({ preventScroll: true }); } catch (e2) {}
try { inp.blur(); } catch (e3) {}
}
</script>"""
                                )
                                components.html(_pex_html, height=_pex_h, scrolling=True)
                except requests.RequestException as e:
                    st.error(f"Failed to contact Pexels API: {e}")

    with src_tab2:
        unsplash_query = st.text_input(
            "Search Unsplash",
            placeholder="Type a keyword (e.g. cyberpunk city, cinematic portrait...)",
            key="unsplash_query",
        )
        unsplash_per_page = st.slider(
            "Results", min_value=3, max_value=30, value=12, step=3, key="unsplash_per_page"
        )

        _refs_n_sel = (
            len(st.session_state.get("refs_selected_pexels") or set())
            + len(st.session_state.get("refs_selected_unsplash") or set())
            + len(st.session_state.get("refs_selected_art_chicago") or set())
        )
        if _refs_n_sel > 0:
            with st.container(border=True):
                st.markdown(
                    '<div style="height:1px;background:linear-gradient(90deg,transparent,rgba(245,245,220,0.4),transparent);'
                    'margin:0 0 0.65rem;"></div>'
                    f'<p style="margin:0 0 12px;color:#9E9E8A;font-size:0.74rem;font-family:\'Open Sans\',sans-serif;">'
                    f'<span style="color:var(--refs-cream, #F5F5DC);font-weight:700;">{_refs_n_sel}</span> '
                    f"image(s) selected — send to workspace</p>",
                    unsafe_allow_html=True,
                )
                _n_uns_tab = len(st.session_state.get("refs_selected_unsplash") or set())
                col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1], gap="small")
                with col_btn1:
                    if st.button(
                        "STORYBOARD",
                        key="refs_bar_storyboard_btn_unsplash",
                        width="stretch",
                    ):
                        _a, _dup, _fail = _refs_send_selected_to_storyboard()
                        _parts = []
                        if _a:
                            _parts.append(f"Added {_a} image(s) to Storyboard")
                        if _dup:
                            _parts.append(f"{_dup} duplicate(s) skipped")
                        if _fail:
                            _parts.append(f"{_fail} failed (refresh search or check network)")
                        st.toast(
                            ". ".join(_parts)
                            if _parts
                            else "Nothing added — repeat the search, then select again."
                        )
                        st.rerun()
                with col_btn2:
                    if st.button(
                        "ASSET",
                        key="refs_bar_asset_btn_unsplash",
                        width="stretch",
                    ):
                        _sv, _fl = _refs_send_selected_to_assets()
                        if _sv:
                            st.toast(f"Saved {_sv} image(s) to Assets" + (f" ({_fl} failed)" if _fl else ""))
                        elif _fl:
                            st.toast(f"Could not save ({_fl} failed). Check network or search again.")
                        else:
                            st.toast("Nothing saved — repeat the search, then select again.")
                        st.rerun()
                with col_btn3:
                    if st.button(
                        "CLEAR",
                        key="refs_unsplash_clear_sel",
                        width="stretch",
                        disabled=(_n_uns_tab == 0),
                    ):
                        st.session_state.refs_selected_unsplash = set()
                        if "selected_images" in st.session_state:
                            for _k in list(st.session_state.selected_images.keys()):
                                if str(_k).startswith("unsplash:"):
                                    del st.session_state.selected_images[_k]
                        st.rerun()

        if unsplash_query and str(unsplash_query).strip():
            query = unsplash_query.strip()
            if not UNSPLASH_API_KEY:
                st.error(
                    "Unsplash access key is missing. Set UNSPLASH_ACCESS_KEY or UNSPLASH_API_KEY in your environment."
                )
            else:
                try:
                    resp = requests.get(
                        "https://api.unsplash.com/search/photos",
                        params={"query": query, "per_page": int(unsplash_per_page)},
                        headers={"Authorization": f"Client-ID {UNSPLASH_API_KEY}"},
                        timeout=15,
                    )
                    if resp.status_code != 200:
                        st.error(f"Unsplash API error ({resp.status_code}).")
                    else:
                        payload = resp.json() or {}
                        results = payload.get("results") or []
                        if not results:
                            st.warning("No results found for your search term.")
                        else:
                            _uns_cards = []
                            for _ui, photo in enumerate(results):
                                urls = photo.get("urls") or {}
                                user = photo.get("user") or {}
                                links = photo.get("links") or {}
                                user_links = user.get("links") or {}
                                img_url = urls.get("regular")
                                full_url = urls.get("full")
                                user_name = user.get("name") or "Photographer"
                                download_endpoint = links.get("download_location")
                                user_html = user_links.get("html")
                                if not img_url or not full_url:
                                    continue
                                _uns_cards.append(
                                    {
                                        "photo": photo,
                                        "img_url": img_url,
                                        "full_url": full_url,
                                        "user_name": user_name,
                                        "download_endpoint": download_endpoint,
                                        "user_link": (
                                            f"{user_html}?utm_source=ai_dop_console&utm_medium=referral"
                                            if user_html
                                            else "https://unsplash.com/?utm_source=ai_dop_console&utm_medium=referral"
                                        ),
                                        "unsplash_link": "https://unsplash.com/?utm_source=ai_dop_console&utm_medium=referral",
                                    }
                                )

                            if not _uns_cards:
                                st.warning("No preview URLs in results.")
                            else:
                                st.session_state["_refs_unsplash_by_id"] = {
                                    str(uc["photo"].get("id")): uc
                                    for uc in _uns_cards
                                    if uc.get("photo") and uc["photo"].get("id") is not None
                                }
                                _uns_sig = query
                                if st.session_state.get("_refs_unsplash_query_sig") != _uns_sig:
                                    st.session_state._refs_unsplash_query_sig = _uns_sig
                                    st.session_state.refs_selected_unsplash = set()
                                    if "selected_images" in st.session_state:
                                        for _k in list(st.session_state.selected_images.keys()):
                                            if str(_k).startswith("unsplash:"):
                                                del st.session_state.selected_images[_k]

                                def _refs_uns_bridge_cb():
                                    _refs_sel_bridge_on_change("refs_unsplash_sel_bridge", "unsplash")

                                st.text_input(
                                    "refs_unsplash_sel_bridge",
                                    key="refs_unsplash_sel_bridge",
                                    on_change=_refs_uns_bridge_cb,
                                    label_visibility="collapsed",
                                )
                                _n_uns = len(st.session_state.refs_selected_unsplash)
                                _uns_ab1, _uns_ab2 = st.columns([2, 1])
                                with _uns_ab1:
                                    st.markdown(
                                        f'<p style="color:#FFEB3B;font-size:0.8rem;font-weight:600;'
                                        f'font-family:Open Sans,sans-serif;margin:4px 0 8px;">'
                                        f"{_n_uns} selected</p>",
                                        unsafe_allow_html=True,
                                    )
                                # CLEAR moved to the top STORYBOARD/ASSET/CLEAR dock row.

                                _uns_gal_exp = (
                                    '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" '
                                    'xmlns="http://www.w3.org/2000/svg">'
                                    '<path d="M1 4.5V1H4.5M7.5 1H11V4.5M11 7.5V11H7.5M4.5 11H1V7.5" '
                                    'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
                                    'stroke-linejoin="round"/></svg>'
                                )
                                _uns_cards_html = ""
                                for _j, uc in enumerate(_uns_cards):
                                    photo = uc["photo"]
                                    _pid = photo.get("id", _j)
                                    _sid = str(_pid)
                                    _safe_src = (
                                        str(uc["img_url"])
                                        .replace("&", "&amp;")
                                        .replace('"', "&quot;")
                                        .replace("<", "&lt;")
                                    )
                                    _uw = _uh = None
                                    try:
                                        _uw = int(photo.get("width") or 0)
                                        _uh = int(photo.get("height") or 0)
                                    except (TypeError, ValueError):
                                        _uw = _uh = 0
                                    _uns_wh_attr = (
                                        f' width="{_uw}" height="{_uh}"'
                                        if _uw and _uh
                                        else ""
                                    )
                                    _full_u = uc["full_url"]
                                    _zoom_attr_u = (
                                        str(_full_u)
                                        .replace("&", "&amp;")
                                        .replace('"', "&quot;")
                                        .replace("'", "&#39;")
                                    )
                                    _cap_line = _html_stdlib.escape(
                                        f"{(uc['user_name'] or '')[:28]} — Unsplash"[:40]
                                    )
                                    _is_us = _sid in st.session_state.refs_selected_unsplash
                                    _wrap_sel_u = " ref-stock-selected" if _is_us else ""
                                    _wrap_nd_u = (
                                        " ref-stock-no-dims"
                                        if not (_uw and _uh)
                                        else ""
                                    )
                                    _ph_style_u = _refs_placeholder_style_attr(
                                        photo.get("color")
                                    )
                                    _sel_chk_u = (
                                        '<div class="ref-stock-sel-check">&#10003;</div>'
                                        if _is_us
                                        else ""
                                    )
                                    _uns_cards_html += f"""<div class="gal-card ref-stock-card" onclick="refsUnsplashSel('{_sid}')">
<div class="gal-badge">{_j + 1}</div>
<div class="ref-stock-img-wrap{_wrap_sel_u}{_wrap_nd_u}"{_ph_style_u}>
<div class="ref-stock-ph" aria-hidden="true"></div>
<div class="gal-expand" data-zoom="{_zoom_attr_u}" onclick="event.stopPropagation();event.preventDefault();var z=this.getAttribute('data-zoom');if(z)window.open(z,'_blank','noopener,noreferrer');" title="Open full size">{_uns_gal_exp}</div>
{_sel_chk_u}
<img class="ref-stock-img" src="{_safe_src}" alt="" loading="lazy" decoding="async"{_uns_wh_attr} draggable="false"/>
</div>
<div class="gal-caption">{_cap_line}</div>
</div>"""

                                _uns_n = len(_uns_cards)
                                _uns_h = min(5600, 360 + _uns_n * 280)
                                _uns_html = (
                                    _REFS_STOCK_IFRAME_CSS
                                    + f'<div class="ref-stock-masonry">{_uns_cards_html}</div>'
                                    + """
<script>
function refsUnsplashSel(id) {
var inp = window.parent.document.querySelector('input[aria-label="refs_unsplash_sel_bridge"]');
if (!inp) return;
var ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
var payload = String(id) + '|' + Date.now();
ns.call(inp, payload);
inp.dispatchEvent(new Event('input', {bubbles:true}));
inp.dispatchEvent(new Event('change', {bubbles:true}));
try { inp.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertFromPaste', data: payload })); } catch (e) {}
try { inp.focus({ preventScroll: true }); } catch (e2) {}
try { inp.blur(); } catch (e3) {}
}
</script>"""
                                )
                                components.html(_uns_html, height=_uns_h, scrolling=True)

                                for _ur in range((len(_uns_cards) + 2) // 3):
                                    _u_cols = st.columns(3)
                                    for _uc in range(3):
                                        _ux = _ur * 3 + _uc
                                        if _ux >= len(_uns_cards):
                                            break
                                        uc = _uns_cards[_ux]
                                        photo = uc["photo"]
                                        user_name = uc["user_name"]
                                        full_url = uc["full_url"]
                                        download_endpoint = uc["download_endpoint"]
                                        user_link = uc["user_link"]
                                        unsplash_link = uc["unsplash_link"]
                                        _pid = photo.get("id", _ux)
                                        with _u_cols[_uc]:
                                            st.markdown(
                                                f"<p style='font-size:0.6rem; color:#7a7a6e; margin:2px 0 4px;'>"
                                                f"Photo by <a href='{_html_stdlib.escape(user_link)}' target='_blank' style='color:#BB86FC; text-decoration:none;'>{_html_stdlib.escape(user_name)}</a> on "
                                                f"<a href='{_html_stdlib.escape(unsplash_link)}' target='_blank' style='color:#BB86FC; text-decoration:none;'>Unsplash</a></p>",
                                                unsafe_allow_html=True,
                                            )
                                            if st.button(
                                                "SAVE TO ASSETS",
                                                key=f"unsplash_save_{_pid}",
                                                width="stretch",
                                            ):
                                                if download_endpoint:
                                                    try:
                                                        requests.get(
                                                            download_endpoint,
                                                            headers={
                                                                "Authorization": f"Client-ID {UNSPLASH_API_KEY}"
                                                            },
                                                            timeout=15,
                                                        )
                                                    except Exception:
                                                        pass
                                                try:
                                                    img_resp = requests.get(full_url, timeout=45)
                                                    img_resp.raise_for_status()
                                                    with tempfile.NamedTemporaryFile(
                                                        delete=False, suffix=".jpg"
                                                    ) as tmp:
                                                        tmp.write(img_resp.content)
                                                        tmp_path = tmp.name
                                                    try:
                                                        _us_prov = _refs_unsplash_provenance(
                                                            uc, str(_pid), full_url
                                                        )
                                                        result = add_to_assets(
                                                            source_path=tmp_path,
                                                            original_name=f"unsplash_{_pid}.jpg",
                                                            provenance=_us_prov,
                                                        )
                                                    finally:
                                                        if os.path.exists(tmp_path):
                                                            os.unlink(tmp_path)
                                                    if result:
                                                        st.toast(
                                                            f"Saved image by {user_name} to Assets!"
                                                        )
                                                except Exception:
                                                    st.error(
                                                        "Could not download or save this image."
                                                    )
                except requests.RequestException as e:
                    st.error(f"Failed to contact Unsplash API: {e}")

    with src_tab3:
        art_query = st.text_input(
            "Search Art Chicago",
            placeholder="Type a keyword (e.g. impressionism, portrait, landscape...)",
            key="art_chicago_query",
        )
        art_chicago_limit = st.slider(
            "Results",
            min_value=5,
            max_value=50,
            value=15,
            step=5,
            key="art_chicago_limit",
        )

        _refs_n_sel = (
            len(st.session_state.get("refs_selected_pexels") or set())
            + len(st.session_state.get("refs_selected_unsplash") or set())
            + len(st.session_state.get("refs_selected_art_chicago") or set())
        )
        if _refs_n_sel > 0:
            with st.container(border=True):
                st.markdown(
                    '<div style="height:1px;background:linear-gradient(90deg,transparent,rgba(245,245,220,0.4),transparent);'
                    'margin:0 0 0.65rem;"></div>'
                    f'<p style="margin:0 0 12px;color:#9E9E8A;font-size:0.74rem;font-family:\'Open Sans\',sans-serif;">'
                    f'<span style="color:var(--refs-cream, #F5F5DC);font-weight:700;">{_refs_n_sel}</span> '
                    f"image(s) selected — send to workspace</p>",
                    unsafe_allow_html=True,
                )
                _n_art_tab = len(st.session_state.get("refs_selected_art_chicago") or set())
                col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1], gap="small")
                with col_btn1:
                    if st.button(
                        "STORYBOARD",
                        key="refs_bar_storyboard_btn_art_chicago",
                        width="stretch",
                    ):
                        _a, _dup, _fail = _refs_send_selected_to_storyboard()
                        _parts = []
                        if _a:
                            _parts.append(f"Added {_a} image(s) to Storyboard")
                        if _dup:
                            _parts.append(f"{_dup} duplicate(s) skipped")
                        if _fail:
                            _parts.append(f"{_fail} failed (refresh search or check network)")
                        st.toast(
                            ". ".join(_parts)
                            if _parts
                            else "Nothing added — repeat the search, then select again."
                        )
                        st.rerun()
                with col_btn2:
                    if st.button(
                        "ASSET",
                        key="refs_bar_asset_btn_art_chicago",
                        width="stretch",
                    ):
                        _sv, _fl = _refs_send_selected_to_assets()
                        if _sv:
                            st.toast(f"Saved {_sv} image(s) to Assets" + (f" ({_fl} failed)" if _fl else ""))
                        elif _fl:
                            st.toast(f"Could not save ({_fl} failed). Check network or search again.")
                        else:
                            st.toast("Nothing saved — repeat the search, then select again.")
                        st.rerun()
                with col_btn3:
                    if st.button(
                        "CLEAR",
                        key="refs_art_clear_sel",
                        width="stretch",
                        disabled=(_n_art_tab == 0),
                    ):
                        st.session_state.refs_selected_art_chicago = set()
                        if "selected_images" in st.session_state:
                            for _k in list(st.session_state.selected_images.keys()):
                                if str(_k).startswith("art_chicago:"):
                                    del st.session_state.selected_images[_k]
                        st.rerun()

        if art_query and str(art_query).strip():
            _art_term = str(art_query).strip()
            try:
                resp = requests.get(
                    "https://api.artic.edu/api/v1/artworks/search",
                    params={
                        "q": _art_term,
                        "query[term][is_public_domain]": "true",
                        "fields": "id,title,image_id,artist_display",
                        "limit": int(art_chicago_limit),
                    },
                    timeout=20,
                )
                if resp.status_code != 200:
                    st.error(f"Art Chicago API error ({resp.status_code}).")
                else:
                    payload = resp.json() or {}
                    results = payload.get("data") or []

                    _art_by_id = {}
                    for r in results:
                        _rid = r.get("id")
                        image_id = r.get("image_id")
                        if _rid is None or not image_id:
                            continue
                        _art_by_id[str(_rid)] = {
                            "id": _rid,
                            "image_id": image_id,
                            "title": r.get("title"),
                            "artist_display": r.get("artist_display"),
                            "original_width": None,
                            "original_height": None,
                        }
                    st.session_state["_refs_art_chicago_by_id"] = _art_by_id

                    if st.session_state.get("_refs_art_chicago_query_sig") != _art_term:
                        st.session_state._refs_art_chicago_query_sig = _art_term
                        st.session_state.refs_selected_art_chicago = set()
                        if "selected_images" in st.session_state:
                            for _k in list(st.session_state.selected_images.keys()):
                                if str(_k).startswith("art_chicago:"):
                                    del st.session_state.selected_images[_k]

                    def _refs_art_bridge_cb():
                        _refs_sel_bridge_on_change("refs_art_sel_bridge", "art_chicago")

                    st.text_input(
                        "refs_art_sel_bridge",
                        key="refs_art_sel_bridge",
                        on_change=_refs_art_bridge_cb,
                        label_visibility="collapsed",
                    )

                    _art_gal_exp = (
                        '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" '
                        'xmlns="http://www.w3.org/2000/svg">'
                        '<path d="M1 4.5V1H4.5M7.5 1H11V4.5M11 7.5V11H7.5M4.5 11H1V7.5" '
                        'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
                        'stroke-linejoin="round"/></svg>'
                    )

                    _art_cards_html = ""
                    _art_n = 0
                    for _idx, r in enumerate(results):
                        _rid = r.get("id")
                        image_id = r.get("image_id")
                        if _rid is None or not image_id:
                            continue
                        _sid = str(_rid)
                        iiif_url = f"https://www.artic.edu/iiif/2/{image_id}/full/843,/0/default.jpg"
                        _safe_src = (
                            str(iiif_url)
                            .replace("&", "&amp;")
                            .replace('"', "&quot;")
                            .replace("<", "&lt;")
                        )
                        _zoom_attr = (
                            str(iiif_url)
                            .replace("&", "&amp;")
                            .replace('"', "&quot;")
                            .replace("'", "&#39;")
                        )
                        title = r.get("title") or "Untitled"
                        artist_display = r.get("artist_display") or "Unknown artist"
                        _cap_line = _html_stdlib.escape(
                            f"{title} — {artist_display}"[:140]
                        )
                        _is_sel = _sid in st.session_state.refs_selected_art_chicago
                        _wrap_sel = " ref-stock-selected" if _is_sel else ""
                        _wrap_nd = " ref-stock-no-dims"
                        _sel_chk = (
                            '<div class="ref-stock-sel-check">&#10003;</div>'
                            if _is_sel
                            else ""
                        )

                        _art_n += 1
                        _art_cards_html += f"""<div class="gal-card ref-stock-card" onclick="refsArtSel('{_sid}')">
<div class="gal-badge">{_art_n}</div>
<div class="ref-stock-img-wrap{_wrap_sel}{_wrap_nd}">
<div class="ref-stock-ph" aria-hidden="true"></div>
<div class="gal-expand" data-zoom="{_zoom_attr}" onclick="event.stopPropagation();event.preventDefault();var z=this.getAttribute('data-zoom');if(z)window.open(z,'_blank','noopener,noreferrer');" title="Open full size">{_art_gal_exp}</div>
{_sel_chk}
<img class="ref-stock-img" src="{_safe_src}" alt="" loading="lazy" decoding="async" draggable="false"/>
</div>
<div class="gal-caption">{_cap_line}</div>
</div>"""

                    if not _art_cards_html:
                        st.warning("No public-domain artworks with a valid image_id found.")
                    else:
                        _art_h = min(5600, 360 + _art_n * 280)
                        _art_html = (
                            _REFS_STOCK_IFRAME_CSS
                            + f'<div class="ref-stock-masonry">{_art_cards_html}</div>'
                            + """
<script>
function refsArtSel(id) {
var inp = window.parent.document.querySelector('input[aria-label="refs_art_sel_bridge"]');
if (!inp) return;
var ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
var payload = String(id) + '|' + Date.now();
ns.call(inp, payload);
inp.dispatchEvent(new Event('input', {bubbles:true}));
inp.dispatchEvent(new Event('change', {bubbles:true}));
try { inp.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertFromPaste', data: payload })); } catch (e) {}
try { inp.focus({ preventScroll: true }); } catch (e2) {}
try { inp.blur(); } catch (e3) {}
}
</script>"""
                        )
                        components.html(_art_html, height=_art_h, scrolling=True)

            except requests.RequestException as e:
                st.error(f"Failed to contact Art Chicago API: {e}")

    with src_tab4:
        met_query = st.text_input(
            "Search The Metropolitan Museum of Art",
            placeholder="Type a keyword (e.g. Rembrandt, chiaroscuro, landscape, portrait...)",
            key="met_query",
        )
        met_limit = st.slider(
            "Results",
            min_value=5,
            max_value=20,
            value=12,
            step=1,
            key="met_limit",
        )

        _refs_met_n_sel = len(st.session_state.get("refs_selected_met") or set())
        if _refs_met_n_sel > 0:
            with st.container(border=True):
                st.markdown(
                    '<div style="height:1px;background:linear-gradient(90deg,transparent,rgba(245,245,220,0.4),transparent);'
                    'margin:0 0 0.65rem;"></div>'
                    f'<p style="margin:0 0 12px;color:#9E9E8A;font-size:0.74rem;font-family:\'Open Sans\',sans-serif;">'
                    f'<span style="color:var(--refs-cream, #F5F5DC);font-weight:700;">{_refs_met_n_sel}</span> '
                    f"image(s) selected — send to workspace</p>",
                    unsafe_allow_html=True,
                )
                col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1], gap="small")
                with col_btn1:
                    if st.button(
                        "STORYBOARD",
                        key="refs_bar_storyboard_btn_met",
                        width="stretch",
                    ):
                        _a, _dup, _fail = _refs_send_selected_to_storyboard()
                        _parts = []
                        if _a:
                            _parts.append(f"Added {_a} image(s) to Storyboard")
                        if _dup:
                            _parts.append(f"{_dup} duplicate(s) skipped")
                        if _fail:
                            _parts.append(f"{_fail} failed")
                        st.toast(". ".join(_parts) if _parts else "Nothing added.")
                        st.rerun()
                with col_btn2:
                    if st.button(
                        "ASSET",
                        key="refs_bar_asset_btn_met",
                        width="stretch",
                    ):
                        _sv, _fl = _refs_send_selected_to_assets()
                        if _sv:
                            st.toast(f"Saved {_sv} image(s) to Assets" + (f" ({_fl} failed)" if _fl else ""))
                        elif _fl:
                            st.toast(f"Could not save ({_fl} failed).")
                        else:
                            st.toast("Nothing saved.")
                        st.rerun()
                with col_btn3:
                    if st.button(
                        "CLEAR",
                        key="refs_met_clear_sel",
                        width="stretch",
                        disabled=(_refs_met_n_sel == 0),
                    ):
                        st.session_state.refs_selected_met = set()
                        if "selected_images" in st.session_state:
                            for _k in list(st.session_state.selected_images.keys()):
                                if str(_k).startswith("met:"):
                                    del st.session_state.selected_images[_k]
                        st.rerun()

        if met_query and str(met_query).strip():
            _met_term = str(met_query).strip()
            try:
                # Step 1: search → get objectIDs
                resp = requests.get(
                    "https://collectionapi.metmuseum.org/public/collection/v1/search",
                    params={"q": _met_term, "hasImages": "true", "isPublicDomain": "true"},
                    timeout=20,
                )
                if resp.status_code != 200:
                    st.error(f"Met API error ({resp.status_code}).")
                else:
                    payload = resp.json() or {}
                    object_ids = (payload.get("objectIDs") or [])[: int(met_limit)]

                    if not object_ids:
                        st.warning("No public-domain artworks found.")
                    else:
                        # Step 2: fetch details for each object
                        _met_by_id = {}
                        with st.spinner(f"Loading {len(object_ids)} artworks from The Met..."):
                            for oid in object_ids:
                                try:
                                    obj_resp = requests.get(
                                        f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{oid}",
                                        timeout=10,
                                    )
                                    if obj_resp.status_code != 200:
                                        continue
                                    obj = obj_resp.json() or {}
                                    img_url = obj.get("primaryImageSmall") or obj.get("primaryImage") or ""
                                    if not img_url or not obj.get("isPublicDomain"):
                                        continue
                                    _sid = str(oid)
                                    title = obj.get("title") or "Untitled"
                                    artist = obj.get("artistDisplayName") or "Unknown"
                                    _met_by_id[_sid] = {
                                        "id": oid,
                                        "title": title,
                                        "artist_display": artist,
                                        "image_url": img_url,
                                        "full_url": obj.get("primaryImage") or img_url,
                                        "original_width": None,
                                        "original_height": None,
                                    }
                                except Exception:
                                    continue

                        st.session_state["_refs_met_by_id"] = _met_by_id

                        if st.session_state.get("_refs_met_query_sig") != _met_term:
                            st.session_state._refs_met_query_sig = _met_term
                            st.session_state.refs_selected_met = set()
                            if "selected_images" in st.session_state:
                                for _k in list(st.session_state.selected_images.keys()):
                                    if str(_k).startswith("met:"):
                                        del st.session_state.selected_images[_k]

                        def _refs_met_bridge_cb():
                            _refs_sel_bridge_on_change("refs_met_sel_bridge", "met")

                        st.text_input(
                            "refs_met_sel_bridge",
                            key="refs_met_sel_bridge",
                            on_change=_refs_met_bridge_cb,
                            label_visibility="collapsed",
                        )

                        _met_gal_exp = (
                            '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" '
                            'xmlns="http://www.w3.org/2000/svg">'
                            '<path d="M1 4.5V1H4.5M7.5 1H11V4.5M11 7.5V11H7.5M4.5 11H1V7.5" '
                            'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
                            'stroke-linejoin="round"/></svg>'
                        )

                        _met_cards_html = ""
                        _met_n = 0
                        for _sid, obj_data in _met_by_id.items():
                            img_url = obj_data.get("image_url", "")
                            full_url = obj_data.get("full_url", img_url)
                            title = obj_data.get("title", "Untitled")
                            artist = obj_data.get("artist_display", "Unknown")
                            _safe_src = str(img_url).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
                            _zoom_attr = str(full_url).replace("&", "&amp;").replace('"', "&quot;").replace("'", "&#39;")
                            _cap_line = _html_stdlib.escape(f"{title} — {artist}"[:140])
                            _is_sel = _sid in st.session_state.refs_selected_met
                            _wrap_sel = " ref-stock-selected" if _is_sel else ""
                            _wrap_nd = " ref-stock-no-dims"
                            _sel_chk = '<div class="ref-stock-sel-check">&#10003;</div>' if _is_sel else ""

                            _met_n += 1
                            _met_cards_html += f"""<div class="gal-card ref-stock-card" onclick="refsMetSel('{_sid}')">
<div class="gal-badge">{_met_n}</div>
<div class="ref-stock-img-wrap{_wrap_sel}{_wrap_nd}">
<div class="ref-stock-ph" aria-hidden="true"></div>
<div class="gal-expand" data-zoom="{_zoom_attr}" onclick="event.stopPropagation();event.preventDefault();var z=this.getAttribute('data-zoom');if(z)window.open(z,'_blank','noopener,noreferrer');" title="Open full size">{_met_gal_exp}</div>
{_sel_chk}
<img class="ref-stock-img" src="{_safe_src}" alt="" loading="lazy" decoding="async" draggable="false"/>
</div>
<div class="gal-caption">{_cap_line}</div>
</div>"""

                        if not _met_cards_html:
                            st.warning("No artworks with valid images found.")
                        else:
                            _met_h = min(5600, 360 + _met_n * 280)
                            _met_html = (
                                _REFS_STOCK_IFRAME_CSS
                                + f'<div class="ref-stock-masonry">{_met_cards_html}</div>'
                                + """
<script>
function refsMetSel(id) {
var inp = window.parent.document.querySelector('input[aria-label="refs_met_sel_bridge"]');
if (!inp) return;
var ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
var payload = String(id) + '|' + Date.now();
ns.call(inp, payload);
inp.dispatchEvent(new Event('input', {bubbles:true}));
inp.dispatchEvent(new Event('change', {bubbles:true}));
try { inp.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertFromPaste', data: payload })); } catch (e) {}
try { inp.focus({ preventScroll: true }); } catch (e2) {}
try { inp.blur(); } catch (e3) {}
}
</script>"""
                            )
                            components.html(_met_html, height=_met_h, scrolling=True)

            except requests.RequestException as e:
                st.error(f"Failed to contact Met Museum API: {e}")

    with src_tab5:
        pexels_video_query = st.text_input(
            "Search Pexels Video",
            placeholder="Type a keyword (e.g. dancer, city night, cinematic portrait...)",
            key="pexels_video_query",
        )
        pexels_video_limit = st.slider(
            "Results",
            min_value=5,
            max_value=15,
            value=15,
            step=5,
            key="pexels_video_limit",
        )

        if pexels_video_query and str(pexels_video_query).strip():
            pexels_api_key = os.getenv("PEXELS_API_KEY")
            if not pexels_api_key:
                st.error(
                    "PEXELS_API_KEY is missing. Add it to environment variables to enable video search."
                )
            else:

                def _pick_mp4_link(video_obj):
                    files = video_obj.get("video_files") or []
                    if not files:
                        return None

                    def _match(q):
                        for vf in files:
                            if (
                                vf.get("quality") == q
                                and vf.get("link")
                                and (
                                    vf.get("file_type") == "video/mp4"
                                    or str(vf.get("link")).lower().endswith(".mp4")
                                )
                            ):
                                return vf.get("link")
                        return None

                    return _match("hd") or _match("sd") or next(
                        (
                            vf.get("link")
                            for vf in files
                            if vf.get("link")
                            and (
                                vf.get("file_type") == "video/mp4"
                                or str(vf.get("link")).lower().endswith(".mp4")
                            )
                        ),
                        None,
                    )

                def _on_pexels_video_sel_change(vid_id: str):
                    vid_id = str(vid_id)
                    box_key = f"refs_pexels_video_sel_{vid_id}"
                    checked = bool(st.session_state.get(box_key, False))
                    if checked:
                        st.session_state.refs_selected_pexels_videos.add(vid_id)
                        meta = (st.session_state.get("_refs_pexels_video_by_id") or {}).get(
                            vid_id
                        )
                        if meta:
                            st.session_state.selected_images[f"pexels_video:{vid_id}"] = meta
                    else:
                        st.session_state.refs_selected_pexels_videos.discard(vid_id)
                        st.session_state.selected_images.pop(
                            f"pexels_video:{vid_id}", None
                        )

                _prev_ids = list(st.session_state.get("_refs_pexels_video_ids_current") or [])
                _term = str(pexels_video_query).strip()
                try:
                    resp = requests.get(
                        "https://api.pexels.com/videos/search",
                        headers={"Authorization": pexels_api_key},
                        params={"query": _term, "per_page": int(pexels_video_limit)},
                        timeout=20,
                    )
                    if resp.status_code != 200:
                        st.error(f"Pexels Video API error ({resp.status_code}).")
                    else:
                        payload = resp.json() or {}
                        videos = payload.get("videos") or []

                        _by_id = {}
                        _ids = []
                        for v in videos:
                            _vid = v.get("id")
                            if _vid is None:
                                continue
                            _mp4 = _pick_mp4_link(v)
                            if not _mp4:
                                continue
                            _uid = str(_vid)
                            user = v.get("user") or {}
                            user_name = user.get("name") or "Pexels"
                            duration = v.get("duration") or None
                            cap = (
                                f"{user_name} · {duration}s"
                                if duration is not None
                                else user_name
                            )
                            _by_id[_uid] = {
                                "source": "pexels_video",
                                "id": _uid,
                                "url": _mp4,
                                "video_url": _mp4,
                                "caption": cap,
                            }
                            _ids.append(_uid)

                        st.session_state["_refs_pexels_video_by_id"] = _by_id
                        st.session_state["_refs_pexels_video_ids_current"] = _ids

                        # Query change: clear previous selections + checkbox states.
                        if st.session_state.get("_refs_pexels_video_query_sig") != _term:
                            st.session_state._refs_pexels_video_query_sig = _term
                            st.session_state.refs_selected_pexels_videos = set()
                            for _k in list(st.session_state.selected_images.keys()):
                                if str(_k).startswith("pexels_video:"):
                                    del st.session_state.selected_images[_k]

                            for _vid in _prev_ids + list(_ids):
                                st.session_state[f"refs_pexels_video_sel_{_vid}"] = False

                        _n_vid_sel = len(st.session_state.refs_selected_pexels_videos)
                        if _n_vid_sel > 0:
                            with st.container(border=True):
                                st.markdown(
                                    '<div style="height:1px;background:linear-gradient(90deg,transparent,rgba(245,245,220,0.4),transparent);'
                                    'margin:0 0 0.65rem;"></div>'
                                    f'<p style="margin:0 0 12px;color:#9E9E8A;font-size:0.74rem;font-family:\'Open Sans\',sans-serif;">'
                                    f'<span style="color:var(--refs-cream, #F5F5DC);font-weight:700;">{_n_vid_sel}</span> '
                                    f"video(s) selected — send to workspace</p>",
                                    unsafe_allow_html=True,
                                )
                                col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1], gap="small")
                                with col_btn1:
                                    if st.button(
                                        "STORYBOARD",
                                        key="refs_bar_storyboard_btn_pexels_video",
                                        width="stretch",
                                    ):
                                        st.toast(
                                            "Pexels videos selection stored in session_state."
                                        )
                                        st.rerun()
                                with col_btn2:
                                    if st.button(
                                        "ASSET",
                                        key="refs_bar_asset_btn_pexels_video",
                                        width="stretch",
                                    ):
                                        _vby = st.session_state.get("_refs_pexels_video_by_id") or {}
                                        _v_saved = 0
                                        _v_failed = 0
                                        for _vid in sorted(st.session_state.refs_selected_pexels_videos):
                                            _vmeta = _vby.get(str(_vid))
                                            if not _vmeta or not _vmeta.get("video_url"):
                                                _v_failed += 1
                                                continue
                                            _vpath = _refs_download_url_to_downloads(
                                                _vmeta["video_url"], f"pexels_video_{_vid}.mp4"
                                            )
                                            if not _vpath:
                                                _v_failed += 1
                                                continue
                                            _vresult = add_to_assets(
                                                source_path=_vpath,
                                                original_name=f"pexels_video_{_vid}.mp4",
                                                provenance={
                                                    "source": "pexels_video",
                                                    "id": str(_vid),
                                                    "caption": _vmeta.get("caption", ""),
                                                    "video_url": _vmeta["video_url"],
                                                },
                                            )
                                            if _vresult:
                                                _v_saved += 1
                                            else:
                                                _v_failed += 1
                                        if _v_saved:
                                            st.toast(f"Saved {_v_saved} video(s) to Assets" + (f" ({_v_failed} failed)" if _v_failed else ""))
                                        elif _v_failed:
                                            st.toast(f"Could not save ({_v_failed} failed). Check network.")
                                        else:
                                            st.toast("Nothing saved — select videos first.")
                                        st.rerun()
                                with col_btn3:
                                    if st.button(
                                        "CLEAR",
                                        key="refs_pexels_video_clear_sel",
                                        width="stretch",
                                        disabled=(_n_vid_sel == 0),
                                    ):
                                        st.session_state.refs_selected_pexels_videos = set()
                                        for _k in list(st.session_state.selected_images.keys()):
                                            if str(_k).startswith("pexels_video:"):
                                                del st.session_state.selected_images[_k]
                                        for _vid in st.session_state.get("_refs_pexels_video_ids_current") or []:
                                            st.session_state[
                                                f"refs_pexels_video_sel_{_vid}"
                                            ] = False
                                        st.rerun()

                        if not _ids:
                            st.warning("No public-domain videos with an hd/sd mp4 link found.")
                        else:
                            VIDEO_COLS = 3
                            for row_start in range(0, len(_ids), VIDEO_COLS):
                                cols = st.columns(VIDEO_COLS, gap="small")
                                for ci in range(VIDEO_COLS):
                                    idx = row_start + ci
                                    if idx >= len(_ids):
                                        break
                                    vid_id = _ids[idx]
                                    meta = _by_id.get(vid_id) or {}
                                    with cols[ci]:
                                        if meta.get("video_url"):
                                            st.video(meta["video_url"])
                                        _rv_left, _rv_right = st.columns([4, 1], gap="small")
                                        with _rv_left:
                                            st.caption(meta.get("caption") or "")
                                        with _rv_right:
                                            box_key = f"refs_pexels_video_sel_{vid_id}"
                                            st.checkbox(
                                                "Select",
                                                value=vid_id in st.session_state.refs_selected_pexels_videos,
                                                key=box_key,
                                                on_change=_on_pexels_video_sel_change,
                                                args=(vid_id,),
                                            )
                except requests.RequestException as e:
                    st.error(f"Failed to contact Pexels Video API: {e}")

    with src_tab6:
        pixabay_video_query = st.text_input(
            "Search Pixabay Video",
            placeholder="Type a keyword (e.g. ocean, timelapse, abstract art...)",
            key="pixabay_video_query",
        )
        pixabay_video_limit = st.slider(
            "Results",
            min_value=5,
            max_value=20,
            value=15,
            step=5,
            key="pixabay_video_limit",
        )

        if pixabay_video_query and str(pixabay_video_query).strip():
            pixabay_api_key = os.getenv("PIXABAY_API_KEY")
            if not pixabay_api_key:
                st.error("PIXABAY_API_KEY is missing. Add it to environment variables.")
            else:

                def _on_pixabay_video_sel_change(vid_id: str):
                    vid_id = str(vid_id)
                    box_key = f"refs_pixabay_video_sel_{vid_id}"
                    checked = bool(st.session_state.get(box_key, False))
                    if checked:
                        st.session_state.refs_selected_pixabay_videos.add(vid_id)
                        meta = (st.session_state.get("_refs_pixabay_video_by_id") or {}).get(
                            vid_id
                        )
                        if meta:
                            st.session_state.selected_images[f"pixabay_video:{vid_id}"] = meta
                    else:
                        st.session_state.refs_selected_pixabay_videos.discard(vid_id)
                        st.session_state.selected_images.pop(f"pixabay_video:{vid_id}", None)

                _prev_pxv_ids = list(st.session_state.get("_refs_pixabay_video_ids_current") or [])
                _pxv_term = str(pixabay_video_query).strip()
                try:
                    resp = requests.get(
                        "https://pixabay.com/api/videos/",
                        params={
                            "key": pixabay_api_key,
                            "q": _pxv_term,
                            "per_page": int(pixabay_video_limit),
                            "safesearch": "true",
                        },
                        timeout=20,
                    )
                    if resp.status_code != 200:
                        st.error(f"Pixabay Video API error ({resp.status_code}).")
                    else:
                        payload = resp.json() or {}
                        hits = payload.get("hits") or []

                        _pxv_by_id = {}
                        _pxv_ids = []
                        for v in hits:
                            _vid = v.get("id")
                            if _vid is None:
                                continue
                            vids = v.get("videos") or {}
                            _mp4 = (
                                (vids.get("large") or {}).get("url")
                                or (vids.get("medium") or {}).get("url")
                                or (vids.get("small") or {}).get("url")
                                or (vids.get("tiny") or {}).get("url")
                            )
                            if not _mp4:
                                continue
                            _uid = str(_vid)
                            user_name = v.get("user") or "Pixabay"
                            duration = v.get("duration") or None
                            tags = v.get("tags") or ""
                            cap = (
                                f"{user_name} · {duration}s"
                                if duration is not None
                                else user_name
                            )
                            _pxv_by_id[_uid] = {
                                "source": "pixabay_video",
                                "id": _uid,
                                "url": _mp4,
                                "video_url": _mp4,
                                "caption": cap,
                                "tags": tags,
                            }
                            _pxv_ids.append(_uid)

                        st.session_state["_refs_pixabay_video_by_id"] = _pxv_by_id
                        st.session_state["_refs_pixabay_video_ids_current"] = _pxv_ids

                        if st.session_state.get("_refs_pixabay_video_query_sig") != _pxv_term:
                            st.session_state._refs_pixabay_video_query_sig = _pxv_term
                            st.session_state.refs_selected_pixabay_videos = set()
                            for _k in list(st.session_state.selected_images.keys()):
                                if str(_k).startswith("pixabay_video:"):
                                    del st.session_state.selected_images[_k]
                            for _vid in _prev_pxv_ids + list(_pxv_ids):
                                st.session_state[f"refs_pixabay_video_sel_{_vid}"] = False

                        _n_pxv_sel = len(st.session_state.refs_selected_pixabay_videos)
                        if _n_pxv_sel > 0:
                            with st.container(border=True):
                                st.markdown(
                                    '<div style="height:1px;background:linear-gradient(90deg,transparent,rgba(245,245,220,0.4),transparent);'
                                    'margin:0 0 0.65rem;"></div>'
                                    f'<p style="margin:0 0 12px;color:#9E9E8A;font-size:0.74rem;font-family:\'Open Sans\',sans-serif;">'
                                    f'<span style="color:var(--refs-cream, #F5F5DC);font-weight:700;">{_n_pxv_sel}</span> '
                                    f"video(s) selected — send to workspace</p>",
                                    unsafe_allow_html=True,
                                )
                                col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1], gap="small")
                                with col_btn1:
                                    if st.button(
                                        "STORYBOARD",
                                        key="refs_bar_storyboard_btn_pixabay_video",
                                        width="stretch",
                                    ):
                                        st.toast("Pixabay videos stored in session_state.")
                                        st.rerun()
                                with col_btn2:
                                    if st.button(
                                        "ASSET",
                                        key="refs_bar_asset_btn_pixabay_video",
                                        width="stretch",
                                    ):
                                        _vby = st.session_state.get("_refs_pixabay_video_by_id") or {}
                                        _v_saved = 0
                                        _v_failed = 0
                                        for _vid in sorted(st.session_state.refs_selected_pixabay_videos):
                                            _vmeta = _vby.get(str(_vid))
                                            if not _vmeta or not _vmeta.get("video_url"):
                                                _v_failed += 1
                                                continue
                                            _vpath = _refs_download_url_to_downloads(
                                                _vmeta["video_url"], f"pixabay_video_{_vid}.mp4"
                                            )
                                            if not _vpath:
                                                _v_failed += 1
                                                continue
                                            _vresult = add_to_assets(
                                                source_path=_vpath,
                                                original_name=f"pixabay_video_{_vid}.mp4",
                                                provenance={
                                                    "source": "pixabay_video",
                                                    "id": str(_vid),
                                                    "caption": _vmeta.get("caption", ""),
                                                    "video_url": _vmeta["video_url"],
                                                },
                                            )
                                            if _vresult:
                                                _v_saved += 1
                                            else:
                                                _v_failed += 1
                                        if _v_saved:
                                            st.toast(
                                                f"Saved {_v_saved} video(s) to Assets"
                                                + (f" ({_v_failed} failed)" if _v_failed else "")
                                            )
                                        elif _v_failed:
                                            st.toast(f"Could not save ({_v_failed} failed).")
                                        else:
                                            st.toast("Nothing saved — select videos first.")
                                        st.rerun()
                                with col_btn3:
                                    if st.button(
                                        "CLEAR",
                                        key="refs_pixabay_video_clear_sel",
                                        width="stretch",
                                        disabled=(_n_pxv_sel == 0),
                                    ):
                                        st.session_state.refs_selected_pixabay_videos = set()
                                        for _k in list(st.session_state.selected_images.keys()):
                                            if str(_k).startswith("pixabay_video:"):
                                                del st.session_state.selected_images[_k]
                                        for _vid in st.session_state.get("_refs_pixabay_video_ids_current") or []:
                                            st.session_state[f"refs_pixabay_video_sel_{_vid}"] = False
                                        st.rerun()

                        if not _pxv_ids:
                            st.warning("No videos found.")
                        else:
                            VIDEO_COLS = 3
                            for row_start in range(0, len(_pxv_ids), VIDEO_COLS):
                                cols = st.columns(VIDEO_COLS, gap="small")
                                for ci in range(VIDEO_COLS):
                                    idx = row_start + ci
                                    if idx >= len(_pxv_ids):
                                        break
                                    vid_id = _pxv_ids[idx]
                                    meta = _pxv_by_id.get(vid_id) or {}
                                    with cols[ci]:
                                        if meta.get("video_url"):
                                            st.video(meta["video_url"])
                                        _rv_left, _rv_right = st.columns([4, 1], gap="small")
                                        with _rv_left:
                                            st.caption(meta.get("caption") or "")
                                        with _rv_right:
                                            box_key = f"refs_pixabay_video_sel_{vid_id}"
                                            st.checkbox(
                                                "Select",
                                                value=vid_id in st.session_state.refs_selected_pixabay_videos,
                                                key=box_key,
                                                on_change=_on_pixabay_video_sel_change,
                                                args=(vid_id,),
                                            )
                except requests.RequestException as e:
                    st.error(f"Failed to contact Pixabay Video API: {e}")

    with src_tab7:
        coverr_video_query = st.text_input(
            "Search Coverr Video",
            placeholder="Type a keyword (e.g. crane shot, dolly, aerial, cinematic...)",
            key="coverr_video_query",
        )
        coverr_video_limit = st.slider(
            "Results",
            min_value=3,
            max_value=15,
            value=9,
            step=3,
            key="coverr_video_limit",
        )

        if coverr_video_query and str(coverr_video_query).strip():
            coverr_api_key = os.getenv("COVERR_API_KEY")
            if not coverr_api_key:
                st.error(
                    "COVERR_API_KEY is missing. Add it to environment variables."
                )
            else:

                def _on_coverr_video_sel_change(vid_id: str):
                    vid_id = str(vid_id)
                    box_key = f"refs_coverr_video_sel_{vid_id}"
                    checked = bool(st.session_state.get(box_key, False))
                    if checked:
                        st.session_state.refs_selected_coverr_videos.add(vid_id)
                        meta = (st.session_state.get("_refs_coverr_video_by_id") or {}).get(vid_id)
                        if meta:
                            st.session_state.selected_images[f"coverr_video:{vid_id}"] = meta
                    else:
                        st.session_state.refs_selected_coverr_videos.discard(vid_id)
                        st.session_state.selected_images.pop(f"coverr_video:{vid_id}", None)

                _prev_cvr_ids = list(st.session_state.get("_refs_coverr_video_ids_current") or [])
                _cvr_term = str(coverr_video_query).strip()
                try:
                    resp = requests.get(
                        "https://api.coverr.co/videos",
                        headers={"Authorization": f"Bearer {coverr_api_key}"},
                        params={
                            "query": _cvr_term,
                            "page_size": int(coverr_video_limit),
                        },
                        timeout=20,
                    )
                    if resp.status_code != 200:
                        st.error(f"Coverr Video API error ({resp.status_code}). {resp.text[:200]}")
                    else:
                        payload = resp.json() or {}
                        hits = payload.get("hits") or []

                        _cvr_by_id = {}
                        _cvr_ids = []
                        for v in hits:
                            _vid = v.get("id") or v.get("video_id")
                            if _vid is None:
                                continue
                            _playback = v.get("playback_id")
                            if not _playback:
                                continue
                            _mp4 = f"https://stream.mux.com/{_playback}/medium.mp4"
                            _uid = str(_vid)
                            title = v.get("title") or ""
                            duration = v.get("duration")
                            try:
                                dur_str = f"{float(duration):.0f}s" if duration else ""
                            except (ValueError, TypeError):
                                dur_str = ""
                            cap = f"{title[:40]} · {dur_str}" if dur_str else title[:40]
                            _cvr_by_id[_uid] = {
                                "source": "coverr_video",
                                "id": _uid,
                                "url": _mp4,
                                "video_url": _mp4,
                                "caption": cap,
                                "title": title,
                                "tags": v.get("tags") or [],
                                "thumbnail": v.get("thumbnail") or "",
                            }
                            _cvr_ids.append(_uid)

                        st.session_state["_refs_coverr_video_by_id"] = _cvr_by_id
                        st.session_state["_refs_coverr_video_ids_current"] = _cvr_ids

                        if st.session_state.get("_refs_coverr_video_query_sig") != _cvr_term:
                            st.session_state._refs_coverr_video_query_sig = _cvr_term
                            st.session_state.refs_selected_coverr_videos = set()
                            for _k in list(st.session_state.selected_images.keys()):
                                if str(_k).startswith("coverr_video:"):
                                    del st.session_state.selected_images[_k]
                            for _vid in _prev_cvr_ids + list(_cvr_ids):
                                st.session_state[f"refs_coverr_video_sel_{_vid}"] = False

                        _n_cvr_sel = len(st.session_state.refs_selected_coverr_videos)
                        if _n_cvr_sel > 0:
                            with st.container(border=True):
                                st.markdown(
                                    '<div style="height:1px;background:linear-gradient(90deg,transparent,rgba(245,245,220,0.4),transparent);'
                                    'margin:0 0 0.65rem;"></div>'
                                    f'<p style="margin:0 0 12px;color:#9E9E8A;font-size:0.74rem;font-family:\'Open Sans\',sans-serif;">'
                                    f'<span style="color:var(--refs-cream, #F5F5DC);font-weight:700;">{_n_cvr_sel}</span> '
                                    f"video(s) selected — send to workspace</p>",
                                    unsafe_allow_html=True,
                                )
                                col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1], gap="small")
                                with col_btn1:
                                    if st.button(
                                        "STORYBOARD",
                                        key="refs_bar_storyboard_btn_coverr_video",
                                        width="stretch",
                                    ):
                                        st.toast("Coverr videos stored in session_state.")
                                        st.rerun()
                                with col_btn2:
                                    if st.button(
                                        "ASSET",
                                        key="refs_bar_asset_btn_coverr_video",
                                        width="stretch",
                                    ):
                                        _vby = st.session_state.get("_refs_coverr_video_by_id") or {}
                                        _v_saved = 0
                                        _v_failed = 0
                                        for _vid in sorted(st.session_state.refs_selected_coverr_videos):
                                            _vmeta = _vby.get(str(_vid))
                                            if not _vmeta or not _vmeta.get("video_url"):
                                                _v_failed += 1
                                                continue
                                            _vpath = _refs_download_url_to_downloads(
                                                _vmeta["video_url"], f"coverr_video_{_vid}.mp4"
                                            )
                                            if not _vpath:
                                                _v_failed += 1
                                                continue
                                            _vresult = add_to_assets(
                                                source_path=_vpath,
                                                original_name=f"coverr_video_{_vid}.mp4",
                                                provenance={
                                                    "source": "coverr_video",
                                                    "id": str(_vid),
                                                    "caption": _vmeta.get("caption", ""),
                                                    "video_url": _vmeta["video_url"],
                                                },
                                            )
                                            if _vresult:
                                                _v_saved += 1
                                            else:
                                                _v_failed += 1
                                        if _v_saved:
                                            st.toast(f"Saved {_v_saved} video(s) to Assets" + (f" ({_v_failed} failed)" if _v_failed else ""))
                                        elif _v_failed:
                                            st.toast(f"Could not save ({_v_failed} failed).")
                                        else:
                                            st.toast("Nothing saved — select videos first.")
                                        st.rerun()
                                with col_btn3:
                                    if st.button(
                                        "CLEAR",
                                        key="refs_coverr_video_clear_sel",
                                        width="stretch",
                                        disabled=(_n_cvr_sel == 0),
                                    ):
                                        st.session_state.refs_selected_coverr_videos = set()
                                        for _k in list(st.session_state.selected_images.keys()):
                                            if str(_k).startswith("coverr_video:"):
                                                del st.session_state.selected_images[_k]
                                        for _vid in st.session_state.get("_refs_coverr_video_ids_current") or []:
                                            st.session_state[f"refs_coverr_video_sel_{_vid}"] = False
                                        st.rerun()

                        if not _cvr_ids:
                            st.warning("No videos found.")
                        else:
                            VIDEO_COLS = 3
                            for row_start in range(0, len(_cvr_ids), VIDEO_COLS):
                                cols = st.columns(VIDEO_COLS, gap="small")
                                for ci in range(VIDEO_COLS):
                                    idx = row_start + ci
                                    if idx >= len(_cvr_ids):
                                        break
                                    vid_id = _cvr_ids[idx]
                                    meta = _cvr_by_id.get(vid_id) or {}
                                    with cols[ci]:
                                        if meta.get("video_url"):
                                            st.video(meta["video_url"])
                                        _rv_left, _rv_right = st.columns([4, 1], gap="small")
                                        with _rv_left:
                                            st.caption(meta.get("caption") or "")
                                        with _rv_right:
                                            box_key = f"refs_coverr_video_sel_{vid_id}"
                                            st.checkbox(
                                                "Select",
                                                value=vid_id in st.session_state.refs_selected_coverr_videos,
                                                key=box_key,
                                                on_change=_on_coverr_video_sel_change,
                                                args=(vid_id,),
                                            )
                except requests.RequestException as e:
                    st.error(f"Failed to contact Coverr API: {e}")

    with src_tab8:
        st.markdown(
            "[Google Arts & Culture](https://artsandculture.google.com/) does not publish an official collection API. "
            "Use **Open search** below, or configure Programmable Search (Custom Search JSON API) for thumbnails in-app."
        )
        google_arts_query = st.text_input(
            "Search Google Arts & Culture",
            placeholder="e.g. Rembrandt, Uffizi, ukiyo-e, Van Gogh...",
            key="google_arts_query",
        )
        google_arts_limit = st.slider(
            "Results (Custom Search returns max 10 per query)",
            min_value=3,
            max_value=10,
            value=8,
            step=1,
            key="google_arts_limit",
        )
        _ga_term = (google_arts_query or "").strip()
        if _ga_term:
            _ga_open = f"https://artsandculture.google.com/search?q={quote(_ga_term)}"
            st.link_button(
                "Open search on artsandculture.google.com →",
                _ga_open,
                width="stretch",
                help="Opens Google Arts & Culture in a new tab",
            )

        _refs_ga_n_sel = len(st.session_state.get("refs_selected_google_arts") or set())
        if _refs_ga_n_sel > 0:
            with st.container(border=True):
                st.markdown(
                    '<div style="height:1px;background:linear-gradient(90deg,transparent,rgba(245,245,220,0.4),transparent);'
                    'margin:0 0 0.65rem;"></div>'
                    f'<p style="margin:0 0 12px;color:#9E9E8A;font-size:0.74rem;font-family:\'Open Sans\',sans-serif;">'
                    f'<span style="color:var(--refs-cream, #F5F5DC);font-weight:700;">{_refs_ga_n_sel}</span> '
                    f"item(s) selected — Storyboard/Assets need a preview image URL from search</p>",
                    unsafe_allow_html=True,
                )
                col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1], gap="small")
                with col_btn1:
                    if st.button(
                        "STORYBOARD",
                        key="refs_bar_storyboard_btn_google_arts",
                        width="stretch",
                    ):
                        _a, _dup, _fail = _refs_send_selected_to_storyboard()
                        _parts = []
                        if _a:
                            _parts.append(f"Added {_a} image(s) to Storyboard")
                        if _dup:
                            _parts.append(f"{_dup} duplicate(s) skipped")
                        if _fail:
                            _parts.append(f"{_fail} failed (need image preview — enable Custom Search)")
                        st.toast(". ".join(_parts) if _parts else "Nothing added.")
                        st.rerun()
                with col_btn2:
                    if st.button(
                        "ASSET",
                        key="refs_bar_asset_btn_google_arts",
                        width="stretch",
                    ):
                        _sv, _fl = _refs_send_selected_to_assets()
                        if _sv:
                            st.toast(f"Saved {_sv} image(s) to Assets" + (f" ({_fl} failed)" if _fl else ""))
                        elif _fl:
                            st.toast(f"Could not save ({_fl} failed).")
                        else:
                            st.toast("Nothing saved.")
                        st.rerun()
                with col_btn3:
                    if st.button(
                        "CLEAR",
                        key="refs_google_arts_clear_sel",
                        width="stretch",
                        disabled=(_refs_ga_n_sel == 0),
                    ):
                        st.session_state.refs_selected_google_arts = set()
                        if "selected_images" in st.session_state:
                            for _k in list(st.session_state.selected_images.keys()):
                                if str(_k).startswith("google_arts:"):
                                    del st.session_state.selected_images[_k]
                        st.rerun()

        _cse_key = os.getenv("GOOGLE_CUSTOM_SEARCH_API_KEY")
        _cse_cx = os.getenv("GOOGLE_ARTS_CSE_CX")
        if _ga_term and _cse_key and _cse_cx:
            try:
                _cr = requests.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params={
                        "key": _cse_key,
                        "cx": _cse_cx,
                        "q": _ga_term,
                        "num": min(10, int(google_arts_limit)),
                    },
                    timeout=25,
                )
                if _cr.status_code != 200:
                    try:
                        _em = (_cr.json() or {}).get("error", {}).get("message", _cr.text[:200])
                    except Exception:
                        _em = _cr.text[:200]
                    st.error(f"Custom Search API error ({_cr.status_code}): {_em}")
                else:
                    _cj = _cr.json() or {}
                    _items = _cj.get("items") or []
                    _ga_by_id = {}
                    for it in _items:
                        _link = (it.get("link") or "").strip()
                        if "artsandculture.google.com" not in _link:
                            continue
                        _sid = hashlib.md5(_link.encode("utf-8")).hexdigest()[:16]
                        _thumb = (_refs_google_arts_thumb_from_cse_item(it) or "").strip()
                        _ga_by_id[_sid] = {
                            "id": _sid,
                            "title": (it.get("title") or "Result")[:220],
                            "snippet": (it.get("snippet") or "")[:400],
                            "page_url": _link,
                            "image_url": _thumb,
                        }

                    st.session_state["_refs_google_arts_by_id"] = _ga_by_id

                    if st.session_state.get("_refs_google_arts_query_sig") != _ga_term:
                        st.session_state._refs_google_arts_query_sig = _ga_term
                        st.session_state.refs_selected_google_arts = set()
                        if "selected_images" in st.session_state:
                            for _k in list(st.session_state.selected_images.keys()):
                                if str(_k).startswith("google_arts:"):
                                    del st.session_state.selected_images[_k]

                    def _refs_ga_bridge_cb():
                        _refs_sel_bridge_on_change("refs_google_arts_sel_bridge", "google_arts")

                    st.text_input(
                        "refs_google_arts_sel_bridge",
                        key="refs_google_arts_sel_bridge",
                        on_change=_refs_ga_bridge_cb,
                        label_visibility="collapsed",
                    )

                    _ga_gal_exp = (
                        '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" '
                        'xmlns="http://www.w3.org/2000/svg">'
                        '<path d="M1 4.5V1H4.5M7.5 1H11V4.5M11 7.5V11H7.5M4.5 11H1V7.5" '
                        'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
                        'stroke-linejoin="round"/></svg>'
                    )
                    _ga_pl = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
                    _ga_cards_html = ""
                    _ga_n = 0
                    for _sid, _obj in _ga_by_id.items():
                        _img_u = (_obj.get("image_url") or "").strip()
                        _page_u = (_obj.get("page_url") or "").strip()
                        _title = _obj.get("title") or "Result"
                        _cap_line = _html_stdlib.escape(f"{_title}"[:140])
                        _is_sel = _sid in st.session_state.refs_selected_google_arts
                        _wrap_sel = " ref-stock-selected" if _is_sel else ""
                        _wrap_nd = " ref-stock-no-dims"
                        _sel_chk = '<div class="ref-stock-sel-check">&#10003;</div>' if _is_sel else ""
                        _src = _img_u if _img_u else _ga_pl
                        _safe_src = str(_src).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
                        _zoom_attr = str(_page_u).replace("&", "&amp;").replace('"', "&quot;").replace("'", "&#39;")
                        _safe_id_js = str(_sid).replace("\\", "\\\\").replace("'", "\\'")
                        _ga_n += 1
                        _ga_cards_html += f"""<div class="gal-card ref-stock-card" onclick="refsGaSel('{_safe_id_js}')">
<div class="gal-badge">{_ga_n}</div>
<div class="ref-stock-img-wrap{_wrap_sel}{_wrap_nd}">
<div class="ref-stock-ph" aria-hidden="true"></div>
<div class="gal-expand" data-zoom="{_zoom_attr}" onclick="event.stopPropagation();event.preventDefault();var z=this.getAttribute('data-zoom');if(z)window.open(z,'_blank','noopener,noreferrer');" title="Open on Arts & Culture">{_ga_gal_exp}</div>
{_sel_chk}
<img class="ref-stock-img" src="{_safe_src}" alt="" loading="lazy" decoding="async" draggable="false"/>
</div>
<div class="gal-caption">{_cap_line}</div>
</div>"""

                    if not _ga_cards_html:
                        st.warning("No Arts & Culture pages in results (check CSE is limited to artsandculture.google.com).")
                    else:
                        _ga_h = min(5600, 360 + _ga_n * 280)
                        _ga_html = (
                            _REFS_STOCK_IFRAME_CSS
                            + f'<div class="ref-stock-masonry">{_ga_cards_html}</div>'
                            + """
<script>
function refsGaSel(id) {
var inp = window.parent.document.querySelector('input[aria-label="refs_google_arts_sel_bridge"]');
if (!inp) return;
var ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
var payload = String(id) + '|' + Date.now();
ns.call(inp, payload);
inp.dispatchEvent(new Event('input', {bubbles:true}));
inp.dispatchEvent(new Event('change', {bubbles:true}));
try { inp.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertFromPaste', data: payload })); } catch (e) {}
try { inp.focus({ preventScroll: true }); } catch (e2) {}
try { inp.blur(); } catch (e3) {}
}
</script>"""
                        )
                        components.html(_ga_html, height=_ga_h, scrolling=True)
            except requests.RequestException as e:
                st.error(f"Failed to contact Custom Search API: {e}")
        elif _ga_term and not (_cse_key and _cse_cx):
            st.info(
                "Optional: set **GOOGLE_CUSTOM_SEARCH_API_KEY** and **GOOGLE_ARTS_CSE_CX** "
                "(Programmable Search Engine restricted to `artsandculture.google.com`) to show selectable previews here. "
                "See [Custom Search JSON API](https://developers.google.com/custom-search/v1/overview)."
            )

    with src_tab9:
        wiki_query = st.text_input(
            "Search Wikimedia Commons",
            placeholder="Type a keyword (e.g. Renaissance painting, daguerreotype, Art Nouveau...)",
            key="wiki_query",
        )
        wiki_limit = st.slider(
            "Results",
            min_value=5,
            max_value=20,
            value=12,
            step=1,
            key="wiki_limit",
        )

        _refs_wiki_n_sel = len(st.session_state.get("refs_selected_wiki") or set())
        if _refs_wiki_n_sel > 0:
            with st.container(border=True):
                st.markdown(
                    '<div style="height:1px;background:linear-gradient(90deg,transparent,rgba(245,245,220,0.4),transparent);'
                    'margin:0 0 0.65rem;"></div>'
                    f'<p style="margin:0 0 12px;color:#9E9E8A;font-size:0.74rem;font-family:\'Open Sans\',sans-serif;">'
                    f'<span style="color:var(--refs-cream, #F5F5DC);font-weight:700;">{_refs_wiki_n_sel}</span> '
                    f"image(s) selected — send to workspace</p>",
                    unsafe_allow_html=True,
                )
                col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1], gap="small")
                with col_btn1:
                    if st.button("STORYBOARD", key="refs_bar_storyboard_btn_wiki", use_container_width=True):
                        _a, _dup, _fail = _refs_send_selected_to_storyboard()
                        _parts = []
                        if _a:
                            _parts.append(f"Added {_a} image(s) to Storyboard")
                        if _dup:
                            _parts.append(f"{_dup} duplicate(s) skipped")
                        if _fail:
                            _parts.append(f"{_fail} failed")
                        st.toast(". ".join(_parts) if _parts else "Nothing added.")
                        st.rerun()
                with col_btn2:
                    if st.button("ASSET", key="refs_bar_asset_btn_wiki", use_container_width=True):
                        _sv, _fl = _refs_send_selected_to_assets()
                        if _sv:
                            st.toast(f"Saved {_sv} image(s) to Assets" + (f" ({_fl} failed)" if _fl else ""))
                        elif _fl:
                            st.toast(f"Could not save ({_fl} failed).")
                        else:
                            st.toast("Nothing saved.")
                        st.rerun()
                with col_btn3:
                    if st.button("CLEAR", key="refs_wiki_clear_sel", use_container_width=True, disabled=(_refs_wiki_n_sel == 0)):
                        st.session_state.refs_selected_wiki = set()
                        if "selected_images" in st.session_state:
                            for _k in list(st.session_state.selected_images.keys()):
                                if str(_k).startswith("wiki:"):
                                    del st.session_state.selected_images[_k]
                        st.rerun()

        if wiki_query and str(wiki_query).strip():
            _wiki_term = str(wiki_query).strip()
            try:
                resp = requests.get(
                    "https://commons.wikimedia.org/w/api.php",
                    headers={"User-Agent": "ArkitectAgent/1.0 (https://console.alessiovalori.com; alessio@alessiovalori.com)"},
                    params={
                        "action": "query",
                        "generator": "search",
                        "gsrsearch": f"filetype:bitmap {_wiki_term}",
                        "gsrlimit": str(int(wiki_limit)),
                        "gsrnamespace": "6",
                        "prop": "imageinfo",
                        "iiprop": "url|size|mime|extmetadata",
                        "iiurlwidth": "800",
                        "format": "json",
                    },
                    timeout=20,
                )
                if resp.status_code != 200:
                    st.error(f"Wikimedia API error ({resp.status_code}).")
                else:
                    payload = resp.json() or {}
                    pages = (payload.get("query") or {}).get("pages") or {}

                    _wiki_by_id = {}
                    for pid, page in pages.items():
                        ii = (page.get("imageinfo") or [{}])[0]
                        thumb_url = ii.get("thumburl") or ""
                        full_url = ii.get("url") or ""
                        mime = ii.get("mime") or ""
                        if not thumb_url or not mime.startswith("image"):
                            continue
                        title = (page.get("title") or "").replace("File:", "").rsplit(".", 1)[0]
                        ext_meta = ii.get("extmetadata") or {}
                        artist = (ext_meta.get("Artist") or {}).get("value") or "Unknown"
                        import re as _re_wiki
                        artist = _re_wiki.sub(r"<[^>]+>", "", artist).strip()[:60]
                        _wiki_by_id[pid] = {
                            "id": pid,
                            "title": title[:80],
                            "artist_display": artist,
                            "image_url": thumb_url,
                            "full_url": full_url,
                            "original_width": ii.get("width"),
                            "original_height": ii.get("height"),
                        }

                    st.session_state["_refs_wiki_by_id"] = _wiki_by_id

                    if st.session_state.get("_refs_wiki_query_sig") != _wiki_term:
                        st.session_state._refs_wiki_query_sig = _wiki_term
                        st.session_state.refs_selected_wiki = set()
                        if "selected_images" in st.session_state:
                            for _k in list(st.session_state.selected_images.keys()):
                                if str(_k).startswith("wiki:"):
                                    del st.session_state.selected_images[_k]

                    def _refs_wiki_bridge_cb():
                        _refs_sel_bridge_on_change("refs_wiki_sel_bridge", "wiki")

                    st.text_input(
                        "refs_wiki_sel_bridge",
                        key="refs_wiki_sel_bridge",
                        on_change=_refs_wiki_bridge_cb,
                        label_visibility="collapsed",
                    )

                    _wiki_gal_exp = (
                        '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" '
                        'xmlns="http://www.w3.org/2000/svg">'
                        '<path d="M1 4.5V1H4.5M7.5 1H11V4.5M11 7.5V11H7.5M4.5 11H1V7.5" '
                        'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
                        'stroke-linejoin="round"/></svg>'
                    )

                    _wiki_cards_html = ""
                    _wiki_n = 0
                    for _sid, obj_data in _wiki_by_id.items():
                        img_url = obj_data.get("image_url", "")
                        full_url = obj_data.get("full_url", img_url)
                        title = obj_data.get("title", "Untitled")
                        artist = obj_data.get("artist_display", "Unknown")
                        _safe_src = str(img_url).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
                        _zoom_attr = str(full_url).replace("&", "&amp;").replace('"', "&quot;").replace("'", "&#39;")
                        _cap_line = _html_stdlib.escape(f"{title} — {artist}"[:140])
                        _is_sel = _sid in st.session_state.get("refs_selected_wiki", set())
                        _wrap_sel = " ref-stock-selected" if _is_sel else ""
                        _wrap_nd = " ref-stock-no-dims"
                        _sel_chk = '<div class="ref-stock-sel-check">&#10003;</div>' if _is_sel else ""

                        _wiki_n += 1
                        _wiki_cards_html += f"""<div class="gal-card ref-stock-card" onclick="refsWikiSel('{_sid}')">
<div class="gal-badge">{_wiki_n}</div>
<div class="ref-stock-img-wrap{_wrap_sel}{_wrap_nd}">
<div class="ref-stock-ph" aria-hidden="true"></div>
<div class="gal-expand" data-zoom="{_zoom_attr}" onclick="event.stopPropagation();event.preventDefault();var z=this.getAttribute('data-zoom');if(z)window.open(z,'_blank','noopener,noreferrer');" title="Open full size">{_wiki_gal_exp}</div>
{_sel_chk}
<img class="ref-stock-img" src="{_safe_src}" alt="" loading="lazy" decoding="async" draggable="false"/>
</div>
<div class="gal-caption">{_cap_line}</div>
</div>"""

                    if not _wiki_cards_html:
                        st.warning("No images found on Wikimedia Commons.")
                    else:
                        _wiki_h = min(5600, 360 + _wiki_n * 280)
                        _wiki_html = (
                            _REFS_STOCK_IFRAME_CSS
                            + f'<div class="ref-stock-masonry">{_wiki_cards_html}</div>'
                            + """
<script>
function refsWikiSel(id) {
var inp = window.parent.document.querySelector('input[aria-label="refs_wiki_sel_bridge"]');
if (!inp) return;
var ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
var payload = String(id) + '|' + Date.now();
ns.call(inp, payload);
inp.dispatchEvent(new Event('input', {bubbles:true}));
inp.dispatchEvent(new Event('change', {bubbles:true}));
try { inp.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertFromPaste', data: payload })); } catch (e) {}
try { inp.focus({ preventScroll: true }); } catch (e2) {}
try { inp.blur(); } catch (e3) {}
}
</script>"""
                        )
                        components.html(_wiki_html, height=_wiki_h, scrolling=True)

            except requests.RequestException as e:
                st.error(f"Failed to contact Wikimedia API: {e}")
