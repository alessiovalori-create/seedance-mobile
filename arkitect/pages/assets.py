import os
import html as _html_stdlib

import streamlit as st

from arkitect.storage import (
    load_asset_catalog,
    save_asset_catalog,
    add_to_assets,
    get_active_project_id,
    get_active_project_name,
    next_project_image_asset_name,
)
from arkitect.ui_helpers import _render_project_name_inline_right
from arkitect.console_state import _asset_picker_label




def render_assets_page():
    """Render the Assets page (uploaded image/video/audio catalog)."""
    _run_id = st.session_state.get("_streamlit_run_id", 0)
    if st.session_state.get(f"_rendered_assets_{_run_id}"):
        return
    st.session_state[f"_rendered_assets_{_run_id}"] = True

    # ── Navigation ──
    if "assets_nav" not in st.session_state:
        st.session_state.assets_nav = "Assets"
    elif st.session_state.assets_nav not in ("Console", "Projects", "Gallery", "Assets", "References", "Storyboard", "Editing"):
        st.session_state.assets_nav = "Assets"

    def _on_assets_nav_change():
        val = st.session_state.assets_nav
        if val == "Console":
            st.session_state.assets_nav = "Assets"
            st.session_state["_console_was_away"] = True
            st.session_state.active_page = "console"
        elif val == "Projects":
            st.session_state.assets_nav = "Assets"
            st.session_state.active_page = "projects"
        elif val == "Gallery":
            st.session_state.assets_nav = "Assets"
            st.session_state.active_page = "gallery"
        elif val == "References":
            st.session_state.assets_nav = "Assets"
            st.session_state.active_page = "references"
        elif val == "Storyboard":
            st.session_state.assets_nav = "Assets"
            st.session_state.active_page = "storyboard"
        elif val == "Editing":
            st.session_state.assets_nav = "Assets"
            st.session_state.active_page = "editing"

    _assets_nav_col, _assets_proj_col = st.columns([4, 1])
    with _assets_nav_col:
        st.radio(
            "assets_nav_label",
            ["Console", "Projects", "Gallery", "Assets", "References", "Storyboard", "Editing"],
            horizontal=True,
            key="assets_nav",
            on_change=_on_assets_nav_change,
            label_visibility="collapsed",
        )
    with _assets_proj_col:
        _render_project_name_inline_right()

    catalog = load_asset_catalog()
    active_proj = get_active_project_id()
    if active_proj:
        catalog = [a for a in catalog if a.get("project_id") == active_proj]

    # ── Filter (All / Images / …) a sinistra, browse file a destra ──
    filter_col1, filter_col2 = st.columns([3, 2])
    with filter_col1:
        asset_filter = st.radio(
            "Filter",
            ["All", "Images", "Videos", "Audio"],
            horizontal=True,
            key="assets_filter_radio",
            label_visibility="collapsed",
        )
    with filter_col2:
        uploaded_assets = st.file_uploader(
            "Upload from desktop",
            type=['png', 'jpg', 'jpeg', 'webp', 'gif', 'mp4', 'mov', 'webm', 'mp3', 'wav', 'ogg', 'm4a', 'flac', 'aac'],
            accept_multiple_files=True,
            key="assets_desktop_upload",
            help="Images, videos, and audio files",
            label_visibility="collapsed",
        )

    if uploaded_assets:
        ids_before = {a["id"] for a in load_asset_catalog()}
        saved_count = 0
        active_proj = get_active_project_id()
        proj_name = get_active_project_name()
        for uf in uploaded_assets:
            mime = getattr(uf, "type", None) or ""
            asset_name = None
            if mime.startswith("image"):
                ext = os.path.splitext(uf.name)[1].lower() or ".jpg"
                asset_name = next_project_image_asset_name(
                    project_id=active_proj,
                    project_name=proj_name,
                    ext=ext,
                )
            result = add_to_assets(uploaded_file=uf, asset_name=asset_name)
            if result and result.get("id") not in ids_before:
                ids_before.add(result["id"])
                saved_count += 1
        if saved_count > 0:
            st.toast(f"Added {saved_count} file(s) to Assets")
            st.rerun()

    # Apply filter
    if asset_filter == "Images":
        filtered = [a for a in catalog if a["type"] == "image"]
    elif asset_filter == "Videos":
        filtered = [a for a in catalog if a["type"] == "video"]
    elif asset_filter == "Audio":
        filtered = [a for a in catalog if a["type"] == "audio"]
    else:
        filtered = catalog

    # Sort newest first
    filtered.sort(key=lambda x: x.get("uploaded_at", ""), reverse=True)

    st.markdown(
        f'<p style="color:#9E9E8A; font-size:0.72rem; text-align:right; margin:4px 0 8px 0;">'
        f'{len(filtered)} files</p>',
        unsafe_allow_html=True,
    )

    _img_assets_all = [a for a in catalog if a.get("type") == "image"]
    if _img_assets_all:
        with st.expander("Send to Console (Seedance 2.0 references)", expanded=False):
            _pick_opts = {_asset_picker_label(a): a for a in _img_assets_all}
            _picked_labels = st.multiselect(
                "Select images (order = @Image 1, @Image 2, …)",
                options=list(_pick_opts.keys()),
                default=[
                    x for x in st.session_state.get("assets_console_pick", [])
                    if x in _pick_opts
                ],
                key="assets_console_pick",
                placeholder="Choose images from Assets…",
            )
            if _picked_labels:
                _tag_preview = " · ".join(
                    f"@Image {i + 1} → {_pick_opts[_picked_labels[i]]['name'][:28]}"
                    for i in range(len(_picked_labels))
                )
                st.caption(_tag_preview)
            _send_ep = st.radio(
                "Console workflow",
                ["First Frame", "First and Last Frames", "All-in-One Reference"],
                horizontal=True,
                key="assets_console_entry",
            )
            _send_usage = None
            if _send_ep == "All-in-One Reference":
                _send_usage = st.selectbox(
                    "Image usage (All-in-One)",
                    ["auto", "first_frame", "reference_only", "composite"],
                    format_func=lambda x: {
                        "auto": "Auto",
                        "first_frame": "First frame",
                        "reference_only": "Reference only",
                        "composite": "Composite",
                    }[x],
                    key="assets_console_image_usage",
                )
            _send_disabled = not _picked_labels
            if _send_ep == "First Frame":
                if len(_picked_labels) != 1:
                    st.caption("First Frame: select exactly 1 image.")
                    _send_disabled = True
            elif _send_ep == "First and Last Frames":
                if len(_picked_labels) != 2:
                    st.caption("First + Last: select exactly 2 images (@Image 1 = first, @Image 2 = last).")
                    _send_disabled = True
            elif len(_picked_labels) > 9:
                st.warning("All-in-One allows at most 9 images; only the first 9 will be sent.")
            if st.button(
                "Send to Console",
                type="primary",
                use_container_width=True,
                disabled=_send_disabled,
                key="assets_send_to_console_btn",
            ):
                _ordered = [_pick_opts[lab] for lab in _picked_labels]
                if _send_ep == "First Frame":
                    _ordered = _ordered[:1]
                elif _send_ep == "First and Last Frames":
                    _ordered = _ordered[:2]
                else:
                    _ordered = _ordered[:9]
                st.session_state["_assets_to_console_pending"] = {
                    "entry_point": _send_ep,
                    "asset_ids": [a["id"] for a in _ordered],
                    "catalog": _img_assets_all,
                    "image_usage": _send_usage,
                }
                # Keep _console_param_snapshot from last Console visit — do NOT
                # re-save here (Assets page has no Console widgets in session_state).
                st.session_state["_console_was_away"] = True
                st.session_state.active_page = "console"
                st.toast(
                    f"Opening Console with {', '.join(f'@Image {i + 1}' for i in range(len(_ordered)))}"
                )
                st.rerun()

    if not filtered:
        st.info("No assets yet. Upload files from desktop, or save from Gallery / Storyboard / Editing.")
    else:
        # ── Pagination ──
        ASSETS_PER_PAGE = 12
        total_assets = len(filtered)
        total_pages = max(1, (total_assets + ASSETS_PER_PAGE - 1) // ASSETS_PER_PAGE)
        if st.session_state.assets_page >= total_pages:
            st.session_state.assets_page = max(0, total_pages - 1)
        current_page = st.session_state.assets_page
        page_start = current_page * ASSETS_PER_PAGE
        page_end = min(page_start + ASSETS_PER_PAGE, total_assets)
        page_items = filtered[page_start:page_end]

        if total_pages > 1:
            pn1, pn2, pn3 = st.columns([1, 2, 1])
            with pn1:
                if st.button("← PREV", key="assets_prev", use_container_width=True,
                             disabled=(current_page == 0)):
                    st.session_state.assets_page -= 1
                    st.rerun()
            with pn2:
                st.markdown(
                    f'<p style="color:#9E9E8A; font-size:0.72rem; text-align:center; margin-top:8px;">'
                    f'Page {current_page + 1} / {total_pages}</p>',
                    unsafe_allow_html=True,
                )
            with pn3:
                if st.button("NEXT →", key="assets_next", use_container_width=True,
                             disabled=(current_page >= total_pages - 1)):
                    st.session_state.assets_page += 1
                    st.rerun()

        def _do_asset_delete(_a, _fp, _fn):
            try:
                if os.path.exists(_fp):
                    os.remove(_fp)
            except Exception:
                pass
            cat = load_asset_catalog()
            cat = [a for a in cat if a["id"] != _a["id"]]
            save_asset_catalog(cat)
            st.toast(f"Removed: {_fn}")
            st.rerun()

        # Mapping: file name (as in catalog / upload) → @tag for Console references
        _live_tags = st.session_state.get("_console_ref_tag_map")
        if isinstance(_live_tags, dict) and _live_tags:
            _console_tag_map = dict(_live_tags)
        else:
            _console_tag_map = {}
            _cached_imgs = []
            _s2_multi = list(st.session_state.get("_cached_s2_images") or [])
            if _s2_multi:
                _cached_imgs = _s2_multi
            else:
                _s2ff = st.session_state.get("_cached_s2_first_frame")
                _s2lf = st.session_state.get("_cached_s2_last_frame")
                if _s2ff or _s2lf:
                    _cached_imgs = [x for x in (_s2ff, _s2lf) if x]
                else:
                    _s2fo = st.session_state.get("_cached_s2_first_only")
                    if _s2fo:
                        _cached_imgs = [_s2fo]
                    else:
                        _cached_imgs = []
            _cached_vids = list(st.session_state.get("_cached_s2_videos") or [])
            _cached_auds = list(st.session_state.get("_cached_s2_audio") or [])
            for _i, _f in enumerate(_cached_imgs):
                _k = getattr(_f, "name", "") or ""
                if _k:
                    _console_tag_map[_k] = f"@Image {_i + 1}"
            for _i, _f in enumerate(_cached_vids):
                _k = getattr(_f, "name", "") or ""
                if _k:
                    _console_tag_map[_k] = f"@Video {_i + 1}"
            for _i, _f in enumerate(_cached_auds):
                _k = getattr(_f, "name", "") or ""
                if _k:
                    _console_tag_map[_k] = f"@Audio {_i + 1}"
            for _i, _f in enumerate(list(st.session_state.get("_cached_sd_refs") or [])):
                _k = getattr(_f, "name", "") or ""
                if _k:
                    _console_tag_map[_k] = f"@Image {_i + 1}"

        # ── Grid ──
        GRID_COLS = 4
        for row_start in range(0, len(page_items), GRID_COLS):
            row = page_items[row_start:row_start + GRID_COLS]
            cols = st.columns(GRID_COLS, gap="small")
            for ci in range(GRID_COLS):
                with cols[ci]:
                    if ci >= len(row):
                        st.empty()
                        continue

                    asset = row[ci]
                    ftype = asset["type"]
                    fpath = asset["path"]
                    fname = asset["name"]
                    size_str = asset.get("size_str", "")

                    type_colors = {"image": "#00E5CC", "video": "#FF9800", "audio": "#BB86FC"}
                    type_labels = {"image": "IMG", "video": "VID", "audio": "AUD"}
                    badge_color = type_colors.get(ftype, "#9E9E8A")
                    badge_label = type_labels.get(ftype, "FILE")
                    _orig_name = asset.get("original_name") or ""
                    _pick_labels_live = st.session_state.get("assets_console_pick", [])
                    _asset_label = _asset_picker_label(asset)
                    _at_tag = ""
                    if _asset_label in _pick_labels_live:
                        _at_tag = f"@Image {_pick_labels_live.index(_asset_label) + 1}"
                    if not _at_tag:
                        _at_tag = _console_tag_map.get(_orig_name, "") or _console_tag_map.get(fname, "")
                    _at_tag_esc = _html_stdlib.escape(_at_tag) if _at_tag else ""
                    _at_tag_html = (
                        f'<span style="color:#FFEB3B; font-size:0.6rem; font-weight:700; '
                        f'font-family:Open Sans,sans-serif; background:rgba(255,235,59,0.12); '
                        f'padding:1px 5px; border-radius:3px; margin-left:6px;">{_at_tag_esc}</span>'
                    ) if _at_tag_esc else ""

                    st.markdown(
                        f'<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">'
                        f'<span style="color:{badge_color}; font-size:0.65rem; font-weight:700; '
                        f'font-family:Open Sans,sans-serif; letter-spacing:0.08em;">{badge_label}{_at_tag_html}</span>'
                        f'<span style="color:#7a7a6e; font-size:0.6rem; font-family:Open Sans,sans-serif;">{size_str}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                    # Media preview
                    if ftype == "image" and os.path.exists(fpath):
                        try:
                            st.image(fpath, width="stretch")
                        except Exception:
                            st.warning(f"Cannot display: {fname}")
                    elif ftype == "video" and os.path.exists(fpath):
                        try:
                            st.video(fpath)
                        except Exception:
                            st.warning(f"Cannot play: {fname}")
                    elif ftype == "audio" and os.path.exists(fpath):
                        try:
                            st.audio(fpath)
                        except Exception:
                            st.warning(f"Cannot play: {fname}")
                    else:
                        st.warning("File not found")

                    display_name = fname[:30] + "..." if len(fname) > 30 else fname

                    # Image/video: una riga sotto il media — nome a sinistra, cestino a destra (no overlay)
                    if ftype in ("image", "video"):
                        _del_key = f"asset_del_{ftype}_{asset['id']}"
                        _cap_l, _cap_r = st.columns([10, 1.25], gap="small")
                        with _cap_l:
                            st.markdown(
                                f'<p style="color:#7a7a6e; font-size:0.6rem; font-family:Open Sans,sans-serif; '
                                f'margin:2px 0 0 0; padding:0; line-height:1.25; '
                                f'white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">'
                                f"{display_name}</p>",
                                unsafe_allow_html=True,
                            )
                        with _cap_r:
                            if st.button(
                                "🗑",
                                key=_del_key,
                                help="Remove from Assets",
                                width="stretch",
                            ):
                                _do_asset_delete(asset, fpath, fname)
                    else:
                        _fn_c, _del_c = st.columns([7, 1])
                        with _fn_c:
                            st.markdown(
                                f'<p style="color:#7a7a6e; font-size:0.6rem; font-family:Open Sans,sans-serif; '
                                f'margin:-6px 0 0 0; padding:0 2px 0 0; line-height:1.25; '
                                f'white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">'
                                f'{display_name}</p>',
                                unsafe_allow_html=True,
                            )
                        with _del_c:
                            if st.button(
                                "🗑",
                                key=f"asset_del_audio_{asset['id']}",
                                help="Remove from Assets",
                                width="stretch",
                            ):
                                _do_asset_delete(asset, fpath, fname)
