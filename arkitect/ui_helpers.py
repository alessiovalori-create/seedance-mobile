import streamlit as st

from arkitect.storage import get_active_project_name


def _section_title(text):
    st.markdown(
        f'<p style="color: #00E5CC; font-size: 2rem; font-weight: 600; margin-bottom: 0.25rem; text-align: center;">{text}</p>',
        unsafe_allow_html=True
    )

def _inject_pulse_css():
    st.markdown("""
    <style>
    @keyframes pulse-yellow {
        0%, 100% { opacity: 1; filter: brightness(1); }
        50% { opacity: 0.85; filter: brightness(1.15); }
    }
    @keyframes pulse-green {
        0%, 100% { opacity: 1; filter: brightness(1); }
        50% { opacity: 0.85; filter: brightness(1.15); }
    }
    .pulse-msg-yellow {
        color: #FFEB3B;
        font-weight: 600;
        text-align: center;
        padding: 0.5rem 1rem;
        border-radius: 0.5rem;
        background: rgba(255, 235, 59, 0.12);
        animation: pulse-yellow 1.8s ease-in-out infinite;
    }
    .pulse-msg-green {
        color: #00E676;
        font-weight: 600;
        text-align: center;
        padding: 0.5rem 1rem;
        border-radius: 0.5rem;
        background: rgba(0, 230, 118, 0.12);
        animation: pulse-green 1.8s ease-in-out infinite;
    }
    </style>
    """, unsafe_allow_html=True)


def _render_project_name_inline_right():
    """Right-aligned 'Project : name' in the top nav row (same style as Gallery)."""
    _pname = get_active_project_name()
    _pcol = "#FFEB3B" if _pname != "All Projects" else "#555"
    st.markdown(
        f'<p style="text-align:right; color:{_pcol}; font-size:0.75rem; font-weight:600; '
        f'font-family:Open Sans,sans-serif; letter-spacing:0.05em; '
        f'margin:10px 0 0; -webkit-text-fill-color:{_pcol};">'
        f'Project : {_pname}</p>',
        unsafe_allow_html=True,
    )
