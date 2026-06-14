import streamlit as st

from arkitect.ui_helpers import _render_project_name_inline_right
from arkitect.storyboard_io import (
    _render_storyboard_save_load,
    _render_storyboard_projects_sidebar,
    _render_editing_projects_sidebar,
)



def render_storyboard_page():
    """Render the Storyboard page (image grid + save/load)."""
    if "sbi_nav" not in st.session_state:
        st.session_state.sbi_nav = "Storyboard"
    elif st.session_state.sbi_nav not in ("Console", "Projects", "Gallery", "Assets", "References", "Storyboard", "Editing", "LAB"):
        st.session_state.sbi_nav = "Storyboard"

    def _on_sbi_nav_change():
        val = st.session_state.sbi_nav
        if val == "Console":
            st.session_state.sbi_nav = "Storyboard"
            st.session_state["_console_was_away"] = True
            st.session_state.active_page = "console"
        elif val == "Projects":
            st.session_state.sbi_nav = "Storyboard"
            st.session_state.active_page = "projects"
        elif val == "Gallery":
            st.session_state.sbi_nav = "Storyboard"
            st.session_state.active_page = "gallery"
        elif val == "Assets":
            st.session_state.sbi_nav = "Storyboard"
            st.session_state.active_page = "assets"
        elif val == "References":
            st.session_state.sbi_nav = "Storyboard"
            st.session_state.active_page = "references"
        elif val == "Editing":
            st.session_state.sbi_nav = "Storyboard"
            st.session_state.active_page = "editing"
        elif val == "LAB":
            st.session_state.sbi_nav = "Storyboard"
            st.session_state.active_page = "lab"

    # "Storyboard" per primo: un reset sporadico del radio non seleziona "Console" → main page
    _SBI_NAV_ORDER = ["Storyboard", "Console", "Projects", "Gallery", "Assets", "References", "Editing", "LAB"]
    _sbi_nav_col, _sbi_proj_col = st.columns([4, 1])
    with _sbi_nav_col:
        st.radio(
            "sbi_nav_label",
            _SBI_NAV_ORDER,
            horizontal=True,
            key="sbi_nav",
            on_change=_on_sbi_nav_change,
            label_visibility="collapsed",
        )
    with _sbi_proj_col:
        _render_project_name_inline_right()

    _render_storyboard_projects_sidebar()
    _render_storyboard_save_load("sbi", use_projects_layout=True)

def render_editing_page():
    """Render the Editing page (video timeline + save/load)."""
    if "sbv_nav" not in st.session_state:
        st.session_state.sbv_nav = "Editing"
    elif st.session_state.sbv_nav not in ("Console", "Projects", "Gallery", "Assets", "References", "Storyboard", "Editing", "LAB"):
        st.session_state.sbv_nav = "Editing"

    def _on_sbv_nav_change():
        val = st.session_state.sbv_nav
        if val == "Console":
            st.session_state.sbv_nav = "Editing"
            st.session_state["_console_was_away"] = True
            st.session_state.active_page = "console"
        elif val == "Projects":
            st.session_state.sbv_nav = "Editing"
            st.session_state.active_page = "projects"
        elif val == "Gallery":
            st.session_state.sbv_nav = "Editing"
            st.session_state.active_page = "gallery"
        elif val == "Assets":
            st.session_state.sbv_nav = "Editing"
            st.session_state.active_page = "assets"
        elif val == "References":
            st.session_state.sbv_nav = "Editing"
            st.session_state.active_page = "references"
        elif val == "Storyboard":
            st.session_state.sbv_nav = "Editing"
            st.session_state.active_page = "storyboard"
        elif val == "LAB":
            st.session_state.sbv_nav = "Editing"
            st.session_state.active_page = "lab"

    _SBV_NAV_ORDER = ["Editing", "Console", "Projects", "Gallery", "Assets", "References", "Storyboard", "LAB"]
    _sbv_nav_col, _sbv_proj_col = st.columns([4, 1])
    with _sbv_nav_col:
        st.radio(
            "sbv_nav_label",
            _SBV_NAV_ORDER,
            horizontal=True,
            key="sbv_nav",
            on_change=_on_sbv_nav_change,
            label_visibility="collapsed",
        )
    with _sbv_proj_col:
        _render_project_name_inline_right()

    _render_editing_projects_sidebar()
    _render_storyboard_save_load("sbv", use_projects_layout=True)
