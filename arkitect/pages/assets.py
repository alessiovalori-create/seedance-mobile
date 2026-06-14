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
from arkitect.ratings import apply_gallery_sort, get_rating_for_item, item_key_for_rating
from arkitect.rating_ui import (
    inject_rating_styles,
    process_rating_bridge,
    render_gallery_sort_mode,
    render_rating_dots,
)
from arkitect.ui_helpers import _render_project_name_inline_right
from arkitect.console_state import _asset_picker_label, build_console_reference_tag_map
from arkitect.storyboard_io import _autosave_storyboard_snapshot




def _assets_sorted_items(items):
    mode = st.session_state.get("assets_sort_mode", "Rating")
    return apply_gallery_sort(list(items), mode, date_field="uploaded_at")


def _assets_display_tag_map(catalog: list) -> dict[str, str]:
    """
    IMG/VID badges on Assets grid.
    - Active selection → @Image 1, 2, … from current pick order (fresh numbering).
    - No selection → Console tag map / caches (persist during same generation).
    """
    sel_ids = st.session_state.get("assets_selected_ordered") or []
    if sel_ids:
        by_id = {a["id"]: a for a in catalog if a.get("id")}
        tag_map: dict[str, str] = {}
        img_n = vid_n = 0
        for aid in sel_ids:
            asset = by_id.get(aid)
            if not asset:
                continue
            ftype = asset.get("type")
            if ftype == "image":
                img_n += 1
                tag = f"@Image {img_n}"
            elif ftype == "video":
                vid_n += 1
                tag = f"@Video {vid_n}"
            else:
                continue
            tag_map[asset["name"]] = tag
            orig = asset.get("original_name")
            if orig:
                tag_map[orig] = tag
        return tag_map

    return build_console_reference_tag_map(catalog)


def _process_assets_rating_bridge() -> bool:
    _key = "assets_rat_act"
    raw = (st.session_state.get(_key) or "").strip()
    if not raw or "|" not in raw:
        return False
    st.session_state[_key] = ""
    return process_rating_bridge(raw)


def render_assets_page():
    """Render the Assets page (uploaded image/video/audio catalog)."""
    _run_id = st.session_state.get("_streamlit_run_id", 0)
    if st.session_state.get(f"_rendered_assets_{_run_id}"):
        return
    st.session_state[f"_rendered_assets_{_run_id}"] = True

    # ── Navigation ──
    if "assets_nav" not in st.session_state:
        st.session_state.assets_nav = "Assets"
    elif st.session_state.assets_nav not in ("Console", "Projects", "Gallery", "Assets", "References", "Storyboard", "Editing", "LAB"):
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
        elif val == "LAB":
            st.session_state.assets_nav = "Assets"
            st.session_state.active_page = "lab"

    _assets_nav_col, _assets_proj_col = st.columns([4, 1])
    with _assets_nav_col:
        st.radio(
            "assets_nav_label",
            ["Console", "Projects", "Gallery", "Assets", "References", "Storyboard", "Editing", "LAB"],
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

    # ── Click-to-select state (session-scoped; cleared on project change) ──
    if "assets_selected_ordered" not in st.session_state:
        st.session_state["assets_selected_ordered"] = []
    if st.session_state.get("_assets_sel_last_project") != active_proj:
        st.session_state["assets_selected_ordered"] = []
        st.session_state["_assets_sel_last_project"] = active_proj

    # ── Selection styling (injected ONCE) — yellow border matches Gallery (#FFEB3B, 3px) ──
    st.markdown(
        """
        <style>
        div[data-testid="stColumn"]:has(.asset-sel-marker),
        div[data-testid="column"]:has(.asset-sel-marker){
            border:3px solid #FFEB3B !important;
            border-radius:6px !important;
            box-shadow:0 0 0 1px #FFEB3B;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

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
        filtered = list(catalog)

    if "assets_sort_mode" not in st.session_state:
        st.session_state.assets_sort_mode = "Rating"

    inject_rating_styles()
    if _process_assets_rating_bridge():
        st.rerun()

    _audio_only = [a for a in filtered if a["type"] == "audio"]
    _visual = [a for a in filtered if a["type"] in ("image", "video")]
    if _visual:
        _visual = _assets_sorted_items(_visual)
    filtered = _visual + _audio_only

    if _visual:
        _sort_col, _sort_sp = st.columns([2, 3])
        with _sort_col:
            render_gallery_sort_mode("assets_sort_mode")
        with _sort_sp:
            st.caption(
                "Rating: green → orange → red (newest within each). "
                "Chronological: newest first."
            )

    st.text_input(
        "assets_rat_bridge_inp",
        key="assets_rat_act",
        label_visibility="collapsed",
    )

    st.markdown(
        f'<p style="color:#9E9E8A; font-size:0.72rem; text-align:right; margin:4px 0 8px 0;">'
        f'{len(filtered)} files</p>',
        unsafe_allow_html=True,
    )

    _img_assets_all = [a for a in catalog if a.get("type") == "image"]
    _full_by_id = {a["id"]: a for a in catalog}

    # ── Selection panel (native sidebar — Option 1 per spec) ──
    _sel_ids = st.session_state["assets_selected_ordered"]
    _n_sel = len(_sel_ids)
    with st.sidebar:
        if st.button(
            "→ Send to Seedance 2.0",
            type="primary",
            use_container_width=True,
            disabled=(_n_sel == 0),
            key="assets_panel_send_s2",
        ):
            st.session_state["_assets_to_console_pending"] = {
                "asset_ids": list(st.session_state["assets_selected_ordered"]),
                "catalog": catalog,
                "image_usage": None,
                "preserve_workflow": True,
            }
            st.session_state["_console_was_away"] = True
            st.session_state.active_page = "console"
            st.session_state["assets_selected_ordered"] = []
            st.toast(f"Sending {_n_sel} reference(s) to Seedance 2.0")
            st.rerun()
        _has_non_image = any(
            (_full_by_id.get(x) or {}).get("type", "image") != "image"
            for x in _sel_ids
        )
        _sd_disabled = (_n_sel == 0) or _has_non_image
        if st.button(
            "→ Send to Seedream 5.0",
            type="primary",
            use_container_width=True,
            disabled=_sd_disabled,
            key="assets_panel_send_sd",
            help=("Seedream accepts images only. Remove video items from your selection."
                  if _has_non_image else None),
        ):
            _send_ids = list(st.session_state["assets_selected_ordered"])
            _truncated = len(_send_ids) > 14
            _send_ids = _send_ids[:14]
            st.session_state["_assets_to_console_pending_seedream"] = {
                "asset_ids": _send_ids,
                "catalog": _img_assets_all,
            }
            st.session_state["_console_was_away"] = True
            st.session_state.active_page = "console"
            st.session_state["assets_selected_ordered"] = []
            if _truncated:
                st.toast(f"Sending 14 reference(s) to Seedream 5.0 (max). {_n_sel - 14} items were not sent.")
            else:
                st.toast(f"Sending {len(_send_ids)} reference(s) to Seedream 5.0")
            st.rerun()
        _img_sel_ids = [
            x for x in _sel_ids
            if (_full_by_id.get(x) or {}).get("type", "image") == "image"
        ]
        _sb_disabled = (len(_img_sel_ids) == 0)
        if st.button(
            "→ Send to Storyboard",
            type="primary",
            use_container_width=True,
            disabled=_sb_disabled,
            key="assets_panel_send_sb",
            help=("Storyboard accepts images only. Select at least one image."
                  if _sb_disabled else None),
        ):
            if (
                "sb_active_images" not in st.session_state
                or st.session_state.get("sb_mode") not in ("new", "loaded")
            ):
                st.session_state.sb_mode = "new"
                st.session_state.sb_active_name = ""
                st.session_state.sb_active_images = []
            _existing_paths = {
                it.get("image_path")
                for it in st.session_state.get("sb_active_images", [])
                if it.get("image_path")
            }
            _active_pid = get_active_project_id()
            _added = 0
            for _aid in _img_sel_ids:
                _a = _full_by_id.get(_aid)
                if not _a:
                    continue
                _p = (_a.get("path") or "").strip()
                if not _p or _p in _existing_paths:
                    continue
                st.session_state.sb_active_images.append({
                    "image_path": _p,
                    "url": _p if _p.startswith("http") else "",
                    "caption": _a.get("name", ""),
                    "project_id": _a.get("project_id", _active_pid),
                })
                _existing_paths.add(_p)
                _added += 1
            _autosave_storyboard_snapshot()
            st.session_state["assets_selected_ordered"] = []
            st.session_state.active_page = "storyboard"
            st.toast(f"Added {_added} image(s) to storyboard")
            st.rerun()
        if _n_sel > 0:
            if st.button("Clear selection", use_container_width=True, key="assets_panel_clear"):
                st.session_state["assets_selected_ordered"] = []
                st.rerun()

        st.markdown(
            '<hr style="border:none;border-top:1px solid #2a2a28;margin:16px 0;">',
            unsafe_allow_html=True,
        )
        if st.button("CLEAR", key="assets_sidebar_clear", use_container_width=True):
            if _n_sel > 0:
                _removed = 0
                cat = load_asset_catalog()
                for _aid in list(_sel_ids):
                    _a = _full_by_id.get(_aid)
                    if not _a:
                        continue
                    _fp = _a.get("path") or ""
                    try:
                        if _fp and os.path.exists(_fp):
                            os.remove(_fp)
                    except Exception:
                        pass
                    cat = [x for x in cat if x["id"] != _aid]
                    _removed += 1
                save_asset_catalog(cat)
                st.session_state["assets_selected_ordered"] = []
                if _removed:
                    st.toast(f"Removed {_removed} item(s) from Assets")
                else:
                    st.toast("No items removed")
                st.rerun()
            else:
                st.session_state["assets_selected_ordered"] = []
                st.toast("Selection cleared.")
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

        _console_tag_map = _assets_display_tag_map(catalog)

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
                    _a_ikey = item_key_for_rating(asset) if ftype in ("image", "video") else ""
                    _is_sel = (
                        asset["id"] in st.session_state["assets_selected_ordered"]
                        if ftype in ("image", "video")
                        else False
                    )
                    if ftype in ("image", "video") and _is_sel:
                        st.markdown('<div class="asset-sel-marker"></div>', unsafe_allow_html=True)

                    type_colors = {"image": "#00E5CC", "video": "#FF9800", "audio": "#BB86FC"}
                    type_labels = {"image": "IMG", "video": "VID", "audio": "AUD"}
                    badge_color = type_colors.get(ftype, "#9E9E8A")
                    badge_label = type_labels.get(ftype, "FILE")
                    _orig_name = asset.get("original_name") or ""
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
                        f'font-family:Open Sans,sans-serif; letter-spacing:0.08em;">'
                        f'{badge_label}{_at_tag_html}</span>'
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

                    if ftype in ("image", "video"):
                        _vc_cap, _vc_rat, _vc_sel = st.columns(
                            [3, 2, 1], gap="small", vertical_alignment="center"
                        )
                        with _vc_cap:
                            _safe_name = _html_stdlib.escape(display_name)
                            st.markdown(
                                f'<p style="margin:0;color:#7a7a6e;font-size:0.72rem;'
                                f'font-family:Open Sans,sans-serif;white-space:nowrap;'
                                f'overflow:hidden;text-overflow:ellipsis;'
                                f'line-height:1.4;">{_safe_name}</p>',
                                unsafe_allow_html=True,
                            )
                        with _vc_rat:
                            if _a_ikey:
                                render_rating_dots(
                                    _a_ikey,
                                    bridge_aria_label="assets_rat_bridge_inp",
                                    fn_name="postAssetRating",
                                    item=asset,
                                    inline=True,
                                )
                        with _vc_sel:
                            _asset_box_key = f"asset_sel_{asset['id']}"

                            def _on_asset_sel_change(_aid=asset["id"]):
                                if st.session_state.get(f"asset_sel_{_aid}", False):
                                    if _aid not in st.session_state["assets_selected_ordered"]:
                                        st.session_state["assets_selected_ordered"].append(_aid)
                                elif _aid in st.session_state["assets_selected_ordered"]:
                                    st.session_state["assets_selected_ordered"].remove(_aid)

                            st.checkbox(
                                "Select",
                                value=_is_sel,
                                key=_asset_box_key,
                                on_change=_on_asset_sel_change,
                                args=(asset["id"],),
                                label_visibility="collapsed",
                            )
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
