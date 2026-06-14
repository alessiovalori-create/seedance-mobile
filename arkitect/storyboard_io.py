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
from io import BytesIO

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
    load_asset_catalog,
)
from arkitect.media_server import _to_media_url
from arkitect.shared import _EXPORTS_DIR

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
    tl_raw = out.get("timeline_start")
    if tl_raw is not None:
        try:
            out["timeline_start"] = round(max(0.0, float(tl_raw)), 2)
        except (TypeError, ValueError):
            out.pop("timeline_start", None)
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


def _load_storyboard_frame_pil(item):
    """Load a storyboard frame as RGB PIL Image, or None if unavailable."""
    path = (item.get("image_path") or item.get("url") or item.get("src") or "").strip()
    if not path:
        return None
    try:
        from PIL import Image as _PILImage
        if path.startswith("http://") or path.startswith("https://"):
            import requests
            resp = requests.get(path, timeout=30)
            resp.raise_for_status()
            with _PILImage.open(BytesIO(resp.content)) as im:
                return im.convert("RGB")
        if os.path.exists(path):
            with _PILImage.open(path) as im:
                return im.convert("RGB")
    except Exception:
        return None
    return None


STORYBOARD_SHEET_QUALITY_OPTIONS = (480, 720, 1080)


def _scale_frame_to_export_box(frame_im, box_w, box_h):
    """Scale frame to fit export cell (upscale or downscale), preserving aspect ratio."""
    from PIL import Image as _PILImage

    iw, ih = frame_im.size
    if iw < 1 or ih < 1:
        return frame_im
    scale = min(box_w / iw, box_h / ih)
    nw = max(1, int(round(iw * scale)))
    nh = max(1, int(round(ih * scale)))
    if nw == iw and nh == ih:
        return frame_im
    return frame_im.resize((nw, nh), _PILImage.LANCZOS)


def _storyboard_sheet_fonts():
    from PIL import ImageFont
    for path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ):
        if os.path.exists(path):
            try:
                return (
                    ImageFont.truetype(path, 18),
                    ImageFont.truetype(path, 13),
                    ImageFont.truetype(path, 11),
                )
            except Exception:
                pass
    default = ImageFont.load_default()
    return default, default, default


def _render_storyboard_sheet_page(items_chunk, *, cols, cell_w, img_h, header_h, caption_h, margin, title, page_num, total_pages):
    """Render one sheet page (subset of frames) as PIL Image."""
    from PIL import Image as _PILImage, ImageDraw

    title_h = 36 if title else 0
    cell_h = header_h + img_h + caption_h
    rows = max(1, (len(items_chunk) + cols - 1) // cols)
    sheet_w = cols * cell_w + (cols + 1) * margin
    sheet_h = title_h + rows * cell_h + (rows + 1) * margin
    if total_pages > 1:
        sheet_h += 22

    sheet = _PILImage.new("RGB", (sheet_w, sheet_h), (26, 26, 24))
    draw = ImageDraw.Draw(sheet)
    font_title, font_hdr, font_cap = _storyboard_sheet_fonts()

    y0 = margin
    if title:
        draw.text((margin, y0), title, fill=(240, 236, 228), font=font_title)
        y0 += title_h

    for local_i, item in enumerate(items_chunk):
        row, col = divmod(local_i, cols)
        x = margin + col * (cell_w + margin)
        y = y0 + row * (cell_h + margin)

        draw.rectangle(
            [x, y, x + cell_w - 1, y + cell_h - 1],
            outline=(255, 235, 59),
            width=2,
        )

        global_idx = item.get("_sheet_idx", local_i + 1)
        draw.rectangle([x + 2, y + 2, x + 44, y + header_h - 2], fill=(0, 0, 0))
        draw.text((x + 8, y + 6), str(global_idx), fill=(255, 255, 255), font=font_hdr)

        img_box = (x + 4, y + header_h, x + cell_w - 4, y + header_h + img_h)
        frame_im = _load_storyboard_frame_pil(item)
        if frame_im is not None:
            box_w = img_box[2] - img_box[0]
            box_h = img_box[3] - img_box[1]
            frame_im = _scale_frame_to_export_box(frame_im, box_w, box_h)
            paste_x = img_box[0] + (box_w - frame_im.width) // 2
            paste_y = img_box[1] + (box_h - frame_im.height) // 2
            sheet.paste(frame_im, (paste_x, paste_y))
        else:
            draw.rectangle(img_box, fill=(42, 42, 40))
            draw.text((x + 12, y + header_h + img_h // 2 - 6), "Image unavailable", fill=(120, 120, 110), font=font_cap)

        cap = (item.get("caption") or item.get("notes") or "").strip()[:48]
        if not cap:
            cap = f"Frame {global_idx}"
        draw.text((x + 8, y + header_h + img_h + 6), cap, fill=(180, 180, 170), font=font_cap)

    if total_pages > 1:
        draw.text(
            (margin, sheet_h - 18),
            f"Page {page_num} / {total_pages}",
            fill=(120, 120, 110),
            font=font_cap,
        )
    return sheet


@st.cache_data(show_spinner=False)
def _build_storyboard_sheet_bytes(
    paths_key: tuple,
    captions_key: tuple,
    fmt: str,
    storyboard_name: str,
    quality_px: int,
) -> bytes | None:
    """Build PNG or PDF storyboard contact sheet from frame paths (cacheable)."""
    from PIL import Image as _PILImage

    items = [
        {"image_path": p, "url": p if p.startswith("http") else "", "caption": c, "_sheet_idx": i + 1}
        for i, (p, c) in enumerate(zip(paths_key, captions_key))
    ]
    if not items:
        return None

    q = int(quality_px) if int(quality_px) in STORYBOARD_SHEET_QUALITY_OPTIONS else 720
    n = len(items)
    cols = 2
    img_h = q
    cell_w = int(round(q * 16 / 9))
    # Fewer frames per page at higher resolution to keep page size manageable
    if q >= 1080:
        frames_per_page = 4
    elif q >= 720:
        frames_per_page = 6
    else:
        frames_per_page = 8
    header_h, caption_h, margin = 28, 32, 14
    pdf_resolution = 72.0 + (q / 1080.0) * 128.0
    title = (storyboard_name or "Storyboard").strip() or "Storyboard"

    pages = []
    for start in range(0, n, frames_per_page):
        chunk = items[start : start + frames_per_page]
        total_pages = (n + frames_per_page - 1) // frames_per_page
        page_num = start // frames_per_page + 1
        pages.append(
            _render_storyboard_sheet_page(
                chunk,
                cols=cols,
                cell_w=cell_w,
                img_h=img_h,
                header_h=header_h,
                caption_h=caption_h,
                margin=margin,
                title=title if page_num == 1 else "",
                page_num=page_num,
                total_pages=total_pages,
            )
        )

    buf = BytesIO()
    fmt_l = (fmt or "png").lower()
    if fmt_l == "pdf":
        if len(pages) == 1:
            pages[0].save(buf, format="PDF", resolution=pdf_resolution)
        else:
            pages[0].save(buf, format="PDF", resolution=pdf_resolution, save_all=True, append_images=pages[1:])
    else:
        if len(pages) == 1:
            pages[0].save(buf, format="PNG", optimize=True)
        else:
            total_h = sum(p.height for p in pages) + 20 * (len(pages) - 1)
            combined = _PILImage.new("RGB", (pages[0].width, total_h), (26, 26, 24))
            y_off = 0
            for p in pages:
                combined.paste(p, (0, y_off))
                y_off += p.height + 20
            combined.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


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
    """Sidebar STORYBOARD dedicata: menu collassabile a sinistra (come Gallery/Assets)."""
    with st.sidebar:
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
    """Sidebar EDITING dedicata: menu collassabile a sinistra (come Gallery/Assets)."""
    with st.sidebar:
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
            st.session_state.gallery_selected_ordered = []
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
    sel_key = f"{page_prefix}_selected"
    if sel_key not in st.session_state:
        st.session_state[sel_key] = []
    action_val = st.session_state.get(action_key, "")
    if action_val:
        st.session_state[action_key] = ""
        if action_val.startswith("reorder:"):
            try:
                new_indices = [int(x) for x in action_val.replace("reorder:", "").split(",") if x.strip().isdigit()]
                if len(new_indices) == total and sorted(new_indices) == list(range(total)):
                    st.session_state[items_key] = [items[i] for i in new_indices]
                    # Remap selection to new positions (old index o is now at position p where new_indices[p] == o)
                    _old_sel = st.session_state.get(sel_key, [])
                    st.session_state[sel_key] = [p for p, o in enumerate(new_indices) if o in _old_sel]
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
                    # Keep selection consistent: drop removed index, shift higher ones down by 1
                    _old_sel = st.session_state.get(sel_key, [])
                    st.session_state[sel_key] = [s if s < rm_idx else s - 1 for s in _old_sel if s != rm_idx]
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
        elif action_val.startswith("toggleselect:"):
            try:
                ts_idx = int(action_val.replace("toggleselect:", ""))
                _cur = list(st.session_state.get(sel_key, []))
                if ts_idx in _cur:
                    _cur.remove(ts_idx)
                elif 0 <= ts_idx < total:
                    _cur.append(ts_idx)
                st.session_state[sel_key] = _cur
                st.rerun()
            except (ValueError, IndexError):
                pass
    thumb_size = 300 if media_type == "image" else 300
    # Sanitize selection for rendering (drop any stale out-of-range indices)
    selected_indices = [s for s in st.session_state.get(sel_key, []) if 0 <= s < total]
    st.session_state[sel_key] = selected_indices
    cards_html = ""
    for i, item in enumerate(items):
        src = _get_thumbnail_src_resized(item, max_px=800)
        caption = item.get("caption", "")[:20]
        notes = (item.get("notes", "") or "").replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
        if media_type == "image":
            media_el = f'<img src="{src}" onclick="event.stopPropagation(); toggleSelect({i});" style="width:100%;height:auto;max-height:{thumb_size}px;object-fit:contain;border-radius:4px;display:block;background:#0d0d0c;cursor:grab;" draggable="false"/>'
        else:
            if src == "VIDEO_PLACEHOLDER":
                media_el = f'<div onclick="event.stopPropagation(); toggleSelect({i});" style="width:100%;height:{thumb_size}px;background:#2a2a28;border:1px solid #444;border-radius:4px;display:flex;align-items:center;justify-content:center;cursor:pointer;"><span style="color:#FFEB3B;font-size:32px;">▶</span></div>'
            elif src.startswith("data:image"):
                media_el = f'<div onclick="event.stopPropagation(); toggleSelect({i});" style="position:relative;cursor:pointer;"><img src="{src}" style="width:100%;height:{thumb_size}px;object-fit:cover;border-radius:4px;display:block;" draggable="false"/><div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:#FFEB3B;font-size:32px;text-shadow:0 2px 8px rgba(0,0,0,0.8);">▶</div></div>'
            else:
                media_el = f'<video src="{src}" onclick="event.stopPropagation(); toggleSelect({i});" style="width:100%;height:{thumb_size}px;object-fit:cover;border-radius:4px;display:block;cursor:pointer;" muted preload="metadata"></video>'
        cards_html += f'''
        <div class="gal-card{' gal-selected' if i in selected_indices else ''}" data-idx="{i}">
            <div class="gal-drag-handle" title="Trascina per riordinare"><span class="gal-badge-num">{i + 1}</span><span class="gal-drag-grip">⋮⋮</span></div>
            <div class="gal-remove" onclick="event.stopPropagation(); removeItem({i})">×</div>
            {media_el}
            <div class="gal-caption gal-drag-handle">{caption}</div>
            <div class="gal-notes" contenteditable="true"
                 data-idx="{i}"
                 onblur="saveNote({i}, this.textContent)"
                 placeholder="note...">{notes}</div>
        </div>'''
    cols_count = 4
    html_code = f'''
    <script src="https://cdnjs.cloudflare.com/ajax/libs/Sortable/1.15.3/Sortable.min.js"></script>
    <style>
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ background: transparent; font-family: 'Open Sans', sans-serif; }}
        .gal-grid {{ display:grid; grid-template-columns:repeat({cols_count},1fr); gap:8px; padding:4px; }}
        .gal-card {{ position:relative; background:#1a1a18; border-radius:6px; overflow:hidden; cursor:grab; border:2px solid transparent; transition:border-color .2s,box-shadow .2s; }}
        .gal-card:active {{ cursor:grabbing; }}
        .gal-card:hover {{ border-color:rgba(255,235,59,.35); box-shadow:0 4px 16px rgba(0,0,0,.35); }}
        .gal-card.sortable-ghost {{ opacity:.35; border-color:#FFEB3B; }}
        .gal-card.gal-selected {{ border-color:#FFEB3B !important; box-shadow:0 0 0 1px #FFEB3B; }}
        .gal-drag-handle {{ cursor:grab; user-select:none; touch-action:none; }}
        .gal-drag-handle:active {{ cursor:grabbing; }}
        .gal-drag-handle.gal-caption {{ cursor:grab; }}
        .gal-card > .gal-drag-handle:first-of-type {{
            position:absolute; top:0; left:0; right:36px; height:32px;
            display:flex; align-items:center; gap:6px;
            background:linear-gradient(180deg,rgba(0,0,0,.82) 0%,rgba(0,0,0,.45) 70%,transparent 100%);
            color:#fff; font-size:10px; font-weight:700; padding:4px 8px; z-index:3;
            border-radius:6px 6px 0 0;
        }}
        .gal-drag-grip {{ color:#FFEB3B; font-size:12px; letter-spacing:-1px; line-height:1; margin-left:auto; }}
        .gal-remove {{ position:absolute; top:4px; right:4px; color:#666; font-size:12px; cursor:pointer; z-index:2; width:16px; height:16px; text-align:center; line-height:16px; border-radius:50%; }}
        .gal-remove:hover {{ color:#ff4444; background:rgba(255,68,68,.15); }}
        .gal-caption {{ color:#999; font-size:12px; padding:5px 8px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
        .gal-notes {{
            color: #FFEB3B;
            font-size: 10px;
            padding: 4px 8px 6px;
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
        function sendAction(payload) {{
            var inp = window.parent.document.querySelector(
                'input[aria-label="sb_action_input_{page_prefix}"]'
            );
            if (!inp) return;
            var ns = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
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

        const grid = document.getElementById('sortableGrid');
        Sortable.create(grid, {{
            animation: 200,
            ghostClass:'sortable-ghost',
            chosenClass:'sortable-chosen',
            draggable: '.gal-card',
            filter: '.gal-notes,.gal-remove',
            preventOnFilter: false,
            forceFallback: true,
            fallbackOnBody: true,
            fallbackTolerance: 5,
            onEnd: function(evt) {{
                if (evt.oldIndex === evt.newIndex) return;
                const cards = grid.querySelectorAll('.gal-card');
                const newOrder = Array.from(cards).map(c => c.dataset.idx);
                cards.forEach((c,i) => {{
                    var num = c.querySelector('.gal-badge-num');
                    if (num) num.textContent = i+1;
                }});
                sendAction('reorder:' + newOrder.join(','));
            }}
        }});
        function removeItem(idx) {{
            sendAction('remove:' + idx);
        }}
        function toggleSelect(idx) {{
            sendAction('toggleselect:' + idx);
        }}
        function saveNote(idx, text) {{
            sendAction('note:' + idx + ':' + text.substring(0, 200));
        }}
    </script>'''
    st.text_input(f"sb_action_input_{page_prefix}", value="", key=f"{page_prefix}_action", label_visibility="collapsed")
    grid_height = ((total // cols_count) + (1 if total % cols_count else 0)) * (thumb_size + 80) + 20
    components.html(html_code, height=grid_height, scrolling=False)
    st.markdown(f'<p style="color:#f0ece4;font-size:0.78rem;font-weight:600;font-family:Open Sans,sans-serif;margin-top:8px;">{total} {media_type}s</p>', unsafe_allow_html=True)

def _process_editing_actions(items_key, page_prefix):
    """Process pending editing actions from the JS timeline player.
    Must be called BEFORE any SAVE logic to ensure state is current."""
    _action_key = f"{page_prefix}_action"
    _av = st.session_state.get(_action_key, "")
    if not _av:
        return False
    st.session_state[_action_key] = ""

    if _av.startswith("exportactive:"):
        sync_clips = _decode_editing_timeline_payload(_av[13:])
        if sync_clips is not None:
            _rebuild_editing_items_from_timeline(sync_clips, items_key)
        _run_editing_export(items_key, "ed_active_name")
        return True

    if _av.startswith("export:"):
        sync_clips = _decode_editing_timeline_payload(_av[7:])
        if sync_clips is not None:
            _rebuild_editing_items_from_timeline(sync_clips, items_key)
        _run_editing_export(items_key, "ed_active_name")
        return True

    if _av.startswith("timeline:"):
        sync_clips = _decode_editing_timeline_payload(_av[9:])
        if sync_clips is not None:
            _rebuild_editing_items_from_timeline(sync_clips, items_key)
            return True
        return False

    items = list(st.session_state.get(items_key, []))
    changed = False
    try:
        if _av.startswith("trim:"):
            p = _av.split(":")
            tidx, ts, te, dur = int(p[1]), float(p[2]), float(p[3]), float(p[4])
            if 0 <= tidx < len(items):
                items[tidx]["trim_start"] = round(max(0, ts), 2)
                items[tidx]["trim_end"] = round(te, 2)
                items[tidx]["duration"] = round(dur, 2)
                st.session_state[items_key] = items
                changed = True
                if st.session_state.get("ed_active_name"):
                    upsert_snapshot_entry("editing", st.session_state.ed_active_name, items)
        elif _av.startswith("remove:"):
            ridx = int(_av.split(":", 1)[1])
            if 0 <= ridx < len(items):
                items.pop(ridx)
                st.session_state[items_key] = items
                changed = True
                if st.session_state.get("ed_active_name"):
                    upsert_snapshot_entry("editing", st.session_state.ed_active_name, items)
        elif _av.startswith("reorder:"):
            rest = _av.split(":", 1)[1]
            ni = [int(x) for x in rest.split(",") if x.strip().isdigit()]
            if len(ni) == len(items) and sorted(ni) == list(range(len(items))):
                items = [items[i] for i in ni]
                st.session_state[items_key] = items
                changed = True
                if st.session_state.get("ed_active_name"):
                    upsert_snapshot_entry("editing", st.session_state.ed_active_name, items)
        elif _av.startswith("cut:"):
            parts = _av.split(":")
            cidx = int(parts[1])
            cut_t = float(parts[2])
            if 0 <= cidx < len(items):
                item = dict(items[cidx])
                ts = float(item.get("trim_start") or 0)
                te = float(item.get("trim_end") or 0)
                dur = float(item.get("duration") or 0)
                if te <= 0:
                    te = dur if dur > 0 else 10.0
                if dur <= 0:
                    dur = te
                if ts + 0.15 < cut_t < te - 0.15:
                    left = _normalize_editing_video_item(item)
                    left["trim_end"] = round(cut_t, 2)
                    right = _normalize_editing_video_item(item)
                    right["trim_start"] = round(cut_t, 2)
                    right["trim_end"] = round(te, 2)
                    items[cidx] = left
                    items.insert(cidx + 1, right)
                    st.session_state[items_key] = items
                    changed = True
                    st.session_state["_ed_cut_toast"] = f"Cut at {cut_t:.2f}s — clip split into 2"
                    if st.session_state.get("ed_active_name"):
                        upsert_snapshot_entry("editing", st.session_state.ed_active_name, items)
    except (ValueError, IndexError):
        pass
    return changed


def _decode_editing_timeline_payload(payload: str):
    """Decode timeline JSON from the editing-room iframe (plain or base64)."""
    raw = (payload or "").strip()
    if not raw:
        return None
    if raw.startswith("["):
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else None
        except json.JSONDecodeError:
            return None
    try:
        pad = "=" * (-len(raw) % 4)
        decoded = _b64.b64decode(raw + pad).decode("utf-8")
        data = json.loads(decoded)
        return data if isinstance(data, list) else None
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _rebuild_editing_items_from_timeline(sync_clips, items_key: str) -> bool:
    """Replace session timeline items with the clip list from the JS player."""
    if not isinstance(sync_clips, list):
        return False

    source = list(st.session_state.get(items_key, []))
    by_path: dict[str, list] = {}
    for it in source:
        p = _resolve_editing_video_path(it)
        if p:
            by_path.setdefault(p, []).append(dict(it))

    templates: dict[str, dict] = {}
    for key, plist in by_path.items():
        if plist:
            templates[key] = dict(plist[0])

    new_items = []
    for sc in sync_clips:
        if not isinstance(sc, dict):
            continue
        path = (sc.get("path") or "").strip()
        if not path:
            continue
        norm = os.path.abspath(path) if os.path.isfile(path) else path
        pool = by_path.get(norm)
        matched_key = norm
        if not pool:
            for key, plist in by_path.items():
                if os.path.basename(key) == os.path.basename(norm):
                    pool = plist
                    matched_key = key
                    break
        if pool:
            it = dict(pool.pop(0))
        elif matched_key in templates:
            it = dict(templates[matched_key])
        elif templates:
            it = dict(next(iter(templates.values())))
        else:
            continue
        ts = float(sc.get("ts", 0))
        te = float(sc.get("te", -1))
        it["trim_start"] = round(max(0.0, ts), 2)
        it["trim_end"] = round(te, 2) if te >= 0 else -1
        d = float(sc.get("d", 0))
        if d > 0:
            it["duration"] = round(d, 2)
        if "tlStart" in sc:
            try:
                it["timeline_start"] = round(max(0.0, float(sc["tlStart"])), 2)
            except (TypeError, ValueError):
                pass
        new_items.append(_normalize_editing_video_item(it))

    st.session_state[items_key] = new_items
    if st.session_state.get("ed_active_name"):
        upsert_snapshot_entry("editing", st.session_state.ed_active_name, new_items)
    return True


def _run_editing_export(items_key: str, name_key: str) -> None:
    items = list(st.session_state.get(items_key, []))
    project_name = st.session_state.get(name_key, "untitled")
    path, err = _export_editing_video(items, project_name)
    st.session_state["_ed_last_export_path"] = path
    st.session_state["_ed_last_export_err"] = err


def _apply_editing_timeline_payload(raw: str, items_key: str, page_prefix: str) -> bool:
    if not raw.startswith("timeline:"):
        return False
    sync_clips = _decode_editing_timeline_payload(raw[9:])
    if sync_clips is None:
        return False
    _rebuild_editing_items_from_timeline(sync_clips, items_key)
    st.session_state[f"{page_prefix}_timeline_cache"] = sync_clips
    return True


def _decode_editing_sync_payload(payload: str):
    """Decode combined timeline + undo/redo payload from the editing-room iframe."""
    raw = (payload or "").strip()
    if not raw:
        return None
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
    try:
        pad = "=" * (-len(raw) % 4)
        decoded = _b64.b64decode(raw + pad).decode("utf-8")
        data = json.loads(decoded)
        return data if isinstance(data, dict) else None
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _apply_editing_sync_payload(raw: str, items_key: str, page_prefix: str) -> bool:
    if not raw.startswith("sync:"):
        return False
    data = _decode_editing_sync_payload(raw[5:])
    if not data:
        return False
    clips = data.get("clips")
    if isinstance(clips, list) and clips:
        _rebuild_editing_items_from_timeline(clips, items_key)
        st.session_state[f"{page_prefix}_timeline_cache"] = clips
    if "undo" in data and isinstance(data["undo"], list):
        st.session_state[f"{page_prefix}_undo_stack"] = data["undo"]
    if "redo" in data and isinstance(data["redo"], list):
        st.session_state[f"{page_prefix}_redo_stack"] = data["redo"]
    try:
        st.session_state[f"{page_prefix}_active_idx"] = int(data.get("activeIdx", 0))
    except (TypeError, ValueError):
        pass
    return True


def _apply_editing_export_payload(raw: str, items_key: str, page_prefix: str) -> bool:
    sync_clips = None
    if raw.startswith("exportactive:"):
        sync_clips = _decode_editing_timeline_payload(raw[13:])
    elif raw.startswith("export:"):
        sync_clips = _decode_editing_timeline_payload(raw[7:])
    else:
        return False
    if sync_clips is not None:
        _rebuild_editing_items_from_timeline(sync_clips, items_key)
        st.session_state[f"{page_prefix}_timeline_cache"] = sync_clips
    _run_editing_export(items_key, "ed_active_name")
    return True


def _drain_editing_bridges(page_prefix: str, items_key: str) -> bool:
    """Process hidden bridge inputs from the editing-room iframe (fallback if on_change missed)."""
    changed = False
    export_key = f"{page_prefix}_export_bridge"
    timeline_key = f"{page_prefix}_timeline"

    export_raw = (st.session_state.get(export_key) or "").strip()
    if export_raw:
        st.session_state[export_key] = ""
        if _apply_editing_export_payload(export_raw, items_key, page_prefix):
            changed = True

    sync_key = f"{page_prefix}_sync"
    sync_raw = (st.session_state.get(sync_key) or "").strip()
    if sync_raw:
        st.session_state[sync_key] = ""
        if _apply_editing_sync_payload(sync_raw, items_key, page_prefix):
            changed = True

    timeline_raw = (st.session_state.get(timeline_key) or "").strip()
    if timeline_raw:
        st.session_state[timeline_key] = ""
        if _apply_editing_timeline_payload(timeline_raw, items_key, page_prefix):
            changed = True

    return changed


def _resolve_editing_video_path(item):
    """Resolve a timeline clip to a readable local file path (same rules as the player)."""
    candidates = [
        (item.get("video_path") or "").strip(),
        (item.get("url") or "").strip(),
    ]
    _pkg_dir = os.path.dirname(os.path.abspath(__file__))
    _app_root = os.path.dirname(_pkg_dir)
    for raw in candidates:
        if not raw or raw.startswith(("http://", "https://")):
            continue
        if os.path.isfile(raw):
            return os.path.abspath(raw)
        for base in (_pkg_dir, _app_root):
            joined = os.path.join(base, raw)
            if os.path.isfile(joined):
                return os.path.abspath(joined)
    return None


def _editing_clip_trim_bounds(item):
    """trim_start / trim_end for export; trim_end < 0 means full clip."""
    dur = float(item.get("duration") or 10)
    if dur <= 0:
        dur = 10.0
    ts = float(item.get("trim_start") or 0)
    te_raw = item.get("trim_end", -1)
    try:
        te = float(te_raw)
    except (TypeError, ValueError):
        te = -1.0
    if te_raw is None or te < 0:
        return ts, None, dur
    if te <= ts:
        te = dur
    return ts, te, dur


def _ffmpeg_stderr_tail(result, max_chars=400):
    err = (result.stderr or b"").decode("utf-8", errors="replace").strip()
    if not err:
        return ""
    return err[-max_chars:]


def _export_editing_video(items, project_name="untitled"):
    """Export the editing timeline as a single video using ffmpeg.
    Respects trim_start/trim_end and timeline_start gaps (black frames)."""
    if not items:
        return None, "Timeline is empty."

    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        for p in ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"]:
            if os.path.exists(p):
                ffmpeg_path = p
                break
    if not ffmpeg_path:
        return None, "ffmpeg not found. Install it (e.g. brew install ffmpeg)."

    export_dir = _EXPORTS_DIR
    os.makedirs(export_dir, exist_ok=True)

    safe_name = re.sub(r'[^\w\-]', '_', project_name.lower().strip()) or "untitled"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(export_dir, f"{safe_name}_{timestamp}.mp4")

    valid_clips = []
    for order, item in enumerate(items):
        vpath = _resolve_editing_video_path(item)
        if not vpath:
            continue
        ts, te, dur = _editing_clip_trim_bounds(item)
        trim_dur = (te if te is not None else dur) - ts
        if trim_dur <= 0.05:
            continue
        tl_raw = item.get("timeline_start")
        tl_start = None
        if tl_raw is not None:
            try:
                tl_start = round(max(0.0, float(tl_raw)), 2)
            except (TypeError, ValueError):
                tl_start = None
        valid_clips.append({
            "path": vpath, "ts": ts, "te": te, "trim_dur": round(trim_dur, 2),
            "tl_start": tl_start, "order": order,
        })

    if not valid_clips:
        return None, "No local video files found for the clips in this timeline."

    has_tl = any(c["tl_start"] is not None for c in valid_clips)
    if not has_tl:
        cursor = 0.0
        for c in valid_clips:
            c["tl_start"] = cursor
            cursor += c["trim_dur"]
    else:
        for c in valid_clips:
            if c["tl_start"] is None:
                c["tl_start"] = 0.0

    valid_clips.sort(key=lambda c: (c["tl_start"], c["order"]))

    segments = []
    cursor = 0.0
    for c in valid_clips:
        if c["tl_start"] > cursor + 0.02:
            segments.append(("black", round(c["tl_start"] - cursor, 2)))
        segments.append(("video", c))
        cursor = c["tl_start"] + c["trim_dur"]

    def _trim_input_args(clip):
        args = ["-ss", str(clip["ts"])]
        if clip["te"] is not None:
            args.extend(["-to", str(clip["te"])])
        args.extend(["-i", clip["path"]])
        return args

    def _encode_video_segment(clip, seg_path):
        cmd = [
            ffmpeg_path, "-y",
            *_trim_input_args(clip),
            "-c:v", "libx264", "-preset", "fast",
            "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-r", "30",
            "-pix_fmt", "yuv420p",
            "-s", "1920x1080",
            seg_path,
        ]
        return subprocess.run(cmd, capture_output=True, timeout=300)

    def _encode_black_segment(dur, seg_path):
        cmd = [
            ffmpeg_path, "-y",
            "-f", "lavfi",
            "-i", f"color=c=black:s=1920x1080:r=30:d={dur}",
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-c:v", "libx264", "-preset", "fast",
            "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-shortest",
            seg_path,
        ]
        return subprocess.run(cmd, capture_output=True, timeout=300)

    if len(segments) == 1 and segments[0][0] == "video":
        c = segments[0][1]
        cmd = [
            ffmpeg_path, "-y",
            *_trim_input_args(c),
            "-c:v", "libx264", "-preset", "fast",
            "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            "-pix_fmt", "yuv420p",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            detail = _ffmpeg_stderr_tail(result)
            return None, f"ffmpeg failed.{f' {detail}' if detail else ''}"
        return output_path, None

    temp_dir = tempfile.mkdtemp(prefix="arkitect_export_")
    segment_paths = []
    concat_file = None
    last_ffmpeg_err = ""

    try:
        for idx, seg in enumerate(segments):
            seg_path = os.path.join(temp_dir, f"seg_{idx:04d}.mp4")
            if seg[0] == "black":
                result = _encode_black_segment(seg[1], seg_path)
            else:
                result = _encode_video_segment(seg[1], seg_path)
            if result.returncode != 0:
                last_ffmpeg_err = _ffmpeg_stderr_tail(result)
                continue
            if os.path.exists(seg_path) and os.path.getsize(seg_path) > 0:
                segment_paths.append(seg_path)

        if not segment_paths:
            detail = last_ffmpeg_err or "Could not build any clip segment."
            return None, f"ffmpeg failed. {detail}"

        concat_file = os.path.join(temp_dir, "concat.txt")
        with open(concat_file, "w") as f:
            for sp in segment_paths:
                f.write(f"file '{sp}'\n")

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
            detail = _ffmpeg_stderr_tail(result)
            return None, f"ffmpeg concat failed.{f' {detail}' if detail else ''}"

        if os.path.exists(output_path):
            return output_path, None
        return None, "Export finished but output file was not created."

    finally:
        for sp in segment_paths:
            try:
                os.remove(sp)
            except OSError:
                pass
        try:
            if concat_file and os.path.exists(concat_file):
                os.remove(concat_file)
            os.rmdir(temp_dir)
        except OSError:
            pass

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
    _has_explicit_tl = any(it.get("timeline_start") is not None for it in items)
    _tl_acc = 0.0
    for i, item in enumerate(items):
        dur = float(item.get("duration") or 10)
        if dur <= 0:
            dur = 10
        ts = float(item.get("trim_start") or 0)
        te = float(item.get("trim_end") or dur)
        if te <= 0:
            te = dur
        if _has_explicit_tl and item.get("timeline_start") is not None:
            tl_start = float(item.get("timeline_start") or 0)
        else:
            tl_start = _tl_acc
        _trim_len = max(0.01, te - ts)

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
                        im.thumbnail((120, 64), _PILImage.LANCZOS)
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
                            scale = min(120 / max(w, 1), 64 / max(h, 1))
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
        _clip_path = _resolve_editing_video_path(item) or _local_path or ""

        clips_js.append(
            {
                "i": i,
                "ts": float(round(ts, 2)),
                "te": float(round(te, 2)),
                "d": float(round(dur, 2)),
                "tlStart": float(round(max(0.0, tl_start), 2)),
                "thumb": thumb,
                "vurl": vurl,
                "path": _clip_path,
                "cap": (item.get("caption", "") or "")[:20],
            }
        )
        _tl_acc = max(_tl_acc, tl_start + _trim_len)

    clips_b64 = _b64.b64encode(
        json.dumps(clips_js, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    undo_stack = st.session_state.get(f"{page_prefix}_undo_stack", [])
    redo_stack = st.session_state.get(f"{page_prefix}_redo_stack", [])
    if not isinstance(undo_stack, list):
        undo_stack = []
    if not isinstance(redo_stack, list):
        redo_stack = []
    undo_b64 = _b64.b64encode(
        json.dumps(undo_stack, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    redo_b64 = _b64.b64encode(
        json.dumps(redo_stack, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    active_idx_init = int(st.session_state.get(f"{page_prefix}_active_idx", 0) or 0)
    prefix_js = json.dumps(page_prefix)

    _sync_key = f"{page_prefix}_sync"
    _export_bridge_key = f"{page_prefix}_export_bridge"

    def _on_ed_export_bridge_change():
        raw = (st.session_state.get(_export_bridge_key) or "").strip()
        st.session_state[_export_bridge_key] = ""
        if raw:
            _apply_editing_export_payload(raw, items_key, page_prefix)

    st.text_input(
        "ed_sync_bridge",
        value="",
        key=_sync_key,
        label_visibility="collapsed",
    )
    st.text_input(
        "ed_export_bridge",
        value="",
        key=_export_bridge_key,
        label_visibility="collapsed",
        on_change=_on_ed_export_bridge_change,
    )

    # Legacy action channel (trim/remove fallback)
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
background:#111; border-radius:8px; padding:8px 12px 12px;
position:relative; margin-top:4px;
  }
  .ed-timeline-controls {
display:flex; align-items:center; gap:10px; flex-wrap:wrap;
margin-bottom:8px; padding:8px 10px;
background:#1a1a18; border:1px solid #2a2a28; border-radius:8px;
  }
  .ed-timeline-controls-label {
font-size:10px; font-weight:600; letter-spacing:0.08em;
color:#FFEB3B; text-transform:uppercase; min-width:42px;
  }
  .ed-ruler-wrap { margin-bottom:6px; border-bottom:1px solid #222; }
  .ed-ruler-scroll {
overflow:hidden; position:relative; height:34px; cursor:col-resize;
  }
  .ed-ruler-inner { position:relative; height:34px; min-height:34px; }
  .ed-ruler-tick {
position:absolute; bottom:0; width:1px; background:#3a3a38; pointer-events:none;
  }
  .ed-ruler-tick.mid { height:8px; background:#444; }
  .ed-ruler-tick.major { height:14px; background:#666; }
  .ed-ruler-tick.frame { height:5px; background:#2e2e2c; width:1px; }
  .ed-ruler-tick.clip-mark { height:18px; width:2px; background:rgba(255,235,59,0.55); }
  .ed-ruler-label {
position:absolute; top:2px; transform:translateX(-50%);
font-family:'JetBrains Mono',monospace; font-size:9px; color:#9E9E8A;
white-space:nowrap; pointer-events:none;
  }
  .ed-ruler-label.clip-mark {
top:16px; font-size:8px; color:#FFEB3B; transform:translateX(2px);
  }
  .ed-track-scroll {
overflow-x:auto; position:relative; min-height:72px;
  }
  .ed-track-inner {
position:relative; min-height:64px;
background:#0a0a0a;
  }
  .ed-playhead {
position:absolute; top:-8px; bottom:-8px; width:2px; background:#FFEB3B;
z-index:25; pointer-events:none;
box-shadow:0 0 8px rgba(255,235,59,0.5);
  }
  .ed-playhead::before {
content:''; position:absolute; top:0; left:50%; transform:translateX(-50%);
width:0; height:0;
border-left:6px solid transparent; border-right:6px solid transparent;
border-top:8px solid #FFEB3B;
  }
  .ed-playhead-grab {
position:absolute; top:-8px; bottom:-8px; width:36px; margin-left:-17px;
z-index:26; cursor:col-resize; pointer-events:auto;
  }
  .ed-ruler-wrap { cursor:col-resize; }
  .ed-track-scroll { cursor:crosshair; }
  .ed-clip { cursor:crosshair; }
  .ed-clip.dragging { cursor:grabbing; }
  .ed-playhead-grab:hover ~ .ed-playhead,
  .ed-playhead-grab.dragging ~ .ed-playhead {
width:3px; box-shadow:0 0 10px rgba(255,235,59,0.7);
  }
  .ed-clip {
position:absolute; top:0; height:64px;
overflow:hidden; border:2px solid transparent; border-radius:4px;
background:#1a1a18; transition:border-color 0.15s ease, box-shadow 0.15s ease, opacity 0.15s ease;
opacity:0.88; z-index:2;
  }
  .ed-clip.dragging { cursor:grabbing; opacity:0.75; z-index:8; box-shadow:0 4px 16px rgba(0,0,0,0.45); }
  .ed-clip.snap { border-color:#00E5CC !important; box-shadow:0 0 0 1px rgba(0,229,204,0.55), 0 4px 16px rgba(0,0,0,0.45); }
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
position:absolute; top:2px; right:2px; z-index:6; width:20px; height:20px;
line-height:18px; text-align:center; font-size:15px; font-weight:700;
color:rgba(255,255,255,0.2); background:rgba(0,0,0,0.35);
cursor:pointer; transition:color 0.15s ease, background 0.15s ease; border-radius:4px;
  }
  .ed-clip:hover .ed-rm { color:rgba(255,255,255,0.65); }
  .ed-clip.active .ed-rm { color:#ff8a80; background:rgba(0,0,0,0.55); }
  .ed-rm:hover { color:#fff !important; background:#ff5252 !important; }
  .ed-trim-l, .ed-trim-r {
position:absolute; top:0; width:5px; height:100%; background:#fff;
cursor:col-resize; z-index:5; transition:background 0.15s ease;
  }
  .ed-trim-l { left:0; border-radius:2px 0 0 2px; }
  .ed-trim-r { right:0; border-radius:0 2px 2px 0; }
  .ed-trim-l:hover, .ed-trim-r:hover { background:#00E5CC; }
  .ed-total {
margin-left:auto;
font-family:'JetBrains Mono',monospace; font-size:11px; color:#9E9E8A;
white-space:nowrap;
  }
  .ed-zoom-btn {
background:#2a2a28; color:#FFEB3B; border:1px solid rgba(255,235,59,0.35);
border-radius:6px; width:32px; height:32px; font-size:18px; font-weight:700;
cursor:pointer; display:flex; align-items:center; justify-content:center;
transition:background 0.15s, border-color 0.15s;
font-family:'JetBrains Mono',monospace; flex-shrink:0;
  }
  .ed-zoom-btn:hover { background:#333; border-color:rgba(255,235,59,0.65); }
  .ed-zoom-slider {
-webkit-appearance:none; appearance:none; flex:1; min-width:120px; max-width:280px;
height:6px; background:#333; border-radius:3px; outline:none; cursor:pointer;
  }
  .ed-zoom-slider::-webkit-slider-thumb {
-webkit-appearance:none; width:16px; height:16px;
background:#FFEB3B; border:2px solid #1a1a18; border-radius:50%; cursor:pointer;
box-shadow:0 0 6px rgba(255,235,59,0.45);
  }
  .ed-zoom-slider::-moz-range-thumb {
width:16px; height:16px; background:#FFEB3B; border:2px solid #1a1a18;
border-radius:50%; cursor:pointer;
  }
  .ed-zoom-label {
font-family:'JetBrains Mono',monospace; font-size:12px; font-weight:600;
color:#FFEB3B; min-width:36px; text-align:center; flex-shrink:0;
  }
  .ed-toolbar {
display:flex; align-items:center; gap:10px; flex-wrap:wrap;
margin-top:10px; margin-bottom:6px; padding:8px 12px;
background:#1a1a18; border-radius:8px; border:1px solid #2a2a28;
  }
  .ed-toolbar-label {
font-size:10px; font-weight:600; letter-spacing:0.08em;
color:#9E9E8A; text-transform:uppercase; margin-right:4px;
  }
  .ed-tool-cut {
border:1px solid rgba(255,235,59,0.4); color:#FFEB3B;
  }
  .ed-tool-cut:hover:not(:disabled) { background:#2a2a28; }
  .ed-tool-cut:disabled { opacity:0.35; cursor:not-allowed; color:#666; border-color:#333; }
  .ed-tool-export {
border:1px solid rgba(255,235,59,0.35); color:#FFEB3B;
  }
  .ed-tool-export:hover { background:#2a2a28; }
  .ed-toolbar-hint {
font-family:'JetBrains Mono',monospace; font-size:10px; color:#555; margin-left:auto;
  }
  .ed-tool-undo, .ed-tool-redo {
border:1px solid rgba(255,255,255,0.15); color:#f0ece4;
  }
  .ed-tool-undo:hover:not(:disabled), .ed-tool-redo:hover:not(:disabled) { background:#2a2a28; }
  .ed-tool-undo:disabled, .ed-tool-redo:disabled {
opacity:0.35; cursor:not-allowed; color:#666; border-color:#333;
  }
  .ed-tool-delete {
border:1px solid rgba(255,82,82,0.5); color:#ff5252;
  }
  .ed-tool-delete:hover:not(:disabled) { background:#2a1a1a; }
  .ed-tool-delete:disabled { opacity:0.35; cursor:not-allowed; color:#666; border-color:#333; }
  .ed-trim-dim { opacity:0.5; }
  .ed-trim-dim:hover { opacity:1; }
  .ed-clip.split-part { box-shadow:inset 0 0 0 1px rgba(255,235,59,0.2); }
  .ed-badge-split { font-size:8px; opacity:0.85; margin-left:1px; }
  .ed-room:focus { outline:none; }
  .ed-room:focus-visible { outline:1px solid rgba(255,235,59,0.45); outline-offset:2px; border-radius:8px; }
</style>
<div class="ed-room" id="edRoomRoot" tabindex="0">
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
<div class="ed-toolbar">
  <span class="ed-toolbar-label">Timeline tools</span>
  <button type="button" class="ed-tbtn ed-tool-cut" id="edCut" title="Taglia al cursore (C)">CUT</button>
  <button type="button" class="ed-tbtn ed-tool-delete" id="edDelete" title="Elimina clip selezionata (Delete)" disabled>DELETE</button>
  <button type="button" class="ed-tbtn ed-tool-undo" id="edUndo" title="Annulla (Ctrl+Z)" disabled>UNDO</button>
  <button type="button" class="ed-tbtn ed-tool-redo" id="edRedo" title="Ripeti (Ctrl+Shift+Z)" disabled>REDO</button>
  <button type="button" class="ed-tbtn ed-tool-export" id="edExportAll" title="Esporta tutte le clip in timeline">EXPORT TIMELINE</button>
  <button type="button" class="ed-tbtn ed-tool-export" id="edExportSel" title="Esporta solo la clip selezionata">EXPORT SELECTED</button>
  <span class="ed-toolbar-hint" id="edCutHint">Click = playhead + select · ←→ frame · ↑↓ clip · Shift+drag move clip</span>
</div>
  </div>
  <div class="ed-timeline-outer">
<div class="ed-timeline-controls">
  <span class="ed-timeline-controls-label">Zoom</span>
  <button type="button" class="ed-zoom-btn" id="edZoomOut" title="Riduci timeline">−</button>
  <input type="range" class="ed-zoom-slider" id="edZoomSlider" min="0.5" max="8" step="0.25" value="1"/>
  <button type="button" class="ed-zoom-btn" id="edZoomIn" title="Ingrandisci timeline">+</button>
  <span class="ed-zoom-label" id="edZoomLabel">1×</span>
  <span class="ed-total" id="edTotalLab"></span>
</div>
<div class="ed-ruler-wrap">
  <div class="ed-ruler-scroll" id="edRulerScroll">
    <div class="ed-ruler-inner" id="edRulerInner"></div>
  </div>
</div>
<div class="ed-track-scroll" id="edTrackScroll">
  <div class="ed-track-inner" id="edTrackInner">
    <div class="ed-playhead-grab" id="edPlayheadGrab"></div>
    <div class="ed-playhead" id="edPlayhead"></div>
  </div>
</div>
  </div>
</div>
<script>
(function(){
var CLIPS = JSON.parse(atob('__CLIPS_B64__'));
var PREFIX = __PREFIX_JSON__;
var activeIdx = 0;
var playheadTime = 0;
var seekPending = false;
var zoomLevel = 1;
var trimState = null;
var UNDO_STACK = [];
var REDO_STACK = [];
try { UNDO_STACK = JSON.parse(atob('__UNDO_B64__')) || []; } catch(e) { UNDO_STACK = []; }
try { REDO_STACK = JSON.parse(atob('__REDO_B64__')) || []; } catch(e) { REDO_STACK = []; }
if (!Array.isArray(UNDO_STACK)) UNDO_STACK = [];
if (!Array.isArray(REDO_STACK)) REDO_STACK = [];
UNDO_STACK = UNDO_STACK.filter(function(s) { return Array.isArray(s); });
REDO_STACK = REDO_STACK.filter(function(s) { return Array.isArray(s); });
var HISTORY_MAX = 50;
var _splitCounter = 0;

function mediaLookup() {
  var byPath = {};
  function add(c) {
    if (c && c.path) byPath[c.path] = {thumb: c.thumb || '', vurl: c.vurl || ''};
  }
  CLIPS.forEach(add);
  UNDO_STACK.forEach(function(st) { if (Array.isArray(st)) st.forEach(add); });
  REDO_STACK.forEach(function(st) { if (Array.isArray(st)) st.forEach(add); });
  return byPath;
}

function snapshotClips(arr) {
  return arr.map(function(c, idx) {
    return {
      i: idx, ts: c.ts, te: c.te, d: c.d,
      mediaD: c.mediaD || c.d,
      tlStart: c.tlStart != null ? c.tlStart : 0,
      path: c.path || '', cap: c.cap || '',
      splitId: c.splitId || '', splitPart: c.splitPart || ''
    };
  });
}

function reviveClips(snapshot) {
  var byPath = mediaLookup();
  return snapshot.map(function(c, idx) {
    var m = (c.path && byPath[c.path]) ? byPath[c.path] : {};
    return {
      i: idx, ts: c.ts, te: c.te, d: c.d,
      mediaD: c.mediaD || c.d,
      tlStart: c.tlStart != null ? c.tlStart : 0,
      thumb: c.thumb || m.thumb || '',
      vurl: c.vurl || m.vurl || '',
      path: c.path || '', cap: c.cap || '',
      splitId: c.splitId || '', splitPart: c.splitPart || ''
    };
  });
}

function getMediaDur(c) {
  var m = c.mediaD || c.d;
  return (m && m > 0) ? m : 10;
}

function recordHistory() {
  UNDO_STACK.push(snapshotClips(CLIPS));
  if (UNDO_STACK.length > HISTORY_MAX) UNDO_STACK.shift();
  REDO_STACK.length = 0;
  updateUndoRedoButtons();
}

function applyClipsState(snapshot, doSync) {
  CLIPS = reviveClips(snapshot);
  CLIPS.forEach(function(c, k) { c.i = k; ensureClip(c); });
  if (activeIdx >= CLIPS.length) activeIdx = Math.max(0, CLIPS.length - 1);
  trimEndLatch = false;
  if (CLIPS.length) {
    var idx = Math.max(0, Math.min(activeIdx, CLIPS.length - 1));
    seekToGlobalTime(CLIPS[idx].tlStart || 0, false);
  } else {
    buildTrack();
    var v0 = activeVid;
    if (v0) {
      v0.pause();
      v0.removeAttribute('src');
      try { v0.load(); } catch(e) {}
    }
    syncPlayBtn();
  }
  updatePlayhead();
  updateReadout();
  updateCutButton();
  preloadNextByTime();
  if (doSync !== false) pushTimeline();
  updateUndoRedoButtons();
}

function undo() {
  if (!UNDO_STACK.length) return;
  var snap = UNDO_STACK[UNDO_STACK.length - 1];
  if (!Array.isArray(snap) || !snap.length) return;
  UNDO_STACK.pop();
  REDO_STACK.push(snapshotClips(CLIPS));
  applyClipsState(snap, false);
}

function redo() {
  if (!REDO_STACK.length) return;
  var snap = REDO_STACK[REDO_STACK.length - 1];
  if (!Array.isArray(snap) || !snap.length) return;
  REDO_STACK.pop();
  UNDO_STACK.push(snapshotClips(CLIPS));
  applyClipsState(snap, false);
}

function updateUndoRedoButtons() {
  var u = document.getElementById('edUndo');
  var r = document.getElementById('edRedo');
  if (u) u.disabled = UNDO_STACK.length === 0;
  if (r) r.disabled = REDO_STACK.length === 0;
}

function findBridgeInput(label) {
  var roots = [window.parent, window.parent.parent, window.top];
  for (var r = 0; r < roots.length; r++) {
    try {
      var doc = roots[r].document;
      if (!doc) continue;
      var inp = doc.querySelector('input[aria-label="' + label + '"]');
      if (inp) return inp;
    } catch (e) {}
  }
  return null;
}

function postBridge(label, value) {
  var inp = findBridgeInput(label);
  if (!inp) return false;
  var ns = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value'
  ).set;
  ns.call(inp, value);
  inp.dispatchEvent(new Event('input', {bubbles:true}));
  inp.dispatchEvent(new Event('change', {bubbles:true}));
  try {
    inp.dispatchEvent(new InputEvent('input', {
      bubbles: true, inputType: 'insertFromPaste', data: value
    }));
  } catch (e) {}
  try { inp.focus({preventScroll:true}); } catch (e2) {}
  try { inp.blur(); } catch (e3) {}
  return true;
}

function sendAction(str) {
  return postBridge('sb_action_input_' + PREFIX, str);
}

function encodeTimelinePayload(arr) {
  var s = JSON.stringify(arr);
  try {
    return btoa(unescape(encodeURIComponent(s)));
  } catch (e) {
    return s;
  }
}

function clipsPayload(onlyActive) {
  var list = onlyActive ? [CLIPS[activeIdx]] : CLIPS.slice();
  return list.filter(Boolean).map(function(c) {
    return {
      path: c.path || '', ts: c.ts, te: c.te, d: getMediaDur(c),
      tlStart: c.tlStart != null ? c.tlStart : 0
    };
  });
}

function encodeSyncPayload(obj) {
  var s = JSON.stringify(obj);
  try {
    return btoa(unescape(encodeURIComponent(s)));
  } catch (e) {
    return s;
  }
}

function syncToServer() {
  var payload = {
    clips: clipsPayload(false),
    undo: UNDO_STACK,
    redo: REDO_STACK,
    activeIdx: activeIdx
  };
  postBridge('ed_sync_bridge', 'sync:' + encodeSyncPayload(payload));
}

function pushTimeline() {
  syncToServer();
}

function doExport(onlyActive) {
  if (!CLIPS.length) return;
  if (onlyActive && (activeIdx < 0 || activeIdx >= CLIPS.length)) return;
  var cmd = (onlyActive ? 'exportactive:' : 'export:') + encodeTimelinePayload(clipsPayload(onlyActive));
  postBridge('ed_export_bridge', cmd);
}

function ensureClip(c) {
  if (!c.mediaD || c.mediaD <= 0) c.mediaD = c.d || 10;
  if (!c.d || c.d <= 0) c.d = c.mediaD;
  var maxD = getMediaDur(c);
  if (c.te <= 0) c.te = maxD;
  if (c.ts < 0) c.ts = 0;
  if (c.te > maxD) c.te = maxD;
  if (c.te < c.ts + 0.1) c.te = Math.min(maxD, c.ts + 0.1);
}
CLIPS.forEach(function(c) {
  c.mediaD = c.d;
  ensureClip(c);
  if (c.tlStart == null || isNaN(c.tlStart)) c.tlStart = 0;
});

var BASE_PPS = 56;
var CLIP_TRACK_H = 64;
var inGap = false;
var gapGlobalTime = 0;
var gapPlayActive = false;
var gapPlayStartWall = 0;
var gapPlayFrom = 0;
var gapPlayTo = 0;
var clipDragState = null;

function trimDur(c) { return Math.max(0.01, c.te - c.ts); }
function clipEnd(c) { return (c.tlStart || 0) + trimDur(c); }
function totalDur() {
  var t = 0;
  CLIPS.forEach(function(c) {
    var e = clipEnd(c);
    if (e > t) t = e;
  });
  return Math.max(t, 0.01);
}
function clipsSortedByTime() {
  return CLIPS.map(function(c, i) { return { c: c, i: i }; }).sort(function(a, b) {
    return (a.c.tlStart || 0) - (b.c.tlStart || 0);
  });
}
function nextClipAfterTime(t) {
  var best = null;
  CLIPS.forEach(function(c, i) {
    var tl = c.tlStart || 0;
    if (tl > t + 0.001 && (!best || tl < best.tl)) best = { idx: i, tl: tl };
  });
  return best;
}
function prevClipBeforeTime(t) {
  var best = null;
  CLIPS.forEach(function(c, i) {
    var tl = c.tlStart || 0;
    if (tl < t - 0.05 && (!best || tl > best.tl)) best = { idx: i, tl: tl };
  });
  return best;
}
function adjacentClipInOrder(delta) {
  var sorted = clipsSortedByTime();
  if (!sorted.length) return null;
  var pos = -1;
  for (var i = 0; i < sorted.length; i++) {
    if (sorted[i].i === activeIdx) { pos = i; break; }
  }
  if (pos < 0) return delta < 0 ? sorted[sorted.length - 1] : sorted[0];
  var nextPos = pos + delta;
  if (nextPos < 0 || nextPos >= sorted.length) return null;
  return sorted[nextPos];
}
function scrollActiveClipIntoView() {
  if (activeIdx < 0 || activeIdx >= CLIPS.length) return;
  var scroll = document.getElementById('edTrackScroll');
  if (!scroll) return;
  var c = CLIPS[activeIdx];
  var left = timeToPx(c.tlStart || 0);
  var width = timeToPx(trimDur(c));
  var viewLeft = scroll.scrollLeft;
  var viewRight = viewLeft + scroll.clientWidth;
  var margin = 48;
  if (left < viewLeft + margin) {
    scroll.scrollLeft = Math.max(0, left - margin);
  } else if (left + width > viewRight - margin) {
    scroll.scrollLeft = Math.max(0, left + width - scroll.clientWidth + margin);
  }
  var rulerScroll = document.getElementById('edRulerScroll');
  if (rulerScroll) rulerScroll.scrollLeft = scroll.scrollLeft;
}
function selectAdjacentClip(delta) {
  var adj = adjacentClipInOrder(delta);
  if (!adj) return;
  var v = activeVid;
  var wasP = gapPlayActive || (v && !v.paused);
  selectClip(adj.i, wasP);
  scrollActiveClipIntoView();
  focusEditingRoom();
}
function findClipAtGlobalTime(gt) {
  var best = null;
  for (var i = 0; i < CLIPS.length; i++) {
    var c = CLIPS[i];
    var tl = c.tlStart || 0;
    var d = trimDur(c);
    var end = tl + d;
    if (gt >= tl - 0.001 && gt <= end + 0.001) {
      if (!best || tl >= best.tl) {
        best = {
          idx: i,
          localT: Math.max(c.ts, Math.min(c.ts + (gt - tl), c.te)),
          inGap: false,
          tl: tl
        };
      }
    }
  }
  if (best) return best;
  return { idx: -1, localT: 0, inGap: true };
}

function videoMatchesActiveClip() {
  if (activeIdx < 0 || activeIdx >= CLIPS.length) return false;
  var c = CLIPS[activeIdx];
  var v = activeVid;
  if (!c || !v || !c.vurl) return false;
  try {
    return v.src === new URL(c.vurl, window.location.href).href;
  } catch (e) {
    return !!(v.src && v.src.indexOf(c.vurl) >= 0);
  }
}

var SNAP_PX = 14;

function snapClipTlStart(dragIdx, rawTlStart) {
  var clip = CLIPS[dragIdx];
  if (!clip) return Math.max(0, rawTlStart);
  var dur = trimDur(clip);
  var start = Math.max(0, rawTlStart);
  var end = start + dur;
  var pps = pxPerSecond();
  var thresh = Math.max(0.04, SNAP_PX / Math.max(pps, 1));
  var bestDist = thresh + 0.001;
  var bestStart = start;
  var snapped = false;

  function trySnapStart(candidateStart) {
    if (candidateStart < -0.001) return;
    var dist = Math.abs(start - candidateStart);
    if (dist <= thresh && dist < bestDist) {
      bestDist = dist;
      bestStart = candidateStart;
      snapped = true;
    }
  }

  function trySnapEnd(candidateEnd) {
    var candidateStart = candidateEnd - dur;
    if (candidateStart < -0.001) return;
    var dist = Math.abs(end - candidateEnd);
    if (dist <= thresh && dist < bestDist) {
      bestDist = dist;
      bestStart = candidateStart;
      snapped = true;
    }
  }

  trySnapStart(0);

  CLIPS.forEach(function(other, i) {
    if (i === dragIdx) return;
    var oStart = other.tlStart || 0;
    var oEnd = clipEnd(other);
    trySnapStart(oStart);
    trySnapStart(oEnd);
    trySnapEnd(oStart);
    trySnapEnd(oEnd);
  });

  return { tl: Math.round(bestStart * 100) / 100, snapped: snapped };
}

var TIMELINE_FPS = 24;

function frameDuration() {
  return 1 / TIMELINE_FPS;
}

function snapGlobalTimeToFrame(gt) {
  var fd = frameDuration();
  return Math.round(gt / fd) * fd;
}

function focusEditingRoom() {
  var room = document.getElementById('edRoomRoot');
  if (room) try { room.focus({preventScroll: true}); } catch(e) {}
}

function stepFrame(direction) {
  if (!CLIPS.length) return;
  gapPlayActive = false;
  trimEndLatch = false;
  var v = activeVid;
  if (v && !v.paused) {
    v.pause();
    syncPlayBtn();
    stopRaf();
  }
  var gt = snapGlobalTimeToFrame(getElapsed());
  var fd = frameDuration();
  var nextGt = gt + direction * fd;
  if (nextGt < 0 || nextGt > totalDur() + 0.0001) return;
  nextGt = Math.max(0, Math.min(nextGt, totalDur()));
  seekToGlobalTime(nextGt, false);
  focusEditingRoom();
}

function fmtTime(s) {
  if (isNaN(s) || s < 0) s = 0;
  var m = Math.floor(s / 60);
  var sec = Math.floor(s % 60);
  return (m < 10 ? '0' : '') + m + ':' + (sec < 10 ? '0' : '') + sec;
}

function fmtRulerTime(s) {
  if (isNaN(s) || s < 0) s = 0;
  if (s >= 60) return fmtTime(s);
  if (s >= 10) return Math.floor(s) + 's';
  return (Math.round(s * 10) / 10).toFixed(1) + 's';
}

function pxPerSecond() {
  return BASE_PPS * zoomLevel;
}

function timeToPx(t) {
  return Math.max(0, t) * pxPerSecond();
}

function pxToTime(px) {
  var pps = pxPerSecond();
  if (pps <= 0) return 0;
  return Math.max(0, px / pps);
}

function timelineWidthPx() {
  var scroll = document.getElementById('edTrackScroll');
  var cw = scroll ? scroll.clientWidth : 800;
  return Math.max(totalDur() * pxPerSecond(), cw || 800);
}

function chooseRulerSteps(pps) {
  if (pps >= 140) return { major: 1, minor: 0.5, showFrames: true, frameStep: 1 };
  if (pps >= 70)  return { major: 1, minor: 0.25, showFrames: true, frameStep: 2 };
  if (pps >= 35)  return { major: 2, minor: 0.5, showFrames: false, frameStep: 0 };
  if (pps >= 18)  return { major: 5, minor: 1, showFrames: false, frameStep: 0 };
  if (pps >= 9)   return { major: 10, minor: 2, showFrames: false, frameStep: 0 };
  return { major: 30, minor: 10, showFrames: false, frameStep: 0 };
}

function syncRulerWidth() {
  var track = document.getElementById('edTrackInner');
  var rulerInner = document.getElementById('edRulerInner');
  if (!track || !rulerInner) return;
  var w = track.offsetWidth;
  rulerInner.style.width = w + 'px';
}

function updatePlayhead() {
  var ph = document.getElementById('edPlayhead');
  var phg = document.getElementById('edPlayheadGrab');
  if (!ph) return;
  var px = timeToPx(getElapsed());
  ph.style.left = px + 'px';
  if (phg) phg.style.left = px + 'px';
}

function updateRuler() {
  var rulerInner = document.getElementById('edRulerInner');
  if (!rulerInner) return;
  syncRulerWidth();
  rulerInner.innerHTML = '';
  var td = totalDur();
  if (td <= 0) return;
  var pps = pxPerSecond();
  if (pps <= 0) return;
  var steps = chooseRulerSteps(pps);
  var frameDur = 1 / TIMELINE_FPS;

  /* Clip boundaries — align with timeline positions */
  CLIPS.forEach(function(c, i) {
    var px = timeToPx(c.tlStart || 0);
    var cm = document.createElement('div');
    cm.className = 'ed-ruler-tick clip-mark';
    cm.style.left = px + 'px';
    rulerInner.appendChild(cm);
    var cl = document.createElement('div');
    cl.className = 'ed-ruler-label clip-mark';
    cl.style.left = px + 'px';
    cl.textContent = 'C' + (i + 1);
    rulerInner.appendChild(cl);
  });
  var endPx = timeToPx(td);
  var endTick = document.createElement('div');
  endTick.className = 'ed-ruler-tick clip-mark';
  endTick.style.left = endPx + 'px';
  rulerInner.appendChild(endTick);

  /* Frame ticks when zoomed in */
  if (steps.showFrames && steps.frameStep > 0) {
    var stepT = frameDur * steps.frameStep;
    for (var ft = 0; ft <= td + 0.0001; ft += stepT) {
      var fpx = timeToPx(ft);
      var ftk = document.createElement('div');
      ftk.className = 'ed-ruler-tick frame';
      ftk.style.left = fpx + 'px';
      rulerInner.appendChild(ftk);
    }
  }

  /* Time ticks — pixel-aligned to track */
  var minor = steps.minor;
  var major = steps.major;
  for (var t = 0; t <= td + 0.0001; t += minor) {
    var px = timeToPx(t);
    var isMajor = (Math.abs(t % major) < minor * 0.01) || t < 0.001;
    var tk = document.createElement('div');
    tk.className = 'ed-ruler-tick' + (isMajor ? ' major' : ' mid');
    tk.style.left = px + 'px';
    rulerInner.appendChild(tk);
    if (isMajor) {
      var lb = document.createElement('div');
      lb.className = 'ed-ruler-label';
      lb.style.left = px + 'px';
      var frameNum = Math.round(t * TIMELINE_FPS);
      if (steps.showFrames) {
        lb.textContent = fmtRulerTime(t) + ' · F' + (frameNum + 1);
      } else {
        lb.textContent = fmtRulerTime(t);
      }
      rulerInner.appendChild(lb);
    }
  }
}

function buildTrack() {
  var track = document.getElementById('edTrackInner');
  var scroll = document.getElementById('edTrackScroll');
  if (!track || !scroll) return;
  track.querySelectorAll('.ed-clip').forEach(function(n) { n.remove(); });
  var pps = pxPerSecond();
  var tw = timelineWidthPx();
  track.style.width = tw + 'px';
  var ph = document.getElementById('edPlayhead');
  var h = (track.offsetHeight || CLIP_TRACK_H) + 'px';
  if (ph) { ph.style.height = h; }
  var phg = document.getElementById('edPlayheadGrab');
  if (phg) { phg.style.height = h; }

  CLIPS.forEach(function(clip, i) {
    var div = document.createElement('div');
    var cls = 'ed-clip' + (i === activeIdx ? ' active' : '');
    if (clip.splitPart) cls += ' split-part';
    if (clipDragState && clipDragState.idx === i) {
      cls += ' dragging';
      if (clipDragState.snapped) cls += ' snap';
    }
    div.className = cls;
    div.dataset.idx = String(i);
    var cw = Math.max(28, Math.round(timeToPx(trimDur(clip))));
    div.style.width = cw + 'px';
    div.style.left = Math.round(timeToPx(clip.tlStart || 0)) + 'px';
    div.style.minWidth = '28px';

    if (clip.thumb) {
      div.innerHTML = '<img src="' + clip.thumb + '" draggable="false" alt=""/>';
    } else if (clip.vurl) {
      div.innerHTML = '<video src="' + clip.vurl + '" preload="metadata" muted playsinline></video>';
    } else {
      div.innerHTML = '<div class="ed-clip-fallback">' + (i + 1) + '</div>';
    }
    var badge = String(i + 1);
    if (clip.splitPart) badge += '<span class="ed-badge-split">' + clip.splitPart + '</span>';
    div.innerHTML += '<div class="ed-badge">' + badge + '</div>';
    div.innerHTML += '<div class="ed-rm" data-rm="' + i + '">&times;</div>';
    var trimDim = (i !== activeIdx) ? ' ed-trim-dim' : '';
    div.innerHTML += '<div class="ed-trim-l' + trimDim + '" data-idx="' + i + '" data-side="left"></div>';
    div.innerHTML += '<div class="ed-trim-r' + trimDim + '" data-idx="' + i + '" data-side="right"></div>';
    track.appendChild(div);
  });

  track.querySelectorAll('.ed-rm').forEach(function(btn) {
    btn.addEventListener('mousedown', function(e) {
      e.stopPropagation();
      e.preventDefault();
    });
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      removeClip(parseInt(btn.getAttribute('data-rm'), 10));
    });
  });

  syncRulerWidth();
  updateRuler();
  updatePlayhead();
  updateReadout();
  updateCutButton();
  updateDeleteButton();
}

function selectedClipIdx() {
  if (activeIdx >= 0 && activeIdx < CLIPS.length) return activeIdx;
  var hit = findClipAtGlobalTime(getElapsed());
  if (!hit.inGap && hit.idx >= 0) return hit.idx;
  return -1;
}

function updateDeleteButton() {
  var btn = document.getElementById('edDelete');
  if (!btn) return;
  btn.disabled = selectedClipIdx() < 0;
}

function deleteSelectedClip() {
  var idx = selectedClipIdx();
  if (idx < 0) return;
  removeClip(idx);
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

function setPlayheadTime(gt) {
  playheadTime = Math.max(0, Math.min(Number(gt) || 0, totalDur()));
  gapGlobalTime = playheadTime;
}

function syncPlayheadFromVideo() {
  if (seekPending || inGap || gapPlayActive || activeIdx < 0) return;
  if (!videoMatchesActiveClip()) return;
  var v = activeVid;
  var c = CLIPS[activeIdx];
  if (!c || !v) return;
  if (v.seeking) return;
  var tl = c.tlStart || 0;
  setPlayheadTime(tl + Math.max(0, Math.min(v.currentTime - c.ts, trimDur(c))));
}

function getElapsed() {
  if (gapPlayActive) {
    var elapsed = (performance.now() - gapPlayStartWall) / 1000;
    setPlayheadTime(Math.min(gapPlayFrom + elapsed, gapPlayTo));
  }
  return playheadTime;
}

function updateReadout() {
  var el = document.getElementById('edTimeReadout');
  if (!el) return;
  var td = totalDur();
  el.textContent = fmtTime(getElapsed()) + ' / ' + fmtTime(td);
  var tl = document.getElementById('edTotalLab');
  if (tl) tl.textContent = 'TOTAL ' + fmtTime(td);
  updateCutButton();
}

function syncPlayBtn() {
  var b = document.getElementById('edPlayPause');
  if (!b) return;
  if (gapPlayActive) {
    b.textContent = 'PAUSE';
    return;
  }
  if (inGap) {
    b.textContent = 'PLAY';
    return;
  }
  var v = activeVid;
  if (!v) return;
  b.textContent = v.paused ? 'PLAY' : 'PAUSE';
}

function stopRaf() {
  if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
}
function loop() {
  if (gapPlayActive) {
    getElapsed();
    if (playheadTime >= gapPlayTo - 0.02) {
      gapPlayActive = false;
      var next = nextClipAfterTime(gapPlayTo - 0.001);
      if (next) {
        inGap = false;
        seekToGlobalTime(next.tl, true);
      } else {
        inGap = true;
        setPlayheadTime(gapPlayTo);
        activeVid.pause();
        syncPlayBtn();
      }
    }
    updatePlayhead();
    updateReadout();
    rafId = requestAnimationFrame(loop);
    return;
  }
  syncPlayheadFromVideo();
  updatePlayhead();
  updateReadout();
  var v = activeVid;
  if (v && !v.paused) rafId = requestAnimationFrame(loop);
  else rafId = null;
}
function startRaf() {
  if (!rafId) rafId = requestAnimationFrame(loop);
}

function preloadNextByTime() {
  var gt = getElapsed();
  var next = nextClipAfterTime(gt);
  if (next) preloadInto(standbyVid, next.idx);
}

function clientXToGlobalTime(clientX) {
  var inner = document.getElementById('edTrackInner');
  var scroll = document.getElementById('edTrackScroll');
  if (!inner || !scroll) return playheadTime;
  var rect = inner.getBoundingClientRect();
  var x = clientX - rect.left + scroll.scrollLeft;
  return Math.max(0, Math.min(pxToTime(x), totalDur()));
}

function resolvePlayheadAt(gt) {
  gt = Math.max(0, Math.min(Number(gt) || 0, totalDur()));
  setPlayheadTime(gt);
  var hit = findClipAtGlobalTime(gt);
  if (!hit.inGap && hit.idx >= 0) {
    inGap = false;
    activeIdx = hit.idx;
    return hit;
  }
  inGap = true;
  activeIdx = -1;
  return null;
}

function selectClipAtPointer(clientX, clipIdx) {
  var gt = clientXToGlobalTime(clientX);
  if (clipIdx >= 0 && clipIdx < CLIPS.length) {
    var c = CLIPS[clipIdx];
    var tl = c.tlStart || 0;
    var end = tl + trimDur(c);
    gt = Math.max(tl, Math.min(gt, end));
    setPlayheadTime(gt);
    inGap = false;
    activeIdx = clipIdx;
    trimEndLatch = false;
    return clipIdx;
  }
  resolvePlayheadAt(gt);
  return activeIdx;
}

function refreshPlayheadUI() {
  updatePlayhead();
  updateReadout();
  updateCutButton();
  updateDeleteButton();
  buildTrack();
}

function syncVideoToPlayhead(andPlay) {
  gapPlayActive = false;
  trimEndLatch = false;
  if (activeIdx < 0) {
    seekPending = false;
    var vGap = activeVid;
    if (vGap) {
      vGap.pause();
      vGap.removeAttribute('src');
      try { vGap.load(); } catch(e) {}
    }
    stopRaf();
    syncPlayBtn();
    return;
  }
  if (inGap) {
    seekPending = false;
    stopRaf();
    syncPlayBtn();
    return;
  }
  var hit = findClipAtGlobalTime(playheadTime);
  if (hit && !hit.inGap && hit.idx >= 0) {
    activeIdx = hit.idx;
    inGap = false;
  }
  var idx = activeIdx;
  if (idx < 0 || idx >= CLIPS.length) {
    seekPending = false;
    syncPlayBtn();
    return;
  }
  var c = CLIPS[idx];
  var v = activeVid;
  var wantPlay = andPlay === true;
  if (!c || !c.vurl || !v) {
    seekPending = false;
    syncPlayBtn();
    return;
  }
  v.pause();
  stopRaf();
  var applySeek = function() {
    seekPending = false;
    var h = findClipAtGlobalTime(playheadTime);
    var localT = c.ts;
    if (h && !h.inGap) {
      localT = h.localT;
    } else {
      var tl = c.tlStart || 0;
      localT = Math.max(c.ts, Math.min(c.ts + (playheadTime - tl), c.te > 0 ? c.te : c.ts + trimDur(c)));
    }
    v.currentTime = localT;
    setPlayheadTime(playheadTime);
    if (wantPlay) { v.play().catch(function(){}); startRaf(); }
    refreshPlayheadUI();
    preloadNextByTime();
    syncPlayBtn();
  };
  seekPending = true;
  if (videoMatchesActiveClip() && v.readyState >= 1) {
    applySeek();
  } else {
    v.src = c.vurl;
    v.addEventListener('loadedmetadata', function once() {
      v.removeEventListener('loadedmetadata', once);
      applySeek();
    });
    v.addEventListener('error', function onErr() {
      v.removeEventListener('error', onErr);
      seekPending = false;
      refreshPlayheadUI();
    });
    try { v.load(); } catch(e2) {
      seekPending = false;
    }
  }
}

function seekToGlobalTime(gt, andPlay) {
  resolvePlayheadAt(gt);
  refreshPlayheadUI();
  syncVideoToPlayhead(andPlay);
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
  seekPending = false;
  bindActiveEvents();
  syncPlayheadFromVideo();
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
  c.mediaD = Math.round(realDur * 100) / 100;
  c.d = c.mediaD;
  if (c.te > c.mediaD || c.te <= 0) c.te = c.mediaD;
  if (c.ts >= c.mediaD) c.ts = 0;
}
v.currentTime = c.ts;
if (wantPlay) { v.play().catch(function(){}); startRaf(); }
buildTrack(); updatePlayhead(); updateReadout(); syncPlayBtn();
preloadNextByTime();
if (onReady) onReady();
return;
  }
  v.src = c.vurl;
  var onMeta = function() {
v.removeEventListener('loadedmetadata', onMeta);
var realDur = v.duration;
if (realDur && isFinite(realDur) && realDur > 0) {
  c.mediaD = Math.round(realDur * 100) / 100;
  c.d = c.mediaD;
  if (c.te > c.mediaD || c.te <= 0) c.te = c.mediaD;
  if (c.ts >= c.mediaD) c.ts = 0;
}
v.currentTime = c.ts;
if (wantPlay) { v.play().catch(function(){}); startRaf(); }
buildTrack(); updatePlayhead(); updateReadout(); syncPlayBtn();
preloadNextByTime();
if (onReady) onReady();
  };
  v.addEventListener('loadedmetadata', onMeta);
  try { v.load(); } catch(e2) {}
  syncPlayBtn();
}

function selectClip(idx, playOn, keepPosition) {
  trimEndLatch = false;
  gapPlayActive = false;
  if (idx < 0 || idx >= CLIPS.length) return;
  var c = CLIPS[idx];
  if (keepPosition) {
    var hit = findClipAtGlobalTime(getElapsed());
    if (!hit.inGap && hit.idx === idx) {
      inGap = false;
      activeIdx = idx;
      buildTrack();
      updateDeleteButton();
      focusEditingRoom();
      if (playOn && c.vurl && activeVid) {
        activeVid.play().catch(function(){});
        startRaf();
        syncPlayBtn();
      }
      return;
    }
  }
  inGap = false;
  seekToGlobalTime(c.tlStart || 0, playOn);
  focusEditingRoom();
}

function bindActiveEvents() {
  var v = activeVid;
  v.onplay = function() { syncPlayBtn(); startRaf(); };
  v.onpause = function() { syncPlayBtn(); stopRaf(); syncPlayheadFromVideo(); updatePlayhead(); updateReadout(); };
  v.onseeked = function() {
    trimEndLatch = false;
    syncPlayheadFromVideo();
    updatePlayhead();
    updateReadout();
  };
  v.ontimeupdate = handleTimeUpdate;
  v.onended = function() {
    trimEndLatch = true;
    advanceToNext();
  };
}

function handleTimeUpdate() {
  if (trimEndLatch) return;
  var v = activeVid;
  var c = CLIPS[activeIdx];
  if (!c || !c.vurl) { updatePlayhead(); updateReadout(); return; }
  if (c.te < c.d && v.currentTime >= c.te - 0.12) {
    trimEndLatch = true;
    advanceToNext();
    return;
  }
  syncPlayheadFromVideo();
  updatePlayhead();
  updateReadout();
}

function advanceToNext() {
  var c = CLIPS[activeIdx];
  if (!c) { trimEndLatch = false; return; }
  var endT = clipEnd(c);
  var next = nextClipAfterTime(endT - 0.001);
  if (!next) {
    trimEndLatch = false;
    activeVid.pause();
    syncPlayBtn();
    return;
  }
  if (next.tl > endT + 0.02) {
    trimEndLatch = false;
    seekPending = false;
    activeVid.pause();
    inGap = true;
    setPlayheadTime(endT);
    gapPlayActive = true;
    gapPlayFrom = endT;
    gapPlayTo = next.tl;
    gapPlayStartWall = performance.now();
    updatePlayhead();
    startRaf();
    syncPlayBtn();
    return;
  }
  activeIdx = next.idx;
  inGap = false;
  seekPending = true;
  setPlayheadTime(next.tl);
  var nc = CLIPS[next.idx];
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
    preloadNextByTime();
    trimEndLatch = false;
  } else {
    sb.src = nc.vurl;
    sb.addEventListener('canplay', function once() {
      sb.removeEventListener('canplay', once);
      sb.currentTime = nc.ts;
      setPlayheadTime(next.tl);
      swapToStandby(true);
      preloadNextByTime();
      trimEndLatch = false;
    });
    try { sb.load(); } catch(e3) {
      seekPending = false;
      trimEndLatch = false;
    }
  }
}

/* ═══ Remove clip ═══ */
function removeClip(idx) {
  if (idx < 0 || idx >= CLIPS.length) return;
  recordHistory();
  var timePos = getElapsed();
  CLIPS.splice(idx, 1);
  if (!CLIPS.length) {
activeIdx = 0;
var v = activeVid;
if (v) { v.pause(); v.removeAttribute('src'); try { v.load(); } catch(e) {} }
buildTrack(); syncPlayBtn(); updatePlayhead(); updateReadout();
pushTimeline();
return;
  }
  for (var k = 0; k < CLIPS.length; k++) CLIPS[k].i = k;
  var wasPaused = (activeVid && activeVid.paused) && !gapPlayActive;
  seekToGlobalTime(Math.min(timePos, totalDur()), !wasPaused);
  pushTimeline();
}

/* ═══ CUT at playhead — split active clip ═══ */
function canCutAtPlayhead() {
  if (!CLIPS.length || inGap || gapPlayActive) return false;
  var gt = getElapsed();
  var hit = findClipAtGlobalTime(gt);
  if (hit.inGap || hit.idx < 0) return false;
  var c = CLIPS[hit.idx];
  var local = gt - (c.tlStart || 0);
  return local > 0.15 && local < trimDur(c) - 0.15;
}

function updateCutButton() {
  var btn = document.getElementById('edCut');
  var hint = document.getElementById('edCutHint');
  if (!btn) return;
  var ok = canCutAtPlayhead();
  btn.disabled = !ok;
  if (hint) {
    hint.textContent = ok
      ? 'Split clip at playhead (C)'
      : 'Move playhead inside a clip to cut';
  }
}

function cutAtPlayhead() {
  if (!canCutAtPlayhead()) return;
  recordHistory();
  var gt = getElapsed();
  var hit = findClipAtGlobalTime(gt);
  if (hit.inGap || hit.idx < 0) return;
  var i = hit.idx;
  var c = CLIPS[i];
  var localInTrim = gt - (c.tlStart || 0);
  var cutSourceT = Math.round((c.ts + localInTrim) * 100) / 100;
  var mediaD = getMediaDur(c);
  var splitId = c.splitId || ('s' + (++_splitCounter));
  c.splitId = splitId;
  c.splitPart = 'A';
  var baseCap = (c.cap || '').replace(/ \(A\)$/, '').replace(/ \(B\)$/, '');
  c.cap = baseCap + ' (A)';
  var rightClip = {
    i: i + 1,
    ts: cutSourceT,
    te: c.te,
    d: mediaD,
    mediaD: mediaD,
    tlStart: Math.round(((c.tlStart || 0) + localInTrim) * 100) / 100,
    thumb: c.thumb,
    vurl: c.vurl,
    path: c.path || '',
    cap: baseCap + ' (B)',
    splitId: splitId,
    splitPart: 'B'
  };
  c.te = cutSourceT;
  c.d = mediaD;
  c.mediaD = mediaD;
  CLIPS.splice(i + 1, 0, rightClip);
  for (var k = 0; k < CLIPS.length; k++) CLIPS[k].i = k;
  trimEndLatch = false;
  activeIdx = i;
  var v = activeVid;
  if (v && c.vurl) v.currentTime = cutSourceT;
  buildTrack();
  updatePlayhead();
  updateReadout();
  updateCutButton();
  preloadNextByTime();
  pushTimeline();
}

/* ═══ Timeline zoom ═══ */
function applyZoom(val) {
  zoomLevel = Math.max(0.5, Math.min(8, Math.round(val * 4) / 4));
  var sl = document.getElementById('edZoomSlider');
  var lb = document.getElementById('edZoomLabel');
  if (sl) sl.value = zoomLevel;
  if (lb) lb.textContent = zoomLevel + '×';
  buildTrack();
  updateRuler();
  updatePlayhead();
}

document.getElementById('edZoomIn').addEventListener('click', function() {
  applyZoom(zoomLevel + 0.25);
});
document.getElementById('edZoomOut').addEventListener('click', function() {
  applyZoom(zoomLevel - 0.25);
});
document.getElementById('edZoomSlider').addEventListener('input', function() {
  applyZoom(parseFloat(this.value));
});

document.getElementById('edTrackScroll').addEventListener('wheel', function(e) {
  if (e.ctrlKey || e.metaKey) {
    e.preventDefault();
    applyZoom(zoomLevel + (e.deltaY < 0 ? 0.25 : -0.25));
  }
}, {passive:false});
(function() {
  var zoomBar = document.querySelector('.ed-timeline-controls');
  if (!zoomBar) return;
  zoomBar.addEventListener('wheel', function(e) {
    e.preventDefault();
    applyZoom(zoomLevel + (e.deltaY < 0 ? 0.25 : -0.25));
  }, {passive:false});
})();

/* Keep ruler scroll locked to track when timeline is wider than viewport */
(function() {
  var trackScroll = document.getElementById('edTrackScroll');
  var rulerScroll = document.getElementById('edRulerScroll');
  if (!trackScroll || !rulerScroll) return;
  trackScroll.addEventListener('scroll', function() {
    rulerScroll.scrollLeft = trackScroll.scrollLeft;
  });
  rulerScroll.addEventListener('scroll', function() {
    trackScroll.scrollLeft = rulerScroll.scrollLeft;
  });
})();

/* ═══ Transport controls ═══ */
document.getElementById('edPrev').addEventListener('click', function() {
  var wasP = gapPlayActive || (activeVid && !activeVid.paused);
  var prev = prevClipBeforeTime(getElapsed());
  if (!prev) return;
  selectClip(prev.idx, wasP);
});
document.getElementById('edNext').addEventListener('click', function() {
  var wasP = gapPlayActive || (activeVid && !activeVid.paused);
  var next = nextClipAfterTime(getElapsed());
  if (!next) return;
  selectClip(next.idx, wasP);
});
document.getElementById('edPlayPause').addEventListener('click', function() {
  if (gapPlayActive) {
    gapPlayActive = false;
    gapGlobalTime = getElapsed();
    inGap = true;
    stopRaf();
    syncPlayBtn();
    return;
  }
  if (inGap) {
    var next = nextClipAfterTime(gapGlobalTime);
    if (next) {
      gapPlayActive = true;
      gapPlayFrom = gapGlobalTime;
      gapPlayTo = next.tl;
      gapPlayStartWall = performance.now();
      inGap = false;
      startRaf();
      syncPlayBtn();
    }
    return;
  }
  var v = activeVid;
  if (!v || !CLIPS[activeIdx] || !CLIPS[activeIdx].vurl) return;
  if (v.paused) { v.play().catch(function(){}); startRaf(); } else { v.pause(); }
  syncPlayBtn();
});

document.getElementById('edCut').addEventListener('click', function() {
  cutAtPlayhead();
});
document.getElementById('edDelete').addEventListener('click', function() {
  deleteSelectedClip();
});
document.getElementById('edUndo').addEventListener('click', function() {
  undo();
});
document.getElementById('edRedo').addEventListener('click', function() {
  redo();
});

/* ═══ Keyboard shortcuts ═══ */
document.addEventListener('keydown', function(e) {
  var tag = (e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea') return;
  var v = activeVid;
  if ((e.ctrlKey || e.metaKey) && e.code === 'KeyZ') {
    e.preventDefault();
    if (e.shiftKey) redo(); else undo();
    return;
  }
  switch(e.code) {
case 'Space': case 'KeyK':
  e.preventDefault();
  document.getElementById('edPlayPause').click();
  break;
case 'ArrowLeft':
  e.preventDefault();
  if (e.shiftKey) {
    var p = prevClipBeforeTime(getElapsed());
    if (p) selectClip(p.idx, gapPlayActive || (v && !v.paused));
  } else {
    stepFrame(-1);
  }
  break;
case 'ArrowRight':
  e.preventDefault();
  if (e.shiftKey) {
    var n = nextClipAfterTime(getElapsed());
    if (n) selectClip(n.idx, gapPlayActive || (v && !v.paused));
  } else {
    stepFrame(1);
  }
  break;
case 'ArrowUp':
  e.preventDefault();
  selectAdjacentClip(-1);
  break;
case 'ArrowDown':
  e.preventDefault();
  selectAdjacentClip(1);
  break;
case 'KeyJ':
  e.preventDefault();
  gapPlayActive = false;
  if (v && !v.paused) { v.pause(); syncPlayBtn(); stopRaf(); }
  seekToGlobalTime(Math.max(0, getElapsed() - 1), false);
  focusEditingRoom();
  break;
case 'KeyL':
  e.preventDefault();
  gapPlayActive = false;
  if (v && !v.paused) { v.pause(); syncPlayBtn(); stopRaf(); }
  seekToGlobalTime(Math.min(totalDur(), getElapsed() + 1), false);
  focusEditingRoom();
  break;
case 'Home':
  e.preventDefault(); seekToGlobalTime(0, false); break;
case 'End':
  e.preventDefault();
  { var sorted = clipsSortedByTime(); if (sorted.length) seekToGlobalTime(sorted[sorted.length - 1].c.tlStart || 0, false); }
  break;
case 'KeyC':
  e.preventDefault();
  cutAtPlayhead();
  break;
case 'Delete': case 'Backspace':
  e.preventDefault();
  deleteSelectedClip();
  break;
case 'Equal': case 'NumpadAdd':
  if (e.ctrlKey || e.metaKey) { e.preventDefault(); applyZoom(zoomLevel + 0.25); }
  break;
case 'Minus': case 'NumpadSubtract':
  if (e.ctrlKey || e.metaKey) { e.preventDefault(); applyZoom(zoomLevel - 0.25); }
  break;
case 'Digit0': case 'Numpad0':
  if (e.ctrlKey || e.metaKey) { e.preventDefault(); applyZoom(1); }
  break;
  }
});

/* ── Playhead scrub system: click ruler or drag playhead to seek ── */
var scrubState = null;

function scrubToX(clientX, clipIdx) {
  if (clipIdx >= 0) {
    selectClipAtPointer(clientX, clipIdx);
  } else {
    resolvePlayheadAt(clientXToGlobalTime(clientX));
  }
  refreshPlayheadUI();
  focusEditingRoom();
}

function clipIndexFromEvent(e) {
  var clipEl = e.target.closest('.ed-clip');
  if (!clipEl) return -1;
  var cidx = parseInt(clipEl.dataset.idx, 10);
  return (isNaN(cidx) || cidx < 0 || cidx >= CLIPS.length) ? -1 : cidx;
}

function beginPlayheadScrub(e, source) {
  if (e.target.closest('.ed-trim-l') || e.target.closest('.ed-trim-r') ||
      e.target.closest('.ed-rm')) return false;
  if (e.shiftKey && e.target.closest('.ed-clip')) return false;
  focusEditingRoom();
  e.preventDefault();
  gapPlayActive = false;
  seekPending = false;
  var clipIdx = clipIndexFromEvent(e);
  scrubState = {
    source: source || 'track',
    moved: false,
    startX: e.clientX,
    clipIdx: clipIdx
  };
  var v = activeVid;
  if (v && !v.paused) {
    scrubState.wasPlaying = true;
    v.pause();
    stopRaf();
  }
  scrubToX(e.clientX, clipIdx);
  return true;
}

document.getElementById('edPlayheadGrab').addEventListener('mousedown', function(e) {
  e.preventDefault();
  e.stopPropagation();
  this.classList.add('dragging');
  beginPlayheadScrub(e, 'playhead');
});

document.getElementById('edRulerScroll').addEventListener('mousedown', function(e) {
  beginPlayheadScrub(e, 'ruler');
});

document.getElementById('edTrackInner').addEventListener('mousedown', function(e) {
  if (e.target.closest('.ed-playhead-grab')) return;
  beginPlayheadScrub(e, e.target.closest('.ed-clip') ? 'clip' : 'track');
});

document.addEventListener('mousemove', function(e) {
  if (!scrubState) return;
  if (Math.abs(e.clientX - scrubState.startX) > 2) {
    scrubState.moved = true;
    scrubState.clipIdx = -1;
  }
  e.preventDefault();
  scrubToX(e.clientX, scrubState.moved ? -1 : scrubState.clipIdx);
});

document.addEventListener('mouseup', function(e) {
  if (clipDragState) {
    if (clipDragState.moved) {
      var rawEnd = clipDragState.origTlStart +
        ((e.clientX - clipDragState.startX) / Math.max(pxPerSecond(), 1));
      var snapEnd = snapClipTlStart(clipDragState.idx, rawEnd);
      CLIPS[clipDragState.idx].tlStart = snapEnd.tl;
      recordHistory();
      pushTimeline();
      buildTrack();
    }
    clipDragState = null;
  }
  if (!scrubState) return;
  var phg = document.getElementById('edPlayheadGrab');
  if (phg) phg.classList.remove('dragging');
  if (!scrubState.moved && scrubState.clipIdx >= 0) {
    selectClipAtPointer(e.clientX, scrubState.clipIdx);
    refreshPlayheadUI();
  }
  var resume = scrubState.wasPlaying && !inGap;
  syncVideoToPlayhead(resume);
  scrubState = null;
});

document.addEventListener('mousedown', function(e) {
  if (e.shiftKey) {
    var clipEl = e.target.closest('.ed-clip');
    if (clipEl && !e.target.closest('.ed-trim-l') && !e.target.closest('.ed-trim-r') &&
        !e.target.closest('.ed-rm')) {
      e.preventDefault();
      e.stopPropagation();
      var cidx = parseInt(clipEl.dataset.idx, 10);
      if (!isNaN(cidx) && cidx >= 0 && cidx < CLIPS.length) {
        clipDragState = {
          idx: cidx,
          startX: e.clientX,
          origTlStart: CLIPS[cidx].tlStart || 0,
          moved: false,
          snapped: false
        };
      }
    }
    return;
  }
  var h = e.target;
  if (!h.classList || (!h.classList.contains('ed-trim-l') && !h.classList.contains('ed-trim-r'))) return;
  e.preventDefault();
  e.stopPropagation();
  var idx = parseInt(h.getAttribute('data-idx'), 10);
  if (isNaN(idx) || idx < 0 || idx >= CLIPS.length) return;
  recordHistory();
  if (idx !== activeIdx) selectClip(idx, false);
  var clipEl = h.closest('.ed-clip');
  if (!clipEl) return;
  var rect = clipEl.getBoundingClientRect();
  var mc = CLIPS[idx];
  var maxD = getMediaDur(mc);
  trimState = {
idx: idx,
side: h.getAttribute('data-side'),
startX: e.clientX,
rect: rect,
origStart: mc.ts,
origEnd: mc.te,
mediaD: maxD
  };
});
document.addEventListener('mousemove', function(e) {
  if (clipDragState) {
    e.preventDefault();
    var dx = e.clientX - clipDragState.startX;
    if (Math.abs(dx) > 4) clipDragState.moved = true;
    var pps = pxPerSecond();
    if (pps > 0) {
      var dSec = dx / pps;
      var rawTl = clipDragState.origTlStart + dSec;
      var snap = snapClipTlStart(clipDragState.idx, rawTl);
      CLIPS[clipDragState.idx].tlStart = snap.tl;
      clipDragState.snapped = snap.snapped;
      buildTrack();
      updatePlayhead();
    }
    return;
  }
  if (!trimState) return;
  e.preventDefault();
  var clipEl = document.querySelector('.ed-clip[data-idx="' + trimState.idx + '"]');
  if (clipEl) trimState.rect = clipEl.getBoundingClientRect();
  var dx = e.clientX - trimState.startX;
  var span = Math.max(0.1, trimState.origEnd - trimState.origStart);
  var ds = dx / (trimState.rect.width / span);
  var maxD = trimState.mediaD;
  if (trimState.side === 'left') {
CLIPS[trimState.idx].ts = Math.round(
  Math.max(0, Math.min(trimState.origStart + ds, trimState.origEnd - 0.3)) * 100) / 100;
  } else {
CLIPS[trimState.idx].te = Math.round(
  Math.max(trimState.origStart + 0.3, Math.min(trimState.origEnd + ds, maxD)) * 100) / 100;
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
pushTimeline();
trimState = null;
  }
});

document.getElementById('edExportAll').addEventListener('click', function() {
  doExport(false);
});
document.getElementById('edExportSel').addEventListener('click', function() {
  doExport(true);
});

window.addEventListener('resize', function() {
  buildTrack();
  updateRuler();
  updatePlayhead();
});

function init() {
  bindActiveEvents();
  focusEditingRoom();
  updateUndoRedoButtons();
  var startIdx = __ACTIVE_IDX__;
  if (isNaN(startIdx) || startIdx < 0) startIdx = 0;
  if (startIdx >= CLIPS.length) startIdx = Math.max(0, CLIPS.length - 1);
  activeIdx = startIdx;
  if (CLIPS.length) {
    seekToGlobalTime(CLIPS[startIdx].tlStart || 0, false);
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
        _ed_room_html.replace("__CLIPS_B64__", clips_b64)
        .replace("__UNDO_B64__", undo_b64)
        .replace("__REDO_B64__", redo_b64)
        .replace("__ACTIVE_IDX__", str(active_idx_init))
        .replace("__PREFIX_JSON__", prefix_js)
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
                                  disabled=True, width="stretch")

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
                _sbi_prefix = f"sbi{key_suffix}"
                _render_storyboard_grid("sb_active_images", "gallery_selected_imgs", media_type, _sbi_prefix)

                _sb_selected = st.session_state.get(f"{_sbi_prefix}_selected", [])
                if _sb_selected:
                    _del_cols = st.columns([1, 1, 4])
                    with _del_cols[0]:
                        if st.button(f"Delete {len(_sb_selected)} selected", key=f"{_sbi_prefix}_bulk_delete", type="secondary"):
                            _bd_items = st.session_state.get("sb_active_images", [])
                            st.session_state["sb_active_images"] = [it for i, it in enumerate(_bd_items) if i not in _sb_selected]
                            _n_deleted = len(_sb_selected)
                            st.session_state[f"{_sbi_prefix}_selected"] = []
                            _autosave_storyboard_snapshot()
                            st.toast(f"Deleted {_n_deleted} item(s)")
                            st.rerun()
                    with _del_cols[1]:
                        if st.button("Clear selection", key=f"{_sbi_prefix}_clear_selection", type="secondary"):
                            st.session_state[f"{_sbi_prefix}_selected"] = []
                            st.rerun()

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

                if is_storyboard:
                    st.markdown(
                        '<p style="color:#9E9E8A;font-size:0.72rem;font-weight:600;letter-spacing:0.06em;'
                        'margin:14px 0 6px;">EXPORT STORYBOARD SHEET</p>',
                        unsafe_allow_html=True,
                    )
                    _sheet_cols = st.columns([2, 2, 1, 1])
                    with _sheet_cols[0]:
                        _sheet_fmt = st.radio(
                            "Sheet format",
                            ["PNG", "PDF"],
                            horizontal=True,
                            key=f"{page_prefix}_sheet_fmt{key_suffix}",
                            label_visibility="collapsed",
                        )
                    with _sheet_cols[1]:
                        _sheet_quality = st.radio(
                            "Export quality",
                            list(STORYBOARD_SHEET_QUALITY_OPTIONS),
                            horizontal=True,
                            format_func=lambda q: f"{q}p",
                            key=f"{page_prefix}_sheet_quality{key_suffix}",
                            label_visibility="collapsed",
                        )
                    _paths_key = tuple(
                        (it.get("image_path") or it.get("url") or "").strip() for it in items
                    )
                    _caps_key = tuple((it.get("caption") or "")[:80] for it in items)
                    _sheet_bytes = _build_storyboard_sheet_bytes(
                        _paths_key,
                        _caps_key,
                        _sheet_fmt.lower(),
                        current_name,
                        int(_sheet_quality),
                    )
                    _frame_w = int(round(int(_sheet_quality) * 16 / 9))
                    _fpp = 4 if int(_sheet_quality) >= 1080 else (6 if int(_sheet_quality) >= 720 else 8)
                    with _sheet_cols[2]:
                        if _sheet_bytes:
                            st.download_button(
                                "📄 EXPORT SHEET",
                                data=_sheet_bytes,
                                file_name=f"{safe_name}_storyboard_{_sheet_quality}p.{_sheet_fmt.lower()}",
                                mime="application/pdf" if _sheet_fmt == "PDF" else "image/png",
                                key=f"{page_prefix}_export_sheet{key_suffix}",
                                use_container_width=True,
                            )
                        else:
                            st.caption("No exportable images on disk.")
                    with _sheet_cols[3]:
                        st.caption(
                            f"{len(items)} frame(s) · {_frame_w}×{_sheet_quality}px per image · "
                            f"{'multi-page' if len(items) > _fpp else 'single sheet'}"
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
                                 disabled=(sb_n_sel == 0), width="stretch"):
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
                                  disabled=True, width="stretch")

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
                                _ed_hist = f"sbv{key_suffix}"
                                st.session_state[f"{_ed_hist}_undo_stack"] = []
                                st.session_state[f"{_ed_hist}_redo_stack"] = []
                                st.session_state[f"{_ed_hist}_active_idx"] = 0
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

            _ed_prefix = f"sbv{key_suffix}"
            _process_editing_actions("ed_active_videos", _ed_prefix)
            _drain_editing_bridges(_ed_prefix, "ed_active_videos")
            _cut_msg = st.session_state.pop("_ed_cut_toast", None)
            if _cut_msg:
                st.toast(_cut_msg)

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
                                width="stretch",
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
                                width="stretch",
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
                        width="stretch",
                        type="secondary",
                    )
                with _exp_c2:
                    if not is_storyboard:
                        _export_key = f"{page_prefix}_export_video{key_suffix}"
                        if st.button(
                            "📥 EXPORT VIDEO",
                            key=_export_key,
                            width="stretch",
                            type="secondary",
                            help="Esporta le clip in timeline. Se hai appena modificato la timeline, usa EXPORT TIMELINE nel player.",
                        ):
                            _cache = st.session_state.get(f"sbv{key_suffix}_timeline_cache")
                            if _cache:
                                _rebuild_editing_items_from_timeline(_cache, items_key)
                            with st.spinner("Exporting video with ffmpeg..."):
                                _run_editing_export(items_key, name_key)
                            st.rerun()

                        _exp_result = st.session_state.get("_ed_last_export_path")
                        _exp_err = st.session_state.get("_ed_last_export_err")
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
                        elif _exp_err:
                            st.error(_exp_err)

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
                                 disabled=(ed_n_sel == 0), width="stretch"):
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
