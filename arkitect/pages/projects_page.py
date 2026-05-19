import os
import random
import html as _html_stdlib
import base64 as _b64
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components

from arkitect.storage import load_projects, save_projects


def render_projects_page():
    """Render the Projects page (list / create / delete projects)."""
    from ui_app import (
        _render_project_name_inline_right,
        _clear_console_prompts_for_project_change,
        _save_project_console_settings,
        _load_project_console_settings,
    )

    # ── Navigation ──
    if "proj_nav" not in st.session_state:
        st.session_state.proj_nav = "Projects"

    def _on_proj_nav_change():
        val = st.session_state.proj_nav
        if val == "Console":
            st.session_state.proj_nav = "Projects"
            st.session_state["_console_was_away"] = True
            st.session_state.active_page = "console"
        elif val == "Gallery":
            st.session_state.proj_nav = "Projects"
            st.session_state.active_page = "gallery"
        elif val == "Assets":
            st.session_state.proj_nav = "Projects"
            st.session_state.active_page = "assets"
        elif val == "References":
            st.session_state.proj_nav = "Projects"
            st.session_state.active_page = "references"
        elif val == "Storyboard":
            st.session_state.proj_nav = "Projects"
            st.session_state.active_page = "storyboard"
        elif val == "Editing":
            st.session_state.proj_nav = "Projects"
            st.session_state.active_page = "editing"

    _proj_nav_col, _proj_name_col = st.columns([4, 1])
    with _proj_nav_col:
        st.radio(
            "proj_nav_label",
            ["Console", "Projects", "Gallery", "Assets", "References", "Storyboard", "Editing"],
            horizontal=True,
            key="proj_nav",
            on_change=_on_proj_nav_change,
            label_visibility="collapsed",
        )
    with _proj_name_col:
        _render_project_name_inline_right()

    proj_data = load_projects()
    project_list = proj_data.get("projects", [])
    active_id = st.session_state.get("active_project_id")

    # ── Helper: get thumbnail for a project ──
    def _get_project_thumbnail(pid):
        """Return a base64 data URI thumbnail for the given project, or empty string."""
        # Try gallery videos first (last_frame_path), then gallery images
        all_videos = st.session_state.get("gallery_videos", [])
        for v in all_videos:
            if v.get("project_id") == pid:
                lfp = v.get("last_frame_path") or ""
                if lfp and os.path.exists(lfp):
                    try:
                        from PIL import Image as _PILImage
                        import io as _io
                        with _PILImage.open(lfp) as im:
                            im.thumbnail((400, 240), _PILImage.LANCZOS)
                            buf = _io.BytesIO()
                            im.convert("RGB").save(buf, format="JPEG", quality=75)
                            return f"data:image/jpeg;base64,{_b64.b64encode(buf.getvalue()).decode('ascii')}"
                    except Exception:
                        pass
                # Try cv2 frame extraction
                vpath = v.get("video_path") or ""
                if vpath and os.path.exists(vpath):
                    try:
                        import cv2
                        cap = cv2.VideoCapture(vpath)
                        if cap.isOpened():
                            ret, frame = cap.read()
                            if ret:
                                h, w = frame.shape[:2]
                                scale = min(400 / max(w, 1), 240 / max(h, 1), 1.0)
                                if scale < 1:
                                    frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
                                _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 72])
                                return f"data:image/jpeg;base64,{_b64.b64encode(buf.tobytes()).decode('ascii')}"
                        cap.release()
                    except Exception:
                        pass

        all_images = st.session_state.get("gallery_images", [])
        for img in all_images:
            if img.get("project_id") == pid:
                ipath = img.get("image_path") or img.get("url") or ""
                if ipath and os.path.exists(ipath):
                    try:
                        from PIL import Image as _PILImage
                        import io as _io
                        with _PILImage.open(ipath) as im:
                            im.thumbnail((400, 240), _PILImage.LANCZOS)
                            buf = _io.BytesIO()
                            im.convert("RGB").save(buf, format="JPEG", quality=75)
                            return f"data:image/jpeg;base64,{_b64.b64encode(buf.getvalue()).decode('ascii')}"
                    except Exception:
                        pass
                elif ipath and ipath.startswith("http"):
                    return ipath
        return ""

    # ── Helper: get last modified date ──
    def _get_project_last_modified(pid):
        """Return the most recent created_at from gallery items for this project."""
        latest = ""
        for coll in ["gallery_videos", "gallery_images"]:
            for item in st.session_state.get(coll, []):
                if item.get("project_id") == pid:
                    ca = item.get("created_at", "")
                    if ca > latest:
                        latest = ca
        return latest

    def _get_project_spent(pid):
        """Sum estimated_cost from all gallery items for this project."""
        total = 0.0
        for coll in ["gallery_videos", "gallery_images"]:
            for item in st.session_state.get(coll, []):
                if item.get("project_id") == pid:
                    total += item.get("estimated_cost", 0.0)
        return total

    # ── Build project cards list (thumbnail + metadata for HTML grid) ──
    cards = []
    for proj in project_list:
        pid = proj["id"]
        pname = proj["name"]
        is_active = (pid == active_id)
        thumb = _get_project_thumbnail(pid)
        created_raw = proj.get("created_at", "") or ""
        created_disp = created_raw[:16].replace("T", " ") if created_raw else "—"
        last_mod = _get_project_last_modified(pid)
        last_disp = last_mod[:16].replace("T", " ") if last_mod else "—"
        _spent = _get_project_spent(pid)
        _spent_str = f"${_spent:.2f}" if _spent >= 0.01 else "$0.00"
        cards.append({
            "id": pid,
            "name": pname,
            "thumb": thumb,
            "created": created_disp,
            "last_mod": last_disp,
            "is_active": is_active,
            "spent": _spent_str,
        })

    _proj_pick_key = "proj_pick_act"

    def _on_proj_pick_change():
        raw = (st.session_state.get(_proj_pick_key) or "").strip()
        if not raw:
            return
        st.session_state[_proj_pick_key] = ""
        pid = raw.split("|")[0].strip()
        prev_pid = st.session_state.get("active_project_id")
        pd = load_projects()
        for p in pd.get("projects", []):
            if p["id"] == pid:
                pd["active_project_id"] = pid
                save_projects(pd)
                st.session_state.active_project_id = pid
                st.session_state.active_project_name = p["name"]
                if pid != prev_pid:
                    if prev_pid:
                        _save_project_console_settings(prev_pid)
                    _clear_console_prompts_for_project_change()
                    _load_project_console_settings(pid)
                    st.session_state["_project_just_switched"] = True
                return

    _col_main, _col_side = st.columns([4, 1], gap="large")

    with _col_side:
        st.markdown(
            '<p style="color:#9E9E8A;font-size:0.75rem;font-weight:600;letter-spacing:0.08em;'
            'margin:0 0 8px;">NEW PROJECT</p>',
            unsafe_allow_html=True,
        )
        new_proj_name = st.text_input(
            "Project name",
            key="new_project_name_input",
            label_visibility="collapsed",
            placeholder="Project name...",
        )
        if st.button("NEW PROJECT", key="create_project_btn", use_container_width=True):
            name = (new_proj_name or "").strip()
            proj_data = load_projects()
            plist = proj_data.get("projects", [])
            if not name:
                st.warning("Enter a project name.")
            elif any(p["name"].lower() == name.lower() for p in plist):
                st.warning(f"Project '{name}' already exists.")
            else:
                new_id = f"proj_{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(100, 999)}"
                new_proj = {
                    "id": new_id,
                    "name": name,
                    "description": "",
                    "created_at": datetime.now().isoformat(),
                }
                proj_data["projects"].append(new_proj)
                proj_data["active_project_id"] = new_id
                save_projects(proj_data)
                st.session_state.active_project_id = new_id
                st.session_state.active_project_name = name
                _clear_console_prompts_for_project_change()
                st.toast(f"Created & activated: {name}")
                st.rerun()

        st.markdown(
            '<hr style="border:none;border-top:1px solid #2a2a28;margin:16px 0;">',
            unsafe_allow_html=True,
        )
        if st.button(
            "DELETE",
            key="proj_delete_active_btn",
            use_container_width=True,
        ):
            pd = load_projects()
            aid = st.session_state.get("active_project_id")
            if not aid:
                st.toast("Seleziona un progetto nella griglia, poi usa DELETE.")
            else:
                pd["projects"] = [p for p in pd.get("projects", []) if p["id"] != aid]
                if pd.get("active_project_id") == aid:
                    pd["active_project_id"] = None
                save_projects(pd)
                st.session_state.active_project_id = None
                st.session_state.active_project_name = "All Projects"
                _clear_console_prompts_for_project_change()
                st.toast("Project deleted.")
                st.rerun()

        st.markdown(
            '<hr style="border:none;border-top:1px solid #2a2a28;margin:16px 0;">',
            unsafe_allow_html=True,
        )
        _is_all = st.session_state.get("active_project_id") is None
        _all_lbl = "ALL PROJECTS" + (" ✓" if _is_all else "")
        if st.button(_all_lbl, key="select_all_projects", use_container_width=True):
            pd = load_projects()
            pd["active_project_id"] = None
            save_projects(pd)
            if st.session_state.get("active_project_id") is not None:
                _clear_console_prompts_for_project_change()
            st.session_state.active_project_id = None
            st.session_state.active_project_name = "All Projects"
            st.toast("Switched to: All Projects")
            st.rerun()

    with _col_main:
        st.text_input(
            "proj_pick_bridge",
            key=_proj_pick_key,
            on_change=_on_proj_pick_change,
            label_visibility="collapsed",
        )

        if not cards:
            st.info("No projects yet. Use **NEW PROJECT** in the sidebar to create one.")
        else:
            COLS = 4
            cards_html_parts = []
            for c in cards:
                _cname = _html_stdlib.escape(c["name"])
                _thumb = (c["thumb"] or "").replace('"', "&quot;")
                bcol = "#FFEB3B" if c["is_active"] else "transparent"
                init = _html_stdlib.escape(c["name"][:2].upper())
                _cr = _html_stdlib.escape(c["created"])
                _lm = _html_stdlib.escape(c["last_mod"])
                _safe_id = c["id"].replace("\\", "\\\\").replace("'", "\\'")
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
                _spent_val = _html_stdlib.escape(c["spent"])
                cards_html_parts.append(
                    f'''
                    <div class="proj-cell" onclick="projPick('{_safe_id}')">
                        <div class="proj-thumb" style="border-color:{bcol};">{thumb_block}</div>
                        <div class="proj-title">{_cname}</div>
                        <div class="proj-meta">Created: {_cr}</div>
                        <div class="proj-meta">Last modified: {_lm}</div>
                        <div class="proj-spent">Spent: {_spent_val}</div>
                    </div>'''
                )
            cards_html = "".join(cards_html_parts)
            nrows = (len(cards) + COLS - 1) // COLS
            grid_h = max(420, nrows * 210)

            proj_grid_html = f'''
            <style>
                * {{ margin:0; padding:0; box-sizing:border-box; }}
                body {{ background:transparent; font-family:Open Sans,sans-serif; }}
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
                .proj-spent {{
                    color:#FFEB3B;
                    font-size:0.68rem;
                    font-weight:700;
                    line-height:1.35;
                    margin:2px 0 0;
                    font-family:Open Sans,sans-serif;
                }}
            </style>
            <div class="proj-grid">{cards_html}</div>
            <script>
                function projPick(pid) {{
                    if (!pid) return;
                    var inp = window.parent.document.querySelector(
                        'input[aria-label="proj_pick_bridge"]'
                    );
                    if (!inp) return;
                    var ns = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    ).set;
                    var payload = pid + '|' + Date.now();
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

            components.html(proj_grid_html, height=grid_h, scrolling=False)
