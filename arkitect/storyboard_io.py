import os
import re
import json
import random
import html as _html_stdlib
import base64 as _b64
import shutil
import subprocess
import tempfile
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components

from arkitect.storage import (
    load_all_snapshots,
    save_all_snapshots,
    snapshot_entry_items,
    filter_snapshot_names,
    upsert_snapshot_entry,
    get_active_project_id,
    add_to_assets,
)
from arkitect.media_server import _to_media_url

def _normalize_editing_video_item(item):
    """trim_start >= 0; trim_end defaults to -1 (full duration)."""
    out = dict(item)
    ts_raw = out.get("trim_start", 0)
    try:
        ts = float(ts_raw)
    except (TypeError, ValueError):
        ts = 0.0
    if ts < 0 or ts_raw is None:
        ts = 0.0
    out["trim_start"] = round(ts, 2)
    te_raw = out.get("trim_end", -1)
    if te_raw is None:
        te = -1.0
    else:
        try:
            te = float(te_raw)
        except (TypeError, ValueError):
            te = -1.0
    out["trim_end"] = round(te, 2)
    return out


def _get_thumbnail_src(item):
    # Prioritize image thumbnails for videos (last_frame_path), then standard paths
    src = item.get("last_frame_path") or item.get("image_path") or item.get("video_path") or item.get("url") or item.get("src") or ""
    if not src:
        return ""
    if src.startswith("http://") or src.startswith("https://"):
        return src

    if os.path.exists(src):
        ext = os.path.splitext(src)[1].lower()
        # DANGER: Do not base64 encode massive video files. Return a flag.
        if ext in [".mp4", ".mov", ".webm"]:
            return "VIDEO_PLACEHOLDER"

        try:
            mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
            mime = mime_map.get(ext, "image/jpeg")
            with open(src, "rb") as f:
                data = _b64.b64encode(f.read()).decode("utf-8")
            return f"data:{mime};base64,{data}"
        except Exception:
            return ""

    return src

def _get_thumbnail_src_resized(item, max_px=320):
    """
    Like _get_thumbnail_src but resizes local images to max_px on the
    longest side before base64-encoding. Keeps URLs and VIDEO_PLACEHOLDER
    unchanged. Falls back to _get_thumbnail_src on any error.
    """
    src = (item.get("image_path") or item.get("url") or
           item.get("src") or item.get("last_frame_path") or "")
    if not src:
        return ""
    # URLs and remote srcs: return as-is
    if src.startswith("http://") or src.startswith("https://"):
        return src
    if not os.path.exists(src):
        return src
    ext = os.path.splitext(src)[1].lower()
    if ext in (".mp4", ".mov", ".webm"):
        return "VIDEO_PLACEHOLDER"
    try:
        from PIL import Image as _PILImage
        import io as _io
        mime_map = {".png": "image/png", ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg", ".webp": "image/webp",
                    ".gif": "image/gif"}
        mime = mime_map.get(ext, "image/jpeg")
        with _PILImage.open(src) as im:
            im.thumbnail((max_px, max_px), _PILImage.LANCZOS)
            buf = _io.BytesIO()
            save_fmt = "JPEG" if mime == "image/jpeg" else "PNG"
            im.convert("RGB").save(buf, format=save_fmt, quality=82, optimize=True)
            data = _b64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:{mime};base64,{data}"
    except Exception:
        # PIL not available or error: fall back to original
        return _get_thumbnail_src(item)


def _sync_storyboard_name_from_widgets():
    """Preferisce sb_active_name; altrimenti il primo campo sb_name_field* compilato."""
    v = (st.session_state.get("sb_active_name") or "").strip()
    if v:
        return v
    for key in list(st.session_state.keys()):
        if key.startswith("sb_name_field"):
            v = (st.session_state.get(key) or "").strip()
            if v:
                st.session_state.sb_active_name = v
                return v
    return ""


def _autosave_storyboard_snapshot():
    """Salvataggio immediato su disco se c'è un nome (usato da grid / gallery)."""
    nm = _sync_storyboard_name_from_widgets()
    if not nm:
        return
    upsert_snapshot_entry("storyboard", nm, st.session_state.get("sb_active_images", []))


def _on_storyboard_grid_pick_change():
    raw = (st.session_state.get("sb_pick_act") or "").strip()
    if not raw:
        return
    st.session_state["sb_pick_act"] = ""
    sname = raw.split("|")[0].strip()
    sd = load_all_snapshots()
    sd_map = sd.get("storyboard", {})
    if sname not in sd_map:
        return
    raw_e = sd_map.get(sname, [])
    items = snapshot_entry_items(raw_e)
    st.session_state.sb_active_images = items
    st.session_state.sb_active_name = sname
    st.session_state.sb_mode = "loaded"


def _thumbnail_for_editing_items(raw_ed_items):
    """Primo frame utile (last_frame o cv2) e numero clip — per griglia Editing."""
    if not raw_ed_items:
        return "", 0
    ed_thumb = ""
    for _ei in raw_ed_items:
        _eip = _ei.get("last_frame_path") or ""
        if _eip and os.path.exists(_eip):
            try:
                from PIL import Image as _PILImage
                import io as _io
                with _PILImage.open(_eip) as _eim:
                    _eim.thumbnail((400, 240), _PILImage.LANCZOS)
                    _ebuf = _io.BytesIO()
                    _eim.convert("RGB").save(_ebuf, format="JPEG", quality=75)
                    ed_thumb = f"data:image/jpeg;base64,{_b64.b64encode(_ebuf.getvalue()).decode('ascii')}"
            except Exception:
                pass
        if not ed_thumb:
            _evp = _ei.get("video_path") or ""
            if _evp and os.path.exists(_evp):
                try:
                    import cv2
                    cap = cv2.VideoCapture(_evp)
                    if cap.isOpened():
                        ret, frame = cap.read()
                        if ret:
                            h, w = frame.shape[:2]
                            scale = min(400 / max(w, 1), 240 / max(h, 1), 1.0)
                            if scale < 1:
                                frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
                            _, _ebuf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 72])
                            ed_thumb = f"data:image/jpeg;base64,{_b64.b64encode(_ebuf.tobytes()).decode('ascii')}"
                    cap.release()
                except Exception:
                    pass
        if ed_thumb:
            break
    return ed_thumb, len(raw_ed_items)


def _on_editing_grid_pick_change():
    raw = (st.session_state.get("ed_pick_act") or "").strip()
    if not raw:
        return
    st.session_state["ed_pick_act"] = ""
    ename = raw.split("|")[0].strip()
    sd = load_all_snapshots()
    ed_map = sd.get("editing", {})
    if ename not in ed_map:
        return
    raw_e = ed_map.get(ename, [])
    items = snapshot_entry_items(raw_e)
    st.session_state.ed_active_videos = [_normalize_editing_video_item(dict(x)) for x in items]
    st.session_state.ed_active_name = ename
    st.session_state.ed_mode = "loaded"


def _render_storyboard_projects_sidebar():
    """Sidebar STORYBOARD dedicata: stessa struttura della pagina PROJECTS."""
    st.markdown(
        '<p style="color:#9E9E8A;font-size:0.75rem;font-weight:600;letter-spacing:0.08em;'
        'margin:0 0 8px;">NEW STORYBOARD</p>',
        unsafe_allow_html=True,
    )
    new_sb_name = st.text_input(
        "Storyboard name",
        key="sb_page_new_name_input",
        label_visibility="collapsed",
        placeholder="Storyboard name...",
    )
    if st.button("NEW STORYBOARD", key="sbi_sidebar_new_btn", use_container_width=True):
        name = (new_sb_name or "").strip()
        if name:
            snaps = load_all_snapshots()
            all_sb = snaps.get("storyboard", {})
            sb_list = filter_snapshot_names(all_sb, get_active_project_id())
            if any(x.lower() == name.lower() for x in sb_list):
                st.warning(f"Storyboard '{name}' already exists.")
            else:
                st.session_state.sb_mode = "new"
                st.session_state.sb_active_name = name
                st.session_state.sb_active_images = []
                st.toast(f"New storyboard: {name}")
                st.rerun()
        else:
            st.session_state.sb_mode = "new"
            st.session_state.sb_active_name = ""
            st.session_state.sb_active_images = []
            st.rerun()

    st.markdown(
        '<hr style="border:none;border-top:1px solid #2a2a28;margin:16px 0;">',
        unsafe_allow_html=True,
    )
    if st.button("DELETE", key="sbi_sidebar_delete_btn", use_container_width=True):
        name = st.session_state.get("sb_active_name")
        mode = st.session_state.get("sb_mode")
        if not name or mode not in ("new", "loaded"):
            st.toast("Select a storyboard in the grid or create one first.")
        else:
            snaps = load_all_snapshots()
            bucket = snaps.setdefault("storyboard", {})
            if name in bucket:
                bucket.pop(name, None)
                save_all_snapshots(snaps)
                st.toast(f"Deleted: {name}")
            else:
                st.toast("Workspace cleared.")
            st.session_state.sb_mode = None
            st.session_state.sb_active_name = ""
            st.session_state.sb_active_images = []
            st.rerun()

    st.markdown(
        '<hr style="border:none;border-top:1px solid #2a2a28;margin:16px 0;">',
        unsafe_allow_html=True,
    )
    _is_browse = st.session_state.get("sb_mode") is None
    _all_lbl = "ALL STORYBOARDS" + (" ✓" if _is_browse else "")
    if st.button(_all_lbl, key="sbi_sidebar_all_btn", use_container_width=True):
        st.session_state.sb_mode = None
        st.session_state.sb_active_name = ""
        st.session_state.sb_active_images = []
        st.toast("Storyboard workspace reset.")
        st.rerun()

    st.markdown(
        '<hr style="border:none;border-top:1px solid #2a2a28;margin:16px 0;">',
        unsafe_allow_html=True,
    )
    if st.button("CLEAR", key="sbi_sidebar_clear_btn", use_container_width=True):
        st.session_state.sb_active_images = []
        st.session_state.gallery_selected_imgs = set()
        st.session_state.sb_mode = None
        st.session_state.sb_active_name = ""
        st.rerun()




def _render_editing_projects_sidebar():
    """Sidebar EDITING dedicata: stessa struttura di Projects / Storyboard."""
    st.markdown(
        '<p style="color:#9E9E8A;font-size:0.75rem;font-weight:600;letter-spacing:0.08em;'
        'margin:0 0 8px;">NEW EDITING</p>',
        unsafe_allow_html=True,
    )
    new_ed_name = st.text_input(
        "Editing session name",
        key="ed_page_new_name_input",
        label_visibility="collapsed",
        placeholder="Editing name...",
    )
    if st.button("NEW EDITING", key="ed_sidebar_new_btn", use_container_width=True):
        name = (new_ed_name or "").strip()
        if name:
            snaps = load_all_snapshots()
            all_ed = snaps.get("editing", {})
            ed_list = filter_snapshot_names(all_ed, get_active_project_id())
            if any(x.lower() == name.lower() for x in ed_list):
                st.warning(f"Editing '{name}' already exists.")
            else:
                st.session_state.ed_mode = "new"
                st.session_state.ed_active_name = name
                st.session_state.ed_active_videos = []
                st.toast(f"New editing: {name}")
                st.rerun()
        else:
            st.session_state.ed_mode = "new"
            st.session_state.ed_active_name = ""
            st.session_state.ed_active_videos = []
            st.rerun()

    st.markdown(
        '<hr style="border:none;border-top:1px solid #2a2a28;margin:16px 0;">',
        unsafe_allow_html=True,
    )
    if st.button("DELETE", key="ed_sidebar_delete_btn", use_container_width=True):
        name = st.session_state.get("ed_active_name")
        mode = st.session_state.get("ed_mode")
        if not name or mode not in ("new", "loaded"):
            st.toast("Select an editing in the grid or create one first.")
        else:
            snaps = load_all_snapshots()
            bucket = snaps.setdefault("editing", {})
            if name in bucket:
                bucket.pop(name, None)
                save_all_snapshots(snaps)
                st.toast(f"Deleted: {name}")
            else:
                st.toast("Workspace cleared.")
            st.session_state.ed_mode = None
            st.session_state.ed_active_name = ""
            st.session_state.ed_active_videos = []
            st.rerun()

    st.markdown(
        '<hr style="border:none;border-top:1px solid #2a2a28;margin:16px 0;">',
        unsafe_allow_html=True,
    )
    _is_browse_ed = st.session_state.get("ed_mode") is None
    _all_ed_lbl = "ALL EDITINGS" + (" ✓" if _is_browse_ed else "")
    if st.button(_all_ed_lbl, key="ed_sidebar_all_btn", use_container_width=True):
        st.session_state.ed_mode = None
        st.session_state.ed_active_name = ""
        st.session_state.ed_active_videos = []
        st.toast("Editing workspace reset.")
        st.rerun()

    st.markdown(
        '<hr style="border:none;border-top:1px solid #2a2a28;margin:16px 0;">',
        unsafe_allow_html=True,
    )
    if st.button("CLEAR", key="ed_sidebar_clear_btn", use_container_width=True):
        st.session_state.ed_active_videos = []
        st.session_state.gallery_selected_vids = set()
        st.session_state.ed_mode = None
        st.session_state.ed_active_name = ""
        st.rerun()

def _render_storyboard_grid(items_key, selection_key, media_type, page_prefix):
    items = st.session_state.get(items_key, [])
    if not items:
        st.info(f"No {media_type}s selected. Go to Gallery → ☆ to add.")
        return
    total = len(items)
    action_key = f"{page_prefix}_action"
    action_val = st.session_state.get(action_key, "")
    if action_val:
        st.session_state[action_key] = ""
        if action_val.startswith("reorder:"):
            try:
                new_indices = [int(x) for x in action_val.replace("reorder:", "").split(",") if x.strip().isdigit()]
                if len(new_indices) == total and sorted(new_indices) == list(range(total)):
                    st.session_state[items_key] = [items[i] for i in new_indices]
                    if page_prefix.startswith("sbi"):
                        _autosave_storyboard_snapshot()
                    elif page_prefix.startswith("sbv") and st.session_state.get("ed_active_name"):
                        upsert_snapshot_entry("editing", st.session_state.ed_active_name, st.session_state[items_key])
                    st.rerun()
            except (ValueError, IndexError):
                pass
        elif action_val.startswith("remove:"):
            try:
                rm_idx = int(action_val.replace("remove:", ""))
                if 0 <= rm_idx < len(items):
                    items.pop(rm_idx)
                    st.session_state[items_key] = items
                    if page_prefix.startswith("sbi"):
                        _autosave_storyboard_snapshot()
                    elif page_prefix.startswith("sbv") and st.session_state.get("ed_active_name"):
                        upsert_snapshot_entry("editing", st.session_state.ed_active_name, st.session_state[items_key])
                    st.rerun()
            except (ValueError, IndexError):
                pass
        elif action_val.startswith("note:"):
            try:
                parts = action_val.split(":", 2)  # "note:INDEX:TEXT"
                note_idx = int(parts[1])
                note_text = parts[2] if len(parts) > 2 else ""
                if 0 <= note_idx < len(items):
                    items[note_idx]["notes"] = note_text.strip()[:200]
                    st.session_state[items_key] = items
                    if page_prefix.startswith("sbi"):
                        _autosave_storyboard_snapshot()
                    elif page_prefix.startswith("sbv") and st.session_state.get("ed_active_name"):
                        upsert_snapshot_entry("editing", st.session_state.ed_active_name, items)
                    st.rerun()
            except (ValueError, IndexError):
                pass
    thumb_size = 120 if media_type == "image" else 150
    cards_html = ""
    for i, item in enumerate(items):
        src = _get_thumbnail_src(item)
        caption = item.get("caption", "")[:20]
        notes = (item.get("notes", "") or "").replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
        if media_type == "image":
            media_el = f'<img src="{src}" style="width:100%;height:{thumb_size}px;object-fit:cover;border-radius:4px;display:block;" draggable="false"/>'
        else:
            if src == "VIDEO_PLACEHOLDER":
                media_el = f'<div style="width:100%;height:{thumb_size}px;background:#2a2a28;border:1px solid #444;border-radius:4px;display:flex;align-items:center;justify-content:center;"><span style="color:#FFEB3B;font-size:32px;">▶</span></div>'
            elif src.startswith("data:image"):
                media_el = f'<div style="position:relative;"><img src="{src}" style="width:100%;height:{thumb_size}px;object-fit:cover;border-radius:4px;display:block;" draggable="false"/><div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:#FFEB3B;font-size:32px;text-shadow:0 2px 8px rgba(0,0,0,0.8);">▶</div></div>'
            else:
                media_el = f'<video src="{src}" style="width:100%;height:{thumb_size}px;object-fit:cover;border-radius:4px;display:block;" muted preload="metadata"></video>'
        cards_html += f'''
        <div class="gal-card" data-idx="{i}">
            <div class="gal-badge">{i + 1}</div>
            <div class="gal-remove" onclick="removeItem({i})">×</div>
            {media_el}
            <div class="gal-caption">{caption}</div>
            <div class="gal-notes" contenteditable="true"
                 data-idx="{i}"
                 onblur="saveNote({i}, this.textContent)"
                 placeholder="note...">{notes}</div>
        </div>'''
    cols_count = 6 if media_type == "image" else 4
    html_code = f'''
    <script src="https://cdnjs.cloudflare.com/ajax/libs/Sortable/1.15.3/Sortable.min.js"></script>
    <style>
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ background: transparent; font-family: 'Open Sans', sans-serif; }}
        .gal-grid {{ display:grid; grid-template-columns:repeat({cols_count},1fr); gap:8px; padding:4px; }}
        .gal-card {{ position:relative; background:#1a1a18; border-radius:6px; overflow:hidden; cursor:grab; border:2px solid transparent; transition:border-color .2s,box-shadow .2s; }}
        .gal-card:hover {{ border-color:rgba(255,235,59,.35); box-shadow:0 4px 16px rgba(0,0,0,.35); }}
        .gal-card.sortable-ghost {{ opacity:.35; border-color:#FFEB3B; }}
        .gal-badge {{ position:absolute; top:4px; left:4px; background:rgba(0,0,0,.75); color:#fff; font-size:9px; font-weight:700; padding:1px 6px; border-radius:3px; z-index:2; pointer-events:none; }}
        .gal-remove {{ position:absolute; top:4px; right:4px; color:#666; font-size:12px; cursor:pointer; z-index:2; width:16px; height:16px; text-align:center; line-height:16px; border-radius:50%; }}
        .gal-remove:hover {{ color:#ff4444; background:rgba(255,68,68,.15); }}
        .gal-caption {{ color:#999; font-size:9px; padding:3px 6px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
        .gal-notes {{
            color: #FFEB3B;
            font-size: 8px;
            padding: 2px 6px 4px;
            min-height: 14px;
            outline: none;
            border-top: 1px solid rgba(255,255,255,0.06);
            cursor: text;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .gal-notes:empty::before {{
            content: attr(placeholder);
            color: #444;
        }}
        .gal-notes:focus {{
            color: #fff;
            background: rgba(255,235,59,0.08);
            white-space: normal;
        }}
        div[data-testid="stTextInput"][data-key$="_action"] {{ height:0!important; overflow:hidden!important; margin:0!important; padding:0!important; opacity:0!important; position:absolute!important; }}
    </style>
    <div class="gal-grid" id="sortableGrid">{cards_html}</div>
    <script>
        if (!window.parent.__sbBridgeInstalled) {{
            window.parent.__sbBridgeInstalled = true;
            window.parent.addEventListener('message', function(event) {{
                const data = event.data || {{}};
                if (data.type !== 'sb_action' || !data.prefix) return;
                const input = window.parent.document.querySelector(
                    'input[aria-label="sb_action_input_' + data.prefix + '"]'
                );
                if (!input) return;
                const nativeSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                ).set;
                nativeSetter.call(input, data.payload || '');
                input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                input.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }});
        }}

        function sendAction(payload) {{
            window.parent.postMessage({{
                type: 'sb_action',
                prefix: '{page_prefix}',
                payload: payload
            }}, '*');
        }}

        const grid = document.getElementById('sortableGrid');
        Sortable.create(grid, {{
            animation: 200, ghostClass:'sortable-ghost', chosenClass:'sortable-chosen',
            onEnd: function(evt) {{
                const cards = grid.querySelectorAll('.gal-card');
                const newOrder = Array.from(cards).map(c => c.dataset.idx);
                cards.forEach((c,i) => {{ c.querySelector('.gal-badge').textContent = i+1; }});
                sendAction('reorder:' + newOrder.join(','));
            }}
        }});
        function removeItem(idx) {{
            sendAction('remove:' + idx);
        }}
        function saveNote(idx, text) {{
            sendAction('note:' + idx + ':' + text.substring(0, 200));
        }}
    </script>'''
    st.text_input(f"sb_action_input_{page_prefix}", value="", key=f"{page_prefix}_action", label_visibility="collapsed")
    grid_height = ((total // cols_count) + (1 if total % cols_count else 0)) * (thumb_size + 62) + 20
    components.html(html_code, height=grid_height, scrolling=False)
    st.markdown(f'<p style="color:#f0ece4;font-size:0.78rem;font-weight:600;font-family:Open Sans,sans-serif;margin-top:8px;">{total} {media_type}s</p>', unsafe_allow_html=True)

def _process_editing_actions(items_key, page_prefix):
    """Process any pending editing actions (trim/reorder/remove) from the JS component.
    Must be called BEFORE any SAVE logic to ensure state is current."""
    _action_key = f"{page_prefix}_action"
    _av = st.session_state.get(_action_key, "")
    if not _av:
        return
    st.session_state[_action_key] = ""
    items = list(st.session_state.get(items_key, []))
    try:
        if _av.startswith("trim:"):
            p = _av.split(":")
            tidx, ts, te, dur = int(p[1]), float(p[2]), float(p[3]), float(p[4])
            if 0 <= tidx < len(items):
                items[tidx]["trim_start"] = round(max(0, ts), 2)
                items[tidx]["trim_end"] = round(te, 2)
                items[tidx]["duration"] = round(dur, 2)
                st.session_state[items_key] = items
                if st.session_state.get("ed_active_name"):
                    upsert_snapshot_entry("editing", st.session_state.ed_active_name, items)
        elif _av.startswith("remove:"):
            ridx = int(_av.split(":", 1)[1])
            if 0 <= ridx < len(items):
                items.pop(ridx)
                st.session_state[items_key] = items
                if st.session_state.get("ed_active_name"):
                    upsert_snapshot_entry("editing", st.session_state.ed_active_name, items)
        elif _av.startswith("reorder:"):
            rest = _av.split(":", 1)[1]
            ni = [int(x) for x in rest.split(",") if x.strip().isdigit()]
            if len(ni) == len(items) and sorted(ni) == list(range(len(items))):
                items = [items[i] for i in ni]
                st.session_state[items_key] = items
                if st.session_state.get("ed_active_name"):
                    upsert_snapshot_entry("editing", st.session_state.ed_active_name, items)
    except (ValueError, IndexError):
        pass

def _export_editing_video(items, project_name="untitled"):
    """Export the editing timeline as a single video using ffmpeg.
    Respects trim_start/trim_end for each clip. Returns the output file path or None."""
    if not items:
        return None
    try:
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            # Try common macOS Homebrew paths
            for p in ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"]:
                if os.path.exists(p):
                    ffmpeg_path = p
                    break
        if not ffmpeg_path:
            return None

        export_dir = os.path.join(_DOWNLOADS_DIR, "exports")
        os.makedirs(export_dir, exist_ok=True)

        safe_name = re.sub(r'[^\w\-]', '_', project_name.lower().strip()) or "untitled"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(export_dir, f"{safe_name}_{timestamp}.mp4")

        # Build clip list with trim points
        valid_clips = []
        for item in items:
            vpath = item.get("video_path") or ""
            if not vpath or not os.path.exists(vpath):
                continue
            dur = float(item.get("duration") or 0)
            ts = float(item.get("trim_start") or 0)
            te = float(item.get("trim_end") or dur)
            if te <= 0:
                te = dur
            if te <= ts:
                te = ts + 1  # minimum 1s
            valid_clips.append({"path": vpath, "ts": ts, "te": te})

        if not valid_clips:
            return None

        if len(valid_clips) == 1:
            # Single clip: simple trim
            c = valid_clips[0]
            cmd = [
                ffmpeg_path, "-y",
                "-ss", str(c["ts"]),
                "-to", str(c["te"]),
                "-i", c["path"],
                "-c:v", "libx264", "-preset", "fast",
                "-crf", "18",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                "-pix_fmt", "yuv420p",
                output_path,
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            if result.returncode != 0:
                return None
            return output_path

        # Multiple clips: create trimmed segments, then concatenate
        import tempfile
        temp_dir = tempfile.mkdtemp(prefix="arkitect_export_")
        segment_paths = []
        concat_file = None

        try:
            for idx, c in enumerate(valid_clips):
                seg_path = os.path.join(temp_dir, f"seg_{idx:04d}.mp4")
                cmd = [
                    ffmpeg_path, "-y",
                    "-ss", str(c["ts"]),
                    "-to", str(c["te"]),
                    "-i", c["path"],
                    "-c:v", "libx264", "-preset", "fast",
                    "-crf", "18",
                    "-c:a", "aac", "-b:a", "192k",
                    "-r", "30",
                    "-pix_fmt", "yuv420p",
                    "-s", "1920x1080",
                    seg_path,
                ]
                result = subprocess.run(cmd, capture_output=True, timeout=300)
                if result.returncode != 0:
                    continue
                if os.path.exists(seg_path) and os.path.getsize(seg_path) > 0:
                    segment_paths.append(seg_path)

            if not segment_paths:
                return None

            # Write concat list
            concat_file = os.path.join(temp_dir, "concat.txt")
            with open(concat_file, "w") as f:
                for sp in segment_paths:
                    f.write(f"file '{sp}'\n")

            # Concatenate
            cmd = [
                ffmpeg_path, "-y",
                "-f", "concat", "-safe", "0",
                "-i", concat_file,
                "-c", "copy",
                "-movflags", "+faststart",
                output_path,
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=600)
            if result.returncode != 0:
                return None

            return output_path if os.path.exists(output_path) else None

        finally:
            # Cleanup temp segments
            for sp in segment_paths:
                try:
                    os.remove(sp)
                except Exception:
                    pass
            try:
                if concat_file and os.path.exists(concat_file):
                    os.remove(concat_file)
                os.rmdir(temp_dir)
            except Exception:
                pass

    except Exception:
        return None

def _render_editing_room(items_key, page_prefix):
    """Editing room — unified player + timeline in a single HTML/JS component.
    All playback, selection, and scrubbing is handled client-side in JS.
    Only trim, reorder, and remove actions communicate back to Streamlit."""
    _action_key = f"{page_prefix}_action"

    items = st.session_state.get(items_key, [])
    if not items:
        st.info("No clips remaining.")
        return

    clips_js = []
    for i, item in enumerate(items):
        dur = float(item.get("duration") or 10)
        if dur <= 0:
            dur = 10
        ts = float(item.get("trim_start") or 0)
        te = float(item.get("trim_end") or dur)
        if te <= 0:
            te = dur

        # ── THUMBNAIL: base64 image from last_frame_path or cv2 frame extraction ──
        thumb = ""
        # 1) Try last_frame_path (PNG saved during generation)
        _lfp = item.get("last_frame_path") or ""
        if _lfp and os.path.exists(_lfp):
            try:
                ext_lf = os.path.splitext(_lfp)[1].lower()
                mime_map = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".webp": "image/webp",
                }
                mime_lf = mime_map.get(ext_lf, "image/jpeg")
                try:
                    from PIL import Image as _PILImage
                    import io as _io

                    with _PILImage.open(_lfp) as im:
                        im.thumbnail((200, 120), _PILImage.LANCZOS)
                        buf_lf = _io.BytesIO()
                        im.convert("RGB").save(buf_lf, format="JPEG", quality=72)
                        thumb = (
                            f"data:image/jpeg;base64,"
                            f"{_b64.b64encode(buf_lf.getvalue()).decode('ascii')}"
                        )
                except Exception:
                    with open(_lfp, "rb") as f_lf:
                        thumb = (
                            f"data:{mime_lf};base64,"
                            f"{_b64.b64encode(f_lf.read()).decode('ascii')}"
                        )
            except Exception:
                thumb = ""

        # 2) Fallback: extract first frame from video file with cv2
        if not thumb:
            _vid_file = item.get("video_path") or ""
            if _vid_file and not os.path.isabs(_vid_file):
                _vid_abs = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), _vid_file
                )
                if os.path.exists(_vid_abs):
                    _vid_file = _vid_abs
            if _vid_file and os.path.exists(_vid_file):
                try:
                    import cv2

                    cap = cv2.VideoCapture(_vid_file)
                    if cap.isOpened():
                        ret, frame = cap.read()
                        if ret:
                            h, w = frame.shape[:2]
                            scale = min(200 / max(w, 1), 120 / max(h, 1))
                            if scale < 1:
                                frame = cv2.resize(
                                    frame, (int(w * scale), int(h * scale))
                                )
                            _, buf_cv = cv2.imencode(
                                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70]
                            )
                            thumb = (
                                f"data:image/jpeg;base64,"
                                f"{_b64.b64encode(buf_cv.tobytes()).decode('ascii')}"
                            )
                    cap.release()
                except Exception:
                    thumb = ""

        # ── VIDEO URL: local path via static serving (persistent, no expiry) ──
        _local_path = item.get("video_path") or ""
        if _local_path and not os.path.isabs(_local_path):
            _lp_abs = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), _local_path
            )
            if os.path.exists(_lp_abs):
                _local_path = _lp_abs
        vurl = _to_media_url(_local_path) if _local_path else ""

        clips_js.append(
            {
                "i": i,
                "ts": float(round(ts, 2)),
                "te": float(round(te, 2)),
                "d": float(round(dur, 2)),
                "thumb": thumb,
                "vurl": vurl,
                "cap": (item.get("caption", "") or "")[:20],
            }
        )

    clips_b64 = _b64.b64encode(
        json.dumps(clips_js, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    prefix_js = json.dumps(page_prefix)

    st.text_input(
        f"sb_action_input_{page_prefix}",
        value="",
        key=_action_key,
        label_visibility="collapsed",
    )

    _ed_room_html = r"""<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Open+Sans:wght@400;600&display=swap" rel="stylesheet"/>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Sortable/1.15.3/Sortable.min.js"></script>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  .ed-room {
width:100%; max-width:100%;
background:transparent; color:#f0ece4; font-family:'Open Sans',sans-serif;
  }
  .ed-player-wrap { margin-bottom:12px; }
  .ed-player-stack {
position:relative; width:100%; border-radius:8px; overflow:hidden;
background:#000; aspect-ratio:16/9; max-height:380px;
  }
  .ed-player-stack video {
position:absolute; top:0; left:0; width:100%; height:100%;
background:#000; outline:none; object-fit:contain;
transition:opacity 0.08s ease;
  }
  .ed-player-stack video.standby {
opacity:0; pointer-events:none; z-index:1;
  }
  .ed-player-stack video.active {
opacity:1; pointer-events:auto; z-index:2;
  }
  .ed-transport {
display:inline-flex; align-items:center; gap:12px; margin-top:10px;
flex-wrap:wrap;
  }
  .ed-tbtn {
background:#1a1a18; color:#f0ece4; border:none; border-radius:8px;
padding:8px 14px; font-family:'Open Sans',sans-serif; font-size:12px; font-weight:600;
cursor:pointer; transition:background 0.15s ease, color 0.15s ease, opacity 0.15s ease;
  }
  .ed-tbtn:hover { opacity:0.92; }
  .ed-tbtn:disabled { opacity:0.35; cursor:not-allowed; }
  .ed-time-readout {
font-family:'JetBrains Mono',monospace; font-size:12px; color:#9E9E8A;
min-width:140px;
  }
  .ed-timeline-outer {
background:#111; border-radius:8px; padding:8px 12px 28px;
position:relative; margin-top:4px;
  }
  .ed-ruler-tick {
position:absolute; bottom:0; width:1px; background:#333; height:6px;
  }
  .ed-ruler-tick.major { height:10px; background:#444; }
  .ed-ruler-label {
position:absolute; bottom:12px; transform:translateX(-50%);
font-family:'JetBrains Mono',monospace; font-size:10px; color:#555;
white-space:nowrap;
  }
  .ed-track-scroll {
overflow-x:auto; position:relative; min-height:136px;
  }
  .ed-track-inner {
position:relative; display:flex; align-items:stretch;
gap:2px; min-height:128px;
  }
  .ed-playhead {
position:absolute; top:-8px; bottom:-8px; width:2px; background:#FFEB3B;
z-index:10; pointer-events:none;
box-shadow:0 0 8px rgba(255,235,59,0.5);
  }
  .ed-playhead::before {
content:''; position:absolute; top:0; left:50%; transform:translateX(-50%);
width:0; height:0;
border-left:6px solid transparent; border-right:6px solid transparent;
border-top:8px solid #FFEB3B;
  }
  .ed-playhead-grab {
position:absolute; top:-8px; bottom:-8px; width:24px; margin-left:-11px;
z-index:11; cursor:col-resize; pointer-events:auto;
  }
  .ed-playhead-grab:hover ~ .ed-playhead,
  .ed-playhead-grab.dragging ~ .ed-playhead {
width:3px; box-shadow:0 0 10px rgba(255,235,59,0.7);
  }
  .ed-ruler {
position:relative; height:22px; margin-bottom:6px;
border-bottom:1px solid #222;
cursor:col-resize;
  }
  .ed-clip {
flex-shrink:0; height:128px; position:relative; cursor:pointer;
overflow:hidden; border:2px solid transparent; border-radius:4px;
background:#1a1a18; transition:border-color 0.15s ease, box-shadow 0.15s ease, opacity 0.15s ease;
opacity:0.88; z-index:2;
  }
  .ed-clip:hover { border-color:rgba(255,255,255,0.2); opacity:1; }
  .ed-clip.active {
border-color:#fff; opacity:1;
box-shadow:0 0 0 1px rgba(255,255,255,0.25), 0 0 12px rgba(255,235,59,0.15);
  }
  .ed-clip.sortable-ghost { opacity:0.25; }
  .ed-clip img, .ed-clip video {
width:100%; height:100%; object-fit:cover; display:block; pointer-events:none;
  }
  .ed-clip-fallback {
width:100%; height:100%; background:linear-gradient(135deg,#2a2a28,#1a1a18);
display:flex; align-items:center; justify-content:center;
color:#555; font-size:11px; font-family:'JetBrains Mono',monospace;
  }
  .ed-badge {
position:absolute; top:3px; left:3px; font-size:9px; font-weight:600;
background:rgba(0,0,0,0.55); color:#f0ece4; padding:2px 5px; border-radius:3px;
pointer-events:none; z-index:3; font-family:'Open Sans',sans-serif;
  }
  .ed-rm {
position:absolute; top:2px; right:2px; z-index:6; width:18px; height:18px;
line-height:16px; text-align:center; font-size:14px; color:transparent;
cursor:pointer; transition:color 0.15s ease; border-radius:3px;
  }
  .ed-clip:hover .ed-rm { color:rgba(255,255,255,0.45); }
  .ed-rm:hover { color:#ff5252 !important; background:rgba(0,0,0,0.35); }
  .ed-trim-l, .ed-trim-r {
position:absolute; top:0; width:5px; height:100%; background:#fff;
cursor:col-resize; z-index:5; transition:background 0.15s ease;
  }
  .ed-trim-l { left:0; border-radius:2px 0 0 2px; }
  .ed-trim-r { right:0; border-radius:0 2px 2px 0; }
  .ed-trim-l:hover, .ed-trim-r:hover { background:#00E5CC; }
  .ed-total {
position:absolute; bottom:8px; right:12px;
font-family:'JetBrains Mono',monospace; font-size:11px; color:#9E9E8A;
  }
  .ed-zoom-bar {
display:flex; align-items:center; gap:8px;
padding:6px 0 0;
  }
  .ed-zoom-btn {
background:#1a1a18; color:#f0ece4; border:none; border-radius:4px;
width:26px; height:26px; font-size:16px; font-weight:600;
cursor:pointer; display:flex; align-items:center; justify-content:center;
transition:background 0.15s;
font-family:'JetBrains Mono',monospace;
  }
  .ed-zoom-btn:hover { background:#2a2a28; }
  .ed-zoom-slider {
-webkit-appearance:none; appearance:none;
width:100px; height:4px; background:#333; border-radius:2px;
outline:none; cursor:pointer;
  }
  .ed-zoom-slider::-webkit-slider-thumb {
-webkit-appearance:none; width:12px; height:12px;
background:#FFEB3B; border-radius:50%; cursor:pointer;
  }
  .ed-zoom-label {
font-family:'JetBrains Mono',monospace; font-size:10px;
color:#9E9E8A; min-width:32px; text-align:center;
  }
</style>
<div class="ed-room">
  <div class="ed-player-wrap">
<div class="ed-player-stack" id="edPlayerStack">
  <video id="edVidA" controls playsinline></video>
  <video id="edVidB" controls playsinline></video>
</div>
<div class="ed-transport">
  <button type="button" class="ed-tbtn" id="edPrev">PREV</button>
  <button type="button" class="ed-tbtn" id="edPlayPause">PLAY</button>
  <button type="button" class="ed-tbtn" id="edNext">NEXT</button>
  <span class="ed-time-readout" id="edTimeReadout">00:00 / 00:00</span>
</div>
  </div>
  <div class="ed-timeline-outer">
<div class="ed-ruler" id="edRuler"></div>
<div class="ed-track-scroll" id="edTrackScroll">
  <div class="ed-track-inner" id="edTrackInner">
    <div class="ed-playhead-grab" id="edPlayheadGrab"></div>
    <div class="ed-playhead" id="edPlayhead"></div>
  </div>
</div>
<div class="ed-zoom-bar">
  <button type="button" class="ed-zoom-btn" id="edZoomOut">-</button>
  <input type="range" class="ed-zoom-slider" id="edZoomSlider" min="1" max="10" step="0.5" value="1"/>
  <button type="button" class="ed-zoom-btn" id="edZoomIn">+</button>
  <span class="ed-zoom-label" id="edZoomLabel">1x</span>
</div>
<div class="ed-total" id="edTotalLab"></div>
  </div>
</div>
<script>
(function(){
var CLIPS = JSON.parse(atob('__CLIPS_B64__'));
var PREFIX = __PREFIX_JSON__;
var activeIdx = 0;
var _sortable = null;
var trimState = null;

function sendAction(str) {
  if (!window.parent.__sbBridgeInstalled) {
window.parent.__sbBridgeInstalled = true;
window.parent.addEventListener('message', function(ev) {
  var d = ev.data || {};
  if (d.type !== 'sb_action' || !d.prefix) return;
  var inp = window.parent.document.querySelector(
    'input[aria-label="sb_action_input_' + d.prefix + '"]'
  );
  if (!inp) return;
  var ns = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value'
  ).set;
  ns.call(inp, d.payload || '');
  inp.dispatchEvent(new Event('input', {bubbles:true}));
  inp.dispatchEvent(new Event('change', {bubbles:true}));
});
  }
  window.parent.postMessage({type:'sb_action', prefix:PREFIX, payload:str}, '*');
}

function ensureClip(c) {
  if (!c.d || c.d <= 0) c.d = 10;
  if (c.te <= 0) c.te = c.d;
  if (c.ts < 0) c.ts = 0;
  if (c.te < c.ts + 0.1) c.te = c.ts + 0.1;
}
CLIPS.forEach(ensureClip);

function trimDur(c) { return Math.max(0.01, c.te - c.ts); }
function totalDur() {
  var t = 0;
  CLIPS.forEach(function(c) { t += trimDur(c); });
  return t;
}

function fmtTime(s) {
  if (isNaN(s) || s < 0) s = 0;
  var m = Math.floor(s / 60);
  var sec = Math.floor(s % 60);
  return (m < 10 ? '0' : '') + m + ':' + (sec < 10 ? '0' : '') + sec;
}

function updatePlayhead() {
  var inner = document.getElementById('edTrackInner');
  var ph = document.getElementById('edPlayhead');
  var phg = document.getElementById('edPlayheadGrab');
  if (!inner || !ph) return;
  var td = totalDur();
  var el = getElapsed();
  var w = inner.offsetWidth;
  if (w <= 0 || td <= 0) { ph.style.left = '0px'; if (phg) phg.style.left = '0px'; return; }
  var px = (el / td) * w;
  ph.style.left = px + 'px';
  if (phg) phg.style.left = px + 'px';
}

function updateRuler() {
  var ruler = document.getElementById('edRuler');
  if (!ruler) return;
  ruler.innerHTML = '';
  var td = totalDur();
  if (td <= 0) return;
  var t;
  for (t = 0; t <= td + 0.001; t += 5) {
var pct = (t / td) * 100;
var tick = document.createElement('div');
tick.className = 'ed-ruler-tick' + (Math.round(t) % 10 === 0 ? ' major' : '');
tick.style.left = pct + '%';
ruler.appendChild(tick);
  }
  for (t = 0; t <= td + 0.001; t += 10) {
var lpct = (t / td) * 100;
var lab = document.createElement('div');
lab.className = 'ed-ruler-label';
lab.style.left = lpct + '%';
lab.textContent = String(Math.round(t)) + 's';
ruler.appendChild(lab);
  }
}

function buildTrack() {
  var track = document.getElementById('edTrackInner');
  var scroll = document.getElementById('edTrackScroll');
  if (!track || !scroll) return;
  if (_sortable && typeof _sortable.destroy === 'function') {
_sortable.destroy();
_sortable = null;
  }
  track.querySelectorAll('.ed-clip').forEach(function(n) { n.remove(); });
  var td = totalDur();
  var cw = scroll.clientWidth || 800;
  var widths = [];
  CLIPS.forEach(function(c) {
var w = Math.max(60, Math.round((trimDur(c) / Math.max(td, 0.01)) * cw * zoomLevel));
widths.push(w);
  });
  var sumW = widths.reduce(function(a,b){return a+b;}, 0) + Math.max(0, CLIPS.length - 1) * 2;
  track.style.width = Math.max(sumW, cw) + 'px';
  var ph = document.getElementById('edPlayhead');
  var h = (track.offsetHeight || 64) + 'px';
  if (ph) { ph.style.height = h; }
  var phg = document.getElementById('edPlayheadGrab');
  if (phg) { phg.style.height = h; }

  CLIPS.forEach(function(clip, i) {
var div = document.createElement('div');
div.className = 'ed-clip' + (i === activeIdx ? ' active' : '');
div.dataset.idx = String(i);
div.style.width = widths[i] + 'px';
div.style.minWidth = '60px';

if (clip.thumb) {
  div.innerHTML = '<img src="' + clip.thumb + '" draggable="false" alt=""/>';
} else if (clip.vurl) {
  div.innerHTML = '<video src="' + clip.vurl + '" preload="metadata" muted playsinline></video>';
} else {
  div.innerHTML = '<div class="ed-clip-fallback">' + (i + 1) + '</div>';
}
div.innerHTML += '<div class="ed-badge">' + (i + 1) + '</div>';
div.innerHTML += '<div class="ed-rm" data-rm="' + i + '">&times;</div>';
if (i === activeIdx) {
  div.innerHTML += '<div class="ed-trim-l" data-idx="' + i + '" data-side="left"></div>';
  div.innerHTML += '<div class="ed-trim-r" data-idx="' + i + '" data-side="right"></div>';
}
div.addEventListener('click', function(e) {
  if (e.target.closest('.ed-trim-l') || e.target.closest('.ed-trim-r') ||
      e.target.closest('.ed-rm')) return;
  selectClip(i, false);
  var vid = activeVid;
  if (vid && CLIPS[i].vurl) {
    vid.pause();
    syncPlayBtn();
  }
});
track.appendChild(div);
  });

  track.querySelectorAll('.ed-rm').forEach(function(btn) {
btn.addEventListener('click', function(e) {
  e.stopPropagation();
  removeClip(parseInt(btn.getAttribute('data-rm'), 10));
});
  });

  if (typeof Sortable !== 'undefined') {
_sortable = Sortable.create(track, {
  animation: 180,
  ghostClass: 'sortable-ghost',
  draggable: '.ed-clip',
  filter: '.ed-trim-l,.ed-trim-r,.ed-rm',
  preventOnFilter: false,
  onEnd: function() {
    var cards = track.querySelectorAll('.ed-clip');
    var order = Array.from(cards).map(function(c) { return parseInt(c.dataset.idx, 10); });
    if (order.length !== CLIPS.length) return;
    var timePos = getElapsed();
    var newClips = order.map(function(oi) { return CLIPS[oi]; });
    CLIPS = newClips;
    for (var k = 0; k < CLIPS.length; k++) CLIPS[k].i = k;
    var acc = 0;
    var foundIdx = 0;
    var localT = 0;
    for (var j = 0; j < CLIPS.length; j++) {
      var d = trimDur(CLIPS[j]);
      if (timePos <= acc + d + 0.001) {
        foundIdx = j;
        localT = CLIPS[j].ts + (timePos - acc);
        break;
      }
      acc += d;
      if (j === CLIPS.length - 1) {
        foundIdx = j;
        localT = CLIPS[j].te;
      }
    }
    activeIdx = foundIdx;
    var v = activeVid;
    var c = CLIPS[activeIdx];
    if (c && c.vurl && v) {
      var isSame = false;
      try {
        var abs = new URL(c.vurl, window.location.href).href;
        isSame = (v.src === abs);
      } catch(e) { isSame = v.src && v.src.indexOf(c.vurl) >= 0; }
      if (isSame && v.readyState >= 1) {
        v.currentTime = localT;
        buildTrack();
        updatePlayhead();
        updateReadout();
      } else {
        v.src = c.vurl;
        v.addEventListener('loadedmetadata', function once() {
          v.removeEventListener('loadedmetadata', once);
          v.currentTime = localT;
          buildTrack();
          updatePlayhead();
          updateReadout();
        });
        v.load();
      }
    } else {
      buildTrack();
      updatePlayhead();
      updateReadout();
    }
    preloadInto(standbyVid, activeIdx + 1);
    sendAction('reorder:' + order.join(','));
  }
});
  }
  updateRuler();
  updatePlayhead();
  updateReadout();
}

/* ═══ Double-buffer video engine ═══ */
var vidA = document.getElementById('edVidA');
var vidB = document.getElementById('edVidB');
vidA.className = 'active';
vidB.className = 'standby';
var activeVid = vidA;
var standbyVid = vidB;
var rafId = null;
var trimEndLatch = false;

function activeVideo() { return activeVid; }

function getElapsed() {
  var v = activeVid;
  var off = 0;
  for (var i = 0; i < activeIdx; i++) off += trimDur(CLIPS[i]);
  if (!v || !CLIPS.length) return off;
  var c = CLIPS[activeIdx];
  if (!c || !c.vurl) return off;
  return off + Math.max(0, Math.min(v.currentTime - c.ts, trimDur(c)));
}

function updateReadout() {
  var v = activeVid;
  var el = document.getElementById('edTimeReadout');
  if (!el) return;
  var td = totalDur();
  var c = CLIPS[activeIdx];
  var inClip = 0;
  if (v && c && c.vurl) inClip = Math.max(0, v.currentTime - c.ts);
  el.textContent = fmtTime(inClip) + ' / ' + fmtTime(td);
  var tl = document.getElementById('edTotalLab');
  if (tl) tl.textContent = 'TOTAL ' + fmtTime(td);
}

function syncPlayBtn() {
  var v = activeVid;
  var b = document.getElementById('edPlayPause');
  if (!v || !b) return;
  b.textContent = v.paused ? 'PLAY' : 'PAUSE';
}

function stopRaf() {
  if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
}
function loop() {
  updatePlayhead();
  updateReadout();
  var v = activeVid;
  if (v && !v.paused) rafId = requestAnimationFrame(loop);
  else rafId = null;
}
function startRaf() {
  if (!rafId) rafId = requestAnimationFrame(loop);
}

function preloadInto(vid, idx) {
  if (idx < 0 || idx >= CLIPS.length) return;
  var c = CLIPS[idx];
  if (!c.vurl) return;
  var already = false;
  try {
var abs = new URL(c.vurl, window.location.href).href;
already = (vid.src === abs);
  } catch(e) {
already = vid.src && vid.src.indexOf(c.vurl) >= 0;
  }
  if (!already) {
vid.src = c.vurl;
vid.addEventListener('loadedmetadata', function once() {
  vid.removeEventListener('loadedmetadata', once);
  vid.currentTime = c.ts;
});
try { vid.load(); } catch(e) {}
  }
}

function swapToStandby(andPlay) {
  var old = activeVid;
  old.pause();
  old.className = 'standby';
  standbyVid = old;
  var nv = (old === vidA) ? vidB : vidA;
  nv.className = 'active';
  activeVid = nv;
  bindActiveEvents();
  if (andPlay) {
nv.play().catch(function(){});
  }
  syncPlayBtn();
  buildTrack();
  updatePlayhead();
  updateReadout();
  if (andPlay) startRaf();
}

function loadVideoAt(idx, andPlay, onReady) {
  activeIdx = Math.max(0, Math.min(idx, CLIPS.length - 1));
  var c = CLIPS[activeIdx];
  var v = activeVid;
  var wantPlay = andPlay === true;
  if (!c || !c.vurl) {
v.removeAttribute('src');
try { v.load(); } catch(e) {}
buildTrack(); updatePlayhead(); updateReadout(); syncPlayBtn();
if (onReady) onReady();
return;
  }
  var isSame = false;
  try {
var absUrl = new URL(c.vurl, window.location.href).href;
isSame = (v.src === absUrl);
  } catch(err) {
isSame = v.src && v.src.indexOf(c.vurl) >= 0;
  }
  if (isSame && v.readyState >= 1) {
var realDur = v.duration;
if (realDur && isFinite(realDur) && realDur > 0) {
  c.d = Math.round(realDur * 100) / 100;
  if (c.te > c.d || c.te <= 0) c.te = c.d;
  if (c.ts >= c.d) c.ts = 0;
}
v.currentTime = c.ts;
if (wantPlay) { v.play().catch(function(){}); startRaf(); }
buildTrack(); updatePlayhead(); updateReadout(); syncPlayBtn();
preloadInto(standbyVid, activeIdx + 1);
if (onReady) onReady();
return;
  }
  v.src = c.vurl;
  var onMeta = function() {
v.removeEventListener('loadedmetadata', onMeta);
var realDur = v.duration;
if (realDur && isFinite(realDur) && realDur > 0) {
  c.d = Math.round(realDur * 100) / 100;
  if (c.te > c.d || c.te <= 0) c.te = c.d;
  if (c.ts >= c.d) c.ts = 0;
}
v.currentTime = c.ts;
if (wantPlay) { v.play().catch(function(){}); startRaf(); }
buildTrack(); updatePlayhead(); updateReadout(); syncPlayBtn();
preloadInto(standbyVid, activeIdx + 1);
if (onReady) onReady();
  };
  v.addEventListener('loadedmetadata', onMeta);
  try { v.load(); } catch(e2) {}
  syncPlayBtn();
}

function selectClip(idx, playOn) {
  trimEndLatch = false;
  loadVideoAt(idx, playOn);
}

function bindActiveEvents() {
  var v = activeVid;
  v.onplay = function() { syncPlayBtn(); startRaf(); };
  v.onpause = function() { syncPlayBtn(); stopRaf(); updatePlayhead(); updateReadout(); };
  v.onseeked = function() { trimEndLatch = false; updatePlayhead(); updateReadout(); };
  v.ontimeupdate = handleTimeUpdate;
  v.onended = function() {
if (activeIdx < CLIPS.length - 1) {
  trimEndLatch = true;
  advanceToNext();
} else {
  syncPlayBtn(); updatePlayhead(); updateReadout();
}
  };
}

function handleTimeUpdate() {
  if (trimEndLatch) return;
  var v = activeVid;
  var c = CLIPS[activeIdx];
  if (!c || !c.vurl) { updatePlayhead(); updateReadout(); return; }
  if (c.te < c.d && v.currentTime >= c.te - 0.12) {
if (activeIdx < CLIPS.length - 1) {
  trimEndLatch = true;
  advanceToNext();
} else {
  v.pause();
  syncPlayBtn();
}
return;
  }
  updatePlayhead();
  updateReadout();
}

function advanceToNext() {
  var nextIdx = activeIdx + 1;
  if (nextIdx >= CLIPS.length) { trimEndLatch = false; return; }
  var nc = CLIPS[nextIdx];
  activeIdx = nextIdx;
  if (!nc.vurl) {
activeVid.pause();
trimEndLatch = false;
buildTrack(); syncPlayBtn();
return;
  }
  var sb = standbyVid;
  var sbReady = false;
  try {
var abs2 = new URL(nc.vurl, window.location.href).href;
sbReady = (sb.src === abs2 && sb.readyState >= 2);
  } catch(e) {
sbReady = (sb.src && sb.src.indexOf(nc.vurl) >= 0 && sb.readyState >= 2);
  }
  if (sbReady) {
sb.currentTime = nc.ts;
swapToStandby(true);
preloadInto(standbyVid, activeIdx + 1);
trimEndLatch = false;
  } else {
sb.src = nc.vurl;
sb.addEventListener('canplay', function once() {
  sb.removeEventListener('canplay', once);
  sb.currentTime = nc.ts;
  swapToStandby(true);
  preloadInto(standbyVid, activeIdx + 1);
  trimEndLatch = false;
});
try { sb.load(); } catch(e3) {}
  }
}

/* ═══ Remove clip ═══ */
function removeClip(idx) {
  if (idx < 0 || idx >= CLIPS.length) return;
  var timePos = getElapsed();
  CLIPS.splice(idx, 1);
  if (!CLIPS.length) {
activeIdx = 0;
var v = activeVid;
if (v) { v.pause(); v.removeAttribute('src'); try { v.load(); } catch(e) {} }
buildTrack(); syncPlayBtn(); updatePlayhead(); updateReadout();
sendAction('remove:' + idx);
return;
  }
  for (var k = 0; k < CLIPS.length; k++) CLIPS[k].i = k;
  var acc = 0;
  var foundIdx = 0;
  for (var j = 0; j < CLIPS.length; j++) {
var d = trimDur(CLIPS[j]);
if (timePos <= acc + d + 0.001) { foundIdx = j; break; }
acc += d;
if (j === CLIPS.length - 1) foundIdx = j;
  }
  var wasPaused = activeVid && activeVid.paused;
  activeIdx = foundIdx;
  var c = CLIPS[activeIdx];
  var v = activeVid;
  if (c && c.vurl && v) {
var isSame = false;
try {
  var abs = new URL(c.vurl, window.location.href).href;
  isSame = (v.src === abs);
} catch(e) { isSame = v.src && v.src.indexOf(c.vurl) >= 0; }
if (isSame && v.readyState >= 1) {
  buildTrack(); updatePlayhead(); updateReadout();
} else {
  v.src = c.vurl;
  v.addEventListener('loadedmetadata', function once() {
    v.removeEventListener('loadedmetadata', once);
    v.currentTime = c.ts;
    if (!wasPaused) v.play().catch(function(){});
    buildTrack(); updatePlayhead(); updateReadout(); syncPlayBtn();
  });
  v.load();
}
  } else {
buildTrack(); updatePlayhead(); updateReadout();
  }
  preloadInto(standbyVid, activeIdx + 1);
  sendAction('remove:' + idx);
}

/* ═══ Timeline zoom ═══ */
var zoomLevel = 1;

function applyZoom(val) {
  zoomLevel = Math.max(1, Math.min(10, Math.round(val * 2) / 2));
  var sl = document.getElementById('edZoomSlider');
  var lb = document.getElementById('edZoomLabel');
  if (sl) sl.value = zoomLevel;
  if (lb) lb.textContent = zoomLevel + 'x';
  buildTrack();
  updateRuler();
  updatePlayhead();
}

document.getElementById('edZoomIn').addEventListener('click', function() {
  applyZoom(zoomLevel + 0.5);
});
document.getElementById('edZoomOut').addEventListener('click', function() {
  applyZoom(zoomLevel - 0.5);
});
document.getElementById('edZoomSlider').addEventListener('input', function() {
  applyZoom(parseFloat(this.value));
});

document.getElementById('edTrackScroll').addEventListener('wheel', function(e) {
  if (e.ctrlKey || e.metaKey) {
e.preventDefault();
applyZoom(zoomLevel + (e.deltaY < 0 ? 0.5 : -0.5));
  }
}, {passive:false});

/* ═══ Transport controls ═══ */
document.getElementById('edPrev').addEventListener('click', function() {
  if (activeIdx <= 0) return;
  var wasP = activeVid && !activeVid.paused;
  selectClip(activeIdx - 1, wasP);
});
document.getElementById('edNext').addEventListener('click', function() {
  if (activeIdx >= CLIPS.length - 1) return;
  var wasP = activeVid && !activeVid.paused;
  selectClip(activeIdx + 1, wasP);
});
document.getElementById('edPlayPause').addEventListener('click', function() {
  var v = activeVid;
  if (!v || !CLIPS[activeIdx] || !CLIPS[activeIdx].vurl) return;
  if (v.paused) { v.play().catch(function(){}); } else { v.pause(); }
  syncPlayBtn();
});

/* ═══ Keyboard shortcuts ═══ */
document.addEventListener('keydown', function(e) {
  var tag = (e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea') return;
  var v = activeVid;
  switch(e.code) {
case 'Space': case 'KeyK':
  e.preventDefault();
  if (!v || !CLIPS[activeIdx] || !CLIPS[activeIdx].vurl) return;
  if (v.paused) { v.play().catch(function(){}); } else { v.pause(); }
  syncPlayBtn();
  break;
case 'ArrowLeft':
  e.preventDefault();
  if (activeIdx > 0) selectClip(activeIdx - 1, v && !v.paused);
  break;
case 'ArrowRight':
  e.preventDefault();
  if (activeIdx < CLIPS.length - 1) selectClip(activeIdx + 1, v && !v.paused);
  break;
case 'KeyJ':
  e.preventDefault();
  if (v && CLIPS[activeIdx]) {
    v.currentTime = Math.max(CLIPS[activeIdx].ts, v.currentTime - 1);
    updatePlayhead(); updateReadout();
  }
  break;
case 'KeyL':
  e.preventDefault();
  if (v && CLIPS[activeIdx]) {
    v.currentTime = Math.min(CLIPS[activeIdx].te, v.currentTime + 1);
    updatePlayhead(); updateReadout();
  }
  break;
case 'Home':
  e.preventDefault(); selectClip(0, false); break;
case 'End':
  e.preventDefault(); selectClip(CLIPS.length - 1, false); break;
case 'Delete': case 'Backspace':
  e.preventDefault();
  if (CLIPS.length > 0) removeClip(activeIdx);
  break;
case 'Equal': case 'NumpadAdd':
  if (e.ctrlKey || e.metaKey) { e.preventDefault(); applyZoom(zoomLevel + 0.5); }
  break;
case 'Minus': case 'NumpadSubtract':
  if (e.ctrlKey || e.metaKey) { e.preventDefault(); applyZoom(zoomLevel - 0.5); }
  break;
case 'Digit0': case 'Numpad0':
  if (e.ctrlKey || e.metaKey) { e.preventDefault(); applyZoom(1); }
  break;
  }
});

/* ── Playhead scrub system: click ruler or drag playhead to seek ── */
var scrubState = null;

function scrubToX(clientX) {
  var inner = document.getElementById('edTrackInner');
  var scroll = document.getElementById('edTrackScroll');
  if (!inner || !scroll) return;
  var rect = inner.getBoundingClientRect();
  var x = clientX - rect.left + scroll.scrollLeft;
  var w = inner.offsetWidth;
  var td = totalDur();
  if (w <= 0 || td <= 0) return;
  var gt = Math.max(0, Math.min((x / w) * td, td));
  var acc = 0;
  for (var i = 0; i < CLIPS.length; i++) {
var d = trimDur(CLIPS[i]);
if (gt <= acc + d + 0.0001) {
  var localT = CLIPS[i].ts + (gt - acc);
  var v = activeVid;
  var c = CLIPS[i];
  if (i !== activeIdx) {
    trimEndLatch = false;
    activeIdx = i;
    if (c.vurl && v) {
      v.pause();
      v.src = c.vurl;
      v.addEventListener('loadedmetadata', function once() {
        v.removeEventListener('loadedmetadata', once);
        v.currentTime = localT;
        buildTrack();
        updatePlayhead();
        updateReadout();
        syncPlayBtn();
      });
      v.load();
    } else {
      buildTrack();
      updatePlayhead();
      updateReadout();
    }
  } else if (v && c.vurl) {
    v.currentTime = localT;
    updatePlayhead();
    updateReadout();
  }
  return;
}
acc += d;
  }
}

document.getElementById('edPlayheadGrab').addEventListener('mousedown', function(e) {
  e.preventDefault();
  e.stopPropagation();
  scrubState = { source: 'playhead' };
  this.classList.add('dragging');
  var v = activeVid;
  if (v && !v.paused) { scrubState.wasPlaying = true; v.pause(); }
  scrubToX(e.clientX);
});

document.getElementById('edRuler').addEventListener('mousedown', function(e) {
  e.preventDefault();
  scrubState = { source: 'ruler' };
  var v = activeVid;
  if (v && !v.paused) { scrubState.wasPlaying = true; v.pause(); }
  scrubToX(e.clientX);
});

document.getElementById('edTrackScroll').addEventListener('mousedown', function(e) {
  if (e.target.closest('.ed-clip') || e.target.closest('.ed-playhead-grab')) return;
  e.preventDefault();
  scrubState = { source: 'track' };
  var v = activeVid;
  if (v && !v.paused) { scrubState.wasPlaying = true; v.pause(); }
  scrubToX(e.clientX);
});

document.addEventListener('mousemove', function(e) {
  if (!scrubState) return;
  e.preventDefault();
  scrubToX(e.clientX);
});

document.addEventListener('mouseup', function(e) {
  if (!scrubState) return;
  var phg = document.getElementById('edPlayheadGrab');
  if (phg) phg.classList.remove('dragging');
  if (scrubState.wasPlaying) {
var v = activeVid;
if (v) v.play().catch(function(){});
syncPlayBtn();
  }
  scrubState = null;
});

document.addEventListener('mousedown', function(e) {
  var h = e.target;
  if (!h.classList || (!h.classList.contains('ed-trim-l') && !h.classList.contains('ed-trim-r'))) return;
  e.preventDefault();
  e.stopPropagation();
  var idx = parseInt(h.getAttribute('data-idx'), 10);
  if (isNaN(idx) || idx < 0 || idx >= CLIPS.length) return;
  var clipEl = h.closest('.ed-clip');
  if (!clipEl) return;
  var rect = clipEl.getBoundingClientRect();
  trimState = {
idx: idx,
side: h.getAttribute('data-side'),
startX: e.clientX,
rect: rect,
origStart: CLIPS[idx].ts,
origEnd: CLIPS[idx].te,
duration: CLIPS[idx].d
  };
});
document.addEventListener('mousemove', function(e) {
  if (!trimState) return;
  e.preventDefault();
  var dx = e.clientX - trimState.startX;
  var span = Math.max(0.1, trimState.origEnd - trimState.origStart);
  var ds = dx / (trimState.rect.width / span);
  if (trimState.side === 'left') {
CLIPS[trimState.idx].ts = Math.round(
  Math.max(0, Math.min(trimState.origStart + ds, trimState.origEnd - 0.3)) * 100) / 100;
  } else {
CLIPS[trimState.idx].te = Math.round(
  Math.max(trimState.origStart + 0.3, Math.min(trimState.origEnd + ds, trimState.duration)) * 100) / 100;
  }
  ensureClip(CLIPS[trimState.idx]);
  buildTrack();
  var v = activeVid;
  if (v && trimState.idx === activeIdx && CLIPS[activeIdx].vurl) {
if (v.currentTime < CLIPS[activeIdx].ts) v.currentTime = CLIPS[activeIdx].ts;
if (v.currentTime > CLIPS[activeIdx].te) v.currentTime = CLIPS[activeIdx].te;
  }
  updatePlayhead();
});
document.addEventListener('mouseup', function() {
  if (trimState) {
var c = CLIPS[trimState.idx];
sendAction('trim:' + trimState.idx + ':' + c.ts + ':' + c.te + ':' + c.d);
trimState = null;
  }
});

window.addEventListener('resize', function() {
  buildTrack();
  updateRuler();
});

function init() {
  bindActiveEvents();
  if (CLIPS.length) {
loadVideoAt(0, false);
  } else {
buildTrack();
  }
}
if (document.readyState === 'complete' || document.readyState === 'interactive') {
  setTimeout(init, 80);
} else {
  document.addEventListener('DOMContentLoaded', function() { setTimeout(init, 80); });
}
})();
</script>"""

    html_out = (
        _ed_room_html.replace("__CLIPS_B64__", clips_b64).replace(
            "__PREFIX_JSON__", prefix_js
        )
    )
    components.html(html_out, height=700, scrolling=False)


def _render_storyboard_save_load(page_prefix, key_suffix="", use_projects_layout=False):
    is_storyboard = page_prefix.startswith("sbi")
    snap_key = "storyboard" if is_storyboard else "editing"
    mode_key = "sb_mode" if is_storyboard else "ed_mode"
    name_key = "sb_active_name" if is_storyboard else "ed_active_name"
    items_key = "sb_active_images" if is_storyboard else "ed_active_videos"
    media_type = "image" if is_storyboard else "video"

    # ════════════════════════════════════════════
    #  STORYBOARD MANAGER
    # ════════════════════════════════════════════
    if page_prefix == "sbi":
        snaps = load_all_snapshots()
        all_sb = snaps.get("storyboard", {})
        active_proj = get_active_project_id()
        sb_names = filter_snapshot_names(all_sb, active_proj)

        if use_projects_layout and st.session_state.sb_mode == "pick":
            st.session_state.sb_mode = None
            st.rerun()

        # ── Entry screen: no active storyboard ──────
        if st.session_state.sb_mode is None:

            if use_projects_layout:
                snaps_data = snaps.get("storyboard", {})
                st.text_input(
                    "sb_pick_bridge",
                    key="sb_pick_act",
                    on_change=_on_storyboard_grid_pick_change,
                    label_visibility="collapsed",
                )
                if not sb_names:
                    st.info("No storyboards yet. Use **NEW STORYBOARD** in the sidebar to create one.")
                else:
                    sb_cards = []
                    active_nm = st.session_state.get("sb_active_name") or ""
                    cur_mode = st.session_state.get("sb_mode")
                    for sname in sb_names:
                        raw_items = snapshot_entry_items(snaps_data.get(sname, []))
                        sb_thumb = ""
                        for _si in raw_items:
                            _sip = _si.get("image_path") or _si.get("url") or ""
                            if _sip and os.path.exists(_sip):
                                try:
                                    from PIL import Image as _PILImage
                                    import io as _io
                                    with _PILImage.open(_sip) as _sim:
                                        _sim.thumbnail((400, 240), _PILImage.LANCZOS)
                                        _sbuf = _io.BytesIO()
                                        _sim.convert("RGB").save(_sbuf, format="JPEG", quality=75)
                                        sb_thumb = f"data:image/jpeg;base64,{_b64.b64encode(_sbuf.getvalue()).decode('ascii')}"
                                except Exception:
                                    pass
                            elif _sip and _sip.startswith("http"):
                                sb_thumb = _sip
                            if sb_thumb:
                                break
                        sb_cards.append({
                            "name": sname,
                            "thumb": sb_thumb,
                            "frames": len(raw_items),
                            "is_active": (sname == active_nm and cur_mode in ("new", "loaded")),
                        })

                    COLS = 4
                    cards_html_parts = []
                    for c in sb_cards:
                        _cname = _html_stdlib.escape(c["name"])
                        _thumb = (c["thumb"] or "").replace('"', "&quot;")
                        bcol = "#FFEB3B" if c["is_active"] else "transparent"
                        init = _html_stdlib.escape(c["name"][:2].upper())
                        _nf = str(c["frames"])
                        if c["thumb"]:
                            thumb_block = (
                                f'<img src="{_thumb}" style="width:100%;height:100%;object-fit:cover;display:block;" '
                                f'draggable="false" alt=""/>'
                            )
                        else:
                            thumb_block = (
                                f'<span style="color:#3a3a38;font-size:1.6rem;font-weight:300;'
                                f'font-family:Open Sans,sans-serif;">{init}</span>'
                            )
                        _safe = c["name"].replace("\\", "\\\\").replace("'", "\\'")
                        cards_html_parts.append(
                            f'''
                            <div class="proj-cell" onclick="sbPick('{_safe}')">
                                <div class="proj-thumb" style="border-color:{bcol};">{thumb_block}</div>
                                <div class="proj-title">{_cname}</div>
                                <div class="proj-meta">Frames: {_nf}</div>
                            </div>'''
                        )
                    cards_html = "".join(cards_html_parts)
                    nrows = (len(sb_cards) + COLS - 1) // COLS
                    grid_h = max(420, nrows * 210)
                    sb_grid_html = f'''
                    <style>
                        * {{ margin:0; padding:0; box-sizing:border-box; }}
                        body {{ background:transparent; font-family: Open Sans, sans-serif; }}
                        .proj-grid {{
                            display:grid;
                            grid-template-columns:repeat({COLS}, minmax(0, 1fr));
                            gap:14px;
                            padding:4px;
                        }}
                        .proj-cell {{ cursor:pointer; }}
                        .proj-thumb {{
                            position:relative;
                            border:2px solid transparent;
                            border-radius:10px;
                            overflow:hidden;
                            aspect-ratio:16/9;
                            background:#111110;
                            margin-bottom:6px;
                            display:flex;
                            align-items:center;
                            justify-content:center;
                            transition:border-color 0.15s ease;
                        }}
                        .proj-cell:hover .proj-thumb {{ border-color:rgba(255,235,59,0.45) !important; }}
                        .proj-title {{
                            color:#f0ece4;
                            font-size:0.78rem;
                            font-weight:600;
                            margin:0 0 4px;
                            line-height:1.25;
                            word-break:break-word;
                        }}
                        .proj-meta {{
                            color:#7a7a6e;
                            font-size:0.62rem;
                            line-height:1.35;
                            margin:0;
                        }}
                    </style>
                    <div class="proj-grid">{cards_html}</div>
                    <script>
                        function sbPick(name) {{
                            if (!name) return;
                            var inp = window.parent.document.querySelector(
                                'input[aria-label="sb_pick_bridge"]'
                            );
                            if (!inp) return;
                            var ns = Object.getOwnPropertyDescriptor(
                                window.HTMLInputElement.prototype, 'value'
                            ).set;
                            var payload = name + '|' + Date.now();
                            ns.call(inp, payload);
                            inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            try {{
                                inp.dispatchEvent(new InputEvent('input', {{
                                    bubbles: true, inputType: 'insertFromPaste', data: payload
                                }}));
                            }} catch (e) {{}}
                            try {{ inp.focus({{ preventScroll: true }}); }} catch (e2) {{}}
                            try {{ inp.blur(); }} catch (e3) {{}}
                        }}
                    </script>'''
                    components.html(sb_grid_html, height=grid_h, scrolling=False)
            else:
                col_new, col_upload = st.columns([1, 1], gap="small")

                with col_new:
                    if st.button("＋ NEW STORYBOARD", key=f"sb_btn_new{key_suffix}", use_container_width=True):
                        st.session_state.sb_mode = "new"
                        st.session_state.sb_active_name = ""
                        st.session_state.sb_active_images = []
                        st.rerun()

                with col_upload:
                    if sb_names:
                        if st.button("⬆ UPLOAD STORYBOARD", key=f"sb_btn_upload{key_suffix}", use_container_width=True):
                            st.session_state.sb_mode = "pick"
                            st.rerun()
                    else:
                        st.button("⬆ UPLOAD STORYBOARD", key=f"sb_btn_upload_dis{key_suffix}",
                                  disabled=True, use_container_width=True)

        # ── Pick from saved storyboards ─────────────
        elif st.session_state.sb_mode == "pick" and not use_projects_layout:

            if not sb_names:
                st.info("No saved storyboards.")
                if st.button("BACK", key=f"sb_cancel_pick_empty{key_suffix}", use_container_width=True):
                    st.session_state.sb_mode = None
                    st.rerun()
            else:
                snaps_data = snaps.get("storyboard", {})
                SB_COLS = 4
                n_sb_rows = (len(sb_names) + SB_COLS - 1) // SB_COLS
                sb_flat = 0

                for _sr in range(n_sb_rows):
                    sb_cols = st.columns(SB_COLS, gap="medium")
                    for _sc in range(SB_COLS):
                        if sb_flat >= len(sb_names):
                            break
                        sname = sb_names[sb_flat]
                        sb_flat += 1

                        with sb_cols[_sc]:
                            # Get thumbnail from first image in snapshot
                            raw_items = snapshot_entry_items(snaps_data.get(sname, []))
                            sb_thumb = ""
                            for _si in raw_items:
                                _sip = _si.get("image_path") or _si.get("url") or ""
                                if _sip and os.path.exists(_sip):
                                    try:
                                        from PIL import Image as _PILImage
                                        import io as _io
                                        with _PILImage.open(_sip) as _sim:
                                            _sim.thumbnail((300, 180), _PILImage.LANCZOS)
                                            _sbuf = _io.BytesIO()
                                            _sim.convert("RGB").save(_sbuf, format="JPEG", quality=72)
                                            sb_thumb = f"data:image/jpeg;base64,{_b64.b64encode(_sbuf.getvalue()).decode('ascii')}"
                                    except Exception:
                                        pass
                                elif _sip and _sip.startswith("http"):
                                    sb_thumb = _sip
                                if sb_thumb:
                                    break

                            sb_hover_id = f"sb_thumb_{sb_flat}"
                            item_count = len(raw_items)

                            if sb_thumb:
                                st.markdown(
                                    f'<style>#{sb_hover_id}:hover {{ border-color:#FFEB3B !important; cursor:pointer; }}</style>'
                                    f'<div id="{sb_hover_id}" style="border:2px solid transparent; border-radius:10px; '
                                    f'overflow:hidden; aspect-ratio:16/9; background:#111110; '
                                    f'margin-bottom:4px; transition:border-color 0.15s ease;">'
                                    f'<img src="{sb_thumb}" style="width:100%; height:100%; object-fit:cover; display:block;"/>'
                                    f'</div>',
                                    unsafe_allow_html=True,
                                )
                            else:
                                st.markdown(
                                    f'<style>#{sb_hover_id}:hover {{ border-color:#FFEB3B !important; cursor:pointer; }}</style>'
                                    f'<div id="{sb_hover_id}" style="border:2px solid transparent; border-radius:10px; '
                                    f'aspect-ratio:16/9; background:linear-gradient(135deg,#1a1a18,#111110); '
                                    f'display:flex; align-items:center; justify-content:center; '
                                    f'margin-bottom:4px; transition:border-color 0.15s ease;">'
                                    f'<span style="color:#3a3a38; font-size:1.2rem; font-weight:300; '
                                    f'font-family:Open Sans,sans-serif;">{sname[:2].upper()}</span>'
                                    f'</div>',
                                    unsafe_allow_html=True,
                                )

                            # Click to load
                            if st.button(sname, key=f"sb_pick_card_{sb_flat}{key_suffix}", use_container_width=True):
                                raw = snaps_data.get(sname, [])
                                items = snapshot_entry_items(raw)
                                st.session_state.sb_active_images = items
                                st.session_state.sb_active_name = sname
                                st.session_state.sb_mode = "loaded"
                                st.rerun()

                            st.markdown(
                                f'<p style="color:#7a7a6e; font-size:0.6rem; font-family:Open Sans,sans-serif; '
                                f'margin:0; -webkit-text-fill-color:#7a7a6e;">{item_count} frames</p>',
                                unsafe_allow_html=True,
                            )

                st.markdown("")
                if st.button("BACK", key=f"sb_cancel_pick{key_suffix}", use_container_width=True):
                    st.session_state.sb_mode = None
                    st.rerun()

        # ── New or loaded storyboard: show images ───
        elif st.session_state.sb_mode in ("new", "loaded"):

            # Nome solo in sessione / sidebar / griglia elenco; niente box sopra le immagini.

            # Show images from this storyboard
            images = st.session_state.sb_active_images
            if not images:
                st.info("No images yet — go to Gallery › Images and add images to this storyboard.")
            else:
                _render_storyboard_grid("sb_active_images", "gallery_selected_imgs", media_type, f"sbi{key_suffix}")

            # Export JSON
            items = st.session_state.get(items_key, [])
            if items:
                export_data = {
                    "name": st.session_state.get(name_key, "Untitled"),
                    "type": "storyboard" if is_storyboard else "editing",
                    "created": datetime.now().isoformat(),
                    "total_frames": len(items),
                    "frames": [
                        {
                            "position": i + 1,
                            "caption": item.get("caption", ""),
                            "notes": item.get("notes", ""),
                            "prompt": item.get("prompt", ""),
                            "image_path": item.get("image_path", "") if is_storyboard else "",
                            "video_path": item.get("video_path", "") if not is_storyboard else "",
                            "style": item.get("style", ""),
                            "resolution": item.get("resolution", ""),
                            "aspect_ratio": item.get("aspect_ratio", ""),
                            "created_at": item.get("created_at", ""),
                        }
                        for i, item in enumerate(items)
                    ]
                }
                current_name = st.session_state.get(name_key, "untitled")
                safe_name = re.sub(r'[^\w\-]', '_', current_name.lower().strip()) or "untitled"
                st.download_button(
                    "📥 EXPORT JSON",
                    data=json.dumps(export_data, indent=2, ensure_ascii=False),
                    file_name=f"{safe_name}.json",
                    mime="application/json",
                    key=f"{page_prefix}_export{key_suffix}"
                )

            # ── Save to Assets ──
            items = st.session_state.get(items_key, [])
            if items and is_storyboard:
                sb_asset_options = []
                for si, sitem in enumerate(items):
                    slabel = f"#{si + 1} — {(sitem.get('caption', 'Image') or 'Image')[:30]}"
                    sb_asset_options.append((slabel, si))

                sb_ac1, sb_ac2 = st.columns([3, 1])
                with sb_ac1:
                    sb_asset_selected = st.multiselect(
                        "Select images to save to Assets",
                        options=[o[0] for o in sb_asset_options],
                        key=f"{page_prefix}_asset_select{key_suffix}",
                        label_visibility="collapsed",
                        placeholder="Select images for Assets..."
                    )
                with sb_ac2:
                    sb_n_sel = len(sb_asset_selected)
                    sb_alabel = f"💾 ASSETS ({sb_n_sel})" if sb_n_sel > 0 else "💾 TO ASSETS"
                    if st.button(sb_alabel, key=f"{page_prefix}_to_assets{key_suffix}",
                                 disabled=(sb_n_sel == 0), use_container_width=True):
                        label_to_idx = {o[0]: o[1] for o in sb_asset_options}
                        saved = 0
                        for lab in sb_asset_selected:
                            sidx = label_to_idx[lab]
                            if sidx < len(items):
                                src = items[sidx].get("image_path", "")
                                if src and os.path.exists(src):
                                    result = add_to_assets(source_path=src)
                                    if result:
                                        saved += 1
                        if saved > 0:
                            st.toast(f"Saved {saved} image(s) to Assets")
                        st.rerun()

    # ════════════════════════════════════════════
    #  EDITING MANAGER
    # ════════════════════════════════════════════
    else:
        snaps = load_all_snapshots()
        all_ed = snaps.get("editing", {})
        active_proj = get_active_project_id()
        ed_names = filter_snapshot_names(all_ed, active_proj)

        if use_projects_layout and st.session_state.ed_mode == "pick":
            st.session_state.ed_mode = None
            st.rerun()

        # ── Entry screen: no active editing ──────
        if st.session_state.ed_mode is None:

            if use_projects_layout:
                snaps_data = snaps.get("editing", {})
                st.text_input(
                    "ed_pick_bridge",
                    key="ed_pick_act",
                    on_change=_on_editing_grid_pick_change,
                    label_visibility="collapsed",
                )
                if not ed_names:
                    st.info("No editing sessions yet. Use **NEW EDITING** in the sidebar to create one.")
                else:
                    ed_cards = []
                    active_nm = st.session_state.get("ed_active_name") or ""
                    cur_mode = st.session_state.get("ed_mode")
                    for ename in ed_names:
                        raw_items = snapshot_entry_items(snaps_data.get(ename, []))
                        ed_thumb, nclips = _thumbnail_for_editing_items(raw_items)
                        ed_cards.append({
                            "name": ename,
                            "thumb": ed_thumb,
                            "clips": nclips,
                            "is_active": (ename == active_nm and cur_mode in ("new", "loaded")),
                        })

                    COLS = 4
                    cards_html_parts = []
                    for c in ed_cards:
                        _cname = _html_stdlib.escape(c["name"])
                        _thumb = (c["thumb"] or "").replace('"', "&quot;")
                        bcol = "#FF9800" if c["is_active"] else "transparent"
                        init = _html_stdlib.escape(c["name"][:2].upper())
                        _nc = str(c["clips"])
                        if c["thumb"]:
                            thumb_block = (
                                f'<img src="{_thumb}" style="width:100%;height:100%;object-fit:cover;display:block;" '
                                f'draggable="false" alt=""/>'
                            )
                        else:
                            thumb_block = (
                                f'<span style="color:#3a3a38;font-size:1.6rem;font-weight:300;'
                                f'font-family:Open Sans,sans-serif;">{init}</span>'
                            )
                        _safe = c["name"].replace("\\", "\\\\").replace("'", "\\'")
                        cards_html_parts.append(
                            f'''
                            <div class="proj-cell" onclick="edPick('{_safe}')">
                                <div class="proj-thumb ed-proj-thumb" style="border-color:{bcol};">{thumb_block}</div>
                                <div class="proj-title">{_cname}</div>
                                <div class="proj-meta">Clips: {_nc}</div>
                            </div>'''
                        )
                    cards_html = "".join(cards_html_parts)
                    nrows = (len(ed_cards) + COLS - 1) // COLS
                    grid_h = max(420, nrows * 210)
                    ed_grid_html = f'''
                    <style>
                        * {{ margin:0; padding:0; box-sizing:border-box; }}
                        body {{ background:transparent; font-family: Open Sans, sans-serif; }}
                        .proj-grid {{
                            display:grid;
                            grid-template-columns:repeat({COLS}, minmax(0, 1fr));
                            gap:14px;
                            padding:4px;
                        }}
                        .proj-cell {{ cursor:pointer; }}
                        .proj-thumb.ed-proj-thumb {{
                            position:relative;
                            border:2px solid transparent;
                            border-radius:10px;
                            overflow:hidden;
                            aspect-ratio:16/9;
                            background:#111110;
                            margin-bottom:6px;
                            display:flex;
                            align-items:center;
                            justify-content:center;
                            transition:border-color 0.15s ease;
                        }}
                        .proj-cell:hover .proj-thumb.ed-proj-thumb {{ border-color:rgba(255,152,0,0.45) !important; }}
                        .proj-title {{
                            color:#f0ece4;
                            font-size:0.78rem;
                            font-weight:600;
                            margin:0 0 4px;
                            line-height:1.25;
                            word-break:break-word;
                        }}
                        .proj-meta {{
                            color:#7a7a6e;
                            font-size:0.62rem;
                            line-height:1.35;
                            margin:0;
                        }}
                    </style>
                    <div class="proj-grid">{cards_html}</div>
                    <script>
                        function edPick(name) {{
                            if (!name) return;
                            var inp = window.parent.document.querySelector(
                                'input[aria-label="ed_pick_bridge"]'
                            );
                            if (!inp) return;
                            var ns = Object.getOwnPropertyDescriptor(
                                window.HTMLInputElement.prototype, 'value'
                            ).set;
                            var payload = name + '|' + Date.now();
                            ns.call(inp, payload);
                            inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            try {{
                                inp.dispatchEvent(new InputEvent('input', {{
                                    bubbles: true, inputType: 'insertFromPaste', data: payload
                                }}));
                            }} catch (e) {{}}
                            try {{ inp.focus({{ preventScroll: true }}); }} catch (e2) {{}}
                            try {{ inp.blur(); }} catch (e3) {{}}
                        }}
                    </script>'''
                    components.html(ed_grid_html, height=grid_h, scrolling=False)
            else:
                col_new, col_upload = st.columns([1, 1], gap="small")

                with col_new:
                    if st.button("＋ NEW EDITING", key=f"ed_btn_new{key_suffix}", use_container_width=True):
                        st.session_state.ed_mode = "new"
                        st.session_state.ed_active_name = ""
                        st.session_state.ed_active_videos = []
                        st.rerun()

                with col_upload:
                    if ed_names:
                        if st.button("⬆ UPLOAD EDITING", key=f"ed_btn_upload{key_suffix}", use_container_width=True):
                            st.session_state.ed_mode = "pick"
                            st.rerun()
                    else:
                        st.button("⬆ UPLOAD EDITING", key=f"ed_btn_upload_dis{key_suffix}",
                                  disabled=True, use_container_width=True)

        # ── Pick from saved editing snapshots ─────
        elif st.session_state.ed_mode == "pick" and not use_projects_layout:

            if not ed_names:
                st.info("No saved editing sessions.")
                if st.button("BACK", key=f"ed_cancel_pick_empty{key_suffix}", use_container_width=True):
                    st.session_state.ed_mode = None
                    st.rerun()
            else:
                ed_snaps_data = snaps.get("editing", {})
                ED_COLS = 4
                n_ed_rows = (len(ed_names) + ED_COLS - 1) // ED_COLS
                ed_flat = 0

                for _er in range(n_ed_rows):
                    ed_cols_row = st.columns(ED_COLS, gap="medium")
                    for _ec in range(ED_COLS):
                        if ed_flat >= len(ed_names):
                            break
                        ename = ed_names[ed_flat]
                        ed_flat += 1

                        with ed_cols_row[_ec]:
                            raw_ed_items = snapshot_entry_items(ed_snaps_data.get(ename, []))
                            ed_thumb = ""
                            for _ei in raw_ed_items:
                                _eip = _ei.get("last_frame_path") or ""
                                if _eip and os.path.exists(_eip):
                                    try:
                                        from PIL import Image as _PILImage
                                        import io as _io
                                        with _PILImage.open(_eip) as _eim:
                                            _eim.thumbnail((300, 180), _PILImage.LANCZOS)
                                            _ebuf = _io.BytesIO()
                                            _eim.convert("RGB").save(_ebuf, format="JPEG", quality=72)
                                            ed_thumb = f"data:image/jpeg;base64,{_b64.b64encode(_ebuf.getvalue()).decode('ascii')}"
                                    except Exception:
                                        pass
                                if not ed_thumb:
                                    _evp = _ei.get("video_path") or ""
                                    if _evp and os.path.exists(_evp):
                                        try:
                                            import cv2
                                            cap = cv2.VideoCapture(_evp)
                                            if cap.isOpened():
                                                ret, frame = cap.read()
                                                if ret:
                                                    h, w = frame.shape[:2]
                                                    scale = min(300/max(w,1), 180/max(h,1), 1.0)
                                                    if scale < 1:
                                                        frame = cv2.resize(frame, (int(w*scale), int(h*scale)))
                                                    _, _ebuf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                                                    ed_thumb = f"data:image/jpeg;base64,{_b64.b64encode(_ebuf.tobytes()).decode('ascii')}"
                                            cap.release()
                                        except Exception:
                                            pass
                                if ed_thumb:
                                    break

                            ed_hover_id = f"ed_thumb_{ed_flat}"
                            ed_item_count = len(raw_ed_items)

                            if ed_thumb:
                                st.markdown(
                                    f'<style>#{ed_hover_id}:hover {{ border-color:#FFEB3B !important; cursor:pointer; }}</style>'
                                    f'<div id="{ed_hover_id}" style="border:2px solid transparent; border-radius:10px; '
                                    f'overflow:hidden; aspect-ratio:16/9; background:#111110; '
                                    f'margin-bottom:4px; transition:border-color 0.15s ease;">'
                                    f'<img src="{ed_thumb}" style="width:100%; height:100%; object-fit:cover; display:block;"/>'
                                    f'</div>',
                                    unsafe_allow_html=True,
                                )
                            else:
                                st.markdown(
                                    f'<style>#{ed_hover_id}:hover {{ border-color:#FFEB3B !important; cursor:pointer; }}</style>'
                                    f'<div id="{ed_hover_id}" style="border:2px solid transparent; border-radius:10px; '
                                    f'aspect-ratio:16/9; background:linear-gradient(135deg,#1a1a18,#111110); '
                                    f'display:flex; align-items:center; justify-content:center; '
                                    f'margin-bottom:4px; transition:border-color 0.15s ease;">'
                                    f'<span style="color:#3a3a38; font-size:1.2rem; font-weight:300; '
                                    f'font-family:Open Sans,sans-serif;">{ename[:2].upper()}</span>'
                                    f'</div>',
                                    unsafe_allow_html=True,
                                )

                            if st.button(ename, key=f"ed_pick_card_{ed_flat}{key_suffix}", use_container_width=True):
                                raw = ed_snaps_data.get(ename, [])
                                items = snapshot_entry_items(raw)
                                st.session_state.ed_active_videos = [
                                    _normalize_editing_video_item(dict(x)) for x in items
                                ]
                                st.session_state.ed_active_name = ename
                                st.session_state.ed_mode = "loaded"
                                st.rerun()

                            st.markdown(
                                f'<p style="color:#7a7a6e; font-size:0.6rem; font-family:Open Sans,sans-serif; '
                                f'margin:0; -webkit-text-fill-color:#7a7a6e;">{ed_item_count} clips</p>',
                                unsafe_allow_html=True,
                            )

                st.markdown("")
                if st.button("BACK", key=f"ed_cancel_pick{key_suffix}", use_container_width=True):
                    st.session_state.ed_mode = None
                    st.rerun()

        # ── New or loaded editing: show videos ────
        elif st.session_state.ed_mode in ("new", "loaded"):

            _process_editing_actions("ed_active_videos", f"sbv{key_suffix}")

            if not is_storyboard:
                # ── Import videos from Gallery and Assets ──
                with st.expander("＋ IMPORT CLIPS", expanded=False):
                    import_tab1, import_tab2 = st.tabs(["From Gallery", "From Assets"])

                    with import_tab1:
                        all_gallery_vids = st.session_state.get("gallery_videos", [])
                        active_proj = st.session_state.get("active_project_id")
                        if active_proj:
                            all_gallery_vids = [v for v in all_gallery_vids if v.get("project_id") == active_proj]

                        if not all_gallery_vids:
                            st.info("No videos in Gallery. Generate some from the Console.")
                        else:
                            gv_options = []
                            for gi, gv in enumerate(all_gallery_vids):
                                label = f"#{gi+1} — {(gv.get('caption', 'Video') or 'Video')[:35]}"
                                gv_options.append((label, gi))

                            gv_selected = st.multiselect(
                                "Select videos from Gallery",
                                options=[o[0] for o in gv_options],
                                key=f"{page_prefix}_import_gallery{key_suffix}",
                                label_visibility="collapsed",
                                placeholder="Select gallery videos...",
                            )

                            if st.button(
                                f"ADD ({len(gv_selected)})" if gv_selected else "ADD",
                                key=f"{page_prefix}_import_gal_btn{key_suffix}",
                                disabled=(len(gv_selected) == 0),
                                use_container_width=True,
                            ):
                                label_to_idx = {o[0]: o[1] for o in gv_options}
                                existing_paths = {item.get("video_path") for item in st.session_state.get(items_key, []) if item.get("video_path")}
                                added = 0
                                for lab in gv_selected:
                                    idx = label_to_idx[lab]
                                    if idx < len(all_gallery_vids):
                                        item = all_gallery_vids[idx]
                                        vpath = item.get("video_path", "")
                                        if not vpath or vpath not in existing_paths:
                                            st.session_state[items_key].append(
                                                _normalize_editing_video_item(dict(item))
                                            )
                                            if vpath:
                                                existing_paths.add(vpath)
                                            added += 1
                                if st.session_state.get(name_key) and added > 0:
                                    upsert_snapshot_entry(snap_key, st.session_state[name_key], st.session_state[items_key])
                                if added > 0:
                                    st.toast(f"Added {added} clip(s)")
                                st.rerun()

                    with import_tab2:
                        catalog = load_asset_catalog()
                        if active_proj:
                            catalog = [a for a in catalog if a.get("project_id") == active_proj]
                        video_assets = [a for a in catalog if a["type"] == "video"]

                        if not video_assets:
                            st.info("No video assets. Upload some in the Assets page.")
                        else:
                            va_options = []
                            for ai, va in enumerate(video_assets):
                                label = f"{va['name']} ({va.get('size_str', '')})"
                                va_options.append((label, va["id"]))

                            va_selected = st.multiselect(
                                "Select videos from Assets",
                                options=[o[0] for o in va_options],
                                key=f"{page_prefix}_import_assets{key_suffix}",
                                label_visibility="collapsed",
                                placeholder="Select asset videos...",
                            )

                            if st.button(
                                f"ADD ({len(va_selected)})" if va_selected else "ADD",
                                key=f"{page_prefix}_import_asset_btn{key_suffix}",
                                disabled=(len(va_selected) == 0),
                                use_container_width=True,
                            ):
                                label_to_id = {o[0]: o[1] for o in va_options}
                                existing_paths = {item.get("video_path") for item in st.session_state.get(items_key, []) if item.get("video_path")}
                                added = 0
                                for lab in va_selected:
                                    aid = label_to_id[lab]
                                    asset = next((a for a in video_assets if a["id"] == aid), None)
                                    if asset and os.path.exists(asset["path"]):
                                        vpath = os.path.abspath(asset["path"])
                                        if vpath not in existing_paths:
                                            st.session_state[items_key].append({
                                                "video_path": vpath,
                                                "caption": asset.get("original_name", asset["name"])[:50],
                                                "url": "",
                                                "trim_start": 0,
                                                "trim_end": -1,
                                                "duration": 0,
                                                "created_at": asset.get("uploaded_at", ""),
                                            })
                                            existing_paths.add(vpath)
                                            added += 1
                                if st.session_state.get(name_key) and added > 0:
                                    upsert_snapshot_entry(snap_key, st.session_state[name_key], st.session_state[items_key])
                                if added > 0:
                                    st.toast(f"Added {added} clip(s)")
                                st.rerun()

            # Show videos from this editing
            videos = st.session_state.ed_active_videos
            if not videos:
                st.info("No videos yet — go to Gallery › Videos and add videos to this editing session.")
            else:
                _render_editing_room(items_key, f"sbv{key_suffix}")

            # Export JSON
            items = st.session_state.get(items_key, [])
            if items:
                export_data = {
                    "name": st.session_state.get(name_key, "Untitled"),
                    "type": "storyboard" if is_storyboard else "editing",
                    "created": datetime.now().isoformat(),
                    "total_frames": len(items),
                    "frames": [
                        {
                            "position": i + 1,
                            "caption": item.get("caption", ""),
                            "notes": item.get("notes", ""),
                            "prompt": item.get("prompt", ""),
                            "image_path": item.get("image_path", "") if is_storyboard else "",
                            "video_path": item.get("video_path", "") if not is_storyboard else "",
                            "style": item.get("style", ""),
                            "resolution": item.get("resolution", ""),
                            "aspect_ratio": item.get("aspect_ratio", ""),
                            "created_at": item.get("created_at", ""),
                        }
                        for i, item in enumerate(items)
                    ]
                }
                current_name = st.session_state.get(name_key, "untitled")
                safe_name = re.sub(r'[^\w\-]', '_', current_name.lower().strip()) or "untitled"
                _exp_c1, _exp_c2 = st.columns(2, gap="small")
                with _exp_c1:
                    st.download_button(
                        "📥 EXPORT JSON",
                        data=json.dumps(export_data, indent=2, ensure_ascii=False),
                        file_name=f"{safe_name}.json",
                        mime="application/json",
                        key=f"{page_prefix}_export{key_suffix}",
                        use_container_width=True,
                        type="secondary",
                    )
                with _exp_c2:
                    if not is_storyboard:
                        _export_key = f"{page_prefix}_export_video{key_suffix}"
                        if st.button(
                            "📥 EXPORT VIDEO",
                            key=_export_key,
                            use_container_width=True,
                            type="secondary",
                        ):
                            with st.spinner("Exporting video with ffmpeg..."):
                                _exp_name = st.session_state.get(name_key, "untitled")
                                _exp_result = _export_editing_video(items, _exp_name)
                            if _exp_result and os.path.exists(_exp_result):
                                _exp_size = os.path.getsize(_exp_result)
                                _exp_mb = round(_exp_size / (1024 * 1024), 1)
                                st.success(f"Exported: {os.path.basename(_exp_result)} ({_exp_mb} MB)")
                                with open(_exp_result, "rb") as _ef:
                                    st.download_button(
                                        "DOWNLOAD",
                                        data=_ef.read(),
                                        file_name=os.path.basename(_exp_result),
                                        mime="video/mp4",
                                        key=f"{page_prefix}_download_export{key_suffix}",
                                    )
                            else:
                                st.error("Export failed. Check that ffmpeg is installed and video files exist.")

            # ── Save to Assets ──
            items = st.session_state.get(items_key, [])
            if items and not is_storyboard:
                ed_asset_options = []
                for ei, eitem in enumerate(items):
                    elabel = f"#{ei + 1} — {(eitem.get('caption', 'Video') or 'Video')[:30]}"
                    ed_asset_options.append((elabel, ei))

                ed_ac1, ed_ac2 = st.columns([3, 1])
                with ed_ac1:
                    ed_asset_selected = st.multiselect(
                        "Select videos to save to Assets",
                        options=[o[0] for o in ed_asset_options],
                        key=f"{page_prefix}_asset_select{key_suffix}",
                        label_visibility="collapsed",
                        placeholder="Select videos for Assets..."
                    )
                with ed_ac2:
                    ed_n_sel = len(ed_asset_selected)
                    ed_alabel = f"💾 ASSETS ({ed_n_sel})" if ed_n_sel > 0 else "💾 TO ASSETS"
                    if st.button(ed_alabel, key=f"{page_prefix}_to_assets{key_suffix}",
                                 disabled=(ed_n_sel == 0), use_container_width=True):
                        label_to_idx = {o[0]: o[1] for o in ed_asset_options}
                        saved = 0
                        for lab in ed_asset_selected:
                            eidx = label_to_idx[lab]
                            if eidx < len(items):
                                src = items[eidx].get("video_path", "")
                                if src and os.path.exists(src):
                                    result = add_to_assets(source_path=src)
                                    if result:
                                        saved += 1
                        if saved > 0:
                            st.toast(f"Saved {saved} video(s) to Assets")
                        st.rerun()
