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
from arkitect.ratings import (
    apply_gallery_sort,
    clear_rating,
    get_rating_for_item,
    item_key_for_rating,
    rating_keys_for_item,
    set_rating_for_item,
)
from arkitect.rating_ui import (
    iframe_rating_dots_html,
    inject_rating_styles,
    process_rating_bridge,
    render_gallery_sort_mode,
    render_rating_dots,
)
from arkitect.gallery_paths import (
    playable_video_source,
    repair_gallery_media_paths,
    resolve_media_path,
)
from arkitect.ui_helpers import _render_project_name_inline_right
from arkitect.storage import (
    get_active_project_id,
    get_active_project_name,
    add_to_assets,
    load_asset_catalog,
    load_all_snapshots,
    save_gallery_to_disk,
    upsert_snapshot_entry,
)


def _gallery_sorted_items(items):
    mode = st.session_state.get("gal_sort_mode", "Rating")
    return apply_gallery_sort(list(items), mode)


def _show_gallery_video(item: dict | None = None, path: str | None = None) -> bool:
    """Play local/remote video without crashing Streamlit if the file is missing."""
    src = playable_video_source(item, path)
    if not src:
        st.warning("Video non disponibile (file mancante sul disco).")
        return False
    try:
        st.video(src)
        return True
    except Exception:
        fallback = (item or {}).get("url") or ""
        if fallback.startswith("http"):
            try:
                st.video(fallback)
                return True
            except Exception:
                pass
        st.warning("Impossibile riprodurre il video.")
        return False


def _gallery_item_identity(item: dict, *, video: bool = False) -> str:
    if video:
        return item.get("video_path") or item.get("url") or ""
    return item.get("image_path") or item.get("url") or ""


def _unlink_gallery_files(item: dict, *, video: bool = False) -> None:
    """Gallery removal keeps files under generated/ — only the catalog entry is dropped."""
    return


def _delete_selected_gallery_items(
    sorted_items: list,
    selected_indices: set,
    *,
    video: bool = False,
) -> int:
    """Remove selected items from session gallery, disk, and ratings."""
    if not selected_indices:
        return 0
    to_remove = set()
    for idx in selected_indices:
        if 0 <= idx < len(sorted_items):
            ident = _gallery_item_identity(sorted_items[idx], video=video)
            if ident:
                to_remove.add(ident)
    if not to_remove:
        return 0

    session_key = "gallery_videos" if video else "gallery_images"
    kept = []
    removed = 0
    for item in st.session_state.get(session_key) or []:
        ident = _gallery_item_identity(item, video=video)
        if ident and ident in to_remove:
            _unlink_gallery_files(item, video=video)
            for rkey in rating_keys_for_item(item):
                clear_rating(rkey)
            removed += 1
        else:
            kept.append(item)
    st.session_state[session_key] = kept
    save_gallery_to_disk(
        st.session_state.get("gallery_videos") or [],
        st.session_state.get("gallery_images") or [],
    )
    return removed


def _process_gal_rating_bridge() -> bool:
    """Apply pending iframe rating click before grid sort (same pattern as gallery_img_action)."""
    _key = "gal_rat_act"
    raw = (st.session_state.get(_key) or "").strip()
    if not raw or "|" not in raw:
        return False
    st.session_state[_key] = ""
    return process_rating_bridge(raw)


def _render_gallery_sidebar():
    """Selection + controlli Gallery nella sidebar nativa Streamlit (sinistra, come Assets)."""
    _media_tab = st.session_state.get("gal_media_tab", "Images")
    _active_proj = get_active_project_id()
    _all_imgs: list = []
    _all_vids: list = []

    with st.sidebar:
        if _media_tab == "Images":
            _all_imgs = list(st.session_state.get("gallery_images") or [])
            if _active_proj:
                _all_imgs = [img for img in _all_imgs if img.get("project_id") == _active_proj]
            else:
                _all_imgs = []
            _all_imgs = _gallery_sorted_items(_all_imgs)
            n_sel = len(st.session_state.gallery_selected_imgs)

            if st.button(
                "→ Send to: Storyboard",
                type="primary",
                use_container_width=True,
                disabled=(n_sel == 0),
                key="gal_panel_send_storyboard",
            ):
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

            if st.button(
                "→ Send to: Asset",
                type="primary",
                use_container_width=True,
                disabled=(n_sel == 0),
                key="gal_panel_send_img_asset",
            ):
                saved = 0
                skipped_missing_path = 0
                skipped_not_on_disk = 0
                skipped_already_in_catalog = 0
                _pre_ids = {a.get("id") for a in load_asset_catalog()}
                for idx in sorted(st.session_state.gallery_selected_imgs):
                    if idx < len(_all_imgs):
                        item = _all_imgs[idx]
                        src_path = item.get("image_path", "")
                        if not src_path:
                            skipped_missing_path += 1
                        elif not os.path.exists(src_path):
                            skipped_not_on_disk += 1
                        else:
                            result = add_to_assets(source_path=src_path)
                            if result and result.get("id") in _pre_ids:
                                skipped_already_in_catalog += 1
                            elif result:
                                saved += 1
                st.session_state.gallery_selected_imgs = set()
                if saved > 0:
                    st.toast(f"Saved {saved} image(s) to Assets")
                elif skipped_already_in_catalog > 0:
                    st.toast(f"No images saved ({skipped_already_in_catalog} already in Assets)")
                elif skipped_not_on_disk > 0:
                    st.toast(f"No images saved ({skipped_not_on_disk} file(s) missing from disk)")
                elif skipped_missing_path > 0:
                    st.toast(f"No images saved ({skipped_missing_path} without a local file)")
                else:
                    st.toast("No images were saved (already in Assets or unavailable on disk)")
                st.rerun()

            if n_sel > 0:
                if st.button("Clear selection", use_container_width=True, key="gal_panel_clear_img_sel"):
                    st.session_state.gallery_selected_imgs = set()
                    st.rerun()

        else:
            _all_vids = list(st.session_state.get("gallery_videos") or [])
            if _active_proj:
                _all_vids = [v for v in _all_vids if v.get("project_id") == _active_proj]
            else:
                _all_vids = []
            _all_vids = _gallery_sorted_items(_all_vids)
            _sel_idxs = st.session_state.get("gallery_selected_ordered") or []
            vn_sel = len(_sel_idxs)

            if st.button(
                "→ Send to: Editing",
                type="primary",
                use_container_width=True,
                disabled=(vn_sel == 0),
                key="gal_panel_send_editing",
            ):
                if st.session_state.ed_mode not in ("new", "loaded"):
                    st.session_state.ed_mode = "new"
                    st.session_state.ed_active_name = ""
                    st.session_state.ed_active_videos = []
                existing_vpaths = {
                    item.get("video_path")
                    for item in st.session_state.ed_active_videos
                    if item.get("video_path")
                }
                _added_ed = 0
                for idx in _sel_idxs:
                    if idx < len(_all_vids):
                        vitem = _all_vids[idx]
                        vpath = vitem.get("video_path", "")
                        if not vpath or vpath not in existing_vpaths:
                            st.session_state.ed_active_videos.append(
                                _normalize_editing_video_item(dict(vitem))
                            )
                            if vpath:
                                existing_vpaths.add(vpath)
                            _added_ed += 1
                if st.session_state.ed_active_name:
                    upsert_snapshot_entry(
                        "editing",
                        st.session_state.ed_active_name,
                        st.session_state.ed_active_videos,
                    )
                st.session_state.gallery_selected_ordered = []
                st.toast(f"Added {_added_ed} video(s) to editing!")
                st.rerun()

            if st.button(
                "→ Send to: Asset",
                type="primary",
                use_container_width=True,
                disabled=(vn_sel == 0),
                key="gal_panel_send_asset",
            ):
                saved = 0
                skipped_missing_path = 0
                skipped_not_on_disk = 0
                skipped_already_in_catalog = 0
                _pre_ids = {a.get("id") for a in load_asset_catalog()}
                for idx in _sel_idxs:
                    if idx < len(_all_vids):
                        item = _all_vids[idx]
                        src_path = item.get("video_path", "")
                        if not src_path:
                            skipped_missing_path += 1
                        elif not os.path.exists(src_path):
                            skipped_not_on_disk += 1
                        else:
                            result = add_to_assets(source_path=src_path)
                            if result and result.get("id") in _pre_ids:
                                skipped_already_in_catalog += 1
                            elif result:
                                saved += 1
                st.session_state.gallery_selected_ordered = []
                if saved > 0:
                    st.toast(f"Saved {saved} video(s) to Assets")
                elif skipped_already_in_catalog > 0:
                    st.toast(f"No videos saved ({skipped_already_in_catalog} already in Assets)")
                elif skipped_not_on_disk > 0:
                    st.toast(f"No videos saved ({skipped_not_on_disk} file(s) missing from disk)")
                elif skipped_missing_path > 0:
                    st.toast(f"No videos saved ({skipped_missing_path} without a local file)")
                else:
                    st.toast("No videos were saved (already in Assets or unavailable on disk)")
                st.rerun()

            _extend_disabled = vn_sel == 0
            _extend_help = None
            if vn_sel > 1:
                _extend_disabled = True
                _extend_help = "Select exactly one video to extend."
            elif vn_sel == 1:
                _ext_idx = _sel_idxs[0]
                _ext_item = _all_vids[_ext_idx] if 0 <= _ext_idx < len(_all_vids) else None
                if not (
                    _ext_item
                    and _ext_item.get("model") == "Seedance 2.0"
                    and playable_video_source(_ext_item)
                ):
                    _extend_disabled = True
                    _extend_help = "Only playable Seedance 2.0 clips can be extended."

            if st.button(
                "→ Send to: Extend",
                type="primary",
                use_container_width=True,
                disabled=_extend_disabled,
                help=_extend_help,
                key="gal_panel_send_extend",
            ):
                _ext_idx = _sel_idxs[0]
                _ext_item = _all_vids[_ext_idx]
                st.session_state["pending_extend_upgrade"] = {
                    "source_item": dict(_ext_item),
                    "source_index": _ext_idx,
                }
                st.rerun()

            if vn_sel > 0:
                if st.button("Clear selection", use_container_width=True, key="gal_panel_clear_sel"):
                    st.session_state.gallery_selected_ordered = []
                    st.rerun()

        st.markdown(
            '<hr style="border:none;border-top:1px solid #2a2a28;margin:16px 0;">',
            unsafe_allow_html=True,
        )
        if st.button("CLEAR", key="gal_sidebar_clear_sel", use_container_width=True):
            if _media_tab == "Images" and st.session_state.gallery_selected_imgs:
                _n_removed = _delete_selected_gallery_items(
                    _all_imgs,
                    st.session_state.gallery_selected_imgs,
                    video=False,
                )
                st.session_state.gallery_selected_imgs = set()
                if _n_removed:
                    st.toast(f"Removed {_n_removed} image(s) from gallery (files kept on disk)")
                else:
                    st.toast("No images removed")
                st.rerun()
            elif _media_tab != "Images" and st.session_state.gallery_selected_ordered:
                _n_removed = _delete_selected_gallery_items(
                    _all_vids,
                    set(st.session_state.gallery_selected_ordered),
                    video=True,
                )
                st.session_state.gallery_selected_ordered = []
                if _n_removed:
                    st.toast(f"Removed {_n_removed} video(s) from gallery (files kept on disk)")
                else:
                    st.toast("No videos removed")
                st.rerun()
            else:
                st.session_state.gallery_selected_imgs = set()
                st.session_state.gallery_selected_ordered = []
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
        elif val == "LAB":
            st.session_state.gal_nav = "Gallery"
            st.session_state.active_page = "lab"

    # Ordine nav: "Gallery" per prima così un reset sporadico del widget (click rapidi
    # tra controlli affiancati) non seleziona "Console" e non manda alla main page.
    _GAL_MAIN_NAV = ["Gallery", "Console", "Projects", "Assets", "References", "Storyboard", "Editing", "LAB"]
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
    if repair_gallery_media_paths(gallery_videos, gallery_images):
        st.session_state.gallery_videos = gallery_videos
        st.session_state.gallery_images = gallery_images
        try:
            save_gallery_to_disk(gallery_videos, gallery_images)
        except Exception:
            pass
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

    # ── Video selection state (ordered list; reset on project change) ──
    if "gallery_selected_ordered" not in st.session_state:
        st.session_state["gallery_selected_ordered"] = []
    if st.session_state.get("_gallery_sel_last_project") != _active_pid:
        st.session_state["gallery_selected_ordered"] = []
        st.session_state["_gallery_sel_last_project"] = _active_pid

    st.markdown(
        """
        <style>
        div[data-testid="stColumn"]:has(.gallery-sel-marker),
        div[data-testid="column"]:has(.gallery-sel-marker){
            border:3px solid #FFEB3B !important;
            border-radius:6px !important;
            box-shadow:0 0 0 1px #FFEB3B;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if "gal_sort_mode" not in st.session_state:
        st.session_state.gal_sort_mode = "Rating"

    inject_rating_styles()

    if st.session_state.get("gal_nav") == "Gallery":
        _process_gal_rating_bridge()
        gallery_images = _gallery_sorted_items(gallery_images)
        gallery_videos = _gallery_sorted_items(gallery_videos)
        st.text_input(
            "gal_rat_bridge_inp",
            key="gal_rat_act",
            label_visibility="collapsed",
        )

    _render_gallery_sidebar()

    # ──────────────────────────────────────────────
    # EXTEND & UPGRADE — Modal panel (triggered from gallery)
    # ──────────────────────────────────────────────
    _pending_eu = st.session_state.get("pending_extend_upgrade")
    if _pending_eu and isinstance(_pending_eu, dict):
        _src = dict(_pending_eu.get("source_item") or {})
        _raw_vp = (_src.get("video_path") or "").strip()
        if _raw_vp and not _raw_vp.startswith("http"):
            _resolved_vp = resolve_media_path(_raw_vp)
            if _resolved_vp and os.path.isfile(_resolved_vp):
                _src["video_path"] = _resolved_vp
                _pending_eu["source_item"] = _src
                st.session_state["pending_extend_upgrade"] = _pending_eu
        _src_playable = playable_video_source(_src)
        if not _src_playable:
            st.session_state.pop("pending_extend_upgrade", None)
            st.warning("Clip sorgente non trovata — pannello Extend chiuso.")
            _pending_eu = None
    if _pending_eu and isinstance(_pending_eu, dict):
        _src = _pending_eu.get("source_item", {})
        _src_path = _src_playable or _src.get("video_path") or _src.get("url")
        _src_dur = int(_src.get("duration") or 5)
        _src_res = _src.get("resolution") or "720p"
        _src_ar = _src.get("aspect_ratio") or "16:9"
        _can_extend_duration = _src_dur < 14
        _at_max_duration = _src_dur >= 15

        with st.container(border=True):
            st.markdown(
                '<p style="color:#FFEB3B;font-size:0.9rem;font-weight:600;'
                'margin:0 0 8px;">EXTEND & UPGRADE</p>',
                unsafe_allow_html=True
            )
            st.caption(
                f"Source: {_src_res} · {_src_dur}s · {_src_ar} · "
                f"{_src.get('caption','')[:40]}"
            )
            if _src_path:
                _show_gallery_video(_src, _src_path)

            if _can_extend_duration:
                _eu_col1, _eu_col2 = st.columns(2, gap="small")
                with _eu_col1:
                    _target_res = st.selectbox(
                        "Target resolution",
                        ["720p", "1080p", "2K"],
                        index=1,
                        key="eu_target_res",
                    )
                with _eu_col2:
                    _min_target = max(_src_dur + 1, 4)
                    _default_target = min(15, max(_min_target, _src_dur + 5))
                    _target_dur = st.slider(
                        "Target duration (s)",
                        min_value=_min_target,
                        max_value=15,
                        value=_default_target,
                        step=1,
                        key="eu_target_dur",
                    )
            elif _src_dur == 14:
                _eu_col1, _eu_col2 = st.columns(2, gap="small")
                with _eu_col1:
                    _target_res = st.selectbox(
                        "Target resolution",
                        ["720p", "1080p", "2K"],
                        index=1,
                        key="eu_target_res",
                    )
                with _eu_col2:
                    _target_dur = 15
                    st.caption(
                        "Source is 14s — extending to 15s (Seedance maximum)."
                    )
            else:
                _target_res = st.selectbox(
                    "Target resolution",
                    ["720p", "1080p", "2K"],
                    index=1,
                    key="eu_target_res",
                )
                _target_dur = _src_dur
                st.caption(
                    "Source is already at the 15s maximum. Duration cannot be extended "
                    "— quality will be upgraded only."
                )

            _ext_desc = st.text_area(
                "Description for the new segment (what happens after the source clip)",
                placeholder="The character turns toward the window and walks slowly out of frame as the light fades to amber...",
                height=100,
                key="eu_ext_desc",
            )

            _eu_no_change = _target_dur == _src_dur and _target_res == _src_res

            _eu_btn_col1, _eu_btn_col2 = st.columns(2, gap="small")
            with _eu_btn_col1:
                _eu_cancel = st.button("CANCEL", use_container_width=True, key="eu_cancel_btn")
            with _eu_btn_col2:
                _eu_generate = st.button(
                    "GENERATE",
                    type="primary",
                    use_container_width=True,
                    key="eu_generate_btn",
                    disabled=_eu_no_change,
                    help=(
                        "No change requested — adjust resolution or duration to proceed"
                        if _eu_no_change
                        else None
                    ),
                )

            if _eu_cancel:
                st.session_state.pop("pending_extend_upgrade", None)
                st.rerun()

            if _eu_generate:
                st.session_state["_do_generate_extend"] = True

            if st.session_state.get("_do_generate_extend"):
                st.session_state["_do_generate_extend"] = False  # reset immediately to prevent double-generation
                _extend_src = playable_video_source(_src) or _src_path
                if not _extend_src or (
                    not os.path.isfile(_extend_src)
                    and not str(_extend_src).startswith("http")
                ):
                    st.error("Source video path not available.")
                else:
                    from generator import extend_and_upgrade
                    with st.spinner(f"Extending to {_target_dur}s @ {_target_res}..."):
                        _eu_result = extend_and_upgrade(
                            source_video=_extend_src,
                            source_duration=_src_dur,
                            target_duration=_target_dur,
                            target_resolution=_target_res,
                            extension_description=_ext_desc,
                            aspect_ratio=_src_ar,
                            project_name=get_active_project_name(),
                        )
                    if isinstance(_eu_result, dict) and _eu_result.get("video"):
                        from datetime import datetime
                        _eu_vp = _eu_result.get("video_path") or ""
                        if _eu_vp:
                            _eu_vp = resolve_media_path(_eu_vp)
                            if not os.path.isfile(_eu_vp):
                                _eu_vp = ""
                        _eu_lf = _eu_result.get("last_frame_path") or ""
                        if _eu_lf:
                            _eu_lf = resolve_media_path(_eu_lf)
                            if not os.path.isfile(_eu_lf):
                                _eu_lf = ""
                        _eu_entry = {
                            "url": _eu_result["video"],
                            "caption": f"Extended: {_src.get('caption','')[:30]}",
                            "prompt": f"[Extend & Upgrade from #{_pending_eu.get('source_index')}]",
                            "resolution": _target_res,
                            "duration": _target_dur,
                            "aspect_ratio": _src_ar,
                            "video_path": _eu_vp or None,
                            "last_frame_path": _eu_lf or None,
                            "model": "Seedance 2.0",
                            "created_at": datetime.now().isoformat(),
                            "project_id": st.session_state.get("active_project_id"),
                            "estimated_cost": None,
                            "schema_version": "1",
                            "is_extend_upgrade": True,
                            "source_index": _pending_eu.get("source_index"),
                        }
                        st.session_state.gallery_videos.append(_eu_entry)
                        set_rating_for_item(_eu_entry, "green")
                        try:
                            from arkitect.storage import save_gallery_to_disk
                            save_gallery_to_disk(
                                st.session_state.gallery_videos,
                                st.session_state.gallery_images,
                            )
                        except Exception:
                            pass
                        st.session_state.pop("pending_extend_upgrade", None)
                        st.success("Extended clip added to gallery.")
                        st.rerun()
                    else:
                        _err = (_eu_result or {}).get("error", str(_eu_result))
                        st.error(f"Generation failed: {_err}")

        st.divider()

    if st.session_state.gal_nav == "Gallery":
        if not gallery_videos and not gallery_images:
            st.info("No media in this project yet. Generate videos or images in the Console.")
            st.stop()
        _sort_col, _sort_sp = st.columns([2, 3])
        with _sort_col:
            render_gallery_sort_mode("gal_sort_mode")
        with _sort_sp:
            st.caption(
                "Rating: green → orange → red (newest within each). "
                "Chronological: newest first."
            )

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
                _ikey = item_key_for_rating(item)
                _cur_rat = get_rating_for_item(item)
                _rat_dots = (
                    iframe_rating_dots_html(_ikey, _cur_rat, fn_name="galRate")
                    if _ikey else ""
                )
                _safe_ikey = (_ikey or "").replace('"', "&quot;")

                cards_html += f'''
                <div class="gal-card" data-idx="{abs_i}"
                     data-item-key="{_safe_ikey}"
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
                    {_rat_dots}
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
                .rating-dots-row {{ display:flex; gap:10px; justify-content:center; align-items:center; padding:6px 0 4px; }}
                .rating-dot-btn {{ border-radius:50%; cursor:pointer; transition:opacity .15s ease; }}
            </style>
            <div class="gal-grid" id="galleryImgGrid">{cards_html}</div>
            <script>
                function _ratingUpdateDots(btn, rating) {{
                    var row = btn && btn.closest ? btn.closest('.rating-dots-row') : null;
                    if (!row) return;
                    var wasActive = parseFloat(btn.style.opacity || '0') >= 0.95;
                    row.querySelectorAll('.rating-dot-btn').forEach(function(b) {{
                        if (wasActive) {{
                            b.style.opacity = '0.38';
                        }} else {{
                            b.style.opacity = (b.getAttribute('data-rating') === rating) ? '1' : '0.38';
                        }}
                    }});
                }}
                function galRate(itemKey, rating, btn) {{
                    if (!itemKey) return;
                    var inp = window.parent.document.querySelector(
                        'input[aria-label="gal_rat_bridge_inp"]'
                    );
                    if (!inp) return;
                    var ns = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    ).set;
                    var payload = itemKey + '|' + rating + '|' + Date.now();
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
            grid_height = ((len(page_images) + 4) // 5) * (thumb_h + 58) + 20
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
                        _cap    = (_item.get("caption", "") or "").strip()
                        _v_ikey = item_key_for_rating(_item)
                        _sel_list = st.session_state.get("gallery_selected_ordered") or []
                        _is_sel = _aidx in _sel_list
                        if _is_sel:
                            st.markdown(
                                '<div class="gallery-sel-marker"></div>',
                                unsafe_allow_html=True,
                            )
                        if not _show_gallery_video(_item):
                            pass

                        _vc_cap, _vc_rat, _vc_sel = st.columns(
                            [3, 2, 1], gap="small", vertical_alignment="center"
                        )
                        with _vc_cap:
                            _safe_cap = (
                                _cap.replace("&", "&amp;")
                                .replace("<", "&lt;")
                                .replace(">", "&gt;")
                                .replace('"', "&quot;")
                            )
                            st.markdown(
                                f'<p style="margin:0;color:#999;font-size:0.72rem;'
                                f'font-family:Open Sans,sans-serif;white-space:nowrap;'
                                f'overflow:hidden;text-overflow:ellipsis;'
                                f'line-height:1.4;">{_safe_cap} · #{_badge}</p>',
                                unsafe_allow_html=True,
                            )
                        with _vc_rat:
                            if _v_ikey:
                                render_rating_dots(
                                    _v_ikey,
                                    bridge_aria_label="gal_rat_bridge_inp",
                                    fn_name="postRating",
                                    item=_item,
                                    inline=True,
                                )
                        with _vc_sel:
                            _gv_box_key = f"sel_vid_gal_{_aidx}"

                            def _on_gal_vid_sel_change(_idx=_aidx):
                                if st.session_state.get(f"sel_vid_gal_{_idx}", False):
                                    if _idx not in st.session_state["gallery_selected_ordered"]:
                                        st.session_state["gallery_selected_ordered"].append(_idx)
                                elif _idx in st.session_state["gallery_selected_ordered"]:
                                    st.session_state["gallery_selected_ordered"].remove(_idx)

                            st.checkbox(
                                "Select",
                                value=_is_sel,
                                key=_gv_box_key,
                                on_change=_on_gal_vid_sel_change,
                                args=(_aidx,),
                                label_visibility="collapsed",
                            )

                        # Inline meta caption: source resolution + duration
                        _src_dur = _item.get("duration")
                        _src_res = _item.get("resolution")
                        if _src_dur or _src_res:
                            st.markdown(
                                f'<p style="color:#7a7a6e;font-size:0.65rem;'
                                f'margin:2px 0 0;text-align:center;">'
                                f'{_src_res or ""}{" · " if _src_res and _src_dur else ""}'
                                f'{str(_src_dur)+"s" if _src_dur else ""}</p>',
                                unsafe_allow_html=True
                            )

            st.markdown(
                f'<p style="color:#7a7a6e;font-size:0.72rem;'
                f'margin-top:6px;">{_vtot} videos</p>',
                unsafe_allow_html=True
            )

    st.markdown('</div>', unsafe_allow_html=True)
