import os
import json
import re
import base64 as _b64

import streamlit as st
import streamlit.components.v1 as components

from arkitect.storyboard_io import (
    _autosave_storyboard_snapshot,
    _normalize_editing_video_item,
    _get_thumbnail_src_resized,
)
from arkitect.ui_helpers import _render_project_name_inline_right
from arkitect.storage import (
    get_active_project_id,
    add_to_assets,
    load_all_snapshots,
    upsert_snapshot_entry,
)


def _render_gallery_sidebar():
    """Sidebar pagina Gallery: layout [4,1] come Projects / Storyboard."""
    _media_tab = st.session_state.get("gal_media_tab", "Images")
    _active_proj = get_active_project_id()

    if _media_tab == "Images":
        _all_imgs = list(st.session_state.get("gallery_images") or [])
        if _active_proj:
            _all_imgs = [img for img in _all_imgs if img.get("project_id") == _active_proj]
        else:
            _all_imgs = []
        n_sel = len(st.session_state.gallery_selected_imgs)

        st.markdown(
            f'<p style="color:#FFEB3B;font-size:0.85rem;font-weight:700;'
            f'font-family:Open Sans,sans-serif;margin:0 0 12px;'
            f'-webkit-text-fill-color:#FFEB3B;">{n_sel} selected</p>',
            unsafe_allow_html=True,
        )

        if st.button("STORYBOARD", key="gal_sb_add_imgs_to_sb", use_container_width=True):
            if n_sel == 0:
                st.toast("Seleziona almeno un'immagine nella griglia.")
            else:
                if st.session_state.sb_mode not in ("new", "loaded"):
                    st.session_state.sb_mode = "new"
                    st.session_state.sb_active_name = ""
                    st.session_state.sb_active_images = []
                existing_paths = {
                    item.get("image_path")
                    for item in st.session_state.sb_active_images
                    if item.get("image_path")
                }
                added = 0
                for idx in sorted(st.session_state.gallery_selected_imgs):
                    if idx < len(_all_imgs):
                        item = _all_imgs[idx]
                        path = item.get("image_path", "")
                        if not path or path not in existing_paths:
                            st.session_state.sb_active_images.append(dict(item))
                            if path:
                                existing_paths.add(path)
                            added += 1
                _autosave_storyboard_snapshot()
                st.session_state.gallery_selected_imgs = set()
                st.toast(f"Added {added} images to storyboard")
                st.rerun()

        st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)

        if st.button("ASSETS", key="gal_sb_save_imgs_to_assets", use_container_width=True):
            if n_sel == 0:
                st.toast("Seleziona almeno un'immagine nella griglia.")
            else:
                saved = 0
                for idx in sorted(st.session_state.gallery_selected_imgs):
                    if idx < len(_all_imgs):
                        item = _all_imgs[idx]
                        src_path = item.get("image_path", "")
                        if src_path and os.path.exists(src_path):
                            result = add_to_assets(source_path=src_path)
                            if result:
                                saved += 1
                st.session_state.gallery_selected_imgs = set()
                if saved > 0:
                    st.toast(f"Saved {saved} image(s) to Assets")
                st.rerun()

    else:
        _all_vids = list(st.session_state.get("gallery_videos") or [])
        if _active_proj:
            _all_vids = [v for v in _all_vids if v.get("project_id") == _active_proj]
        else:
            _all_vids = []
        vn_sel = len(st.session_state.gallery_selected_vids)

        st.markdown(
            f'<p style="color:#FFEB3B;font-size:0.85rem;font-weight:700;'
            f'font-family:Open Sans,sans-serif;margin:0 0 12px;'
            f'-webkit-text-fill-color:#FFEB3B;">{vn_sel} selected</p>',
            unsafe_allow_html=True,
        )

        if st.button("EDITING", key="gal_sb_add_vids_to_ed", use_container_width=True):
            if vn_sel == 0:
                st.toast("Select at least one video.")
            else:
                if st.session_state.ed_mode not in ("new", "loaded"):
                    st.session_state.ed_mode = "new"
                    st.session_state.ed_active_name = ""
                    st.session_state.ed_active_videos = []
                existing_vpaths = {
                    item.get("video_path")
                    for item in st.session_state.ed_active_videos
                    if item.get("video_path")
                }
                for idx in sorted(st.session_state.gallery_selected_vids):
                    if idx < len(_all_vids):
                        vitem = _all_vids[idx]
                        vpath = vitem.get("video_path", "")
                        if not vpath or vpath not in existing_vpaths:
                            st.session_state.ed_active_videos.append(
                                _normalize_editing_video_item(dict(vitem))
                            )
                            if vpath:
                                existing_vpaths.add(vpath)
                if st.session_state.ed_active_name:
                    upsert_snapshot_entry(
                        "editing",
                        st.session_state.ed_active_name,
                        st.session_state.ed_active_videos,
                    )
                st.session_state.gallery_selected_vids = set()
                st.toast(f"Added {vn_sel} videos to editing!")
                st.rerun()

        st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)

        if st.button("ASSETS", key="gal_sb_save_vids_to_assets", use_container_width=True):
            if vn_sel == 0:
                st.toast("Select at least one video.")
            else:
                saved = 0
                for idx in sorted(st.session_state.gallery_selected_vids):
                    if idx < len(_all_vids):
                        item = _all_vids[idx]
                        src_path = item.get("video_path", "")
                        if src_path and os.path.exists(src_path):
                            result = add_to_assets(source_path=src_path)
                            if result:
                                saved += 1
                st.session_state.gallery_selected_vids = set()
                if saved > 0:
                    st.toast(f"Saved {saved} video(s) to Assets")
                st.rerun()

    st.markdown(
        '<hr style="border:none;border-top:1px solid #2a2a28;margin:16px 0;">',
        unsafe_allow_html=True,
    )
    if st.button("CLEAR", key="gal_sidebar_clear_sel", use_container_width=True):
        st.session_state.gallery_selected_imgs = set()
        st.session_state.gallery_selected_vids = set()
        st.toast("Selection cleared.")
        st.rerun()

    st.markdown(
        '<hr style="border:none;border-top:1px solid #2a2a28;margin:16px 0;">',
        unsafe_allow_html=True,
    )
    _media_tab_nav = st.session_state.get("gal_media_tab", "Images")
    if _media_tab_nav == "Images":
        _all_imgs_nav = list(st.session_state.get("gallery_images") or [])
        if _active_proj:
            _all_imgs_nav = [img for img in _all_imgs_nav if img.get("project_id") == _active_proj]
        else:
            _all_imgs_nav = []
        _total_nav = len(_all_imgs_nav)
        _per_page_nav = 20
        _pages_nav = max(1, (_total_nav + _per_page_nav - 1) // _per_page_nav)
        _cur_nav = st.session_state.get("gallery_img_page", 0)
        st.markdown(
            f'<p style="color:#9E9E8A;font-size:0.72rem;text-align:center;margin:0 0 6px;">'
            f'Page {_cur_nav + 1} / {_pages_nav}</p>',
            unsafe_allow_html=True,
        )
        if st.button("← PREV", key="gal_sb_img_prev", use_container_width=True, disabled=(_cur_nav == 0)):
            st.session_state.gallery_img_page -= 1
            st.rerun()
        if st.button("NEXT →", key="gal_sb_img_next", use_container_width=True, disabled=(_cur_nav >= _pages_nav - 1)):
            st.session_state.gallery_img_page += 1
            st.rerun()
    else:
        _all_vids_nav = list(st.session_state.get("gallery_videos") or [])
        if _active_proj:
            _all_vids_nav = [v for v in _all_vids_nav if v.get("project_id") == _active_proj]
        else:
            _all_vids_nav = []
        _total_nav = len(_all_vids_nav)
        _per_page_nav = 9
        _pages_nav = max(1, (_total_nav + _per_page_nav - 1) // _per_page_nav)
        _cur_nav = st.session_state.get("gallery_vid_page", 0)
        st.markdown(
            f'<p style="color:#9E9E8A;font-size:0.72rem;text-align:center;margin:0 0 6px;">'
            f'Page {_cur_nav + 1} / {_pages_nav}</p>',
            unsafe_allow_html=True,
        )
        if st.button("← PREV", key="gal_sb_vid_prev", use_container_width=True, disabled=(_cur_nav == 0)):
            st.session_state.gallery_vid_page -= 1
            st.rerun()
        if st.button("NEXT →", key="gal_sb_vid_next", use_container_width=True, disabled=(_cur_nav >= _pages_nav - 1)):
            st.session_state.gallery_vid_page += 1
            st.rerun()


def render_gallery_page():
    """Render the Gallery page (generated videos and images)."""
    GALLERY_PER_PAGE = 20
    GALLERY_COLS = 5
    def _gallery_item_created_at(item):
        return item.get("created_at") or "1970-01-01T00:00:00"
    st.markdown('<div class="gallery-info-wrap">', unsafe_allow_html=True)

    if "gal_media_tab" not in st.session_state:
        st.session_state.gal_media_tab = "Images"
    if "gal_nav" not in st.session_state:
        st.session_state.gal_nav = "Gallery"
    elif st.session_state.gal_nav in ("Images", "Videos"):
        st.session_state.gal_media_tab = st.session_state.gal_nav
        st.session_state.gal_nav = "Gallery"
    elif st.session_state.gal_nav not in ("Console", "Projects", "Gallery", "Assets", "References", "Storyboard", "Editing"):
        st.session_state.gal_nav = "Gallery"

    def _on_gal_nav_change():
        val = st.session_state.gal_nav
        if val == "Console":
            st.session_state.gal_nav = "Gallery"
            st.session_state["_console_was_away"] = True
            st.session_state.active_page = "console"
        elif val == "Projects":
            st.session_state.gal_nav = "Gallery"
            st.session_state.active_page = "projects"
        elif val == "Storyboard":
            st.session_state.gal_nav = "Gallery"
            st.session_state.active_page = "storyboard"
        elif val == "Editing":
            st.session_state.gal_nav = "Gallery"
            st.session_state.active_page = "editing"
        elif val == "Assets":
            st.session_state.gal_nav = "Gallery"
            st.session_state.active_page = "assets"
        elif val == "References":
            st.session_state.gal_nav = "Gallery"
            st.session_state.active_page = "references"

    # Ordine nav: "Gallery" per prima così un reset sporadico del widget (click rapidi
    # tra controlli affiancati) non seleziona "Console" e non manda alla main page.
    _GAL_MAIN_NAV = ["Gallery", "Console", "Projects", "Assets", "References", "Storyboard", "Editing"]
    _gal_row_l, _gal_row_r = st.columns([4, 1])
    with _gal_row_l:
        if st.session_state.gal_nav == "Gallery":
            _gal_in_nav, _gal_in_media = st.columns([4, 1])
        else:
            _gal_in_nav, _gal_in_media = st.container(), None

        with _gal_in_nav:
            st.radio(
                "gal_nav_label",
                _GAL_MAIN_NAV,
                horizontal=True,
                key="gal_nav",
                on_change=_on_gal_nav_change,
                label_visibility="collapsed",
            )

        if _gal_in_media is not None:
            with _gal_in_media:
                def _on_gal_media_tab_change():
                    st.session_state.gal_media_tab = st.session_state._gal_media_nav
                if "gal_media_tab" not in st.session_state:
                    st.session_state.gal_media_tab = "Images"
                st.radio(
                    "gal_media_nav_label",
                    ["Images", "Videos"],
                    index=0 if st.session_state.get("gal_media_tab", "Images") == "Images" else 1,
                    horizontal=True,
                    key="_gal_media_nav",
                    on_change=_on_gal_media_tab_change,
                    label_visibility="collapsed",
                )
    with _gal_row_r:
        _render_project_name_inline_right()

    gallery_videos = list(st.session_state.get("gallery_videos") or [])
    gallery_images = list(st.session_state.get("gallery_images") or [])
    # Filter by active project — only show media for current project
    _active_pid = st.session_state.get("active_project_id")
    if _active_pid:
        gallery_videos = [
            v for v in gallery_videos
            if v.get("project_id") == _active_pid
        ]
        gallery_images = [
            i for i in gallery_images
            if i.get("project_id") == _active_pid
        ]
    else:
        gallery_videos = []
        gallery_images = []

    _gcm, _gcs = st.columns([4, 1], gap="large")
    with _gcs:
        _render_gallery_sidebar()
    with _gcm:
        if st.session_state.gal_nav == "Gallery":
            if not gallery_videos and not gallery_images:
                st.info("No media in this project yet. Generate videos or images in the Console.")
                st.stop()

        if st.session_state.gal_nav == "Gallery" and st.session_state.get("gal_media_tab", "Images") == "Images":
            full_gallery_images = list(st.session_state.gallery_images)
            active_proj = get_active_project_id()
            images = gallery_images
            if not images:
                st.info("No images in this project yet.")
            else:
                total_imgs = len(images)
                img_total_pages = max(1, (total_imgs + GALLERY_PER_PAGE - 1) // GALLERY_PER_PAGE)
                # Clamp current page
                if st.session_state.gallery_img_page >= img_total_pages:
                    st.session_state.gallery_img_page = max(0, img_total_pages - 1)
                img_page = st.session_state.gallery_img_page
                img_start = img_page * GALLERY_PER_PAGE
                img_end   = min(img_start + GALLERY_PER_PAGE, total_imgs)
                page_images = images[img_start:img_end]  # slice for current page

                st.markdown(
                    f'<p style="color:#9E9E8A;font-size:0.72rem;text-align:right;margin:2px 0 6px;">'
                    f'Page {img_page+1} / {img_total_pages} · {total_imgs} images</p>',
                    unsafe_allow_html=True
                )

                img_action_key = "gallery_img_action"
                img_action_val = st.session_state.get(img_action_key, "")
                if img_action_val:
                    st.session_state[img_action_key] = ""
                    if img_action_val.startswith("reorder:"):
                        try:
                            new_order = [x for x in img_action_val.replace("reorder:", "").split(",") if x.strip().isdigit()]
                            if len(new_order) == len(page_images):
                                new_filtered = images[:img_start] + [images[int(x)] for x in new_order] + images[img_end:]
                                if active_proj:
                                    it_nf = iter(new_filtered)
                                    st.session_state.gallery_images = [
                                        next(it_nf) if item.get("project_id") == active_proj else item
                                        for item in full_gallery_images
                                    ]
                                else:
                                    st.session_state.gallery_images = new_filtered
                                st.rerun()
                        except (ValueError, IndexError, StopIteration):
                            pass

                # ── Click-to-select bridge (iframe → Streamlit via on_change; unique |ts forces React to commit) ──
                _gsel_key = "gal_sel_act"

                def _on_gal_sel_change():
                    raw = (st.session_state.get(_gsel_key) or "").strip()
                    if not raw:
                        return
                    st.session_state[_gsel_key] = ""
                    token = raw.split("|")[0].strip()
                    if token.startswith("t:"):
                        token = token[2:]
                    try:
                        _gidx = int(token)
                    except (ValueError, TypeError):
                        return
                    if _gidx in st.session_state.gallery_selected_imgs:
                        st.session_state.gallery_selected_imgs.discard(_gidx)
                    else:
                        st.session_state.gallery_selected_imgs.add(_gidx)

                st.text_input(
                    "gal_sel_bridge_inp",
                    key=_gsel_key,
                    on_change=_on_gal_sel_change,
                    label_visibility="collapsed",
                )

                cards_html = ""
                thumb_h = 120
                for i, item in enumerate(page_images):
                    abs_i = img_start + i
                    src = _get_thumbnail_src_resized(item, max_px=320)
                    caption = (item.get("caption", "Image")[:40]).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    safe_caption_attr = (caption or "").replace('"', "&quot;")
                    safe_src = (src or "").replace('"', "&quot;")

                    # Compute full-res src for lightbox separately from thumbnail
                    full_src = (item.get("image_path") or item.get("url") or item.get("src") or "")
                    lb_src = ""
                    if full_src and not full_src.startswith("http") and os.path.exists(full_src):
                        _ext = os.path.splitext(full_src)[1].lower()
                        _mime = {".png": "image/png", ".jpg": "image/jpeg",
                                 ".jpeg": "image/jpeg", ".webp": "image/webp",
                                 ".gif": "image/gif"}.get(_ext, "image/jpeg")
                        try:
                            from PIL import Image as _PILImage
                            import io as _io
                            with _PILImage.open(full_src) as _im:
                                _im.thumbnail((1280, 1280), _PILImage.LANCZOS)
                                _buf = _io.BytesIO()
                                _im.convert("RGB").save(_buf, format="JPEG", quality=88, optimize=True)
                                lb_src = f"data:{_mime};base64,{_b64.b64encode(_buf.getvalue()).decode()}"
                        except Exception:
                            lb_src = full_src  # fallback: use raw path
                    elif full_src.startswith("http"):
                        lb_src = full_src
                    safe_lb_src = (lb_src or "").replace('"', "&quot;")

                    _is_sel = abs_i in st.session_state.gallery_selected_imgs
                    _sel_bdr = "border-color:#FFEB3B !important;box-shadow:0 0 0 1px #FFEB3B;" if _is_sel else ""
                    _sel_chk = '<div style="position:absolute;bottom:18px;right:4px;background:#FFEB3B;color:#000;width:18px;height:18px;border-radius:50%;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;z-index:4;">&#10003;</div>' if _is_sel else ""

                    cards_html += f'''
                    <div class="gal-card" data-idx="{abs_i}"
                         data-lb-type="image"
                         data-lb-src="{safe_lb_src}"
                         data-lb-caption="{safe_caption_attr}"
                         style="{_sel_bdr}"
                         onclick="galSel({abs_i})">
                        <div class="gal-badge">{i + 1}</div>
                        {_sel_chk}
                        <div class="gal-expand" onclick="event.stopPropagation();lbOpen({i})" title="Expand">
                            <svg width="12" height="12" viewBox="0 0 12 12" fill="none"
                                 xmlns="http://www.w3.org/2000/svg">
                              <path d="M1 4.5V1H4.5M7.5 1H11V4.5M11 7.5V11H7.5M4.5 11H1V7.5"
                                    stroke="currentColor" stroke-width="1.6"
                                    stroke-linecap="round" stroke-linejoin="round"/>
                            </svg>
                        </div>
                        <img src="{safe_src}" style="width:100%;height:{thumb_h}px;object-fit:cover;border-radius:4px;display:block;" draggable="false"/>
                        <div class="gal-caption">{caption}</div>
                    </div>'''

                html_code = f'''
                <script src="https://cdnjs.cloudflare.com/ajax/libs/Sortable/1.15.3/Sortable.min.js"></script>
                <style>
                    * {{ margin:0; padding:0; box-sizing:border-box; }}
                    body {{ background: transparent; font-family:'Open Sans', sans-serif; }}
                    .gal-grid {{ display:grid; grid-template-columns:repeat(5,1fr); gap:8px; padding:4px; }}
                    .gal-card {{ position:relative; background:#1a1a18; border-radius:6px; overflow:hidden; cursor:grab; border:2px solid transparent; transition:border-color .2s,box-shadow .2s; }}
                    .gal-card:hover {{ border-color:rgba(255,235,59,.35); box-shadow:0 4px 16px rgba(0,0,0,.35); }}
                    .gal-card.selected {{ border-color:#FFEB3B !important; box-shadow:0 0 0 1px #FFEB3B; }}
                    .gal-card.sortable-ghost {{ opacity:.35; border-color:#FFEB3B; }}
                    .gal-badge {{ position:absolute; top:4px; left:4px; background:rgba(0,0,0,.75); color:#fff; font-size:9px; font-weight:700; padding:1px 6px; border-radius:3px; z-index:2; pointer-events:none; }}
                    .gal-expand {{ position:absolute; top:4px; right:4px; color:#999; cursor:pointer; z-index:3; width:20px; height:20px; display:flex; align-items:center; justify-content:center; border-radius:3px; background:rgba(0,0,0,0.55); transition:color .15s, background .15s; }}
                    .gal-expand:hover {{ color:#FFEB3B; background:rgba(0,0,0,0.85); }}
                    .gal-caption {{ color:#999; font-size:9px; padding:3px 6px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
                </style>
                <div class="gal-grid" id="galleryImgGrid">{cards_html}</div>
                <script>
                    function galSel(idx) {{
                        var inp = window.parent.document.querySelector(
                            'input[aria-label="gal_sel_bridge_inp"]'
                        );
                        if (!inp) return;
                        var ns = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value'
                        ).set;
                        var payload = String(idx) + '|' + Date.now();
                        ns.call(inp, payload);
                        inp.dispatchEvent(new Event('input', {{bubbles:true}}));
                        inp.dispatchEvent(new Event('change', {{bubbles:true}}));
                        try {{
                            inp.dispatchEvent(new InputEvent('input', {{
                                bubbles: true, inputType: 'insertFromPaste', data: payload
                            }}));
                        }} catch (e) {{}}
                        try {{ inp.focus({{ preventScroll: true }}); }} catch (e2) {{}}
                        try {{ inp.blur(); }} catch (e3) {{}}
                    }}
                    const grid = document.getElementById('galleryImgGrid');
                    Sortable.create(grid, {{
                        animation: 200,
                        delay: 200,
                        delayOnTouchOnly: false,
                        ghostClass: 'sortable-ghost',
                        onEnd: function() {{
                            const cards = grid.querySelectorAll('.gal-card');
                            const newOrder = Array.from(cards).map(c => c.dataset.idx);
                            const msg = 'reorder:' + newOrder.join(',');
                            const input = window.parent.document.querySelector('input[aria-label="gallery_action_input_img"]');
                            if (input) {{
                                const ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                                ns.call(input, msg);
                                input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            }}
                        }}
                    }});

                    const LB_ITEMS = Array.from(
                        document.querySelectorAll('.gal-card')
                    ).map(function(card) {{
                        return {{
                            type:    card.dataset.lbType    || 'image',
                            src:     card.dataset.lbSrc     || '',
                            caption: card.dataset.lbCaption || ''
                        }};
                    }});

                    var _lbCurrent = 0;

                    // Compute safe dimensions once — no CSS min(), no calc()
                    // Use 92% of viewport, capped at 1280 x 720
                    function _lbDims() {{
                        var vw  = window.parent.innerWidth  || 1280;
                        var vh  = window.parent.innerHeight || 800;
                        var w   = Math.min(Math.round(vw * 0.88), 1280);
                        var h   = Math.min(Math.round(vh * 0.78), 720);
                        return {{ w: w, h: h }};
                    }}

                    function lbOpen(idx) {{
                        if (idx < 0 || idx >= LB_ITEMS.length) return;
                        _lbCurrent = idx;
                        var item = LB_ITEMS[idx];
                        var pd   = window.parent.document;
                        var dims = _lbDims();

                        // Remove any previous overlay
                        var old = pd.getElementById('_stlb_overlay');
                        if (old) old.parentNode.removeChild(old);

                        // One-time keyboard listener on parent
                        if (!window.parent._stlbKeyInstalled) {{
                            window.parent._stlbKeyInstalled = true;
                            pd.addEventListener('keydown', function(e) {{
                                if (!pd.getElementById('_stlb_overlay')) return;
                                if (e.key === 'Escape')      lbClose();
                                if (e.key === 'ArrowLeft')   lbStep(-1);
                                if (e.key === 'ArrowRight')  lbStep(1);
                            }});
                        }}

                        // ── Overlay ──────────────────────────────────────────────
                        var ov = pd.createElement('div');
                        ov.id = '_stlb_overlay';
                        ov.setAttribute('style', [
                            'position:fixed',
                            'top:0', 'left:0',
                            'width:100%', 'height:100%',
                            'background:rgba(0,0,0,0.95)',
                            'z-index:2147483647',
                            'display:flex',
                            'flex-direction:column',
                            'align-items:center',
                            'justify-content:center',
                            'box-sizing:border-box',
                            'padding:60px 90px 40px 90px'
                        ].join(';'));
                        ov.addEventListener('click', function(e) {{
                            if (e.target === ov) lbClose();
                        }});

                        // ── Close ─────────────────────────────────────────────────
                        var cls = pd.createElement('button');
                        cls.innerHTML = '&#x2715;';
                        cls.setAttribute('style', [
                            'position:fixed', 'top:16px', 'right:24px',
                            'background:none', 'border:none',
                            'color:#c0bcb5', 'font-size:2rem',
                            'line-height:1', 'cursor:pointer',
                            'z-index:2147483648', 'padding:4px'
                        ].join(';'));
                        cls.onmouseover = function() {{ cls.style.color = '#FFEB3B'; }};
                        cls.onmouseout  = function() {{ cls.style.color = '#c0bcb5'; }};
                        cls.onclick     = lbClose;
                        ov.appendChild(cls);

                        // ── Prev arrow ────────────────────────────────────────────
                        var prev = pd.createElement('button');
                        prev.innerHTML = '&#8592;';
                        prev.id = '_stlb_prev';
                        prev.setAttribute('style', _arrowCss('left:14px'));
                        prev.style.display = (idx === 0) ? 'none' : 'flex';
                        prev.onclick = function(e) {{ e.stopPropagation(); lbStep(-1); }};
                        ov.appendChild(prev);

                        // ── Next arrow ────────────────────────────────────────────
                        var nxt = pd.createElement('button');
                        nxt.innerHTML = '&#8594;';
                        nxt.id = '_stlb_next';
                        nxt.setAttribute('style', _arrowCss('right:14px'));
                        nxt.style.display = (idx >= LB_ITEMS.length - 1) ? 'none' : 'flex';
                        nxt.onclick = function(e) {{ e.stopPropagation(); lbStep(1); }};
                        ov.appendChild(nxt);

                        // ── Media ─────────────────────────────────────────────────
                        var mediaEl;

                        if (!item.src) {{
                            // No source available
                            mediaEl = pd.createElement('div');
                            mediaEl.setAttribute('style', [
                                'width:' + dims.w + 'px',
                                'height:' + Math.round(dims.w * 9/16) + 'px',
                                'background:#1a1a18',
                                'border-radius:8px',
                                'display:flex', 'align-items:center', 'justify-content:center',
                                'color:#9E9E8A', 'font-size:1rem',
                                'font-family:Open Sans,sans-serif'
                            ].join(';'));
                            mediaEl.textContent = 'Source not available for preview';

                        }} else if (item.type === 'video') {{
                            mediaEl = pd.createElement('video');
                            mediaEl.id       = '_stlb_video';
                            mediaEl.controls = true;
                            mediaEl.autoplay = true;
                            mediaEl.playsInline = true;
                            mediaEl.setAttribute('style', [
                                'width:'      + dims.w + 'px',
                                'height:'     + dims.h + 'px',
                                'max-width:100%',
                                'border-radius:8px',
                                'background:#000',
                                'box-shadow:0 8px 48px rgba(0,0,0,0.9)',
                                'display:block'
                            ].join(';'));
                            // Set src AFTER attaching style to avoid 0-height flash
                            mediaEl.src = item.src;
                            mediaEl.load();
                            mediaEl.onerror = function() {{
                                mediaEl.style.display = 'none';
                                var err = pd.createElement('div');
                                err.setAttribute('style', [
                                    'width:'  + dims.w + 'px',
                                    'height:' + dims.h + 'px',
                                    'background:#1a1a18',
                                    'border-radius:8px',
                                    'display:flex', 'align-items:center', 'justify-content:center',
                                    'color:#9E9E8A', 'font-size:0.9rem',
                                    'font-family:Open Sans,sans-serif',
                                    'flex-direction:column', 'gap:8px'
                                ].join(';'));
                                err.innerHTML = '<span style="font-size:2rem;">&#9654;</span>' +
                                                '<span>Video not playable in preview</span>';
                                mediaEl.parentNode && mediaEl.parentNode.insertBefore(err, mediaEl);
                            }};

                        }} else {{
                            // Image
                            mediaEl = pd.createElement('img');
                            mediaEl.setAttribute('style', [
                                'max-width:'  + dims.w + 'px',
                                'max-height:' + dims.h + 'px',
                                'width:auto', 'height:auto',
                                'object-fit:contain',
                                'border-radius:8px',
                                'box-shadow:0 8px 48px rgba(0,0,0,0.9)',
                                'display:block'
                            ].join(';'));
                            mediaEl.src = item.src;
                        }}

                        ov.appendChild(mediaEl);

                        // ── Caption ───────────────────────────────────────────────
                        var cap = pd.createElement('div');
                        cap.textContent = item.caption || '';
                        cap.setAttribute('style', [
                            'color:#9E9E8A', 'font-size:0.78rem',
                            'font-family:Open Sans,sans-serif',
                            'margin-top:14px', 'text-align:center',
                            'max-width:' + dims.w + 'px',
                            'white-space:nowrap', 'overflow:hidden', 'text-overflow:ellipsis'
                        ].join(';'));
                        ov.appendChild(cap);

                        pd.body.appendChild(ov);

                        // Try autoplay after a short delay (some browsers need it)
                        if (item.type === 'video' && item.src) {{
                            setTimeout(function() {{
                                var v = pd.getElementById('_stlb_video');
                                if (v) v.play().catch(function() {{}});
                            }}, 150);
                        }}
                    }}

                    function lbClose() {{
                        var pd  = window.parent.document;
                        var vid = pd.getElementById('_stlb_video');
                        if (vid) {{ vid.pause(); vid.src = ''; }}
                        var ov  = pd.getElementById('_stlb_overlay');
                        if (ov && ov.parentNode) ov.parentNode.removeChild(ov);
                    }}

                    function lbStep(dir) {{
                        var next = _lbCurrent + dir;
                        if (next >= 0 && next < LB_ITEMS.length) lbOpen(next);
                        var pd   = window.parent.document;
                        var prev = pd.getElementById('_stlb_prev');
                        var nxt  = pd.getElementById('_stlb_next');
                        if (prev) prev.style.display = (next === 0) ? 'none' : 'flex';
                        if (nxt)  nxt.style.display  = (next >= LB_ITEMS.length-1) ? 'none' : 'flex';
                    }}

                    function _arrowCss(side) {{
                        return [
                            'position:fixed', 'top:50%', 'transform:translateY(-50%)',
                            side,
                            'background:rgba(255,255,255,0.10)',
                            'border:1px solid rgba(255,255,255,0.20)',
                            'color:#f0ece4', 'font-size:2rem',
                            'cursor:pointer', 'padding:10px 16px',
                            'border-radius:6px', 'z-index:2147483648',
                            'line-height:1', 'align-items:center', 'justify-content:center'
                        ].join(';');
                    }}
                </script>'''
                st.text_input("gallery_action_input_img", key="gallery_img_action", label_visibility="collapsed")
                grid_height = ((len(page_images) + 4) // 5) * (thumb_h + 38) + 20
                components.html(html_code, height=grid_height, scrolling=False)
                st.caption(f"{len(images)} images")

        elif st.session_state.gal_nav == "Gallery" and st.session_state.get("gal_media_tab", "Images") == "Videos":
            full_gallery_videos = list(st.session_state.gallery_videos)
            active_proj = get_active_project_id()
            videos = gallery_videos

            if not videos:
                st.info("No videos in this project yet.")
            else:
                # ── Pagination ────────────────────────────────────────
                _VPP  = 9
                _vtot = len(videos)
                _vpages = max(1, (_vtot + _VPP - 1) // _VPP)
                if st.session_state.gallery_vid_page >= _vpages:
                    st.session_state.gallery_vid_page = max(
                        0, _vpages - 1)
                _vp     = st.session_state.gallery_vid_page
                _vs     = _vp * _VPP
                _ve     = min(_vs + _VPP, _vtot)
                _pvids  = videos[_vs:_ve]

                # ── Nav row ───────────────────────────────────────────
                st.markdown(
                    f'<p style="color:#9E9E8A;font-size:0.72rem;'
                    f'text-align:right;margin:2px 0 10px;">'
                    f'Page {_vp+1} / {_vpages}'
                    f' · {_vtot} videos</p>',
                    unsafe_allow_html=True
                )

                # ── Grid: 3 columns, direct video players ─────────────
                _COLS = 3
                for _ri in range(0, len(_pvids), _COLS):
                    _row  = _pvids[_ri:_ri + _COLS]
                    _gcols = st.columns(_COLS, gap="small")
                    for _ci in range(_COLS):
                        with _gcols[_ci]:
                            if _ci >= len(_row):
                                st.markdown(
                                    '<div style="aspect-ratio:16/9">'
                                    '</div>',
                                    unsafe_allow_html=True)
                                continue
                            _item   = _row[_ci]
                            _aidx   = _vs + _ri + _ci
                            _badge  = _aidx + 1
                            _cap    = _item.get("caption","")[:30]
                            _card_vsrc = _item.get("video_path") or _item.get("url") or ""
                            if _card_vsrc:
                                st.video(_card_vsrc)
                            else:
                                st.warning("Video source not available.")

                            # Caption + Select checkbox on same row
                            _vc_left, _vc_right = st.columns([4, 1], gap="small")
                            with _vc_left:
                                st.caption(f"{_cap} · #{_badge}")
                            with _vc_right:
                                _gv_is_sel = _aidx in st.session_state.gallery_selected_vids
                                _gv_box_key = f"sel_vid_gal_{_aidx}"

                                def _on_gal_vid_sel_change(_idx=_aidx):
                                    if st.session_state.get(f"sel_vid_gal_{_idx}", False):
                                        st.session_state.gallery_selected_vids.add(_idx)
                                    else:
                                        st.session_state.gallery_selected_vids.discard(_idx)

                                st.checkbox(
                                    "Select",
                                    value=_gv_is_sel,
                                    key=_gv_box_key,
                                    on_change=_on_gal_vid_sel_change,
                                    args=(_aidx,),
                                )

                st.markdown(
                    f'<p style="color:#7a7a6e;font-size:0.72rem;'
                    f'margin-top:6px;">{_vtot} videos</p>',
                    unsafe_allow_html=True
                )

    st.markdown('</div>', unsafe_allow_html=True)
